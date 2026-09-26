"""BlendClone native scene graph — port of blendclone/src/viewport/scene.js.

mesh = dict(positions (N,3) f32, normals (N,3) f32, indices (M,) u32).
Meshes are shared by reference, never copied.
"""
from __future__ import annotations

import itertools
import math

import numpy as np

_next_id = itertools.count(1)


def mat4_from_trs(pos: np.ndarray, rot: np.ndarray, scl: np.ndarray) -> np.ndarray:
    """T(pos) * Rz * Ry * Rx * S, rot = euler XYZ radians (matches math.js)."""
    cx, sx = math.cos(rot[0]), math.sin(rot[0])
    cy, sy = math.cos(rot[1]), math.sin(rot[1])
    cz, sz = math.cos(rot[2]), math.sin(rot[2])
    r00, r10, r20 = cy * cz, cy * sz, -sy
    r01, r11, r21 = sx * sy * cz - cx * sz, sx * sy * sz + cx * cz, sx * cy
    r02, r12, r22 = cx * sy * cz + sx * sz, cx * sy * sz - sx * cz, cx * cy
    m = np.eye(4, dtype=np.float32)
    m[0, :3] = (r00 * scl[0], r01 * scl[1], r02 * scl[2])
    m[1, :3] = (r10 * scl[0], r11 * scl[1], r12 * scl[2])
    m[2, :3] = (r20 * scl[0], r21 * scl[1], r22 * scl[2])
    m[:3, 3] = pos
    return m


class Transform:
    def __init__(self, pos=(0.0, 0.0, 0.0), rot_euler=(0.0, 0.0, 0.0),
                 scale=(1.0, 1.0, 1.0)):
        self.pos = np.array(pos, dtype=np.float32)
        self.rot_euler = np.array(rot_euler, dtype=np.float32)
        self.scale = np.array(scale, dtype=np.float32)
        self.matrix = np.eye(4, dtype=np.float32)

    def update_matrix(self) -> np.ndarray:
        self.matrix = mat4_from_trs(self.pos, self.rot_euler, self.scale)
        return self.matrix


class Object3D:
    def __init__(self, mesh=None, name: str = "Object", transform=None,
                 color=(0.55, 0.62, 0.70), id: int | None = None,
                 emissive=(0.0, 0.0, 0.0)):
        self.id = next(_next_id) if id is None else id
        self.name = name
        self.transform = transform if transform is not None else Transform()
        self.mesh = mesh
        self.color = np.array(color, dtype=np.float32)
        self.metallic = 0.0
        self.roughness = 0.5
        self.emissive = np.array(emissive, dtype=np.float32)
        self.selected = False
        self.selected_faces: set[int] = set()


class Scene:
    def __init__(self):
        self.objects: list[Object3D] = []

    def add(self, obj: Object3D) -> Object3D:
        self.objects.append(obj)
        return obj

    def remove(self, obj: Object3D) -> Object3D:
        if obj in self.objects:
            self.objects.remove(obj)
        return obj

    def traverse(self, fn) -> None:
        for o in list(self.objects):
            fn(o)

    def find_by_id(self, id: int) -> Object3D | None:
        for o in self.objects:
            if o.id == id:
                return o
        return None

    def clear(self) -> None:
        self.objects.clear()


def make_cube_mesh(size: float = 1.0) -> dict:
    h = size / 2.0
    faces = [  # normal, 4 corners (CCW from outside)
        ((0, 0, 1), [(-h, -h, h), (h, -h, h), (h, h, h), (-h, h, h)]),
        ((0, 0, -1), [(h, -h, -h), (-h, -h, -h), (-h, h, -h), (h, h, -h)]),
        ((0, 1, 0), [(-h, h, h), (h, h, h), (h, h, -h), (-h, h, -h)]),
        ((0, -1, 0), [(-h, -h, -h), (h, -h, -h), (h, -h, h), (-h, -h, h)]),
        ((1, 0, 0), [(h, -h, h), (h, -h, -h), (h, h, -h), (h, h, h)]),
        ((-1, 0, 0), [(-h, -h, -h), (-h, -h, h), (-h, h, h), (-h, h, -h)]),
    ]
    pos, nor, idx = [], [], []
    for n, corners in faces:
        base = len(pos)
        pos.extend(corners)
        nor.extend([n] * 4)
        idx.extend([base, base + 1, base + 2, base, base + 2, base + 3])
    return {"positions": np.array(pos, np.float32), "normals": np.array(nor, np.float32),
            "indices": np.array(idx, np.uint32)}


def make_sphere_mesh(radius: float = 0.5, lats: int = 16, lons: int = 24) -> dict:
    pos, nor, idx = [], [], []
    for i in range(lats + 1):
        th = math.pi * i / lats
        for j in range(lons + 1):
            ph = 2 * math.pi * j / lons
            n = (math.sin(th) * math.cos(ph), math.cos(th), math.sin(th) * math.sin(ph))
            nor.append(n)
            pos.append((n[0] * radius, n[1] * radius, n[2] * radius))
    for i in range(lats):
        for j in range(lons):
            a, b = i * (lons + 1) + j, (i + 1) * (lons + 1) + j
            idx.extend([a, b, a + 1, b, b + 1, a + 1])
    return {"positions": np.array(pos, np.float32), "normals": np.array(nor, np.float32),
            "indices": np.array(idx, np.uint32)}


def make_grid_mesh(size: float = 10.0, div: int = 10) -> dict:
    pos, idx = [], []
    h = size / 2.0
    for i in range(div + 1):
        t = -h + size * i / div
        base = len(pos)
        pos.extend([(t, 0, -h), (t, 0, h), (-h, 0, t), (h, 0, t)])
        idx.extend([base, base + 1, base + 2, base + 3])
    n = len(pos)
    return {"positions": np.array(pos, np.float32), "normals": np.zeros((n, 3), np.float32),
            "indices": np.array(idx, np.uint32), "lines": True}


def mesh_bounds(mesh: dict) -> dict:
    if "_bounds" in mesh:
        return mesh["_bounds"]
    p = np.asarray(mesh["positions"], dtype=np.float32).reshape(-1, 3)
    mn, mx = p.min(axis=0).astype(np.float32), p.max(axis=0).astype(np.float32)
    c = ((mn + mx) / 2).astype(np.float32)
    mesh["_bounds"] = {"min": mn, "max": mx, "center": c,
                       "radius": float(np.linalg.norm(p - c, axis=1).max(initial=0.0))}
    return mesh["_bounds"]
