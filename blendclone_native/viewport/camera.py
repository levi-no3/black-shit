"""BlendClone native OrbitCamera — port of blendclone/src/viewport/{math,camera}.js.

Conventions (same as web): spherical eye around target, Y-up, 0.005 rad/px
orbit speed, exponential dolly, column-major math expressed as row-major
numpy (4,4) float32 matrices for OpenGL uniforms.
"""
from __future__ import annotations

import math

import numpy as np

MIN_PHI = 0.05
MAX_PHI = math.pi - 0.05
MIN_R = 0.1
MAX_R = 1000.0
_UP = np.array([0.0, 1.0, 0.0], dtype=np.float32)


def perspective(fov: float, aspect: float, near: float, far: float) -> np.ndarray:
    """Perspective matrix (row-major), depth maps [n..f] -> [-1..1]."""
    t = 1.0 / math.tan(fov / 2.0)
    m = np.zeros((4, 4), dtype=np.float32)
    m[0, 0] = t / aspect
    m[1, 1] = t
    m[2, 2] = (far + near) / (near - far)
    m[2, 3] = (2.0 * far * near) / (near - far)
    m[3, 2] = -1.0
    return m


def look_at(eye: np.ndarray, target: np.ndarray, up: np.ndarray = _UP) -> np.ndarray:
    """Row-major lookAt matching mat4LookAt in math.js."""
    eye = np.asarray(eye, dtype=np.float32)
    target = np.asarray(target, dtype=np.float32)
    up = np.asarray(up, dtype=np.float32)
    z = eye - target
    z /= (np.linalg.norm(z) or 1.0)
    x = np.cross(up, z)
    x /= (np.linalg.norm(x) or 1.0)
    y = np.cross(z, x)
    m = np.eye(4, dtype=np.float32)
    m[0, :3] = x
    m[1, :3] = y
    m[2, :3] = z
    m[0, 3] = -float(x @ eye)
    m[1, 3] = -float(y @ eye)
    m[2, 3] = -float(z @ eye)
    return m


class OrbitCamera:
    """Spherical orbit camera around a target point."""

    def __init__(self, target=(0.0, 0.0, 0.0), radius: float = 6.0,
                 theta: float = 0.7, phi: float = 1.1,
                 fov_deg: float = 50.0, near: float = 0.1, far: float = 100.0):
        self.target = np.array(target, dtype=np.float32)
        self.radius = float(radius)
        self.theta = float(theta)
        self.phi = float(min(MAX_PHI, max(MIN_PHI, phi)))
        self.fov = math.radians(fov_deg)
        self.near = float(near)
        self.far = float(far)

    def orbit(self, dx: float, dy: float) -> None:
        self.theta -= dx * 0.005
        self.phi = min(MAX_PHI, max(MIN_PHI, self.phi - dy * 0.005))

    def pan(self, dx: float, dy: float) -> None:
        eye = self.get_eye()
        f = self.target - eye
        f /= (np.linalg.norm(f) or 1.0)
        r = np.cross(f, _UP)
        r /= (np.linalg.norm(r) or 1.0)
        u = np.cross(r, f)
        s = self.radius * 0.0016
        self.target = (self.target - r * np.float32(dx * s)
                       + u * np.float32(dy * s)).astype(np.float32)

    def dolly(self, factor: float) -> None:
        self.radius = float(min(MAX_R, max(MIN_R, self.radius * math.exp(factor))))

    def get_eye(self) -> np.ndarray:
        sp = math.sin(self.phi)
        return np.array([
            self.target[0] + self.radius * sp * math.sin(self.theta),
            self.target[1] + self.radius * math.cos(self.phi),
            self.target[2] + self.radius * sp * math.cos(self.theta),
        ], dtype=np.float32)

    def get_view(self) -> np.ndarray:
        return look_at(self.get_eye(), self.target, _UP)

    def get_proj(self, aspect: float = 1.0) -> np.ndarray:
        return perspective(self.fov, aspect, self.near, self.far)

    def get_ray(self, nx: float, ny: float, aspect: float = 1.0):
        """World-space picking ray through NDC point in [-1..1]."""
        vp = self.get_proj(aspect) @ self.get_view()
        try:
            inv = np.linalg.inv(vp)
        except np.linalg.LinAlgError:
            return np.zeros(3, np.float32), np.array([0, 0, -1], np.float32)
        p0 = inv @ np.array([nx, ny, -1.0, 1.0], dtype=np.float32)
        p1 = inv @ np.array([nx, ny, 1.0, 1.0], dtype=np.float32)
        p0 = p0[:3] / (p0[3] or 1.0)
        p1 = p1[:3] / (p1[3] or 1.0)
        d = p1 - p0
        d /= (np.linalg.norm(d) or 1.0)
        return p0.astype(np.float32), d.astype(np.float32)
