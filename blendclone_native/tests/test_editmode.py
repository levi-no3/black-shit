"""BlendClone NATIVE edit-mode tests — pure logic, NO QApplication.

Covers: ray-tri helper hits cube face at expected distance,
face-delete reduces triCount by N, selection set add/clear semantics.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest

import numpy as np

from modeling.operators import delete_faces
from modeling.primitives import create_cube
from viewport.glwidget import ViewportGL
from viewport.picking import (apply_face_click, clear_faces, delete_faces_dict,
                              ray_triangle_intersect, raycast_mesh)
from viewport.scene import make_cube_mesh


class TestRayTri(unittest.TestCase):
    def test_single_triangle_hit_distance(self):
        v0 = np.array([-1.0, -1.0, 0.0])
        v1 = np.array([1.0, -1.0, 0.0])
        v2 = np.array([1.0, 1.0, 0.0])
        ro = np.array([0.0, 0.0, 5.0])
        rd = np.array([0.0, 0.0, -1.0])
        t = ray_triangle_intersect(ro, rd, v0, v1, v2)
        self.assertIsNotNone(t)
        self.assertAlmostEqual(float(t), 5.0, places=5)

    def test_ray_misses_pointing_away(self):
        v0 = np.array([-1.0, -1.0, 0.0])
        v1 = np.array([1.0, -1.0, 0.0])
        v2 = np.array([0.0, 1.0, 0.0])
        ro = np.array([0.0, 0.0, 5.0])
        rd = np.array([0.0, 0.0, 1.0])
        self.assertIsNone(ray_triangle_intersect(ro, rd, v0, v1, v2))

    def test_ray_hits_cube_face_expected_distance(self):
        d = make_cube_mesh(size=1.0)  # half-extent 0.5, front +z face = tris 0,1
        pos = np.asarray(d["positions"], np.float32)
        idx = np.asarray(d["indices"], np.uint32)
        ro = np.array([0.0, 0.0, 5.0], np.float32)
        rd = np.array([0.0, 0.0, -1.0], np.float32)
        face, t = raycast_mesh(pos, idx, ro, rd, None)
        self.assertIsNotNone(face)
        self.assertIn(int(face), (0, 1))
        self.assertAlmostEqual(float(t), 4.5, places=4)

    def test_ray_hits_cube_world_transform(self):
        d = make_cube_mesh(size=1.0)
        pos = np.asarray(d["positions"], np.float32)
        idx = np.asarray(d["indices"], np.uint32)
        model = np.eye(4, dtype=np.float32)
        model[:3, 3] = (0.0, 0.0, 2.0)  # front face now at z=2.5
        ro = np.array([0.0, 0.0, 5.0], np.float32)
        rd = np.array([0.0, 0.0, -1.0], np.float32)
        face, t = raycast_mesh(pos, idx, ro, rd, model)
        self.assertIsNotNone(face)
        self.assertAlmostEqual(float(t), 2.5, places=4)


class TestFaceDelete(unittest.TestCase):
    def test_dict_delete_reduces_tricount(self):
        d = make_cube_mesh(size=1.0)
        before = int(np.asarray(d["indices"]).size // 3)
        self.assertEqual(before, 12)
        delete_faces_dict(d, [0, 1])
        after = int(np.asarray(d["indices"]).size // 3)
        self.assertEqual(after, before - 2)

    def test_modeling_mesh_delete_reduces_tricount(self):
        m = create_cube(2.0)
        self.assertEqual(m.tri_count, 12)
        delete_faces(m, [0, 1, 2])
        self.assertEqual(m.tri_count, 9)

    def test_delete_empty_is_noop(self):
        m = create_cube(2.0)
        delete_faces(m, [])
        self.assertEqual(m.tri_count, 12)

    def test_delete_bad_id_raises(self):
        m = create_cube(2.0)
        with self.assertRaises(ValueError):
            delete_faces(m, [999])


class TestSelectionSets(unittest.TestCase):
    def test_add_clear_semantics(self):
        sel: set = set()
        apply_face_click(sel, 3, additive=False)  # plain click replaces
        self.assertEqual(sel, {3})
        apply_face_click(sel, 5, additive=True)  # shift-click adds
        self.assertEqual(sel, {3, 5})
        apply_face_click(sel, 7, additive=False)  # plain click replaces again
        self.assertEqual(sel, {7})
        clear_faces(sel)
        self.assertEqual(sel, set())
        # shift-click on empty adds; miss with additive keeps, without clears
        apply_face_click(sel, 1, additive=True)
        self.assertEqual(sel, {1})
        apply_face_click(sel, None, additive=True)
        self.assertEqual(sel, {1})
        apply_face_click(sel, None, additive=False)
        self.assertEqual(sel, set())


class TestEditModeApi(unittest.TestCase):
    def test_viewport_edit_api_exists(self):
        for fn in ("set_edit_mode", "get_selected_faces", "clear_face_selection",
                   "delete_selected_faces"):
            self.assertTrue(hasattr(ViewportGL, fn), f"ViewportGL.{fn} missing")
        self.assertTrue(hasattr(ViewportGL, "faceSelectionChanged"))
        self.assertTrue(hasattr(ViewportGL, "editModeChanged"))


if __name__ == "__main__":
    unittest.main()
