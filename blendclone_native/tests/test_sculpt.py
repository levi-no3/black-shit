"""BlendClone NATIVE sculpt tests — pure numpy logic, NO Qt.

Covers: grab moves verts toward delta, smooth reduces variance,
inflate moves along +normal, falloff is 0 at the edge. No in-place
aliasing: inputs are never mutated.
"""
import unittest

import numpy as np

from sculpt.brush import falloff, grab_brush, inflate_brush, smooth_brush


def _grid(n: int = 5, step: float = 0.5) -> np.ndarray:
    xs = (np.arange(n, dtype=np.float32) - (n - 1) / 2.0) * step
    xx, zz = np.meshgrid(xs, xs)
    return np.ascontiguousarray(
        np.stack([xx.ravel(), np.zeros(n * n, np.float32),
                  zz.ravel()], axis=1), dtype=np.float32)


def _grid_tris(n: int = 5) -> np.ndarray:
    idx = []
    for i in range(n - 1):
        for j in range(n - 1):
            a = i * n + j
            b = a + 1
            c = a + n
            e = c + 1
            idx += [a, c, b, b, c, e]
    return np.ascontiguousarray(np.array(idx, dtype=np.uint32))


class TestFalloff(unittest.TestCase):
    def test_center_is_one(self):
        self.assertAlmostEqual(float(falloff(1.0, 0.0)), 1.0, places=6)

    def test_zero_at_edge(self):
        self.assertAlmostEqual(float(falloff(1.0, 1.0)), 0.0, places=6)

    def test_zero_beyond_edge(self):
        self.assertAlmostEqual(float(falloff(1.0, 2.5)), 0.0, places=6)

    def test_monotonic_and_half(self):
        f0 = float(falloff(2.0, 0.0))
        f1 = float(falloff(2.0, 1.0))
        f2 = float(falloff(2.0, 2.0))
        self.assertGreater(f0, f1)
        self.assertGreater(f1, f2)
        self.assertAlmostEqual(f1, 0.5, places=6)

    def test_degenerate_radius_gives_zero(self):
        self.assertAlmostEqual(float(falloff(0.0, 0.0)), 0.0, places=6)


class TestGrab(unittest.TestCase):
    def test_center_vert_moves_by_full_delta(self):
        p = _grid()
        before = p.copy()
        out = grab_brush(p, center=(0.0, 0.0, 0.0),
                         delta=(1.0, 0.0, 0.0), radius=2.0)
        self.assertEqual(out.dtype, np.float32)
        self.assertTrue(np.array_equal(p, before))  # no aliasing
        self.assertIsNot(out, p)
        ci = len(p) // 2  # grid center vert
        np.testing.assert_allclose(out[ci], before[ci] + (1.0, 0.0, 0.0),
                                   atol=1e-6)

    def test_moves_toward_delta_and_edge_pinned(self):
        p = _grid()
        out = grab_brush(p, center=(0.0, 0.0, 0.0),
                         delta=(0.0, 2.0, 0.0), radius=0.6)
        disp = out - p
        self.assertTrue(np.all(disp[:, 1] >= -1e-6))  # toward +Y
        corner = np.linalg.norm(p, axis=1).argmax()
        np.testing.assert_allclose(out[corner], p[corner], atol=1e-6)

    def test_zero_radius_is_noop(self):
        p = _grid()
        np.testing.assert_array_equal(
            grab_brush(p, (0, 0, 0), (1, 0, 0), 0.0), p)


class TestSmooth(unittest.TestCase):
    def test_reduces_variance(self):
        n = 5
        p = _grid(n).copy()
        rng = np.random.RandomState(0)
        noise = (rng.rand(p.shape[0], 1).astype(np.float32) - 0.5) * 0.8
        p[:, 1:2] += noise
        before_var = float(np.var(p[:, 1]))
        snapshot = p.copy()
        out = smooth_brush(p, _grid_tris(n), center=(0.0, 0.0, 0.0),
                           radius=5.0, strength=1.0)
        np.testing.assert_array_equal(p, snapshot)  # input never mutated
        self.assertLess(float(np.var(out[:, 1])), before_var)

    def test_strength_zero_is_noop(self):
        p = _grid()
        np.testing.assert_array_equal(
            smooth_brush(p, _grid_tris(), (0, 0, 0), 2.0, 0.0), p)

    def test_outside_radius_untouched(self):
        p = _grid()
        out = smooth_brush(p, _grid_tris(), center=(10.0, 0.0, 10.0),
                           radius=0.5, strength=1.0)
        np.testing.assert_array_equal(out, p)


class TestInflate(unittest.TestCase):
    def test_moves_along_plus_normal(self):
        p = _grid()
        nrm = np.zeros_like(p)
        nrm[:, 1] = 1.0
        out = inflate_brush(p, nrm, center=(0.0, 0.0, 0.0),
                            radius=2.0, strength=0.5)
        self.assertTrue(np.array_equal(p[:, 1],
                                        np.zeros(p.shape[0], np.float32)))
        disp = out - p
        self.assertTrue(np.all(disp[:, 1] >= -1e-6))
        ci = len(p) // 2
        self.assertAlmostEqual(float(out[ci, 1]), 0.5, places=5)

    def test_edge_vert_pinned(self):
        p = _grid()
        nrm = np.zeros_like(p)
        nrm[:, 1] = 1.0
        out = inflate_brush(p, nrm, (0, 0, 0), 0.6, 1.0)
        corner = np.linalg.norm(p, axis=1).argmax()
        np.testing.assert_allclose(out[corner], p[corner], atol=1e-6)

    def test_negative_strength_deflates(self):
        p = _grid()
        nrm = np.zeros_like(p)
        nrm[:, 1] = 1.0
        out = inflate_brush(p, nrm, (0, 0, 0), 2.0, -0.25)
        ci = len(p) // 2
        self.assertAlmostEqual(float(out[ci, 1]), -0.25, places=5)


if __name__ == "__main__":
    unittest.main()
