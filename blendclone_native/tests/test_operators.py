"""Operators tests: extrude/inset/delete/loopcut/subdiv (numpy only)."""
import unittest

import numpy as np

from modeling.mesh import Mesh
from modeling.primitives import create_cube, create_plane
from modeling.operators import (
    delete_faces,
    extrude_faces,
    inset_faces,
    loop_cut_stub,
    triangulate_fan,
)
from modeling.modifiers import subdiv_stub


def _tri_areas(m):
    p = np.asarray(m.positions, np.float64)
    t = np.asarray(m.indices, np.uint32).reshape(-1, 3)
    e1 = p[t[:, 1]] - p[t[:, 0]]
    e2 = p[t[:, 2]] - p[t[:, 0]]
    return 0.5 * np.linalg.norm(np.cross(e1, e2), axis=1)


class TestOperators(unittest.TestCase):
    def test_extrude_one_face_grows(self):
        m = create_cube(2.0)
        v0, t0 = m.vert_count, m.tri_count
        _, size0, _ = m.compute_bounds()
        extrude_faces(m, [0, 1], 0.5)
        # one quad face: U=4 new verts, K=2 cap + 8 wall tris
        self.assertEqual(m.vert_count, v0 + 4)
        self.assertEqual(m.tri_count, t0 + 10)
        self.assertEqual(m.indices.size, m.tri_count * 3)
        self.assertTrue(int(m.indices.max()) < m.vert_count)
        self.assertEqual(m.positions.dtype, np.float32)
        self.assertEqual(m.indices.dtype, np.uint32)
        _, size1, _ = m.compute_bounds()
        self.assertGreater(float(size1[2]), float(size0[2]) + 0.4)
        self.assertFalse(bool(np.isnan(m.positions).any()))

    def test_inset_shrinks_area(self):
        m = create_cube(2.0)
        before = float(_tri_areas(m)[[0, 1]].sum())
        v0, t0 = m.vert_count, m.tri_count
        inset_faces(m, [0, 1], 0.3)
        after = float(_tri_areas(m)[[0, 1]].sum())
        self.assertEqual(m.vert_count, v0)
        self.assertEqual(m.tri_count, t0)
        self.assertLess(after, before * 0.95)

    def test_delete_faces_cube(self):
        m = create_cube(2.0)
        delete_faces(m, [0, 1])
        self.assertEqual(m.tri_count, 10)
        self.assertEqual(m.vert_count, 20)
        self.assertTrue(int(m.indices.max()) < m.vert_count)

    def test_loop_cut_plane(self):
        m = create_plane(2.0)
        self.assertEqual(m.tri_count, 2)
        loop_cut_stub(m, axis="x", t=0.5)
        self.assertGreaterEqual(m.tri_count, 4)
        self.assertGreater(m.vert_count, 4)
        self.assertTrue(int(m.indices.max()) < m.vert_count)

    def test_subdiv_quadruples(self):
        m = create_cube(2.0)
        m2 = subdiv_stub(m, levels=1)
        self.assertEqual(m2.tri_count, 12 * 4)
        self.assertEqual(m2.indices.size, m2.tri_count * 3)
        self.assertTrue(int(m2.indices.max()) < m2.vert_count)

    def test_fan(self):
        f = triangulate_fan(5)
        self.assertEqual(tuple(f.shape), (3, 3))
        self.assertEqual(f.dtype, np.uint32)


if __name__ == "__main__":
    unittest.main()
