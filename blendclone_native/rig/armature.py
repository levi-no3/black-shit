"""Armature / skinning basics — numpy only (no Qt).

Linear-blend skinning MVP (1-2 bones): each bone is a rigid transform
(rotating about its head + pos offset); verts are blended by weights
(N,B) float32 rows summing to 1.
"""
from __future__ import annotations

import math

import numpy as np

__all__ = ["Bone", "Armature"]


def _vec3(v) -> np.ndarray:
    a = np.asarray(v, dtype=np.float32).reshape(-1)
    if a.shape != (3,):
        raise ValueError(f"expected 3-vector, got shape {a.shape}")
    return a.copy()


def _rot_from_euler(rot) -> np.ndarray:
    """Rz * Ry * Rx (matches viewport/scene.py mat4_from_trs)."""
    rx, ry, rz = (float(rot[0]), float(rot[1]), float(rot[2]))
    cx, sx, cy, sy, cz, sz = (math.cos(rx), math.sin(rx), math.cos(ry),
                              math.sin(ry), math.cos(rz), math.sin(rz))
    return np.array([
        [cy * cz, sx * sy * cz - cx * sz, cx * sy * cz + sx * sz],
        [cy * sz, sx * sy * sz + cx * cz, cx * sy * sz - sx * cz],
        [-sy, sx * cy, cx * cy]], dtype=np.float64)


class Bone:
    def __init__(self, name: str, head=(0.0, 0.0, 0.0),
                 tail=(0.0, 1.0, 0.0), parent=None):
        self.name = str(name)
        self.head = _vec3(head)
        self.tail = _vec3(tail)
        if parent is None or isinstance(parent, str):
            self.parent = parent
        elif isinstance(parent, Bone):
            self.parent = parent.name
        else:
            self.parent = str(parent)

    def matrix(self) -> np.ndarray:
        """Rest matrix: translation to head (4x4 float32)."""
        m = np.eye(4, dtype=np.float32)
        m[:3, 3] = self.head
        return m

    def to_dict(self) -> dict:
        return {"name": self.name, "head": [float(x) for x in self.head],
                "tail": [float(x) for x in self.tail], "parent": self.parent}

    @classmethod
    def from_dict(cls, d: dict) -> "Bone":
        return cls(d["name"], d["head"], d["tail"], d.get("parent"))


class Armature:
    """Ordered bones + per-bone pose. pose[name] = (pos offset, rot euler)."""

    def __init__(self, bones=()):
        self.bones: dict[str, Bone] = {}
        self.pose: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        for b in bones:
            self.add_bone(b)

    def add_bone(self, bone: Bone) -> Bone:
        if not isinstance(bone, Bone):
            raise TypeError("add_bone: expected Bone")
        if bone.name in self.bones:
            raise ValueError(f"duplicate bone {bone.name!r}")
        self.bones[bone.name] = bone
        self.pose[bone.name] = (np.zeros(3, np.float32), np.zeros(3, np.float32))
        return bone

    def bone_names(self) -> list:
        return list(self.bones.keys())

    def set_pose(self, name: str, pos_offset=(0.0, 0.0, 0.0),
                 rot_euler=(0.0, 0.0, 0.0)) -> None:
        if name not in self.bones:
            raise KeyError(f"unknown bone {name!r}")
        self.pose[name] = (_vec3(pos_offset), _vec3(rot_euler))

    def local_matrix(self, name: str) -> np.ndarray:
        """Posed delta: T(head+off) * R * T(-head); identity at rest."""
        b = self.bones[name]
        off, rot = self.pose.get(name, (np.zeros(3, np.float32),
                                        np.zeros(3, np.float32)))
        r = _rot_from_euler(np.asarray(rot, dtype=np.float64).reshape(3))
        h = b.head.astype(np.float64)
        o = np.asarray(off, dtype=np.float64).reshape(3)
        m = np.eye(4, dtype=np.float64)
        m[:3, :3] = r
        m[:3, 3] = (h + o) - r @ h
        return m.astype(np.float32)

    def bone_matrix(self, name: str, _seen=None) -> np.ndarray:
        """World posed delta, chaining parents (cycle-safe)."""
        if name not in self.bones:
            raise KeyError(f"unknown bone {name!r}")
        _seen = _seen or set()
        if name in _seen:
            raise ValueError(f"bone cycle at {name!r}")
        _seen.add(name)
        local = self.local_matrix(name).astype(np.float64)
        par = self.bones[name].parent
        if par is not None and par in self.bones:
            return (self.bone_matrix(par, set(_seen)).astype(np.float64)
                    @ local).astype(np.float32)
        return local.astype(np.float32)

    def skin(self, mesh_positions, weights) -> np.ndarray:
        p = np.asarray(mesh_positions, dtype=np.float32).reshape(-1, 3)
        names = self.bone_names()
        nb = len(names)
        if nb == 0:
            raise ValueError("skin: armature has no bones")
        w = np.asarray(weights, dtype=np.float32).reshape(p.shape[0], nb)
        out = np.zeros_like(p, dtype=np.float64)
        pf = p.astype(np.float64)
        for j, nm in enumerate(names):
            m = self.bone_matrix(nm).astype(np.float64)
            q = pf @ m[:3, :3].T + m[:3, 3]
            out += q * w[:, j:j + 1].astype(np.float64)
        return np.ascontiguousarray(out, dtype=np.float32)

    def auto_weights_from_x(self, positions, split_x: float = 0.0,
                            width: float = 1.0) -> np.ndarray:
        """Left/right split on x with smoothstep blend. Rows sum to 1."""
        p = np.asarray(positions, dtype=np.float32).reshape(-1, 3)
        n, nb = p.shape[0], len(self.bones)
        if nb == 0:
            raise ValueError("auto_weights: no bones")
        w = np.zeros((n, nb), dtype=np.float32)
        if nb == 1:
            w[:, 0] = 1.0
            return w
        hw = max(float(width), 1e-6) / 2.0
        t = np.clip((p[:, 0].astype(np.float64) - (float(split_x) - hw))
                    / (2.0 * hw), 0.0, 1.0)
        s = (t * t * (3.0 - 2.0 * t)).astype(np.float32)
        w[:, 0], w[:, 1] = 1.0 - s, s
        return np.ascontiguousarray(w, dtype=np.float32)

    def to_dict(self) -> dict:
        return {"bones": [self.bones[k].to_dict() for k in self.bone_names()],
                "pose": {k: {"pos": [float(x) for x in v[0]],
                             "rot": [float(x) for x in v[1]]}
                         for k, v in self.pose.items()}}

    @classmethod
    def from_dict(cls, d: dict) -> "Armature":
        arm = cls([Bone.from_dict(b) for b in d.get("bones") or []])
        for k, v in (d.get("pose") or {}).items():
            if k in arm.bones:
                arm.pose[k] = (_vec3(v.get("pos", (0, 0, 0))),
                               _vec3(v.get("rot", v.get("rot_euler", (0, 0, 0)))))
        return arm
