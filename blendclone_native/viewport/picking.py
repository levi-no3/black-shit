"""BlendClone NATIVE — face picking helpers (numpy only, no Qt).

World-space ray vs triangle (Moller-Trumbore, double-sided) plus a small
selection-set helper used by ViewportGL edit mode and unit tests.
"""
from __future__ import annotations

import numpy as np


def ray_triangle_intersect(ro, rd, v0, v1, v2, eps: float = 1e-9):
    """Moller-Trumbore, double-sided. Returns distance t or None."""
    ro = np.asarray(ro, dtype=np.float64).reshape(3)
    rd = np.asarray(rd, dtype=np.float64).reshape(3)
    v0 = np.asarray(v0, dtype=np.float64).reshape(3)
    v1 = np.asarray(v1, dtype=np.float64).reshape(3)
    v2 = np.asarray(v2, dtype=np.float64).reshape(3)
    e1 = v1 - v0
    e2 = v2 - v0
    p = np.cross(rd, e2)
    det = float(e1 @ p)
    if abs(det) < eps:
        return None
    inv = 1.0 / det
    tvec = ro - v0
    u = float(tvec @ p) * inv
    if u < 0.0 or u > 1.0:
        return None
    q = np.cross(tvec, e1)
    v = float(rd @ q) * inv
    if v < 0.0 or u + v > 1.0:
        return None
    t = float(e2 @ q) * inv
    if t <= eps:
        return None
    return t


def _world_positions(positions, model):
    p = np.asarray(positions, dtype=np.float64).reshape(-1, 3)
    if model is None:
        return p
    m = np.asarray(model, dtype=np.float64).reshape(4, 4)
    ones = np.ones((p.shape[0], 1), dtype=np.float64)
    h = np.hstack([p, ones])  # (N,4)
    w = h @ m.T
    w[:, 3][np.abs(w[:, 3]) < 1e-12] = 1.0
    return w[:, :3] / w[:, 3:4]


def raycast_mesh(positions, indices, ro, rd, model=None):
    """Closest triangle hit in world space.

    Returns (face_id | None, t: float). face_id is triangle index
    (0 .. tri_count-1). t is inf when there is no hit.
    """
    pos = _world_positions(positions, model)
    idx = np.asarray(indices, dtype=np.int64).reshape(-1, 3)
    ro = np.asarray(ro, dtype=np.float64).reshape(3)
    rd = np.asarray(rd, dtype=np.float64).reshape(3)
    n = float(np.linalg.norm(rd))
    if n < 1e-12:
        return None, float("inf")
    rd = rd / n
    best_f, best_t = None, float("inf")
    for f in range(idx.shape[0]):
        t = ray_triangle_intersect(ro, rd, pos[idx[f, 0]], pos[idx[f, 1]], pos[idx[f, 2]])
        if t is not None and t < best_t:
            best_f, best_t = f, t
    return best_f, best_t


# Alias used by glwidget (same signature).
def pick_face(positions, indices, ro, rd, model=None):
    return raycast_mesh(positions, indices, ro, rd, model)


def apply_face_click(sel: set, face: int, additive: bool) -> set:
    """Apply one face click to a selection set (mutates and returns sel).

    additive=False (plain click) replaces the selection with {face}.
    additive=True (Shift-click) adds face to the existing set.
    face=None clears when not additive, no-op when additive.
    """
    if face is None:
        if not additive:
            sel.clear()
        return sel
    f = int(face)
    if additive:
        sel.add(f)
    else:
        sel.clear()
        sel.add(f)
    return sel


def clear_faces(sel: set) -> set:
    sel.clear()
    return sel


def delete_faces_dict(mesh: dict, face_ids) -> dict:
    """Delete TRIANGLE faces from a viewport mesh dict (mutated, returned).

    Compacts orphan verts and clears the `_bounds` cache. tri_count drops
    by len(face_ids). Empty selection is a no-op; bad ids raise ValueError.
    Numpy only (no Qt), so unit tests stay QApplication-free.
    """
    ids = sorted({int(f) for f in (face_ids or [])})
    if not ids:
        return mesh
    tri = np.asarray(mesh["indices"], np.uint32).reshape(-1, 3)
    tc = int(tri.shape[0])
    for f in ids:
        if not (0 <= f < tc):
            raise ValueError("face id out of range")
    keep = np.ones(tc, bool)
    keep[np.asarray(ids, np.int64)] = False
    nt = tri[keep]
    p = np.asarray(mesh["positions"], np.float32).reshape(-1, 3)
    nrm = None
    if mesh.get("normals") is not None:
        nrm = np.asarray(mesh["normals"], np.float32).reshape(-1, 3)
    if nt.size == 0:
        mesh["positions"] = np.zeros((0, 3), np.float32)
        mesh["indices"] = np.zeros((0,), np.uint32)
        if nrm is not None:
            mesh["normals"] = np.zeros((0, 3), np.float32)
        mesh.pop("_bounds", None)
        return mesh
    uq = np.unique(nt)
    lut = np.full(p.shape[0], -1, np.int64)
    lut[uq] = np.arange(uq.shape[0])
    mesh["positions"] = np.ascontiguousarray(p[uq])
    mesh["indices"] = np.ascontiguousarray(lut[nt].ravel().astype(np.uint32))
    if nrm is not None:
        mesh["normals"] = np.ascontiguousarray(nrm[uq])
    mesh.pop("_bounds", None)
    return mesh
