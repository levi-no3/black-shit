"""BlendClone NATIVE — sculpt brushes (numpy only, no Qt).

All brushes operate on (N,3) float32 position arrays and return a NEW
(N,3) float32 array; inputs are never mutated (no in-place aliasing).
Deterministic: no randomness, fixed neighbor accumulation order.
"""
from __future__ import annotations

import numpy as np


def falloff(radius, dist):
    """Smoothstep falloff: 1 at center, 0 at/after the edge.

    radius: float brush radius (>0). dist: scalar or array of distances.
    Returns float for scalar input, ndarray otherwise.
    """
    scalar = np.ndim(dist) == 0
    r = float(radius)
    d = np.asarray(dist, dtype=np.float64)
    if not (r > 0):
        out = np.zeros_like(d)
        return float(out) if scalar else out
    t = np.clip(1.0 - d / r, 0.0, 1.0)
    out = t * t * (3.0 - 2.0 * t)
    return float(out) if scalar else out


def _as_positions(positions) -> np.ndarray:
    return np.asarray(positions, dtype=np.float32).reshape(-1, 3)


def _dist_to(positions_f64: np.ndarray, center) -> np.ndarray:
    c = np.asarray(center, dtype=np.float64).reshape(3)
    return np.linalg.norm(positions_f64 - c, axis=1)


def grab_brush(positions, center, delta, radius) -> np.ndarray:
    """Translate verts toward `delta`, weighted by smoothstep falloff.

    The center vert (dist 0) moves by exactly `delta`; verts at/after
    `radius` do not move.
    """
    p = _as_positions(positions)
    out = p.copy()
    r = float(radius)
    if not (r > 0) or p.shape[0] == 0:
        return np.ascontiguousarray(out, dtype=np.float32)
    d = np.asarray(delta, dtype=np.float64).reshape(3)
    if not np.all(np.isfinite(d)):
        return np.ascontiguousarray(out, dtype=np.float32)
    w = np.asarray(falloff(r, _dist_to(p.astype(np.float64), center)),
                   dtype=np.float64).reshape(-1, 1)
    if not np.any(w > 0):
        return np.ascontiguousarray(out, dtype=np.float32)
    out = p.astype(np.float64) + w * d
    return np.ascontiguousarray(out, dtype=np.float32)


def smooth_brush(positions, indices, center, radius, strength=0.5) -> np.ndarray:
    """Laplacian-ish relax: verts within radius move toward the mean of
    their topological (triangle-adjacency) neighbors.

    Blend per vert is strength * falloff(radius, dist_to_center).
    strength=1 fully snaps to the neighbor average; 0 is a no-op.
    """
    p = _as_positions(positions)
    out = p.copy()
    r = float(radius)
    s = float(strength)
    n = p.shape[0]
    if not (r > 0) or not (s > 0) or n == 0:
        return np.ascontiguousarray(out, dtype=np.float32)
    try:
        tri = np.asarray(indices, dtype=np.int64).reshape(-1, 3)
    except (TypeError, ValueError):
        return np.ascontiguousarray(out, dtype=np.float32)
    if tri.shape[0] == 0:
        return np.ascontiguousarray(out, dtype=np.float32)
    if int(tri.max()) >= n or int(tri.min()) < 0:
        return np.ascontiguousarray(out, dtype=np.float32)
    pf = p.astype(np.float64)
    # Each vert accumulates its triangle partners as neighbors.
    a, b, c = tri[:, 0], tri[:, 1], tri[:, 2]
    dst = np.concatenate([a, a, b, b, c, c])
    src = np.concatenate([b, c, a, c, a, b])
    acc = np.zeros((n, 3), dtype=np.float64)
    cnt = np.zeros(n, dtype=np.float64)
    np.add.at(acc, dst, pf[src])
    np.add.at(cnt, dst, 1.0)
    has = cnt > 0
    avg = pf.copy()
    avg[has] = acc[has] / cnt[has, None]
    w = (np.asarray(falloff(r, _dist_to(pf, center)),
                    dtype=np.float64) * s).reshape(-1, 1)
    w = np.clip(w, 0.0, 1.0)
    out = pf + (avg - pf) * w
    return np.ascontiguousarray(out, dtype=np.float32)


def inflate_brush(positions, normals, center, radius, strength=0.5) -> np.ndarray:
    """Displace verts along their normals, weighted by falloff.

    Positive strength inflates, negative deflates. Missing/degenerate
    normals contribute zero displacement (no-op for those verts).
    """
    p = _as_positions(positions)
    out = p.copy()
    r = float(radius)
    s = float(strength)
    if not (r > 0) or not np.isfinite(s) or s == 0.0 or p.shape[0] == 0:
        return np.ascontiguousarray(out, dtype=np.float32)
    if normals is None:
        return np.ascontiguousarray(out, dtype=np.float32)
    try:
        nrm = np.asarray(normals, dtype=np.float64).reshape(-1, 3)
    except (TypeError, ValueError):
        return np.ascontiguousarray(out, dtype=np.float32)
    if nrm.shape[0] != p.shape[0]:
        return np.ascontiguousarray(out, dtype=np.float32)
    nrm = np.where(np.isfinite(nrm), nrm, 0.0)
    lens = np.linalg.norm(nrm, axis=1, keepdims=True)
    safe = np.where(lens > 1e-12, lens, 1.0)
    unit = nrm / safe
    unit = np.where(lens > 1e-12, unit, 0.0)
    w = np.asarray(falloff(r, _dist_to(p.astype(np.float64), center)),
                   dtype=np.float64).reshape(-1, 1)
    out = p.astype(np.float64) + unit * (w * s)
    return np.ascontiguousarray(out, dtype=np.float32)
