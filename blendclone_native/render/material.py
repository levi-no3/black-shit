"""BlendClone NATIVE render/material.py — Principled-stub material (numpy+stdlib only)."""
from __future__ import annotations

from dataclasses import dataclass, field
import numpy as np

MATERIAL_UBO_FLOATS = 8  # 2 x vec4
MATERIAL_UBO_BYTES = 32

# slot0 = vec4(base_color.rgb, metallic)
# slot1 = vec4(emissive.rgb, roughness)


def _clamp01(x) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 0.0
    if not np.isfinite(v):
        return 0.0
    return 0.0 if v < 0.0 else 1.0 if v > 1.0 else v


def _to_vec3(c, fallback) -> np.ndarray:
    try:
        a = np.asarray(c, dtype=np.float64).ravel()
        if a.size >= 3 and np.all(np.isfinite(a[:3])):
            return np.array([_clamp01(a[0]), _clamp01(a[1]), _clamp01(a[2])],
                            dtype=np.float64)
    except (TypeError, ValueError):
        pass
    return np.array(list(fallback), dtype=np.float64)


@dataclass
class Material:
    base_color: np.ndarray = field(default_factory=lambda: np.array([0.8, 0.8, 0.8]))
    metallic: float = 0.0
    roughness: float = 0.5
    emissive: np.ndarray = field(default_factory=lambda: np.zeros(3))

    def __post_init__(self):
        self.base_color = _to_vec3(self.base_color, [0.8, 0.8, 0.8])
        self.emissive = _to_vec3(self.emissive, [0, 0, 0])
        self.metallic = _clamp01(self.metallic)
        try:
            r = float(self.roughness)
        except (TypeError, ValueError):
            r = 0.5
        if not np.isfinite(r):
            r = 0.5
        self.roughness = min(1.0, max(0.04, r))


def create_material(base_color=(0.8, 0.8, 0.8), metallic=0.0,
                    roughness=0.5, emissive=(0.0, 0.0, 0.0)) -> Material:
    """Create a Principled-stub material with clamped values."""
    return Material(base_color=np.asarray(base_color, dtype=np.float64),
                    metallic=metallic, roughness=roughness,
                    emissive=np.asarray(emissive, dtype=np.float64))


def _as_material(m) -> Material:
    if isinstance(m, Material):
        return m
    if isinstance(m, dict):
        bc = m.get("base_color", m.get("baseColor", (0.8, 0.8, 0.8)))
        em = m.get("emissive", (0.0, 0.0, 0.0))
        return create_material(bc, m.get("metallic", 0.0),
                               m.get("roughness", 0.5), em)
    return create_material()


def pack_material_ubo(mat) -> dict:
    """Pack material to UBO-ish dict: {'data': float32[8], 'floats': 8, 'bytes': 32}."""
    m = _as_material(mat)
    data = np.zeros(MATERIAL_UBO_FLOATS, dtype=np.float32)
    data[0:3] = np.asarray(m.base_color, dtype=np.float32)
    data[3] = np.float32(m.metallic)
    data[4:7] = np.asarray(m.emissive, dtype=np.float32)
    data[7] = np.float32(m.roughness)
    return {"data": data, "floats": MATERIAL_UBO_FLOATS,
            "bytes": MATERIAL_UBO_BYTES}
