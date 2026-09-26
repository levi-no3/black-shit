"""Node-based shading graph — no Qt, numpy only. Deterministic."""
from __future__ import annotations

import numpy as np

from render.material import Material, create_material

INPUTS = {
    "Output": ("surface",),
    "Principled": ("baseColor", "metallic", "roughness", "emissive"),
    "Mix": ("fac", "a", "b"),
    "ColorRamp": ("fac",),
    "Value": (),
    "RGB": (),
}
OUTPUTS = {
    "Output": (),
    "Principled": ("shader",),
    "Mix": ("color",),
    "ColorRamp": ("color",),
    "Value": ("value",),
    "RGB": ("color",),
}
_TYPES = tuple(INPUTS)


def _clamp01(x) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 0.0
    if v != v or v in (float("inf"), float("-inf")):
        return 0.0
    return 0.0 if v < 0.0 else 1.0 if v > 1.0 else v


def _vec3(v, fallback) -> np.ndarray:
    try:
        a = np.asarray(v, dtype=float).ravel()
        if a.size >= 3:
            return np.array([_clamp01(a[0]), _clamp01(a[1]), _clamp01(a[2])],
                            dtype=float)
    except (TypeError, ValueError):
        pass
    return np.array(list(fallback), dtype=float)


def _float(v, fallback: float = 0.0) -> float:
    try:
        f = float(np.asarray(v, dtype=float).ravel()[0])
        return f if f == f else float(fallback)
    except (TypeError, ValueError, IndexError):
        return float(fallback)


def _as_color(v, fallback=(0.0, 0.0, 0.0)) -> np.ndarray:
    if isinstance(v, Material):
        return np.asarray(v.base_color, dtype=float).ravel()[:3].copy()
    if isinstance(v, np.ndarray) and v.size >= 3:
        return _vec3(v, fallback)
    if isinstance(v, (list, tuple)) and len(v) >= 3:
        return _vec3(v, fallback)
    try:
        return np.array([_clamp01(float(v))] * 3, dtype=float)
    except (TypeError, ValueError):
        return np.array(list(fallback), dtype=float)


class Node:
    def __init__(self, nid: str, ntype: str, params: dict | None = None):
        if ntype not in INPUTS:
            raise ValueError(f"unknown node type: {ntype!r}")
        self.id = str(nid)
        self.type = str(ntype)
        self.params = dict(params or {})

    def to_dict(self) -> dict:
        out: dict = {"id": self.id, "type": self.type, "params": {}}
        for k in sorted(self.params):
            v = self.params[k]
            if isinstance(v, np.ndarray):
                v = v.tolist()
            elif isinstance(v, (np.floating, np.integer)):
                v = float(v)
            out["params"][k] = v
        return out

    @staticmethod
    def from_dict(d: dict) -> "Node":
        return Node(str(d["id"]), str(d["type"]), dict(d.get("params") or {}))


