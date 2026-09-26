"""BlendClone NATIVE — mat4 helpers (row-major (4,4) float32) + Mesh ops."""
from __future__ import annotations

import numpy as np


def mat_identity() -> np.ndarray:
    return np.eye(4, dtype=np.float32)


def mat_mul(a, b) -> np.ndarray:
    """Return a @ b (b applies first, column-vector convention)."""
    return np.ascontiguousarray(
        np.asarray(a, dtype=np.float32).reshape(4, 4).astype(np.float64)
        @ np.asarray(b, dtype=np.float32).reshape(4, 4).astype(np.float64),
        dtype=np.float32)


def translation(x: float, y: float, z: float) -> np.ndarray:
    m = np.eye(4, dtype=np.float32)
    m[:3, 3] = (float(x), float(y), float(z))
    return m


def scaling(x: float, y=None, z=None) -> np.ndarray:
    if y is None:
        y = x
    if z is None:
        z = x
    m = np.eye(4, dtype=np.float32)
    m[0, 0], m[1, 1], m[2, 2] = float(x), float(y), float(z)
    return m


def rotation_x(rad: float) -> np.ndarray:
    c, s = float(np.cos(rad)), float(np.sin(rad))
    return np.array([[1, 0, 0, 0], [0, c, -s, 0], [0, s, c, 0], [0, 0, 0, 1]],
                    dtype=np.float32)


def rotation_y(rad: float) -> np.ndarray:
    c, s = float(np.cos(rad)), float(np.sin(rad))
    return np.array([[c, 0, s, 0], [0, 1, 0, 0], [-s, 0, c, 0], [0, 0, 0, 1]],
                    dtype=np.float32)


def rotation_z(rad: float) -> np.ndarray:
    c, s = float(np.cos(rad)), float(np.sin(rad))
    return np.array([[c, -s, 0, 0], [s, c, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]],
                    dtype=np.float32)


# JS-parity aliases (JS was column-major; values are identical transforms).
mat4_identity = mat_identity
mat4Identity = mat_identity
mat4_multiply = mat_mul
mat4Multiply = mat_mul
mat4_translate = translation
mat4Translate = translation
mat4_scale = scaling
mat4Scale = scaling
mat4_rotate_x = rotation_x
mat4RotateX = rotation_x
mat4_rotate_y = rotation_y
mat4RotateY = rotation_y
mat4_rotate_z = rotation_z
mat4RotateZ = rotation_z


# --- Mesh ops (mutate + return mesh for chaining) ---
def translate(mesh, x: float, y: float, z: float):
    return mesh.apply_matrix(translation(x, y, z))


def scale(mesh, x: float, y=None, z=None):
    return mesh.apply_matrix(scaling(x, y, z))


def rotate_x(mesh, rad: float):
    return mesh.apply_matrix(rotation_x(rad))


def rotate_y(mesh, rad: float):
    return mesh.apply_matrix(rotation_y(rad))


def rotate_z(mesh, rad: float):
    return mesh.apply_matrix(rotation_z(rad))


def rotate(mesh, axis: str, rad: float):
    fn = {"x": rotate_x, "y": rotate_y, "z": rotate_z}[axis.lower()]
    return fn(mesh, rad)


# camelCase aliases
rotateX = rotate_x
rotateY = rotate_y
rotateZ = rotate_z
