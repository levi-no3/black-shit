"""BlendClone NATIVE app-wiring tests — MODELING <-> viewport adapter + I/O.

Pure-logic unittest: NO QApplication instance is created. QT_QPA_PLATFORM
is set defensively before any Qt import, but Qt is only imported (never
instantiated) via `app` / `viewport.glwidget`.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest

import numpy as np

from app import (export_obj, import_obj, load_scene, modeling_mesh_to_viewport,
                 save_scene, viewport_mesh_to_modeling)
from modeling.primitives import create_cube, create_uv_sphere
from viewport.glwidget import ViewportGL


class TestAdapter(unittest.TestCase):
    def test_adapter_exists_and_cube_tris(self):
        self.assertTrue(callable(modeling_mesh_to_viewport))
        m = create_cube()
        d = modeling_mesh_to_viewport(m)
        for k in ("positions", "normals", "indices"):
            self.assertIn(k, d)
        self.assertEqual(int(np.asarray(d["indices"]).size // 3), m.tri_count)
        self.assertEqual(m.tri_count, 12)
        self.assertEqual(np.asarray(d["positions"]).shape[0], m.vert_count)

    def test_adapter_sphere_tris(self):
        m = create_uv_sphere(24, 12, 1.0)
        d = modeling_mesh_to_viewport(m)
        self.assertEqual(int(np.asarray(d["indices"]).size // 3), m.tri_count)
        self.assertGreater(m.tri_count, 0)
        back = viewport_mesh_to_modeling(d, "Sphere")
        self.assertEqual(back.tri_count, m.tri_count)


class TestObjViaAdapter(unittest.TestCase):
    def test_export_import_round_trip_cube(self):
        m = create_cube(2.0)
        d = modeling_mesh_to_viewport(m)
        m2 = viewport_mesh_to_modeling(d, "Cube")
        text = export_obj(m2, "Cube")
        m3 = import_obj(text)
        self.assertEqual(m3.tri_count, 12)
        self.assertTrue(np.allclose(np.sort(m.positions.flatten()),
                                    np.sort(m3.positions.flatten()), atol=1e-6))

    def test_export_import_round_trip_sphere(self):
        m = create_uv_sphere(24, 12, 1.0)
        d = modeling_mesh_to_viewport(m)
        m2 = viewport_mesh_to_modeling(d, "Sphere")
        m3 = import_obj(export_obj(m2, "Sphere"))
        self.assertEqual(m3.tri_count, m.tri_count)


class TestSceneJson(unittest.TestCase):
    def test_save_load_round_trip(self):
        cube = create_cube(2.0)
        cube.name = "Cube"
        sph = create_uv_sphere(12, 6, 1.0)
        sph.name = "Sphere"
        text = save_scene({"meshes": [("Cube", cube), ("Sphere", sph)]})
        data = load_scene(text)
        self.assertEqual(data.get("version"), 1)
        got = {m.name: m for m in data["meshes"]}
        self.assertEqual(set(got), {"Cube", "Sphere"})
        self.assertEqual(got["Cube"].tri_count, 12)
        self.assertEqual(got["Sphere"].tri_count, sph.tri_count)
        # Geometry survives JSON: viewport adapter tri counts match.
        for name, orig in (("Cube", cube), ("Sphere", sph)):
            d = modeling_mesh_to_viewport(got[name])
            self.assertEqual(int(np.asarray(d["indices"]).size // 3),
                             orig.tri_count)


class TestGlWidgetApi(unittest.TestCase):
    def test_viewport_mutation_api_exists(self):
        for fn in ("update_object_mesh", "delete_selected", "duplicate_selected"):
            self.assertTrue(hasattr(ViewportGL, fn), f"ViewportGL.{fn} missing")


if __name__ == "__main__":
    unittest.main()
