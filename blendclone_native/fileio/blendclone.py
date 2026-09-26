"""BlendClone NATIVE scene JSON: {version:1, meshes:[{name,positions,indices}]}."""
from __future__ import annotations

import json

import numpy as np

from modeling.mesh import Mesh


def _iter_meshes(scene) -> list[tuple[str, Mesh]]:
    if isinstance(scene, dict) and "meshes" in scene:
        raw = scene["meshes"]
        if isinstance(raw, dict):  # {name: Mesh}
            return [(str(k), v) for k, v in raw.items()]
        items: list[tuple[str, Mesh]] = []
        for m in raw or []:
            if isinstance(m, Mesh):
                items.append((m.name or "mesh", m))
            elif isinstance(m, dict) and isinstance(m.get("mesh"), Mesh):
                items.append((str(m.get("name", m["mesh"].name)), m["mesh"]))
            elif isinstance(m, (list, tuple)) and len(m) == 2 and isinstance(m[1], Mesh):
                items.append((str(m[0]), m[1]))
        return items
    if isinstance(scene, dict):  # plain {name: Mesh}
        return [(str(k), v) for k, v in scene.items() if isinstance(v, Mesh)]
    raise TypeError("save_scene: expected {'meshes': [...]} or {name: Mesh}")


def save_scene(scene) -> str:
    meshes = []
    for name, m in _iter_meshes(scene):
        pos = np.asarray(m.positions, dtype=np.float32).reshape(-1, 3)
        meshes.append({
            "name": name or m.name or "mesh",
            "positions": [[round(float(x), 6) for x in row] for row in pos.tolist()],
            "indices": [int(i) for i in np.asarray(m.indices).reshape(-1).tolist()],
        })
    payload = {"version": 1, "meshes": meshes}
    if isinstance(scene, dict) and scene.get("clip") is not None:
        payload["clip"] = scene["clip"]  # Clip.to_dict(), JSON-safe
    if isinstance(scene, dict):
        for _k in ("shading", "node_graph", "graphs"):
            if scene.get(_k) is not None:
                payload[_k] = scene[_k]  # NodeGraph.to_dict(), JSON-safe
    return json.dumps(payload)


def load_scene(text: str) -> dict:
    data = json.loads(text)
    if not isinstance(data, dict) or data.get("version") != 1:
        raise ValueError("load_scene: unsupported version (expected 1)")
    meshes: list[Mesh] = []
    for entry in data.get("meshes", []):
        meshes.append(Mesh(np.asarray(entry["positions"], dtype=np.float32).reshape(-1, 3),
                           np.asarray(entry.get("indices", []), dtype=np.uint32),
                           None, None, str(entry.get("name", "mesh"))))
    return {"version": 1, "meshes": meshes, "clip": data.get("clip"),
            "shading": data.get("shading", data.get("node_graph")),
            "graphs": data.get("graphs")}
