"""Rig/armature tests — stdlib unittest, numpy only (no Qt)."""
import json
import math
import unittest

import numpy as np

from rig.armature import Armature, Bone


def _two_bone():
    arm = Armature()
    arm.add_bone(Bone("L", (-1.0, 0.0, 0.0), (0.0, 0.0, 0.0)))
    arm.add_bone(Bone("R", (0.0, 0.0, 0.0), (1.0, 0.0, 0.0)))
    return arm


class TestRig(unittest.TestCase):
    def test_weights_rows_sum_to_one(self):
        arm = _two_bone()
        pos = np.array([[-1, 0, 0], [-0.5, 0, 0], [0.0, 0, 0],
                        [0.5, 0, 0], [1, 0, 0]], dtype=np.float32)
        w = arm.auto_weights_from_x(pos, split_x=0.0)
        self.assertEqual(w.shape, (5, 2))
        self.assertEqual(w.dtype, np.float32)
        np.testing.assert_allclose(w.sum(axis=1), np.ones(5), atol=1e-6)
        # clean halves outside the blend band
        np.testing.assert_allclose(w[0], (1, 0), atol=1e-6)
        np.testing.assert_allclose(w[-1], (0, 1), atol=1e-6)

    def test_two_bone_bind_deforms_half_on_90deg(self):
        arm = _two_bone()
        pos = np.array([[-1, 0, 0], [-0.5, 0, 0],
                        [0.5, 0, 0], [1, 0, 0]], dtype=np.float32)
        w = arm.auto_weights_from_x(pos, split_x=0.0)
        rest = arm.skin(pos, w)
        np.testing.assert_allclose(rest, pos, atol=1e-6)
        arm.set_pose("L", (0, 0, 0), (0, 0, math.pi / 2))
        deformed = arm.skin(pos, w)
        # right half bound to identity bone R: unchanged
        np.testing.assert_allclose(deformed[2:], pos[2:], atol=1e-5)
        # left off-pivot vert rotates about L head (-1,0,0): (-0.5,0,0)->(-1,0.5,0)
        np.testing.assert_allclose(deformed[1], (-1, 0.5, 0), atol=1e-5)
        self.assertGreater(float(np.linalg.norm(deformed[1] - pos[1])), 0.1)

    def test_dict_round_trip(self):
        arm = _two_bone()
        arm.set_pose("L", (0.1, 0, 0), (0, 0, 0.5))
        d2 = json.loads(json.dumps(arm.to_dict()))  # must be JSON-safe
        arm2 = Armature.from_dict(d2)
        self.assertEqual(arm2.bone_names(), ["L", "R"])
        self.assertEqual(arm2.bones["L"].parent, None)
        np.testing.assert_allclose(arm2.bones["L"].head, (-1, 0, 0), atol=1e-6)
        pos = np.array([[-1, 0, 0], [1, 0, 0]], dtype=np.float32)
        w = arm.auto_weights_from_x(pos)
        np.testing.assert_allclose(arm2.skin(pos, w), arm.skin(pos, w), atol=1e-6)

    def test_no_qt_imported(self):
        import pathlib
        src = pathlib.Path(__file__).parent.parent.joinpath(
            "rig", "armature.py").read_text()
        self.assertNotIn("PySide6", src)
        self.assertNotIn("PyQt", src)


if __name__ == "__main__":
    unittest.main()
