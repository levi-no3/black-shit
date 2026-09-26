"""BlendClone NATIVE render/pathtracer.py — pure numpy CPU pathtracer (no Qt/GL)."""
from __future__ import annotations

import numpy as np

MAX_DEPTH = 2
_EPS = 1e-9
_OFFSET = 1e-4


def _norm(v) -> np.ndarray:
    a = np.asarray(v, dtype=np.float64).ravel()
    n = float(np.linalg.norm(a))
    return a / n if n > 1e-12 else np.array([0.0, 0.0, 1.0])


def gen_ray(cam_pos, cam_dir, px, py, fov_y=np.radians(50.0),
            aspect=1.0, up=(0.0, 1.0, 0.0)):
    """Pinhole ray. px,py in [0,1] (px: left->right, py: TOP->bottom like image rows).

    Returns (origin (3,), dir (3,) normalized).
    """
    eye = np.asarray(cam_pos, dtype=np.float64).ravel()
    fwd = _norm(cam_dir)
    upv = np.asarray(up, dtype=np.float64).ravel()
    right = np.cross(fwd, upv)
    if float(np.linalg.norm(right)) < 1e-9:
        right = np.array([1.0, 0.0, 0.0])
    right = right / float(np.linalg.norm(right))
    true_up = np.cross(right, fwd)  # unit (right,fwd orthonormal)
    th = float(np.tan(float(fov_y) / 2.0))
    sx = (2.0 * float(px) - 1.0) * th * float(aspect)
    sy = (1.0 - 2.0 * float(py)) * th
    d = _norm(fwd + right * sx + true_up * sy)
    return (eye.copy(), d)


def intersect_sphere(ray_o, ray_d, center, radius) -> float:
    """Nearest positive t or -1.0 on miss (geometric solution, port of JS)."""
    o = np.asarray(ray_o, dtype=np.float64).ravel()
    d = np.asarray(ray_d, dtype=np.float64).ravel()
    c = np.asarray(center, dtype=np.float64).ravel()
    oc = o - c
    tca = -float(np.dot(oc, d))
    d2 = float(np.dot(oc, oc)) - tca * tca
    r2 = float(radius) * float(radius)
    if d2 > r2:
        return -1.0
    thc = float(np.sqrt(max(0.0, r2 - d2)))
    t0, t1 = tca - thc, tca + thc
    if t1 < 0.0:
        return -1.0
    return float(t0 if t0 > 0.0 else t1)


def intersect_tri(ray_o, ray_d, v0, v1, v2) -> float:
    """Moller-Trumbore. Returns t or -1.0 on miss."""
    o = np.asarray(ray_o, dtype=np.float64).ravel()
    d = np.asarray(ray_d, dtype=np.float64).ravel()
    a = np.asarray(v0, dtype=np.float64).ravel()
    e1 = np.asarray(v1, dtype=np.float64).ravel() - a
    e2 = np.asarray(v2, dtype=np.float64).ravel() - a
    p = np.cross(d, e2)
    det = float(np.dot(e1, p))
    if -_EPS < det < _EPS:
        return -1.0
    inv = 1.0 / det
    tv = o - a
    u = float(np.dot(tv, p)) * inv
    if u < 0.0 or u > 1.0:
        return -1.0
    q = np.cross(tv, e1)
    v = float(np.dot(d, q)) * inv
    if v < 0.0 or u + v > 1.0:
        return -1.0
    t = float(np.dot(e2, q)) * inv
    return t if t > _EPS else -1.0


def _light_dir_atten(L: dict, P: np.ndarray):
    if "position" in L or L.get("type") == "point" or L.get("type_id") == 1:
        pp = np.asarray(L.get("position", L.get("vec", [0, 3, 0])), dtype=np.float64).ravel()
        dv = pp - P
        dist = float(np.linalg.norm(dv))
        if dist < 1e-12:
            return np.array([0.0, 1.0, 0.0]), 1.0
        return dv / dist, 1.0 / (1.0 + dist * dist)
    dd = np.asarray(L.get("direction", L.get("vec", [0.5, 0.8, 0.6])), dtype=np.float64).ravel()
    return _norm(dd), 1.0


def shade_lambert(P, N, albedo, lights) -> np.ndarray:
    """Lambert sum over lights. Returns linear RGB (3,) float64."""
    P = np.asarray(P, dtype=np.float64).ravel()
    N = np.asarray(N, dtype=np.float64).ravel()
    alb = np.asarray(albedo, dtype=np.float64).ravel()
    out = np.zeros(3, dtype=np.float64)
    for L in (lights or []):
        try:
            lv, atten = _light_dir_atten(L, P)
            ndl = float(np.dot(N, lv))
            if ndl <= 0.0:
                continue
            I = float(L.get("intensity", 1.0))
            c = np.asarray(L.get("color", [1, 1, 1]), dtype=np.float64).ravel()
            out += alb * c * (I * ndl * atten)
        except (TypeError, ValueError, AttributeError):
            continue
    return out


