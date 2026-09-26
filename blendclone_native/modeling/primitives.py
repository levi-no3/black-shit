"""BlendClone NATIVE — triangulated primitives, Y-up, centered on origin."""
from __future__ import annotations

import numpy as np

from .mesh import Mesh

_CUBE_IDX = np.array([
    0, 1, 2, 0, 2, 3, 4, 5, 6, 4, 6, 7, 8, 9, 10, 8, 10, 11,
    12, 13, 14, 12, 14, 15, 16, 17, 18, 16, 18, 19, 20, 21, 22, 20, 22, 23,
], dtype=np.uint32)

_CUBE_POS = np.array([
    -1, -1, 1, 1, -1, 1, 1, 1, 1, -1, 1, 1,        # +z
    -1, -1, -1, -1, 1, -1, 1, 1, -1, 1, -1, -1,    # -z
    -1, 1, -1, -1, 1, 1, 1, 1, 1, 1, 1, -1,        # +y
    -1, -1, -1, 1, -1, -1, 1, -1, 1, -1, -1, 1,    # -y
    1, -1, -1, 1, 1, -1, 1, 1, 1, 1, -1, 1,        # +x
    -1, -1, -1, -1, -1, 1, -1, 1, 1, -1, 1, -1,    # -x
], dtype=np.float32).reshape(-1, 3)

_CUBE_NRM = np.array([
    0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1,
    0, 0, -1, 0, 0, -1, 0, 0, -1, 0, 0, -1,
    0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0,
    0, -1, 0, 0, -1, 0, 0, -1, 0, 0, -1, 0,
    1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0,
    -1, 0, 0, -1, 0, 0, -1, 0, 0, -1, 0, 0,
], dtype=np.float32).reshape(-1, 3)


def _quad_uvs(quads: int) -> np.ndarray:
    quad = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], dtype=np.float32)
    return np.ascontiguousarray(np.tile(quad, (quads, 1)), dtype=np.float32)


def create_cube(s: float = 2.0) -> Mesh:
    h = float(s) / 2.0
    return Mesh(_CUBE_POS * h, _CUBE_IDX.copy(),
                _CUBE_NRM.copy(), _quad_uvs(6), "Cube")


def create_plane(s: float = 2.0) -> Mesh:
    h = float(s) / 2.0
    pos = np.array([[-h, 0, -h], [h, 0, -h], [h, 0, h], [-h, 0, h]], dtype=np.float32)
    nrm = np.array([[0, 1, 0]] * 4, dtype=np.float32)
    uv = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], dtype=np.float32)
    return Mesh(pos, np.array([0, 2, 1, 0, 3, 2], dtype=np.uint32), nrm, uv, "Plane")


def create_uv_sphere(seg: int = 32, ring: int = 16, r: float = 1.0) -> Mesh:
    seg = max(3, int(seg))
    ring = max(2, int(ring))
    cols, rows = seg + 1, ring + 1
    pos = np.empty((rows * cols, 3), dtype=np.float32)
    nrm = np.empty((rows * cols, 3), dtype=np.float32)
    uv = np.empty((rows * cols, 2), dtype=np.float32)
    for i in range(rows):
        phi = (i / ring) * np.pi
        sp, cp = float(np.sin(phi)), float(np.cos(phi))
        for j in range(cols):
            th = (j / seg) * np.pi * 2.0
            x, y, z = sp * np.cos(th), cp, sp * np.sin(th)
            v = i * cols + j
            pos[v] = (x * r, y * r, z * r)
            nrm[v] = (x, y, z)
            uv[v] = (j / seg, 1.0 - i / ring)
    idx = np.empty((ring * seg * 6,), dtype=np.uint32)
    k = 0
    for i in range(ring):
        for j in range(seg):
            a = i * cols + j
            b = a + cols
            idx[k:k + 6] = (a, a + 1, b, a + 1, b + 1, b)
            k += 6
    return Mesh(pos, idx, nrm, uv, "Sphere")


def create_cylinder(seg: int = 32, r: float = 1.0, h: float = 2.0) -> Mesh:
    seg = max(3, int(seg))
    hy = float(h) / 2.0
    cols = seg + 1
    side_n = cols * 2
    cap_n = 1 + cols
    total = side_n + cap_n * 2
    pos = np.zeros((total, 3), dtype=np.float32)
    nrm = np.zeros((total, 3), dtype=np.float32)
    uv = np.zeros((total, 2), dtype=np.float32)
    th = (np.arange(cols) / seg) * np.pi * 2.0
    xs, zs = np.cos(th), np.sin(th)
    for j in range(cols):  # side rows, radial normals
        for row in range(2):
            v = row * cols + j
            y = -hy if row == 0 else hy
            pos[v] = (xs[j] * r, y, zs[j] * r)
            nrm[v] = (xs[j], 0.0, zs[j])
            uv[v] = (j / seg, float(row))
    v = side_n
    centers = []
    for cap in range(2):  # 0 bottom (-Y), 1 top (+Y)
        y = -hy if cap == 0 else hy
        ny = -1.0 if cap == 0 else 1.0
        centers.append(v)
        pos[v] = (0.0, y, 0.0)
        nrm[v] = (0.0, ny, 0.0)
        uv[v] = (0.5, 0.5)
        v += 1
        for j in range(cols):
            pos[v] = (xs[j] * r, y, zs[j] * r)
            nrm[v] = (0.0, ny, 0.0)
            uv[v] = (j / seg, 0.0 if y < 0 else 1.0)
            v += 1
    idx: list[int] = []
    for j in range(seg):  # side outward
        a, b = j, j + cols
        idx += [a, b, a + 1, a + 1, b, b + 1]
    for cap in range(2):
        c = centers[cap]
        rim = side_n + cap * cap_n + 1
        for j in range(seg):
            if cap == 0:
                idx += [c, rim + j, rim + j + 1]
            else:
                idx += [c, rim + j + 1, rim + j]
    return Mesh(pos, np.array(idx, dtype=np.uint32), nrm, uv, "Cylinder")
