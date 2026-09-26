"""NATIVE operators: numpy only. float32/uint32, contiguous. Walled extrude, inset, loopcut-stub, delete, fan."""
from __future__ import annotations
import numpy as np
_AXES = {"x": 0, "y": 1, "z": 2}
def triangulate(mesh): return mesh.triangulate()
def merge_verts(mesh, tol=1e-4): return mesh.merge_verts(tol)
def triangulate_fan(poly):
    """Fan n-gon -> (N-2,3) uint32. poly: int n | (N,) ids | (N,D) ring."""
    if isinstance(poly, (int, np.integer)):
        n = int(poly)
        if n < 3: return np.zeros((0, 3), np.uint32)
        ids = np.arange(n, dtype=np.uint32)
    else:
        a = np.asarray(poly)
        if a.ndim == 1 and np.issubdtype(a.dtype, np.integer):
            ids = np.asarray(a.ravel(), np.uint32); n = int(ids.size)
            if n < 3: return np.zeros((0, 3), np.uint32)
        else:
            n = int(a.shape[0]) if a.ndim in (1, 2) else 0
            if n < 3: return np.zeros((0, 3), np.uint32)
            ids = np.arange(n, dtype=np.uint32)
    o = np.empty((n - 2, 3), np.uint32); o[:, 0], o[:, 1], o[:, 2] = ids[0], ids[1:-1], ids[2:]
    return np.ascontiguousarray(o)
def extrude_faces(mesh, face_ids, dist):
    """Walled extrude: keep base; cap=uniq-vert dup offset by area-wtd avg-n*dist; 1 quad(2tris)/boundary edge; recalc normals."""
    from .mesh import Mesh
    if not isinstance(mesh, Mesh): raise TypeError("mesh must be Mesh")
    ids = sorted({int(f) for f in (face_ids or [])})
    if not ids: return mesh
    tc = mesh.tri_count
    for f in ids:
        if not (0 <= f < tc): raise ValueError("face id out of range")
    p = np.asarray(mesh.positions, np.float32); tri = np.asarray(mesh.indices, np.uint32).reshape(-1, 3)
    sel = tri[ids]; tp = p[sel].astype(np.float64)
    fn = np.cross(tp[:, 1] - tp[:, 0], tp[:, 2] - tp[:, 0]); a2 = np.linalg.norm(fn, axis=1); a2[a2 < 1e-12] = 1.0
    unl = fn / a2[:, None]; area = a2 * 0.5
    uniq, inv = np.unique(sel, return_inverse=True); inv = np.asarray(inv).ravel()
    acc = np.zeros((uniq.shape[0], 3), np.float64)
    np.add.at(acc, inv, (unl * area[:, None])[np.repeat(np.arange(len(ids)), 3)])
    ln = np.linalg.norm(acc, axis=1); ln[ln < 1e-12] = 1.0
    off = ((acc / ln[:, None]) * float(dist)).astype(np.float32)
    on = int(p.shape[0]); u = int(uniq.shape[0])
    np_ = np.empty((on + u, 3), np.float32); np_[:on] = p; np_[on:] = p[uniq] + off
    nuv = None
    if mesh.uvs is not None:
        uv = np.asarray(mesh.uvs, np.float32); nuv = np.empty((on + u, 2), np.float32); nuv[:on] = uv; nuv[on:] = uv[uniq]
    nnr = None
    if mesh.normals is not None:
        nr = np.asarray(mesh.normals, np.float32); nnr = np.empty((on + u, 3), np.float32); nnr[:on] = nr; nnr[on:] = nr[uniq]
    lut = np.full(on, -1, np.int64); lut[uniq] = np.arange(on, on + u); cap = lut[sel]
    cnt, dmap = {}, {}
    for a, b, c in sel.tolist():
        for e in ((a, b), (b, c), (c, a)):
            k = (e[0], e[1]) if e[0] < e[1] else (e[1], e[0]); cnt[k] = cnt.get(k, 0) + 1
            if k not in dmap: dmap[k] = e
    w = []
    for k, n_ in cnt.items():
        if n_ == 1:
            a, b = dmap[k]; w += [a, b, int(lut[b]), a, int(lut[b]), int(lut[a])]
    parts = [tri.ravel(), cap.ravel().astype(np.uint32)]
    if w: parts.append(np.asarray(w, np.uint32))
    mesh.positions = np.ascontiguousarray(np_); mesh.indices = np.ascontiguousarray(np.concatenate(parts).astype(np.uint32))
    if nuv is not None: mesh.uvs = np.ascontiguousarray(nuv)
    if nnr is not None: mesh.normals = np.ascontiguousarray(nnr)
    mesh.recalc_normals(False); return mesh
