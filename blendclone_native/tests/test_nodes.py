"""Unittests for shading.nodes — no Qt."""
import unittest

import numpy as np

from shading.nodes import NodeGraph
from render.material import Material


class TestNodes(unittest.TestCase):
    def test_principled_passthrough(self):
        g = NodeGraph()
        p = g.add_node("Principled", {"baseColor": [0.1, 0.2, 0.3],
                                      "metallic": 0.7, "roughness": 0.25,
                                      "emissive": [0.0, 0.1, 0.0]})
        o = g.add_node("Output")
        g.link(p, "shader", o, "surface")
        m = g.evaluate()
        self.assertIsInstance(m, Material)
        np.testing.assert_allclose(np.asarray(m.base_color, float),
                                   [0.1, 0.2, 0.3], atol=1e-9)
        self.assertAlmostEqual(m.metallic, 0.7)
        self.assertAlmostEqual(m.roughness, 0.25)
        np.testing.assert_allclose(np.asarray(m.emissive, float),
                                   [0.0, 0.1, 0.0], atol=1e-9)

    def test_mix_half_blends(self):
        g = NodeGraph()
        mx = g.add_node("Mix", {"fac": 0.5, "a": [0.0, 0.0, 0.0],
                                "b": [1.0, 1.0, 1.0]})
        p = g.add_node("Principled", {"metallic": 0.0, "roughness": 0.5})
        o = g.add_node("Output")
        g.link(mx, "color", p, "baseColor")
        g.link(p, "shader", o, "surface")
        m = g.evaluate()
        np.testing.assert_allclose(np.asarray(m.base_color, float),
                                   [0.5, 0.5, 0.5], atol=1e-9)

    def test_dict_round_trip(self):
        g = NodeGraph()
        p = g.add_node("Principled", {"baseColor": [0.9, 0.1, 0.1]})
        o = g.add_node("Output")
        g.link(p, "shader", o, "surface")
        d = g.to_dict()
        import json
        json.dumps(d)  # must be JSON-safe
        g2 = NodeGraph.from_dict(d)
        self.assertEqual(g2.to_dict(), d)
        m1, m2 = g.evaluate(), g2.evaluate()
        np.testing.assert_allclose(np.asarray(m1.base_color, float),
                                   np.asarray(m2.base_color, float))

    def test_missing_output_returns_default(self):
        g = NodeGraph()
        g.add_node("Principled", {"baseColor": [1.0, 0.0, 0.0]})
        m = g.evaluate()  # no Output linked: sane default, no raise
        self.assertIsInstance(m, Material)
        np.testing.assert_allclose(np.asarray(m.base_color, float),
                                   [0.8, 0.8, 0.8], atol=1e-9)


if __name__ == "__main__":
    unittest.main()
