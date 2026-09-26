"""BlendClone NATIVE render/color.py — linear<->sRGB, Reinhard tonemap (numpy vectorized)."""
from __future__ import annotations

import numpy as np

_LIN_THRESH = 0.0031308


def linear_to_srgb(x):
    """Linear (0..1 nominal) -> sRGB (0..1). Scalar in -> float out; array in -> ndarray out."""
    if np.isscalar(x):
        v = float(x)
        if not np.isfinite(v) or v <= 0.0:
            return 0.0
        if v >= 1.0:
            return 1.0
        if v <= _LIN_THRESH:
            return 12.92 * v
        return 1.055 * (v ** (1.0 / 2.4)) - 0.055
    a = np.asarray(x, dtype=np.float64)
    out = np.empty_like(a, dtype=np.float64)
    bad = ~np.isfinite(a) | (a <= 0.0)
    hi = a >= 1.0
    lo = (~bad) & (~hi) & (a <= _LIN_THRESH)
    mid = (~bad) & (~hi) & (~lo)
    out[bad] = 0.0
    out[hi] = 1.0
    out[lo] = 12.92 * a[lo]
    out[mid] = 1.055 * np.power(a[mid], 1.0 / 2.4) - 0.055
    return out


def srgb_to_linear(x):
    """sRGB (0..1) -> linear. Helper for round-trip tests."""
    if np.isscalar(x):
        v = float(x)
        if not np.isfinite(v) or v <= 0.0:
            return 0.0
        if v >= 1.0:
            return 1.0
        if v <= 0.04045:
            return v / 12.92
        return ((v + 0.055) / 1.055) ** 2.4
    a = np.asarray(x, dtype=np.float64)
    out = np.empty_like(a, dtype=np.float64)
    bad = ~np.isfinite(a) | (a <= 0.0)
    hi = a >= 1.0
    lo = (~bad) & (~hi) & (a <= 0.04045)
    mid = (~bad) & (~hi) & (~lo)
    out[bad] = 0.0
    out[hi] = 1.0
    out[lo] = a[lo] / 12.92
    out[mid] = np.power((a[mid] + 0.055) / 1.055, 2.4)
    return out


def tonemap_exposure(src, exposure=0.0):
    """Reinhard: out = (c*E)/(1+c*E), E = 2^exposure. Scalar->float, array->ndarray."""
    E = float(2.0 ** float(exposure))
    if np.isscalar(src):
        v = float(src) * E
        return v / (1.0 + v) if np.isfinite(v) and v > 0.0 else 0.0
    a = np.asarray(src, dtype=np.float64)
    v = a * E
    out = np.zeros_like(a, dtype=np.float64)
    ok = np.isfinite(v) & (v > 0.0)
    out[ok] = v[ok] / (1.0 + v[ok])
    return out


def float_to_uint8(buf, exposure=0.0):
    """Linear-HDR RGB (...,3) floats -> uint8 sRGB (...,3). Tonemap + sRGB + *255."""
    a = np.asarray(buf, dtype=np.float64)
    if a.shape[-1] != 3:
        raise ValueError(f"last dim must be 3, got shape {a.shape}")
    tm = tonemap_exposure(a, exposure)
    srgb = linear_to_srgb(tm)
    return np.clip(np.round(srgb * 255.0), 0, 255).astype(np.uint8)