def inset_faces(mesh, face_ids, t):
    """Inset per connected component: project to plane(centroid,avg-n), scale by (1-t). Topology fixed. t in [0,1)."""
    from .mesh import Mesh
    if not isinstance(mesh, Mesh): raise TypeError("mesh must be Mesh")
    t = float(t)
    if not (0.0 <= t < 1.0): raise ValueError("t must be in [0,1)")
    ids = sorted({int(f) for f in (face_ids or [])})
    if not ids or t == 0.0: return mesh
    tc = mesh.tri_count
    for f in ids:
        if not (0 <= f < tc): raise ValueError("face id out of range")
    p = np.asarray(mesh.positions, np.float32); tri = np.asarray(mesh.indices, np.uint32).reshape(-1, 3); sel = tri[ids]
    k = len(ids); par = list(range(k))
    def find(a):
        while par[a] != a: par[a] = par[par[a]]; a = par[a]
        return a
    own = {}
    for r, (a, b, c) in enumerate(sel.tolist()):
        for v in (a, b, c):
            if v in own:
                ra, rb = find(r), find(own[v])
                if ra != rb: par[rb] = ra
            else: own[v] = r
    comp = {}
    for r in range(k): comp.setdefault(find(r), []).append(r)
    tp = p[sel].astype(np.float64); fn = np.cross(tp[:, 1] - tp[:, 0], tp[:, 2] - tp[:, 0])
    ar = np.linalg.norm(fn, axis=1) * 0.5; l = np.linalg.norm(fn, axis=1); l[l < 1e-12] = 1.0; un = fn / l[:, None]
    out = p.copy()
    for rs in comp.values():
        vs = np.unique(sel[rs]); cp = p[vs].astype(np.float64); cen = cp.mean(axis=0)
        wv = (un[rs] * ar[rs][:, None]).sum(axis=0); wl = float(np.linalg.norm(wv))
        n = wv / wl if wl > 1e-12 else np.array([0.0, 1.0, 0.0])
        pr = cp - ((cp - cen) @ n)[:, None] * n; out[vs] = (cen + (pr - cen) * (1.0 - t)).astype(np.float32)
    mesh.positions = np.ascontiguousarray(out.astype(np.float32)); mesh.recalc_normals(False); return mesh
def delete_faces(mesh, face_ids):
    """Delete tris; compact orphans. Cube quad-face [0,1] -> 12 to 10 tris."""
    from .mesh import Mesh
    if not isinstance(mesh, Mesh): raise TypeError("mesh must be Mesh")
    ids = {int(f) for f in (face_ids or [])}
    if not ids: return mesh
    tc = mesh.tri_count
    for f in ids:
        if not (0 <= f < tc): raise ValueError("face id out of range")
    tri = np.asarray(mesh.indices, np.uint32).reshape(-1, 3); keep = np.ones(tc, bool); keep[sorted(ids)] = False
    nt = tri[keep]; p = np.asarray(mesh.positions, np.float32)
    if nt.size == 0:
        mesh.positions = np.zeros((0, 3), np.float32); mesh.indices = np.zeros((0,), np.uint32)
        if mesh.uvs is not None: mesh.uvs = np.zeros((0, 2), np.float32)
        if mesh.normals is not None: mesh.normals = np.zeros((0, 3), np.float32)
        return mesh
    uq = np.unique(nt); lut = np.full(p.shape[0], -1, np.int64); lut[uq] = np.arange(uq.shape[0])
    mesh.positions = np.ascontiguousarray(p[uq]); mesh.indices = np.ascontiguousarray(lut[nt].ravel().astype(np.uint32))
    if mesh.uvs is not None: mesh.uvs = np.ascontiguousarray(np.asarray(mesh.uvs, np.float32)[uq])
    if mesh.normals is not None: mesh.normals = np.ascontiguousarray(np.asarray(mesh.normals, np.float32)[uq])
    return mesh
