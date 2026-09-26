"""Animation clip: per-object keyframed pos/rot/scale, numpy only (no Qt).

Frames are ints; eval() accepts int/float and linearly interpolates
position, euler rotation and scale. A single key behaves as step (hold);
out-of-range frames clamp to the nearest key. Deterministic: keyframes
are kept sorted by frame, replacements at the same frame are exact.
"""
from __future__ import annotations

import numpy as np

__all__ = ["Keyframe", "Track", "Clip"]


def _vec3(v) -> np.ndarray:
    a = np.asarray(v, dtype=np.float32).reshape(-1)
    if a.shape != (3,):
        raise ValueError(f"expected 3-vector, got shape {a.shape}")
    return a.copy()


def _coerce_transform(t) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Accept a Transform-like (.pos/.rot_euler/.scale) or a triple."""
    if hasattr(t, "pos") and hasattr(t, "rot_euler") and hasattr(t, "scale"):
        return _vec3(t.pos), _vec3(t.rot_euler), _vec3(t.scale)
    if isinstance(t, (list, tuple)) and len(t) == 3:
        return _vec3(t[0]), _vec3(t[1]), _vec3(t[2])
    raise TypeError("transform: expected Transform-like or (pos, rot, scale)")


class Keyframe:
    def __init__(self, frame: int, pos, rot_euler, scale):
        self.frame = int(frame)
        self.pos = _vec3(pos)
        self.rot_euler = _vec3(rot_euler)
        self.scale = _vec3(scale)

    def values(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        return self.pos.copy(), self.rot_euler.copy(), self.scale.copy()

    def to_dict(self) -> dict:
        return {"frame": self.frame, "pos": [float(x) for x in self.pos],
                "rot": [float(x) for x in self.rot_euler],
                "scale": [float(x) for x in self.scale]}

    @classmethod
    def from_dict(cls, d: dict) -> "Keyframe":
        rot = d.get("rot", d.get("rot_euler"))
        return cls(int(d["frame"]), d["pos"], rot, d["scale"])

    def __repr__(self) -> str:
        return (f"Keyframe(frame={self.frame}, pos={self.pos.tolist()}, "
                f"rot={self.rot_euler.tolist()}, scale={self.scale.tolist()})")


class Track:
    """Sorted keyframes for one object id."""

    def __init__(self, obj_id, keyframes=()):
        self.obj_id = obj_id
        self.keyframes: list[Keyframe] = []
        for k in keyframes:
            if isinstance(k, Keyframe):
                self.set(k.frame, k.pos, k.rot_euler, k.scale)
            else:
                self.set(k["frame"], k["pos"],
                         k.get("rot", k.get("rot_euler")), k["scale"])

    def set(self, frame: int, pos, rot_euler, scale) -> Keyframe:
        kf = Keyframe(frame, pos, rot_euler, scale)
        for i, old in enumerate(self.keyframes):
            if old.frame == kf.frame:
                self.keyframes[i] = kf
                return kf
        self.keyframes.append(kf)
        self.keyframes.sort(key=lambda k: k.frame)
        return kf

    def delete(self, frame: int) -> bool:
        for i, old in enumerate(self.keyframes):
            if old.frame == int(frame):
                del self.keyframes[i]
                return True
        return False

    def eval(self, frame) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
        ks = self.keyframes
        if not ks:
            return None
        f = float(frame)
        if len(ks) == 1 or f <= ks[0].frame:
            return ks[0].values()
        if f >= ks[-1].frame:
            return ks[-1].values()
        for a, b in zip(ks, ks[1:]):
            if a.frame <= f <= b.frame:
                span = b.frame - a.frame
                t = 0.0 if span == 0 else (f - a.frame) / span
                pos = (a.pos * (1.0 - t) + b.pos * t).astype(np.float32)
                rot = (a.rot_euler * (1.0 - t) + b.rot_euler * t).astype(np.float32)
                scl = (a.scale * (1.0 - t) + b.scale * t).astype(np.float32)
                return pos, rot, scl
        return ks[-1].values()  # unreachable; deterministic fallback

    def to_dict(self) -> list:
        return [k.to_dict() for k in self.keyframes]

    @classmethod
    def from_dict(cls, obj_id, data: list) -> "Track":
        return cls(obj_id, [Keyframe.from_dict(d) for d in data or []])


class Clip:
    """All animated tracks; keyed by object id. fps informational only."""

    def __init__(self, fps: int = 24, tracks: dict | None = None):
        self.fps = int(fps)
        self.tracks: dict = dict(tracks) if tracks else {}

    def set_key(self, obj_id, frame: int, transform) -> Keyframe:
        pos, rot, scl = _coerce_transform(transform)
        tr = self.tracks.get(obj_id)
        if tr is None:
            tr = Track(obj_id)
            self.tracks[obj_id] = tr
        return tr.set(int(frame), pos, rot, scl)

    def eval(self, obj_id, frame) -> tuple | None:
        tr = self.tracks.get(obj_id)
        return None if tr is None else tr.eval(frame)

    def delete_key(self, obj_id, frame: int) -> bool:
        tr = self.tracks.get(obj_id)
        if tr is None:
            return False
        ok = tr.delete(int(frame))
        if not tr.keyframes:
            del self.tracks[obj_id]
        return ok

    def to_dict(self) -> dict:
        return {"fps": self.fps,
                "tracks": {str(k): v.to_dict()
                           for k, v in sorted(self.tracks.items(),
                                              key=lambda kv: str(kv[0]))}}

    @classmethod
    def from_dict(cls, d: dict) -> "Clip":
        tracks = {}
        for k, v in (d.get("tracks") or {}).items():
            try:
                obj_id: object = int(k)
            except (TypeError, ValueError):
                obj_id = k
            tracks[obj_id] = Track.from_dict(obj_id, v)
        return cls(int(d.get("fps", 24)), tracks)
