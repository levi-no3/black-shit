"""BlendClone NATIVE tests/test_render.py — stdlib unittest for CPU render subsystem."""
import math
import unittest

import numpy as np

from render.color import float_to_uint8, linear_to_srgb, srgb_to_linear, tonemap_exposure
from render.lights import dir_light, pack_lights, point_light, set_lights
from render.material import create_material, pack_material_ubo
from render.pathtracer import gen_ray, intersect_sphere, intersect_tri, render_tile


class TestSphere(unittest.TestCase):
    def test_hit_t4(self):
        t = intersect_sphere([0, 0, 0], [0, 0, -1], [0, 0, -5], 1.0)
        self.assertAlmostEqual(float(t), 4.0, places=6)

    def test_miss(self):
        t = intersect_sphere([0, 0, 0], [0, 1, 0], [0, 0, -5], 1.0)
        self.assertEqual(float(t), -1.0)

    def test_inside_returns_exit(self):
        t = intersect_sphere([0, 0, -5], [0, 0, -1], [0, 0, -5], 1.0)
        self.assertAlmostEqual(float(t), 1.0, places=6)


class TestTri(unittest.TestCase):
    TRI = ([-1, -1, -5], [1, -1, -5], [0, 1, -5])

    def test_hit(self):
        t = intersect_tri([0, 0, 0], [0, 0, -1], *self.TRI)
        self.assertGreater(float(t), 0.0)
        self.assertAlmostEqual(float(t), 5.0, places=6)

    def test_miss(self):
        t = intersect_tri([0, 0, 0], [0, 1, 0], *self.TRI)
        self.assertEqual(float(t), -1.0)


class TestGenRay(unittest.TestCase):
    def test_center_ray(self):
        o, d = gen_ray([0, 0, 0], [0, 0, -1], 0.5, 0.5)
        np.testing.assert_allclose(o, [0, 0, 0])
        np.testing.assert_allclose(d, [0, 0, -1], atol=1e-9)
        self.assertAlmostEqual(float(np.linalg.norm(d)), 1.0, places=9)


class TestRenderTile(unittest.TestCase):
    def test_shape_and_lit(self):
        mat = create_material(base_color=(0.9, 0.2, 0.2))
        scene = {
            "spheres": [{"center": [0, 0, -5], "radius": 1.0, "material": mat}],
            "tris": [],
            "lights": [dir_light(direction=[0, 0, 1], intensity=2.0)],
        }
        cam = {"pos": [0, 0, 0], "dir": [0, 0, -1]}
        img = render_tile(scene, cam, 32, 32, spp=1)
        self.assertEqual(img.shape, (32, 32, 3))
        self.assertEqual(img.dtype, np.float32)
        lit = np.asarray(img).reshape(-1, 3).max(axis=1)
        self.assertGreater(int((lit > 0.05).sum()), 10, "expected lit pixels on sphere")

    def test_deterministic(self):
        scene = {"spheres": [{"center": [0, 0, -4], "radius": 0.5}],
                 "lights": [point_light(position=[2, 2, 0], intensity=5.0)]}
        cam = {"pos": [0, 0, 0], "dir": [0, 0, -1]}
        a = render_tile(scene, cam, 16, 16, spp=1)
        b = render_tile(scene, cam, 16, 16, spp=1)
        np.testing.assert_array_equal(a, b)


class TestColor(unittest.TestCase):
    def test_srgb_endpoints(self):
        self.assertEqual(linear_to_srgb(0.0), 0.0)
        self.assertEqual(linear_to_srgb(-1.0), 0.0)
        self.assertEqual(linear_to_srgb(1.0), 1.0)
        self.assertAlmostEqual(float(linear_to_srgb(0.5)), 0.7353569, places=5)

    def test_roundtrip(self):
        for v in (0.05, 0.2, 0.5, 0.8):
            s = float(linear_to_srgb(v))
            back = float(srgb_to_linear(s))
            self.assertAlmostEqual(back, v, places=4)

    def test_tonemap_reinhard(self):
        self.assertAlmostEqual(float(tonemap_exposure(1.0, 0.0)), 0.5)
        self.assertAlmostEqual(float(tonemap_exposure(0.0, 0.0)), 0.0)

    def test_float_to_uint8(self):
        buf = np.array([[[0.0, 0.0, 0.0], [10.0, 10.0, 10.0]]], dtype=np.float64)
        u8 = float_to_uint8(buf)
        self.assertEqual(u8.shape, (1, 2, 3))
        self.assertEqual(u8.dtype, np.uint8)
        np.testing.assert_array_equal(u8[0, 0], [0, 0, 0])
        self.assertTrue(int(u8[0, 1, 0]) > 200)


class TestMaterialLights(unittest.TestCase):
    def test_pack_shapes(self):
        m = create_material()
        p = pack_material_ubo(m)
        self.assertEqual(p["data"].shape, (8,))
        self.assertEqual(p["bytes"], 32)
        L = set_lights([dir_light()])
        self.assertEqual(len(L), 1)
        pk = pack_lights(L)
        self.assertEqual(pk["data"].shape, (64,))
        self.assertEqual(pk["count"], 1)
        with self.assertRaises(ValueError):
            set_lights([dir_light()] * 9)


if __name__ == "__main__":
    unittest.main()
