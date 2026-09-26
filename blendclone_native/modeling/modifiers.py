"""BlendClone NATIVE modeling/modifiers.py — numpy-only mesh modifiers.

Limits: Mirror mirrors across origin plane (no clipping/weld); Array is a
linear translate stack (no merge); SubdivStub is Catmull-Clark-ish quad split
(face point + shared edge mids, 1 quad->4, triangulated, 4x tris/level).
"""
from __future__ import annotations

import numpy as np

from .mesh import Mesh

_AXES = {"x": 0, "y": 1, "z": 2}


def mirror_modifier(mesh: Mesh, axis: str = "x") -> Mesh:
    """Mirror across origin plane; doubles tris/verts; flips mirrored winding."""
    ax = _AXES.get(str(axis).lower(), 0)
    p = np.asarray(mesh.positions, np.float32)
    idx = np.asarray(mesh.indices, np.uint32).reshape(-1, 3)
    n = p.shape[0]
    p2 = p.copy()
    p2[:, ax] = -p2[:, ax]
    idx2 = idx[:, ::-1] + n  # flip winding so outward faces stay outward
    pos = np.vstack([p, p2]).astype(np.float32)
    out_idx = np.vstack([idx, idx2]).ravel().astype(np.uint32)
    nrm = None
    if mesh.normals is not None:
        nr = np.asarray(mesh.normals, np.float32)
        nr2 = nr.copy()
        nr2[:, ax] = -nr2[:, ax]
        nrm = np.vstack([nr, nr2]).astype(np.float32)
    uvs = None
    if mesh.uvs is not None:
        u = np.asarray(mesh.uvs, np.float32)
        uvs = np.vstack([u, u]).astype(np.float32)
    return Mesh(pos, out_idx, nrm, uvs, (mesh.name or "") + "_mirror")


def array_modifier(mesh: Mesh, count: int = 3, offset=(2.0, 0.0, 0.0)) -> Mesh:
    """Linear array of `count` copies spaced by `offset`; tris x count."""
    k = max(1, int(count))
    off = np.asarray(offset, np.float32).ravel()[:3]
    p = np.asarray(mesh.positions, np.float32)
    idx = np.asarray(mesh.indices, np.uint32).reshape(-1, 3)
    n, t = p.shape[0], idx.shape[0]
    pos = np.vstack([p + float(i) * off for i in range(k)]).astype(np.float32)
    out_idx = np.vstack([idx + i * n for i in range(k)]).ravel().astype(np.uint32)
    nrm = None
    if mesh.normals is not None:
        nr = np.asarray(mesh.normals, np.float32)
        nrm = np.vstack([nr] * k).astype(np.float32)
    uvs = None
    if mesh.uvs is not None:
        u = np.asarray(mesh.uvs, np.float32)
        uvs = np.vstack([u] * k).astype(np.float32)
    return Mesh(pos, out_idx, nrm, uvs, (mesh.name or "") + "_array")


def subdiv_stub(mesh: Mesh, levels: int = 1) -> Mesh:
    """Catmull-Clark-ish quad split: face point smooths corners, shared edge mids.

    Per level: face point = tri centroid; corner = 0.75*v + 0.25*avg incident
    face points; edge mids shared via weld cache (no seam cracks); each tri
    -> 4 tris (quad-split pattern), each quad (2 tris) -> 4 quads = 8 tris.
    Output triangulated, 4x tris/level. Drops uvs (documented limit)."""
    p = np.asarray(mesh.positions, np.float32)
    idx = np.asarray(mesh.indices, np.uint32).reshape(-1, 3)
    for _ in range(max(0, int(levels))):
        n = int(p.shape[0])
        t = int(idx.shape[0])
        if t == 0 or n == 0:
            break
        tp = p[idx].astype(np.float64)  # (T,3,3)
        fp = tp.mean(axis=1)  # (T,3) face points
        cnt = np.zeros(n, dtype=np.int64)
        acc = np.zeros((n, 3), dtype=np.float64)
        for k in range(3):
            np.add.at(acc, idx[:, k], fp)
            np.add.at(cnt, idx[:, k], 1)
        vs = p.astype(np.float64)
        m = cnt > 0
        vs[m] = 0.75 * vs[m] + 0.25 * (acc[m] / cnt[m][:, None])
        cache: dict = {}
        mids: list = []
        mid_of = np.empty((t, 3), dtype=np.int64)
        for ti in range(t):
            a, b, c = int(idx[ti, 0]), int(idx[ti, 1]), int(idx[ti, 2])
            for e, (u, v) in enumerate(((a, b), (b, c), (c, a))):
                kk = (u, v) if u < v else (v, u)
                h = cache.get(kk)
                if h is None:
                    h = n + len(mids)
                    cache[kk] = h
                    mids.append(((vs[u] + vs[v]) * 0.5).tolist())
                mid_of[ti, e] = h
        npos = np.empty((n + len(mids), 3), dtype=np.float64)
        npos[:n] = vs
        if mids:
            npos[n:] = np.asarray(mids, dtype=np.float64)
        out = np.empty((t * 4, 3), dtype=np.uint32)
        for ti in range(t):
            a, b, c = int(idx[ti, 0]), int(idx[ti, 1]), int(idx[ti, 2])
            m01, m12, m20 = int(mid_of[ti, 0]), int(mid_of[ti, 1]), int(mid_of[ti, 2])
            out[ti * 4 + 0] = (a, m01, m20)
            out[ti * 4 + 1] = (b, m12, m01)
            out[ti * 4 + 2] = (c, m20, m12)
            out[ti * 4 + 3] = (m01, m12, m20)
        p = np.ascontiguousarray(npos.astype(np.float32))
        idx = np.ascontiguousarray(out)
    return Mesh(p, idx.ravel(), None, None, (mesh.name or "") + "_subdiv")


# Capitalized aliases matching spec names.
MirrorModifier = mirror_modifier
ArrayModifier = array_modifier
SubdivStub = subdiv_stub
