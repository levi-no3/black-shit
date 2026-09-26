"""BlendClone NATIVE modeling tests (stdlib unittest, numpy allowed)."""
import math
import unittest

import numpy as np

from fileio.obj import export_obj, import_obj
from modeling.mesh import Mesh
from modeling.primitives import create_cube, create_cylinder, create_plane, create_uv_sphere
from modeling.transform import translate


class TestModeling(unittest.TestCase):
    def test_cube_counts(self):
        m = create_cube(2.0)
        self.assertEqual(m.vert_count, 24)
        self.assertEqual(m.tri_count, 12)
        self.assertEqual(m.indices.size, 36)
        self.assertEqual(m.positions.shape, (24, 3))
        self.assertEqual(m.normals.shape, (24, 3))

    def test_sphere_tris_and_unit_normals(self):
        m = create_uv_sphere(32, 16)
        self.assertGreater(m.tri_count, 0)
        lens = np.linalg.norm(m.normals.astype(np.float64), axis=1)
        self.assertTrue(np.allclose(lens, 1.0, atol=1e-5))

    def test_obj_round_trip_cube(self):
        m = create_cube(2.0)
        m2 = import_obj(export_obj(m, "Cube"))
        self.assertEqual(m2.vert_count, 24)
        self.assertEqual(m2.tri_count, 12)
        self.assertTrue(np.allclose(np.sort(m.positions.flatten()),
                                    np.sort(m2.positions.flatten()), atol=1e-6))

    def test_obj_ngon_negative_indices(self):
        txt = "o t\nv 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\nf -4 -3 -2 -1\n"
        m = import_obj(txt)
        self.assertEqual(m.tri_count, 2)

    def test_transform_moves_bounds(self):
        m = create_cube(2.0)
        c0, _, _ = m.compute_bounds()
        translate(m, 5.0, 0.0, 0.0)
        c1, size, radius = m.compute_bounds()
        self.assertAlmostEqual(float(c1[0]) - float(c0[0]), 5.0, places=5)
        self.assertAlmostEqual(float(c1[1]), float(c0[1]), places=5)
        self.assertTrue(np.allclose(size, (2.0, 2.0, 2.0), atol=1e-5))
        self.assertAlmostEqual(radius, math.sqrt(3.0), places=5)

    def test_merge_welds_flat_cube(self):
        m = create_cube(2.0)
        m.recalc_normals(flat=True)
        self.assertEqual(m.vert_count, 36)
        m.merge_verts(1e-4)
        self.assertEqual(m.vert_count, 8)
        self.assertEqual(m.tri_count, 12)

    def test_plane_cylinder_sane(self):
        pl = create_plane(2.0)
        self.assertEqual(pl.tri_count, 2)
        cy = create_cylinder(32)
        self.assertGreater(cy.tri_count, 0)
        self.assertTrue(np.allclose(np.linalg.norm(cy.normals, axis=1), 1.0, atol=1e-3))

    def test_clone_bytesize(self):
        m = create_cube()
        c = m.clone()
        self.assertEqual(c.vert_count, m.vert_count)
        self.assertEqual(c.byte_size(), m.byte_size())
        self.assertIsNot(c.positions, m.positions)


if __name__ == "__main__":
    unittest.main()
