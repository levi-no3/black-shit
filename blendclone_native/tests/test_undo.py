"""UndoStack tests — no Qt."""
import unittest

from core.undo import UndoStack


class TestPushUndoRedo(unittest.TestCase):
    def test_push_undo_redo_restores_value(self):
        st = UndoStack()
        box = {"v": 0}

        def do():
            box["v"] = 1

        def undo():
            box["v"] = 0

        st.push("set-1", do, undo)
        self.assertEqual(box["v"], 1)
        self.assertTrue(st.can_undo)
        self.assertTrue(st.can_undo())
        self.assertFalse(st.can_redo)
        self.assertTrue(st.undo())
        self.assertEqual(box["v"], 0)
        self.assertTrue(st.can_redo)
        self.assertTrue(st.redo())
        self.assertEqual(box["v"], 1)

    def test_undo_empty_is_false(self):
        st = UndoStack()
        self.assertFalse(st.undo())
        self.assertFalse(st.redo())
        self.assertFalse(st.can_undo)
        self.assertFalse(st.can_redo())


class TestEviction(unittest.TestCase):
    def test_eviction_caps_steps(self):
        st = UndoStack(max_steps=3)
        box = {"v": 0}
        for i in range(1, 6):
            def do(v=i):
                box["v"] = v

            def undo(v=i - 1):
                box["v"] = v

            st.push(f"s{i}", do, undo)
        self.assertEqual(len(st), 3)
        self.assertEqual(box["v"], 5)
        # Only last 3 survive: undo -> 3, 2, 1(prev of s3 is 2? check chain)
        self.assertTrue(st.undo())
        self.assertTrue(st.undo())
        self.assertTrue(st.undo())
        self.assertFalse(st.undo())
        self.assertEqual(len(st), 0)

    def test_byte_eviction(self):
        st = UndoStack(max_steps=50, max_bytes=100)
        box = {"v": 0}
        for i in range(1, 5):
            def do(v=i):
                box["v"] = v

            def undo(v=i - 1):
                box["v"] = v

            st.push(f"b{i}", do, undo, byte_size=40)
        # 4x40=160 > 100 -> oldest evicted until <=100 (keeps last 2 = 80)
        self.assertLessEqual(st.total_bytes, 100)
        self.assertLessEqual(len(st), 3)


class TestCoalesce(unittest.TestCase):
    def test_coalesce_merges_drags(self):
        st = UndoStack()
        box = {"v": 0}
        orig = 0
        for v in (10, 20, 30):
            def do(v=v):
                box["v"] = v

            def undo(o=orig):
                box["v"] = o

            st.push_coalesce("drag-1", f"drag {v}", do, undo)
        self.assertEqual(len(st), 1)
        self.assertEqual(box["v"], 30)
        st.undo()
        self.assertEqual(box["v"], orig)
        st.redo()
        self.assertEqual(box["v"], 30)

    def test_coalesce_new_key_pushes(self):
        st = UndoStack()
        box = {"v": 0}
        st.push_coalesce("k1", "a", lambda: box.update(v=1), lambda: box.update(v=0))
        st.push_coalesce("k2", "b", lambda: box.update(v=2), lambda: box.update(v=1))
        self.assertEqual(len(st), 2)


if __name__ == "__main__":
    unittest.main()
