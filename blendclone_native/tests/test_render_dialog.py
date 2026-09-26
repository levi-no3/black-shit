"""Tests for render dialog proxies + modeling modifiers (no Qt event loop)."""
import unittest

import numpy as np

from modeling.modifiers import array_modifier, mirror_modifier, subdiv_stub
from modeling.primitives import create_cube
from render.lights import dir_light
from render.material import create_material
from render.pathtracer import render_tile


class TestModifiers(unittest.TestCase):
    def test_mirror_doubles(self):
        m = create_cube(2.0)
        out = mirror_modifier(m, axis="x")
        self.assertEqual(out.tri_count, m.tri_count * 2)
        self.assertEqual(out.vert_count, m.vert_count * 2)

    def test_array_triples(self):
        m = create_cube(2.0)
        out = array_modifier(m, count=3, offset=(3.0, 0.0, 0.0))
        self.assertEqual(out.tri_count, m.tri_count * 3)

    def test_subdiv_quadruples(self):
        m = create_cube(2.0)
        out = subdiv_stub(m, levels=1)
        self.assertEqual(out.tri_count, m.tri_count * 4)


class TestRenderTileDialog(unittest.TestCase):
    def test_deterministic_nonzero(self):
        mat = create_material(base_color=(0.9, 0.2, 0.2))
        scene = {"spheres": [{"center": [0, 0, -5], "radius": 1.0, "material": mat}],
                 "tris": [], "lights": [dir_light(direction=[0, 0, 1], intensity=2.0)]}
        cam = {"pos": [0, 0, 0], "dir": [0, 0, -1]}
        a = render_tile(scene, cam, 32, 32, spp=1)
        b = render_tile(scene, cam, 32, 32, spp=1)
        self.assertEqual(a.shape, (32, 32, 3))
        np.testing.assert_array_equal(a, b)
        lit = np.asarray(a).reshape(-1, 3).max(axis=1)
        self.assertGreater(int((lit > 0.05).sum()), 10)


if __name__ == "__main__":
    unittest.main()
