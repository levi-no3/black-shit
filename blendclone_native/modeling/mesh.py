"""BlendClone NATIVE — Mesh: indexed triangle mesh, numpy only."""
from __future__ import annotations

import numpy as np


class Mesh:
    """Indexed triangle mesh.

    positions: (N,3) float32, indices: (M,) uint32 (M % 3 == 0),
    normals: (N,3) float32 or None, uvs: (N,2) float32 or None.
    No per-vertex Python objects; all data lives in ndarrays.
    """

    def __init__(self, positions, indices, normals=None, uvs=None, name=""):
        p = np.asarray(positions, dtype=np.float32).reshape(-1, 3)
        idx = np.asarray(indices, dtype=np.uint32).reshape(-1)
        if idx.size % 3 != 0:
            raise ValueError("Mesh: indices.size % 3 != 0")
        if p.shape[0] > 0 and idx.size > 0 and int(idx.max()) >= p.shape[0]:
            raise ValueError("Mesh: index out of range")
        self.positions: np.ndarray = np.ascontiguousarray(p, dtype=np.float32)
        self.indices: np.ndarray = np.ascontiguousarray(idx, dtype=np.uint32)
        n = self.positions.shape[0]
        if uvs is None:
            self.uvs = None
        else:
            u = np.asarray(uvs, dtype=np.float32).reshape(-1, 2)
            if u.shape[0] != n:
                raise ValueError("Mesh: uvs must be (N,2)")
            self.uvs = np.ascontiguousarray(u, dtype=np.float32)
        if normals is None:
            self.normals = None
        else:
            nr = np.asarray(normals, dtype=np.float32).reshape(-1, 3)
            if nr.shape[0] != n:
                raise ValueError("Mesh: normals must be (N,3)")
            self.normals = np.ascontiguousarray(nr, dtype=np.float32)
        self.name: str = name
        if self.normals is None:
            self.recalc_normals(False)

    @property
    def vert_count(self) -> int:
        return int(self.positions.shape[0])

    @property
    def tri_count(self) -> int:
        return int(self.indices.size // 3)

    # camelCase aliases (JS parity)
    @property
    def vertCount(self) -> int:  # noqa: N802
        return self.vert_count

    @property
    def triCount(self) -> int:  # noqa: N802
        return self.tri_count

    def byte_size(self) -> int:
        total = int(self.positions.nbytes + self.indices.nbytes)
        if self.uvs is not None:
            total += int(self.uvs.nbytes)
        if self.normals is not None:
            total += int(self.normals.nbytes)
        return total

    @property
    def byteSize(self) -> int:  # noqa: N802
        return self.byte_size()

    def recalc_normals(self, flat: bool = False):
        """Recompute normals. Smooth: area-weighted average. Flat: split to T*3 verts."""
        p = self.positions
        idx = self.indices
        t = self.tri_count
        if t == 0:
            self.normals = np.zeros_like(p)
            return self
        tris = p[idx.reshape(-1, 3)]  # (T,3,3)
        e1 = tris[:, 1] - tris[:, 0]
        e2 = tris[:, 2] - tris[:, 0]
        w = np.cross(e1, e2).astype(np.float64)  # area-weighted (|w| = 2*area)
        if not flat:
            n = np.zeros((p.shape[0], 3), dtype=np.float64)
            tri = idx.reshape(-1, 3)
            for k in range(3):
                np.add.at(n, tri[:, k], w)
            lens = np.linalg.norm(n, axis=1)
            good = lens > 1e-12
            n[good] /= lens[good, None]
            n[~good] = (0.0, 1.0, 0.0)
            self.normals = np.ascontiguousarray(n, dtype=np.float32)
            return self
        # flat: expand to non-indexed T*3 verts
        flat_idx = idx.reshape(-1, 3).reshape(-1)  # (T*3,)
        self.positions = np.ascontiguousarray(p[flat_idx], dtype=np.float32)
        if self.uvs is not None:
            self.uvs = np.ascontiguousarray(self.uvs[flat_idx], dtype=np.float32)
        lens = np.linalg.norm(w, axis=1)
        lens[lens == 0] = 1.0
        fn = (w / lens[:, None]).astype(np.float32)  # (T,3)
        self.normals = np.ascontiguousarray(np.repeat(fn, 3, axis=0), dtype=np.float32)
        self.indices = np.arange(t * 3, dtype=np.uint32)
        return self

    def apply_matrix(self, m):
        """Apply 4x4 row-major matrix (translation in M[:3,3]).

        Positions use full 4x4 with perspective divide; normals use
        inverse-transpose 3x3 then normalize (correct under non-uniform scale).
        """
        m = np.asarray(m, dtype=np.float32).reshape(4, 4)
        p = self.positions
        if p.shape[0] > 0:
            a = m[:3, :3].astype(np.float64)
            tv = m[:3, 3].astype(np.float64)
            bw = m[3, :3].astype(np.float64)
            w = p.astype(np.float64) @ bw + float(m[3, 3])
            w[np.abs(w) < 1e-12] = 1.0
            q = p.astype(np.float64) @ a.T + tv
            self.positions = np.ascontiguousarray((q / w[:, None]), dtype=np.float32)
        if self.normals is not None and self.normals.shape[0] > 0:
            a = m[:3, :3].astype(np.float64)
            try:
                inv_a = np.linalg.inv(a)
            except np.linalg.LinAlgError:
                inv_a = np.eye(3)
            if not np.all(np.isfinite(inv_a)):
                inv_a = np.eye(3)
            n = self.normals.astype(np.float64) @ inv_a
            lens = np.linalg.norm(n, axis=1)
            good = lens > 1e-12
            n[good] /= lens[good, None]
            self.normals = np.ascontiguousarray(n, dtype=np.float32)
        return self

    def triangulate(self):
        if self.indices.size % 3 != 0:
            raise ValueError("Mesh: indices not triangulated")
        return self

    def merge_verts(self, tol: float = 1e-4):
        """Weld position-duplicates within tol; drops orphan verts."""
        if not (tol > 0):
            return self
        p = self.positions
        idx = self.indices
        n = p.shape[0]
        if n == 0 or idx.size == 0:
            return self
        inv = 1.0 / tol
        mp: dict = {}
        seen = np.full(n, -1, dtype=np.int64)
        new_pos: list = []
        new_uv: list | None = [] if self.uvs is not None else None
        new_nr: list | None = [] if self.normals is not None else None
        out = np.empty_like(idx)
        vc = 0
        for k in range(idx.size):
            o = int(idx[k])
            sid = seen[o]
            if sid == -1:
                key = (int(round(float(p[o, 0]) * inv)),
                       int(round(float(p[o, 1]) * inv)),
                       int(round(float(p[o, 2]) * inv)))
                nid = mp.get(key)
                if nid is None:
                    nid = vc
                    vc += 1
                    mp[key] = nid
                    new_pos.append((float(p[o, 0]), float(p[o, 1]), float(p[o, 2])))
                    if new_uv is not None:
                        new_uv.append((float(self.uvs[o, 0]), float(self.uvs[o, 1])))
                    if new_nr is not None:
                        new_nr.append((float(self.normals[o, 0]),
                                       float(self.normals[o, 1]),
                                       float(self.normals[o, 2])))
                seen[o] = nid
                sid = nid
            out[k] = sid
        self.positions = np.ascontiguousarray(np.array(new_pos, dtype=np.float32).reshape(-1, 3))
        self.indices = np.ascontiguousarray(out, dtype=np.uint32)
        if new_uv is not None:
            self.uvs = np.ascontiguousarray(np.array(new_uv, dtype=np.float32).reshape(-1, 2))
        if new_nr is not None:
            self.normals = np.ascontiguousarray(np.array(new_nr, dtype=np.float32).reshape(-1, 3))
        return self

    def compute_bounds(self):
        """Return (center (3,) float32, size (3,) float32, radius float)."""
        p = self.positions
        if p.shape[0] == 0:
            z = np.zeros(3, dtype=np.float32)
            return z.copy(), z.copy(), 0.0
        mn = p.min(axis=0).astype(np.float64)
        mx = p.max(axis=0).astype(np.float64)
        center = ((mn + mx) * 0.5)
        size = (mx - mn)
        radius = float(np.linalg.norm(p.astype(np.float64) - center, axis=1).max())
        return (np.ascontiguousarray(center, dtype=np.float32),
                np.ascontiguousarray(size, dtype=np.float32), radius)

    def clone(self):
        return Mesh(self.positions.copy(), self.indices.copy(),
                    self.normals.copy() if self.normals is not None else None,
                    self.uvs.copy() if self.uvs is not None else None, self.name)
