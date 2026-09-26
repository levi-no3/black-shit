"""BlendClone NATIVE render/lights.py — light dicts, max 8, UBO-ish pack (numpy+stdlib)."""
from __future__ import annotations

import numpy as np

MAX_LIGHTS = 8

TYPE_DIR = 0
TYPE_POINT = 1
TYPE_SUN = 2

_ACTIVE: list = []


def _vec3(v, fallback):
    try:
        a = np.asarray(v, dtype=np.float64).ravel()
        if a.size >= 3 and np.all(np.isfinite(a[:3])):
            return np.array(a[:3], dtype=np.float64)
    except (TypeError, ValueError):
        pass
    return np.array(list(fallback), dtype=np.float64)


def _color(c):
    a = _vec3(c, [1.0, 1.0, 1.0])
    return np.clip(a, 0.0, None)


def dir_light(direction=(0.5, 0.8, 0.6), color=(1.0, 1.0, 1.0),
              intensity=1.0) -> dict:
    """Directional light. 'direction' points TOWARD the scene (travel dir negated in JS port: stored as-is)."""
    d = _vec3(direction, [0.5, 0.8, 0.6])
    n = float(np.linalg.norm(d))
    d = d / n if n > 1e-12 else np.array([0.5, 0.8, 0.6]) / np.linalg.norm([0.5, 0.8, 0.6])
    return {"type": "dir", "type_id": TYPE_DIR, "direction": d,
            "vec": d.copy(), "color": _color(color), "intensity": float(intensity)}


def point_light(position=(0.0, 3.0, 0.0), color=(1.0, 1.0, 1.0),
                intensity=1.0) -> dict:
    """Point light with 1/(1+d^2) attenuation. Shadows ignored in M1."""
    return {"type": "point", "type_id": TYPE_POINT,
            "position": _vec3(position, [0.0, 3.0, 0.0]),
            "vec": _vec3(position, [0.0, 3.0, 0.0]),
            "color": _color(color), "intensity": float(intensity)}


def sun_light(direction=(0.5, 0.8, 0.6), color=(1.0, 1.0, 1.0),
              intensity=3.0) -> dict:
    """Sun = directional with higher default intensity. Shadows ignored in M1."""
    d = dir_light(direction, color, intensity)
    d["type"] = "sun"
    d["type_id"] = TYPE_SUN
    return d


def set_lights(lights) -> list:
    """Set active lights (max 8). Returns a copy of the stored list."""
    global _ACTIVE
    lst = list(lights) if lights is not None else []
    if len(lst) > MAX_LIGHTS:
        raise ValueError(f"max {MAX_LIGHTS} lights, got {len(lst)}")
    _ACTIVE = [dict(L) for L in lst]
    return get_lights()


def get_lights() -> list:
    """Return a copy of the active light list."""
    return [dict(L) for L in _ACTIVE]


def pack_lights(lights=None) -> dict:
    """Pack to UBO-ish dict. Per light 8 floats: vec.xyz, type_id, color.rgb, intensity."""
    src = list(lights) if lights is not None else get_lights()
    n = min(len(src), MAX_LIGHTS)
    data = np.zeros(MAX_LIGHTS * 8, dtype=np.float32)
    for i in range(n):
        L = src[i]
        tid = int(L.get("type_id", TYPE_DIR if "position" not in L else TYPE_POINT))
        if tid == TYPE_POINT or "position" in L:
            vec = _vec3(L.get("position", L.get("vec", [0, 3, 0])), [0, 3, 0])
        else:
            vec = _vec3(L.get("direction", L.get("vec", [0.5, 0.8, 0.6])), [0.5, 0.8, 0.6])
        col = _color(L.get("color", [1, 1, 1]))
        try:
            inten = float(L.get("intensity", 1.0))
        except (TypeError, ValueError):
            inten = 1.0
        o = i * 8
        data[o:o + 3] = vec.astype(np.float32)
        data[o + 3] = np.float32(tid)
        data[o + 4:o + 7] = col.astype(np.float32)
        data[o + 7] = np.float32(inten)
    return {"data": data, "count": n, "max": MAX_LIGHTS}