class NodeGraph:
    def __init__(self, nodes=None, links=None):
        self.nodes: dict[str, Node] = {}
        self.links: dict[tuple[str, str], tuple[str, str]] = {}
        self._ctr = 0
        for n in nodes or []:
            nd = n if isinstance(n, Node) else Node.from_dict(n)
            self.nodes[nd.id] = nd
            self._ctr = max(self._ctr, self._num(nd.id))
        for lk in links or []:
            if isinstance(lk, dict):
                f, t = lk["from"], lk["to"]
                self.link(f["node"], f["socket"], t["node"], t["socket"])
            else:
                self.link(*lk)

    @staticmethod
    def _num(nid: str) -> int:
        try:
            return int(str(nid).rsplit("_", 1)[1])
        except (ValueError, IndexError):
            return 0

    def add_node(self, ntype: str, params: dict | None = None,
                 node_id: str | None = None) -> str:
        if ntype not in INPUTS:
            raise ValueError(f"unknown node type: {ntype!r}")
        if node_id is None:
            self._ctr += 1
            node_id = f"{ntype}_{self._ctr}"
        if node_id in self.nodes:
            raise ValueError(f"duplicate node id: {node_id!r}")
        self.nodes[node_id] = Node(node_id, ntype, params)
        return node_id

    def link(self, from_node: str, from_socket: str,
             to_node: str, to_socket: str) -> None:
        if from_node not in self.nodes or to_node not in self.nodes:
            raise ValueError("link: unknown node id")
        if from_socket not in OUTPUTS[self.nodes[from_node].type]:
            raise ValueError(f"bad output socket: {from_socket!r}")
        if to_socket not in INPUTS[self.nodes[to_node].type]:
            raise ValueError(f"bad input socket: {to_socket!r}")
        self.links[(to_node, to_socket)] = (from_node, from_socket)

    def _src(self, nid: str, socket: str):
        return self.links.get((nid, socket))

    def evaluate(self) -> Material:
        outs = sorted(n.id for n in self.nodes.values() if n.type == "Output")
        if not outs:  # missing Output: sane default, no crash
            return create_material()
        val = self._eval(outs[0], set())
        return val if isinstance(val, Material) else create_material()

    def _eval(self, nid: str, stack: set):
        if nid in stack:
            raise ValueError(f"cycle at node {nid!r}")
        stack = stack | {nid}
        nd = self.nodes[nid]

        def inp(socket: str):
            s = self._src(nid, socket)
            return self._eval(s[0], stack) if s else None

        if nd.type == "Value":
            return _clamp01(_float(nd.params.get("value", 0.0)))
        if nd.type == "RGB":
            return _vec3(nd.params.get("color", (0.8, 0.8, 0.8)), (0.8, 0.8, 0.8))
        if nd.type == "Mix":
            f = inp("fac")
            f = _clamp01(_float(f, _float(nd.params.get("fac", 0.5), 0.5)))
            a = inp("a")
            b = inp("b")
            ca = _as_color(a, (0.0, 0.0, 0.0)) if a is not None else _vec3(
                nd.params.get("a", (0.0, 0.0, 0.0)), (0.0, 0.0, 0.0))
            cb = _as_color(b, (1.0, 1.0, 1.0)) if b is not None else _vec3(
                nd.params.get("b", (1.0, 1.0, 1.0)), (1.0, 1.0, 1.0))
            return np.clip((1.0 - f) * ca + f * cb, 0.0, 1.0)
        if nd.type == "ColorRamp":  # stub: lerp color0->color1 by fac
            f = inp("fac")
            f = _clamp01(_float(f, _float(nd.params.get("fac", 0.5), 0.5)))
            c0 = _vec3(nd.params.get("color0", (0.0, 0.0, 0.0)), (0.0, 0.0, 0.0))
            c1 = _vec3(nd.params.get("color1", (1.0, 1.0, 1.0)), (1.0, 1.0, 1.0))
            return np.clip((1.0 - f) * c0 + f * c1, 0.0, 1.0)
        if nd.type == "Principled":
            bc = inp("baseColor")
            me = inp("metallic")
            ro = inp("roughness")
            em = inp("emissive")
            base = _as_color(bc, (0.8, 0.8, 0.8)) if bc is not None else _vec3(
                nd.params.get("baseColor", nd.params.get("base_color", (0.8, 0.8, 0.8))),
                (0.8, 0.8, 0.8))
            met = _clamp01(_float(me, _float(nd.params.get("metallic", 0.0), 0.0)))
            rou = _float(ro, _float(nd.params.get("roughness", 0.5), 0.5))
            emi = _as_color(em, (0.0, 0.0, 0.0)) if em is not None else _vec3(
                nd.params.get("emissive", (0.0, 0.0, 0.0)), (0.0, 0.0, 0.0))
            return create_material(base, met, rou, emi)
        # Output
        s = inp("surface")
        if s is None:
            return create_material()
        if isinstance(s, Material):
            return s
        return create_material(_as_color(s, (0.8, 0.8, 0.8)))

    def to_dict(self) -> dict:
        return {"nodes": [self.nodes[k].to_dict() for k in sorted(self.nodes)],
                "links": [{"from": {"node": f[0], "socket": f[1]},
                           "to": {"node": t[0], "socket": t[1]}}
                          for t, f in sorted(self.links.items())]}

    @staticmethod
    def from_dict(d: dict) -> "NodeGraph":
        return NodeGraph(d.get("nodes", []), d.get("links", []))