def _albedo_of(obj) -> np.ndarray:
    if isinstance(obj, dict):
        if "albedo" in obj:
            return np.asarray(obj["albedo"], dtype=np.float64).ravel()[:3]
        m = obj.get("material", {})
        if isinstance(m, dict) and "base_color" in m:
            return np.asarray(m["base_color"], dtype=np.float64).ravel()[:3]
        if isinstance(m, dict) and "baseColor" in m:
            return np.asarray(m["baseColor"], dtype=np.float64).ravel()[:3]
        if hasattr(m, "base_color"):
            return np.asarray(m.base_color, dtype=np.float64).ravel()[:3]
    return np.array([0.8, 0.8, 0.8])


def _emissive_of(obj) -> np.ndarray:
    if isinstance(obj, dict):
        m = obj.get("material", {})
        if isinstance(m, dict) and "emissive" in m:
            return np.asarray(m["emissive"], dtype=np.float64).ravel()[:3]
        if hasattr(m, "emissive"):
            return np.asarray(m.emissive, dtype=np.float64).ravel()[:3]
    return np.zeros(3)


def _metallic_of(obj) -> float:
    try:
        m = obj.get("material", {}) if isinstance(obj, dict) else None
        if isinstance(m, dict):
            return float(m.get("metallic", 0.0))
        if hasattr(m, "metallic"):
            return float(m.metallic)
    except (TypeError, ValueError):
        pass
    return 0.0


def _parse_cam(cam, w: int, h: int):
    if isinstance(cam, (list, tuple)) and len(cam) == 2:
        pos, dr = cam
        return np.asarray(pos, float).ravel(), _norm(dr), np.radians(50.0), w / max(1, h)
    c = dict(cam)
    pos = c.get("pos", c.get("eye", [0, 0, 0]))
    if "dir" in c:
        dr = c["dir"]
    elif "target" in c:
        dr = np.asarray(c["target"], float).ravel() - np.asarray(pos, float).ravel()
    else:
        dr = [0, 0, -1]
    fov = float(c.get("fov_y", c.get("fovY", np.radians(50.0))))
    asp = float(c.get("aspect", w / max(1, h)))
    return np.asarray(pos, float).ravel(), _norm(dr), fov, asp


def _trace(o, d, spheres, tris, lights, depth: int) -> np.ndarray:
    best_t = np.inf
    best_n = None
    best_obj = None
    for s in spheres:
        t = intersect_sphere(o, d, s["center"], s["radius"])
        if 0.0 < t < best_t:
            best_t = float(t)
            p = o + d * best_t
            best_n = _norm(p - np.asarray(s["center"], float).ravel())
            best_obj = s
    for tr in tris:
        t = intersect_tri(o, d, tr["v0"], tr["v1"], tr["v2"])
        if 0.0 < t < best_t:
            best_t = float(t)
            e1 = np.asarray(tr["v1"], float).ravel() - np.asarray(tr["v0"], float).ravel()
            e2 = np.asarray(tr["v2"], float).ravel() - np.asarray(tr["v0"], float).ravel()
            n = _norm(np.cross(e1, e2))
            if float(np.dot(n, d)) > 0.0:
                n = -n
            best_n = n
            best_obj = tr
    if best_obj is None:
        g = min(1.0, max(0.0, float(d[1]) * 0.5 + 0.5))
        return np.array([0.03 + 0.2 * g, 0.04 + 0.26 * g, 0.06 + 0.42 * g])
    P = o + d * best_t
    col = shade_lambert(P, best_n, _albedo_of(best_obj), lights) + _emissive_of(best_obj)
    if _metallic_of(best_obj) > 0.5 and depth + 1 < MAX_DEPTH:
        rd = d - best_n * (2.0 * float(np.dot(d, best_n)))
        rc = _trace(P + best_n * _OFFSET, _norm(rd), spheres, tris, lights, depth + 1)
        k = 0.8
        col = col * (1.0 - k) + rc * k
    return col


def render_tile(objects, cam, w: int, h: int, spp: int = 1) -> np.ndarray:
    """Render (h,w,3) float32 linear-HDR. Deterministic RNG seed 1337. MaxDepth 2."""
    w, h = int(w), int(h)
    n = max(1, min(8, int(spp)))
    if isinstance(objects, dict):
        spheres = list(objects.get("spheres", []))
        tris = list(objects.get("tris", []))
        lights = list(objects.get("lights", []))
    else:  # list of prim dicts
        spheres = [o for o in objects if isinstance(o, dict) and "center" in o]
        tris = [o for o in objects if isinstance(o, dict) and "v0" in o]
        lights = []
    if not lights:
        lights = [{"direction": np.array([0.5, 0.8, 0.6]), "color": np.array([1.0, 1.0, 1.0]), "intensity": 1.0}]
    pos, fwd, fov_y, aspect = _parse_cam(cam, w, h)
    rng = np.random.default_rng(1337)
    out = np.zeros((h, w, 3), dtype=np.float64)
    for j in range(h):
        for i in range(w):
            acc = np.zeros(3)
            for _ in range(n):
                px = (i + float(rng.random())) / w
                py = (j + float(rng.random())) / h
                o, d = gen_ray(pos, fwd, px, py, fov_y, aspect)
                acc += _trace(o, d, spheres, tris, lights, 0)
            out[j, i] = acc / n
    return out.astype(np.float32)
