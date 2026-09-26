"""BlendClone NATIVE core/undo.py — Qt-free command undo stack."""
from __future__ import annotations


class _Flag(int):
    """Int 0/1 that is truthy/falsy AND callable (supports can_undo and can_undo())."""

    def __new__(cls, v):
        return super().__new__(cls, 1 if v else 0)

    def __call__(self):
        return bool(self)


class UndoStack:
    """Bounded undo/redo with byte accounting + drag coalescing."""

    def __init__(self, max_steps: int = 50, max_bytes: int = 120 * 1024 * 1024):
        self.max_steps = int(max_steps)
        self.max_bytes = int(max_bytes)
        self._undo: list = []
        self._redo: list = []
        self._bytes = 0

    @property
    def can_undo(self):
        return _Flag(bool(self._undo))

    @property
    def can_redo(self):
        return _Flag(bool(self._redo))

    @property
    def total_bytes(self) -> int:
        return int(self._bytes)

    def __len__(self) -> int:
        return len(self._undo)

    def _evict(self):
        while len(self._undo) > max(0, self.max_steps):
            old = self._undo.pop(0)
            self._bytes -= int(old.get("bytes", 0))
        while self._bytes > self.max_bytes and len(self._undo) > 1:
            old = self._undo.pop(0)
            self._bytes -= int(old.get("bytes", 0))
        if self._bytes < 0:
            self._bytes = 0

    def push(self, label, do_fn, undo_fn, byte_size: int = 0):
        self._redo.clear()
        if callable(do_fn):
            do_fn()
        self._undo.append({"label": label, "do": do_fn, "undo": undo_fn,
                           "bytes": int(byte_size or 0), "key": None})
        self._bytes += int(byte_size or 0)
        self._evict()
        return True

    def push_coalesce(self, key, label, do_fn, undo_fn, byte_size: int = 0):
        self._redo.clear()
        top = self._undo[-1] if self._undo else None
        if top is not None and top.get("key") == key:
            self._bytes -= int(top.get("bytes", 0))
            top["do"] = do_fn
            top["label"] = label
            top["bytes"] = int(byte_size or 0)
            self._bytes += int(byte_size or 0)
            if callable(do_fn):
                do_fn()
            self._evict()
            return False
        if callable(do_fn):
            do_fn()
        self._undo.append({"label": label, "do": do_fn, "undo": undo_fn,
                           "bytes": int(byte_size or 0), "key": key})
        self._bytes += int(byte_size or 0)
        self._evict()
        return True

    def undo(self):
        if not self._undo:
            return False
        e = self._undo.pop()
        self._bytes -= int(e.get("bytes", 0))
        if self._bytes < 0:
            self._bytes = 0
        try:
            if callable(e.get("undo")):
                e["undo"]()
        finally:
            self._redo.append(e)
        return True

    def redo(self):
        if not self._redo:
            return False
        e = self._redo.pop()
        if callable(e.get("do")):
            e["do"]()
        self._undo.append(e)
        self._bytes += int(e.get("bytes", 0))
        return True

    def clear(self):
        self._undo.clear()
        self._redo.clear()
        self._bytes = 0