def loop_cut_stub(mesh, axis="x", t=0.5):
    """STUB grid-only: split tris crossing plane perp `axis` at lerp(min,max,t). Shared edge-mid cache; 1-vs-2 ->3. OK for cube/plane."""
    from .mesh import Mesh
    if not isinstance(mesh, Mesh): raise TypeError("mesh must be Mesh")
    ax = _AXES.get(str(axis).lower(), 0); t = float(t)
    p = np.asarray(mesh.positions, np.float32); tri = np.asarray(mesh.indices, np.uint32).reshape(-1, 3)
    if tri.shape[0] == 0 or p.shape[0] == 0: return mesh
    mn, mx = float(p[:, ax].min()), float(p[:, ax].max())
    if not (0.0 <= t <= 1.0) or (mx - mn) < 1e-12: return mesh
    cut = mn + t * (mx - mn); tol = 1e-6 * (mx - mn + 1.0)
    d = p[:, ax].astype(np.float64) - cut; sd = np.sign(d); sd[np.abs(d) <= tol] = 0.0
    huv, hnr = mesh.uvs is not None, mesh.normals is not None
    uv = np.asarray(mesh.uvs, np.float32) if huv else None; nr = np.asarray(mesh.normals, np.float32) if hnr else None
    npos = [v for v in p.tolist()]; nuv = [v for v in uv.tolist()] if huv else None; nnr = [v for v in nr.tolist()] if hnr else None
    cache = {}
    def edge(a, b):
        k = (a, b) if a < b else (b, a)
        h = cache.get(k)
        if h is not None: return h
        pa, pb = float(p[a, ax]), float(p[b, ax]); s = (cut - pa) / (pb - pa) if abs(pb - pa) > 1e-12 else 0.5
        qa = p[a].astype(np.float64) * (1 - s) + p[b].astype(np.float64) * s; npos.append((float(qa[0]), float(qa[1]), float(qa[2])))
        if huv:
            q2 = uv[a].astype(np.float64) * (1 - s) + uv[b].astype(np.float64) * s; nuv.append((float(q2[0]), float(q2[1])))
        if hnr:
            q3 = nr[a].astype(np.float64) * (1 - s) + nr[b].astype(np.float64) * s; l = float(np.linalg.norm(q3))
            q3 = q3 / l if l > 1e-12 else np.array([0.0, 1.0, 0.0]); nnr.append((float(q3[0]), float(q3[1]), float(q3[2])))
        ni = len(npos) - 1; cache[k] = ni; return ni
    out = []
    for a, b, c in tri.tolist():
        sa, sb, sc = float(sd[a]), float(sd[b]), float(sd[c])
        if not (max(sa, sb, sc) > 0 and min(sa, sb, sc) < 0): out += [a, b, c]; continue
        vs, ss = [a, b, c], (sa, sb, sc); on = [i for i, s in enumerate(ss) if s == 0.0]
        if len(on) == 1:
            io = on[0]; j, k2 = (io + 1) % 3, (io + 2) % 3
            if ss[j] * ss[k2] < 0:
                m = edge(vs[j], vs[k2]); o, vj, vk = vs[io], vs[j], vs[k2]
                if io == 0: out += [o, vj, m, o, m, vk]
                elif io == 1: out += [vj, vk, m, vj, m, o]
                else: out += [vj, m, o, vj, vk, m]
                continue
            out += [a, b, c]; continue
        lone = -1
        if sa != 0 and sa != sb and sa != sc: lone = 0
        elif sb != 0 and sb != sa and sb != sc: lone = 1
        elif sc != 0 and sc != sa and sc != sb: lone = 2
        if lone < 0: out += [a, b, c]; continue
        i1, i2 = (lone + 1) % 3, (lone + 2) % 3; v0, v1, v2 = vs[lone], vs[i1], vs[i2]
        m01, m02 = edge(v0, v1), edge(v0, v2); out += [v0, m01, m02, m01, v1, v2, m01, v2, m02]
    mesh.positions = np.ascontiguousarray(np.array(npos, np.float32).reshape(-1, 3))
    mesh.indices = np.ascontiguousarray(np.array(out, np.uint32).ravel())
    if huv: mesh.uvs = np.ascontiguousarray(np.array(nuv, np.float32).reshape(-1, 2))
    if hnr: mesh.normals = np.ascontiguousarray(np.array(nnr, np.float32).reshape(-1, 3))
    mesh.recalc_normals(False); return mesh
