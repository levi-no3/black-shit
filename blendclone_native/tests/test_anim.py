"""Animation clip tests — stdlib unittest, numpy only (no Qt)."""
import json
import sys
import unittest

import numpy as np

from anim.clip import Clip, Keyframe, Track


class _T:
    """Minimal Transform-like stub (.pos/.rot_euler/.scale)."""

    def __init__(self, pos, rot, scale):
        self.pos = np.asarray(pos, float)
        self.rot_euler = np.asarray(rot, float)
        self.scale = np.asarray(scale, float)


class TestClip(unittest.TestCase):
    def test_lerp_midpoint(self):
        c = Clip()
        c.set_key(1, 10, _T((0, 0, 0), (0, 0, 0), (1, 1, 1)))
        c.set_key(1, 20, _T((10, 0, 0), (0, 1.0, 0), (3, 3, 3)))
        pos, rot, scl = c.eval(1, 15)
        np.testing.assert_allclose(pos, (5, 0, 0), atol=1e-6)
        np.testing.assert_allclose(rot, (0, 0.5, 0), atol=1e-6)
        np.testing.assert_allclose(scl, (2, 2, 2), atol=1e-6)

    def test_single_key_step(self):
        c = Clip()
        c.set_key(7, 5, _T((1, 2, 3), (0.1, 0.2, 0.3), (2, 2, 2)))
        for f in (1, 5, 100):
            pos, rot, scl = c.eval(7, f)
            np.testing.assert_allclose(pos, (1, 2, 3), atol=1e-6)
            np.testing.assert_allclose(rot, (0.1, 0.2, 0.3), atol=1e-6)
            np.testing.assert_allclose(scl, (2, 2, 2), atol=1e-6)

    def test_delete(self):
        c = Clip()
        c.set_key(1, 10, _T((0, 0, 0), (0, 0, 0), (1, 1, 1)))
        c.set_key(1, 20, _T((10, 0, 0), (0, 0, 0), (1, 1, 1)))
        self.assertTrue(c.delete_key(1, 10))
        pos, _, _ = c.eval(1, 1)  # clamps to remaining key
        np.testing.assert_allclose(pos, (10, 0, 0), atol=1e-6)
        self.assertFalse(c.delete_key(1, 10))  # already gone
        self.assertFalse(c.delete_key(999, 10))  # unknown object
        self.assertIsNone(c.eval(999, 10))

    def test_dict_round_trip(self):
        c = Clip(fps=30)
        c.set_key(1, 10, _T((0, 0, 0), (0, 0, 0), (1, 1, 1)))
        c.set_key(1, 20, _T((10, 0, 0), (0, 1.0, 0), (3, 3, 3)))
        c.set_key(2, 1, _T((5, 5, 5), (0, 0, 0), (1, 1, 1)))
        d2 = json.loads(json.dumps(c.to_dict()))  # must be JSON-safe
        c2 = Clip.from_dict(d2)
        self.assertEqual(c2.fps, 30)
        for obj, fr in ((1, 15), (1, 1), (2, 50)):
            for a, b in zip(c.eval(obj, fr), c2.eval(obj, fr)):
                np.testing.assert_allclose(a, b, atol=1e-6)

    def test_no_qt_imported(self):
        import pathlib
        src = pathlib.Path(__file__).parent.parent.joinpath("anim", "clip.py").read_text()
        self.assertNotIn("PySide6", src)
        self.assertNotIn("PyQt", src)


if __name__ == "__main__":
    unittest.main()
