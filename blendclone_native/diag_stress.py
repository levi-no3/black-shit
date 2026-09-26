"""Stress every interaction; print progress; traceback will show crash site."""
import sys, traceback
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer, QPoint, Qt
from PySide6.QtTest import QTest

app = QApplication(sys.argv)
from app import BlendClone
w = BlendClone()
w.show()
app.processEvents()
v = w.view

def step(name, fn):
    try:
        fn()
        app.processEvents()
        print("OK", name, flush=True)
    except Exception:
        print("FAIL", name, flush=True)
        traceback.print_exc()
        app.quit()

def run_all():
    cx, cy = int(v.width() / 2), int(v.height() / 2)
    step("mode-wire", lambda: v.set_mode("wire"))
    step("mode-studio", lambda: v.set_mode("studio"))
    step("mode-solid", lambda: v.set_mode("solid"))
    step("shadow-off", lambda: v.set_shadow(False))
    step("shadow-on", lambda: v.set_shadow(True))
    step("add-sphere", lambda: w._add_modeling("Sphere", __import__("modeling.primitives", fromlist=["create_uv_sphere"]).create_uv_sphere()))
    step("add-plane", lambda: w._add_modeling("Plane", __import__("modeling.primitives", fromlist=["create_plane"]).create_plane()))
    step("add-cylinder", lambda: w._add_modeling("Cylinder", __import__("modeling.primitives", fromlist=["create_cylinder"]).create_cylinder()))
    step("click-select", lambda: QTest.mouseClick(v, Qt.LeftButton, Qt.NoModifier, QPoint(cx, cy)))
    step("drag-orbit", lambda: (QTest.mousePress(v, Qt.LeftButton, Qt.NoModifier, QPoint(cx, cy)), QTest.mouseMove(v, QPoint(cx + 40, cy)), QTest.mouseRelease(v, Qt.LeftButton, Qt.NoModifier, QPoint(cx + 40, cy))))
    step("edit-mode-on", lambda: v.set_edit_mode(True))
    step("edit-click-face", lambda: QTest.mouseClick(v, Qt.LeftButton, Qt.NoModifier, QPoint(cx, cy)))
    step("delete-faces", lambda: w._delete_faces())
    step("edit-mode-off", lambda: v.set_edit_mode(False))
    step("sculpt-on", lambda: w._toggle_sculpt_mode(True))
    step("sculpt-stroke", lambda: (QTest.mousePress(v, Qt.LeftButton, Qt.NoModifier, QPoint(cx, cy)), QTest.mouseMove(v, QPoint(cx + 20, cy + 10)), QTest.mouseRelease(v, Qt.LeftButton, Qt.NoModifier, QPoint(cx + 20, cy + 10))))
    step("sculpt-off", lambda: w._toggle_sculpt_mode(False))
    step("duplicate", lambda: w._duplicate_selected())
    step("undo", lambda: w._do_undo())
    step("redo", lambda: w._do_redo())
    step("delete", lambda: w._delete_selected())
    step("snapshot", lambda: w._snapshot())
    step("timeline-frame", lambda: w._on_clip_frame(10))
    step("timeline-addkey", lambda: w._on_add_key(10))
    step("timeline-play", lambda: (w.timeline._on_play() if hasattr(w.timeline, "_on_play") else w.timeline.play() if hasattr(w.timeline, "play") else None))
    step("rig-add", lambda: w._rig_add_armature())
    step("rig-bind", lambda: w._rig_bind_selected())
    step("rig-pose", lambda: w._rig_preview(30))
    step("rig-apply", lambda: w._rig_apply())
    step("render-open", lambda: w._open_render())
    print("ALL-DONE", flush=True)
    app.quit()

QTimer.singleShot(1200, run_all)
sys.exit(app.exec())
