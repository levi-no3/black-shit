"""BlendClone NATIVE — Wavefront OBJ: v/vt/vn/f only, numpy port of io/obj.js."""
from __future__ import annotations

import numpy as np

from modeling.mesh import Mesh


def export_obj(mesh: Mesh, name: str = "mesh") -> str:
    p = np.asarray(mesh.positions, dtype=np.float32).reshape(-1, 3)
    idx = np.asarray(mesh.indices, dtype=np.uint32).reshape(-1)
    u = mesh.uvs.reshape(-1, 2) if mesh.uvs is not None else None
    n = mesh.normals.reshape(-1, 3) if mesh.normals is not None else None
    lines = [f"o {name or mesh.name or 'mesh'}"]
    for v in p:
        lines.append(f"v {float(v[0])!r} {float(v[1])!r} {float(v[2])!r}")
    if u is not None:
        for t in u:
            lines.append(f"vt {float(t[0])!r} {float(t[1])!r}")
    if n is not None:
        for w in n:
            lines.append(f"vn {float(w[0])!r} {float(w[1])!r} {float(w[2])!r}")
    has_vt = u is not None
    has_vn = n is not None
    for t in range(idx.size // 3):
        parts = []
        for k in range(3):
            v = int(idx[t * 3 + k]) + 1
            if has_vt and has_vn:
                parts.append(f"{v}/{v}/{v}")
            elif has_vt:
                parts.append(f"{v}/{v}")
            elif has_vn:
                parts.append(f"{v}//{v}")
            else:
                parts.append(f"{v}")
        lines.append("f " + " ".join(parts))
    return "\n".join(lines) + "\n"


def import_obj(text: str) -> Mesh:
    v: list[float] = []
    t: list[float] = []
    n: list[float] = []
    p: list[float] = []
    u: list[float] = []
    nr: list[float] = []
    mp: dict[str, int] = {}
    out: list[int] = []
    name = "mesh"
    uv_count = 0
    vn_count = 0

    def resolve(raw: int, count: int) -> int:
        return count + raw if raw < 0 else raw - 1  # 1-based; negatives relative

    for raw_line in str(text).splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        tag = parts[0]
        if tag == "v" and len(parts) >= 4:
            v += [float(parts[1]), float(parts[2]), float(parts[3])]
        elif tag == "vt" and len(parts) >= 2:
            t += [float(parts[1]), float(parts[2]) if len(parts) >= 3 else 0.0]
        elif tag == "vn" and len(parts) >= 4:
            n += [float(parts[1]), float(parts[2]), float(parts[3])]
        elif tag in ("o", "g") and len(parts) >= 2:
            name = parts[1]
        elif tag == "f" and len(parts) >= 4:
            vs: list[int] = []
            for tok in parts[1:]:
                s = tok.split("/")
                try:
                    vi = resolve(int(s[0]), len(v) // 3)
                except ValueError:
                    continue
                ti = -1
                ni = -1
                if len(s) >= 2 and s[1] not in ("", None):
                    try:
                        ti = resolve(int(s[1]), len(t) // 2)
                    except ValueError:
                        ti = -1
                if len(s) >= 3 and s[2] not in ("", None):
                    try:
                        ni = resolve(int(s[2]), len(n) // 3)
                    except ValueError:
                        ni = -1
                if not (0 <= vi < len(v) // 3):
                    continue
                key = f"{vi}/{ti}/{ni}"
                gid = mp.get(key)
                if gid is None:
                    gid = len(p) // 3
                    mp[key] = gid
                    p += [v[vi * 3], v[vi * 3 + 1], v[vi * 3 + 2]]
                    if 0 <= ti < len(t) // 2:
                        u += [t[ti * 2], t[ti * 2 + 1]]
                        uv_count += 1
                    else:
                        u += [0.0, 0.0]
                    if 0 <= ni < len(n) // 3:
                        nr += [n[ni * 3], n[ni * 3 + 1], n[ni * 3 + 2]]
                        vn_count += 1
                    else:
                        nr += [0.0, 0.0, 0.0]
                vs.append(gid)
            if len(vs) < 3:
                continue
            for k in range(1, len(vs) - 1):  # fan-triangulate n-gons
                out += [vs[0], vs[k], vs[k + 1]]
        # ignore: mtllib, usemtl, s, l, p, vp, etc.
    vc = len(p) // 3
    uvs = np.array(u, dtype=np.float32).reshape(-1, 2) if uv_count > 0 else None
    normals = np.array(nr, dtype=np.float32).reshape(-1, 3) if (vn_count == vc and vc > 0) else None
    return Mesh(np.array(p, dtype=np.float32).reshape(-1, 3),
                np.array(out if out else [], dtype=np.uint32),
                normals, uvs, name)
