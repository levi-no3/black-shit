"""BlendClone native app shell — QMainWindow, no browser/QtWebEngine."""
from __future__ import annotations

import math
import sys
import time

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import (QApplication, QComboBox, QDockWidget, QDoubleSpinBox,
                               QFileDialog, QHBoxLayout, QLabel, QListWidget,
                               QMainWindow, QPushButton, QSlider, QToolBar,
                               QVBoxLayout, QWidget)

from anim.clip import Clip
from anim.timeline import TimelineDock
from rig.armature import Armature, Bone
from modeling.mesh import Mesh
from modeling.primitives import (create_cube, create_cylinder, create_plane,
                                 create_uv_sphere)
import modeling.transform as mtransform
from core.undo import UndoStack
from fileio.blendclone import load_scene, save_scene
from fileio.obj import export_obj, import_obj
from render.dialog import RenderDialog
from shading.editor import NodeDock
from shading.nodes import NodeGraph
from viewport.glwidget import ViewportGL
from viewport.scene import mesh_bounds


def modeling_mesh_to_viewport(mesh: Mesh) -> dict:
    """Adapter: modeling.Mesh -> viewport mesh dict {positions,normals,indices}."""
    pos = np.asarray(mesh.positions, dtype=np.float32).reshape(-1, 3).copy()
    idx = np.asarray(mesh.indices, dtype=np.uint32).reshape(-1).copy()
    if mesh.normals is not None:
        nrm = np.asarray(mesh.normals, dtype=np.float32).reshape(-1, 3).copy()
    else:
        nrm = np.zeros_like(pos)
    return {"positions": pos, "normals": nrm, "indices": idx}


def viewport_mesh_to_modeling(d: dict, name: str = "mesh") -> Mesh:
    """Adapter: viewport mesh dict -> modeling.Mesh (for OBJ/scene I/O)."""
    pos = np.asarray(d["positions"], dtype=np.float32).reshape(-1, 3)
    idx = np.asarray(d["indices"], dtype=np.uint32).reshape(-1)
    nrm = None
    if d.get("normals") is not None:
        nrm = np.asarray(d["normals"], dtype=np.float32).reshape(-1, 3)
    return Mesh(pos.copy(), idx.copy(),
                nrm.copy() if nrm is not None else None, None, name or "mesh")


def _slider(label: str, lo: int, hi: int, val: int, on_change):
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(4, 2, 4, 2)
    lab = QLabel(f"{label}")
    lab.setFixedWidth(70)
    s = QSlider(Qt.Horizontal)
    s.setRange(lo, hi)
    s.setValue(val)
    s.valueChanged.connect(on_change)
    num = QLabel(str(val))
    num.setFixedWidth(36)
    s.valueChanged.connect(lambda v: num.setText(str(v)))
    lay.addWidget(lab)
    lay.addWidget(s, 1)
    lay.addWidget(num)
    return w, s


class BlendClone(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("BlendClone Native")
        self.resize(1100, 700)
        self.view = ViewportGL(self)
        self.setCentralWidget(self.view)
        self.undo_stack = UndoStack()
        self._mat_anchor = None
        self._mat_obj_id = None
        self._scale_before = None
        self._scale_obj_id = None
        self.clip = Clip(fps=24)
        self._clip_frame = 1
        # Rig sidecar: obj_id -> {"armature", "weights", "base"}.
        # NOT stored in .blendclone mesh arrays and NOT saved to scene files.
        self._rig: dict = {}
        self._rig_template = None
        self._rig_before = None
        self._rig_obj_id = None
        self._node_graphs: dict = {}
        self._shading_obj_id = None
        self._counters = {"Cube": 1, "Sphere": 0, "Plane": 0, "Cylinder": 0}
        self._build_toolbar()
        self._build_menu()
        self._build_docks()
        self.view.selectionChanged.connect(self._on_gl_select)
        self.view.faceSelectionChanged.connect(self._on_faces)
        self.view.editModeChanged.connect(self._on_edit_mode)
        self.view.sculptStrokeStarted.connect(self._on_sculpt_started)
        self.view.sculptStrokeUpdated.connect(self._on_sculpt_updated)
        self.view.sculptStrokeFinished.connect(self._on_sculpt_finished)
        self._sculpt_before = None
        self._sculpt_obj_id = None
        self._sculpt_key = None
        self._sculpt_count = 0
        self._face_label = QLabel("faces: 0")
        self.statusBar().addPermanentWidget(self._face_label)
        self.refresh_list()
        self._ensure_selection()
        self._update_face_label(0)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick_fps)
        self._timer.start(500)

    # -- toolbar --
    def _build_toolbar(self):
        tb = QToolBar("Main", self)
        self.addToolBar(Qt.TopToolBarArea, tb)
        a_cube = QAction("Add Cube", self)
        a_cube.triggered.connect(lambda: self._add_modeling("Cube", create_cube()))
        a_sph = QAction("Add Sphere", self)
        a_sph.triggered.connect(
            lambda: self._add_modeling("Sphere", create_uv_sphere(24, 12, 1.0)))
        a_plane = QAction("Add Plane", self)
        a_plane.triggered.connect(lambda: self._add_modeling("Plane", create_plane()))
        a_cyl = QAction("Add Cylinder", self)
        a_cyl.triggered.connect(lambda: self._add_modeling("Cylinder", create_cylinder()))
        tb.addAction(a_cube)
        tb.addAction(a_sph)
        tb.addAction(a_plane)
        tb.addAction(a_cyl)
        tb.addSeparator()
        a_dup = QAction("Duplicate", self)
        a_dup.triggered.connect(self._duplicate_selected)
        tb.addAction(a_dup)
        a_del = QAction("Delete", self)
        a_del.triggered.connect(self._delete_selected)
        tb.addAction(a_del)
        tb.addSeparator()
        grp = QActionGroup(self)
        grp.setExclusive(True)
        for m in ("wire", "solid", "studio"):
            a = QAction(m.capitalize(), self, checkable=True)
            a.setChecked(m == "solid")
            a.triggered.connect(lambda _c, m=m: self.view.set_mode(m))
            grp.addAction(a)
            tb.addAction(a)
        tb.addSeparator()
        a_shadow = QAction("Shadow", self, checkable=True)
        a_shadow.setChecked(True)
        a_shadow.setToolTip("Blob shadow on/off (key 4)")
        a_shadow.toggled.connect(self.view.set_shadow)
        tb.addAction(a_shadow)
        tb.addSeparator()
        self._edit_action = QAction("Edit Mode", self, checkable=True)
        self._edit_action.setToolTip("Object/Edit face-pick toggle (Tab)")
        self._edit_action.setShortcut("Tab")
        self._edit_action.toggled.connect(self._toggle_edit_mode)
        tb.addAction(self._edit_action)
        a_delf = QAction("Delete Faces", self)
        a_delf.setToolTip("Delete selected faces (Edit mode)")
        a_delf.triggered.connect(self._delete_faces)
        tb.addAction(a_delf)
        a_ext = QAction("Extrude", self)
        a_ext.setToolTip("Extrude selected faces (Edit mode)")
        a_ext.triggered.connect(self._extrude_faces)
        tb.addAction(a_ext)
        a_ins = QAction("Inset", self)
        a_ins.setToolTip("Inset selected faces (Edit mode)")
        a_ins.triggered.connect(self._inset_faces)
        tb.addAction(a_ins)
        self._sculpt_action = QAction("Sculpt", self, checkable=True)
        self._sculpt_action.setToolTip("Sculpt mode: left-drag deforms surface")
        self._sculpt_action.toggled.connect(self._toggle_sculpt_mode)
        tb.addAction(self._sculpt_action)
        snap = QAction("Snapshot", self)
        snap.triggered.connect(self._snapshot)
        tb.addAction(snap)

    # -- file menu (JSON scene + OBJ I/O) --
    def _build_menu(self):
        fm = self.menuBar().addMenu("&File")
        a_save = QAction("Save Scene (.blendclone)...", self)
        a_save.triggered.connect(self._save_scene_dialog)
        fm.addAction(a_save)
        a_open = QAction("Open Scene (.blendclone)...", self)
        a_open.triggered.connect(self._open_scene_dialog)
        fm.addAction(a_open)
        fm.addSeparator()
        a_exp = QAction("Export Selected (.obj)...", self)
        a_exp.triggered.connect(self._export_obj_dialog)
        fm.addAction(a_exp)
        a_imp = QAction("Import (.obj)...", self)
        a_imp.triggered.connect(self._import_obj_dialog)
        fm.addAction(a_imp)
        em = self.menuBar().addMenu("&Edit")
        a_undo = QAction("Undo", self)
        a_undo.setShortcut("Ctrl+Z")
        a_undo.triggered.connect(self._do_undo)
        em.addAction(a_undo)
        self._undo_action = a_undo
        a_redo = QAction("Redo", self)
        a_redo.setShortcut("Ctrl+Y")
        a_redo.triggered.connect(self._do_redo)
        em.addAction(a_redo)
        self._redo_action = a_redo
        rm = self.menuBar().addMenu("&Render")
        a_cpu = QAction("Render with CPU...", self)
        a_cpu.triggered.connect(self._open_render)
        rm.addAction(a_cpu)

    # -- docks --
    def _build_docks(self):
        left = QDockWidget("Objects", self)
        self.obj_list = QListWidget()
        self.obj_list.itemClicked.connect(self._on_list_click)
        left.setWidget(self.obj_list)
        self.addDockWidget(Qt.LeftDockWidgetArea, left)
        right = QDockWidget("Properties", self)
        panel = QWidget()
        lay = QVBoxLayout(panel)
        self._sliders = {}
        for ch in "RGB":
            w, s = _slider(ch, 0, 255, 140, lambda _v, ch=ch: self._apply_color())
            lay.addWidget(w)
            self._sliders[ch] = s
        for name in ("Metallic", "Roughness"):
            w, s = _slider(name, 0, 100, 0 if name == "Metallic" else 50,
                           lambda _v: self._apply_pbr())
            lay.addWidget(w)
            self._sliders[name] = s
        w_em, s_em = _slider("Emissive", 0, 100, 0,
                             lambda _v: self._apply_emissive())
        lay.addWidget(w_em)
        self._sliders["Emissive"] = s_em
        for _k in ("R", "G", "B", "Metallic", "Roughness", "Emissive"):
            try:
                self._sliders[_k].sliderPressed.connect(self._mat_grab_anchor)
                self._sliders[_k].sliderReleased.connect(self._mat_release_anchor)
            except (AttributeError, RuntimeError):
                pass
        lay.addWidget(QLabel("Material presets"))
        prow = QWidget()
        play = QHBoxLayout(prow)
        play.setContentsMargins(4, 2, 4, 2)
        for pname in ("Plastic Red", "Metal Gold", "Matte Gray", "Emissive"):
            b = QPushButton(pname)
            b.clicked.connect(lambda _c, p=pname: self._apply_preset(p))
            play.addWidget(b)
        lay.addWidget(prow)
        lay.addWidget(QLabel("Transform (mesh space)"))
        trow = QWidget()
        tlay = QHBoxLayout(trow)
        tlay.setContentsMargins(4, 2, 4, 2)
        self._spins = {}
        for axis in "XYZ":
            sp = QDoubleSpinBox()
            sp.setRange(-100.0, 100.0)
            sp.setSingleStep(0.1)
            sp.setPrefix(axis + " ")
            sp.setValue(0.0)
            tlay.addWidget(sp)
            self._spins[axis] = sp
        lay.addWidget(trow)
        b_trans = QPushButton("Apply Translate")
        b_trans.clicked.connect(self._apply_translate_ui)
        lay.addWidget(b_trans)
        b_roty = QPushButton("Rotate Y +15°")
        b_roty.clicked.connect(self._apply_rotate_y_ui)
        lay.addWidget(b_roty)
        w_scale, self._scale_slider = _slider("Scale %", 25, 200, 100,
                                             lambda _v: self._apply_scale_ui())
        self._scale_anchor = None
        self._scale_slider.sliderPressed.connect(self._scale_grab_anchor)
        self._scale_slider.sliderReleased.connect(self._scale_release_anchor)
        lay.addWidget(w_scale)
        lay.addStretch(1)
        right.setWidget(panel)
        self.addDockWidget(Qt.RightDockWidgetArea, right)
        sculpt = QDockWidget("Sculpt", self)
        spanel = QWidget()
        slay = QVBoxLayout(spanel)
        slay.addWidget(QLabel("Brush"))
        self._brush_combo = QComboBox()
        self._brush_combo.addItems(["Grab", "Smooth", "Inflate"])
        self._brush_combo.currentTextChanged.connect(self._apply_brush_type)
        slay.addWidget(self._brush_combo)
        w_rad, self._radius_slider = _slider("Radius", 10, 200, 50,
                                            lambda _v: self._apply_brush_params())
        slay.addWidget(w_rad)
        w_str, self._strength_slider = _slider("Strength", 5, 100, 50,
                                              lambda _v: self._apply_brush_params())
        slay.addWidget(w_str)
        slay.addStretch(1)
        sculpt.setWidget(spanel)
        self.addDockWidget(Qt.RightDockWidgetArea, sculpt)
        self.timeline = TimelineDock(self, fps=self.clip.fps)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.timeline)
        self.timeline.frameChanged.connect(self._on_clip_frame)
        self.timeline.addKeyRequested.connect(self._on_add_key)
        self._build_rig_dock()
        self.shading_dock = NodeDock(self)
        self.addDockWidget(Qt.RightDockWidgetArea, self.shading_dock)
        try:
            self.shading_dock.materialChanged.connect(self._on_node_material)
        except (AttributeError, RuntimeError):
            pass

    # -- undo helpers (Mesh clone / Transform copy snapshots) --
    def _copy_mesh_dict(self, d):
        if d is None:
            return None
        out = {
            "positions": np.asarray(d["positions"], np.float32).copy(),
            "normals": np.asarray(d["normals"], np.float32).copy(),
            "indices": np.asarray(d["indices"], np.uint32).copy(),
        }
        if d.get("lines"):
            out["lines"] = True
        return out

    def _mesh_dict_bytes(self, d) -> int:
        if d is None:
            return 0
        try:
            n = int(np.asarray(d["positions"]).nbytes + np.asarray(d["indices"]).nbytes)
            if d.get("normals") is not None:
                n += int(np.asarray(d["normals"]).nbytes)
            return n
        except (TypeError, ValueError):
            return 0

    def _snapshot_object(self, o) -> dict | None:
        if o is None:
            return None
        try:
            idx = list(self.view.scene.objects).index(o)
        except ValueError:
            idx = len(self.view.scene.objects)
        try:
            em = np.asarray(getattr(o, "emissive", (0, 0, 0)), np.float32).copy()
        except (TypeError, ValueError):
            em = np.zeros(3, dtype=np.float32)
        return {"id": o.id, "name": o.name, "index": idx,
                "mesh": self._copy_mesh_dict(o.mesh),
                "color": np.asarray(o.color, np.float32).copy(),
                "metallic": float(o.metallic), "roughness": float(o.roughness),
                "emissive": em,
                "pos": np.asarray(o.transform.pos, np.float32).copy(),
                "rot": np.asarray(o.transform.rot_euler, np.float32).copy(),
                "scl": np.asarray(o.transform.scale, np.float32).copy()}

    def _remove_object_by_id(self, obj_id: int) -> bool:
        o = self.view.scene.find_by_id(obj_id)
        if o is None:
            return False
        old = o.mesh
        old_hl = o.__dict__.get("_hl_mesh")
        if old is not None:
            for key in [k for k in list(self.view._gpu.keys())
                        if k[0] in (id(old), id(old_hl))]:
                self.view._gpu.pop(key, None)
        self.view.scene.remove(o)
        try:
            self._rig.pop(o.id, None)
        except AttributeError:
            pass
        if self.view.selected is o:
            self.view.select(None)
        else:
            self.view.update()
        return True

    def _reinsert_object(self, saved: dict):
        if saved is None or self.view.scene.find_by_id(saved["id"]) is not None:
            return self.view.scene.find_by_id(saved["id"]) if saved else None
        from viewport.scene import Object3D
        o2 = Object3D(self._copy_mesh_dict(saved["mesh"]), name=saved["name"],
                      id=saved["id"])
        o2.color = np.asarray(saved["color"], np.float32).copy()
        o2.metallic = float(saved["metallic"])
        o2.roughness = float(saved["roughness"])
        try:
            o2.emissive = np.asarray(saved["emissive"], np.float32).copy()
        except (TypeError, ValueError):
            pass
        o2.transform.pos = np.asarray(saved["pos"], np.float32).copy()
        o2.transform.rot_euler = np.asarray(saved["rot"], np.float32).copy()
        o2.transform.scale = np.asarray(saved["scl"], np.float32).copy()
        o2.transform.update_matrix()
        idx = max(0, min(int(saved.get("index", len(self.view.scene.objects))),
                         len(self.view.scene.objects)))
        self.view.scene.objects.insert(idx, o2)
        self.view.select(o2)
        return o2

    def _undo_push_mesh(self, obj_id: int, label: str, before: dict, after: dict,
                        coalesce_key=None):
        b = self._copy_mesh_dict(before)
        a = self._copy_mesh_dict(after)
        nbytes = self._mesh_dict_bytes(b) + self._mesh_dict_bytes(a)

        def _do(oid=obj_id, mesh=a):
            self.view.update_object_mesh(oid, self._copy_mesh_dict(mesh))
            self.refresh_list()

        def _undo(oid=obj_id, mesh=b):
            self.view.update_object_mesh(oid, self._copy_mesh_dict(mesh))
            self.refresh_list()

        if coalesce_key is not None:
            self.undo_stack.push_coalesce(coalesce_key, label, _do, _undo,
                                          byte_size=nbytes)
        else:
            self.undo_stack.push(label, _do, _undo, byte_size=nbytes)
        self._refresh_undo_actions()

    def _do_undo(self):
        if self.undo_stack.undo():
            self._scale_anchor = None
            self._mat_anchor = None
            self._sculpt_before = None
            self._sculpt_obj_id = None
            self._sculpt_key = None
            self.refresh_list()
            self.view.update()
            self.statusBar().showMessage("undo", 2000)
        else:
            self.statusBar().showMessage("nothing to undo", 2000)
        self._refresh_undo_actions()

    def _do_redo(self):
        if self.undo_stack.redo():
            self._scale_anchor = None
            self._mat_anchor = None
            self._sculpt_before = None
            self._sculpt_obj_id = None
            self._sculpt_key = None
            self.refresh_list()
            self.view.update()
            self.statusBar().showMessage("redo", 2000)
        else:
            self.statusBar().showMessage("nothing to redo", 2000)
        self._refresh_undo_actions()

    def _refresh_undo_actions(self):
        try:
            self._undo_action.setEnabled(bool(self.undo_stack.can_undo))
            self._redo_action.setEnabled(bool(self.undo_stack.can_redo))
        except (AttributeError, RuntimeError):
            pass

    # -- slots --
    def _add(self, kind, mesh):
        self._counters[kind] = self._counters.get(kind, 0) + 1
        name = f"{kind}.{self._counters[kind]}"
        obj = self.view.add_object(self._copy_mesh_dict(mesh), name)
        saved = self._snapshot_object(obj)
        nbytes = self._mesh_dict_bytes(saved["mesh"]) if saved else 0

        def _do(s=saved):
            if self.view.scene.find_by_id(s["id"]) is None:
                self._reinsert_object(s)
                self.refresh_list()

        def _undo(oid=obj.id):
            self._remove_object_by_id(oid)
            self.refresh_list()

        self.undo_stack.push(f"Add {name}", _do, _undo, byte_size=nbytes)
        self.refresh_list()
        self._refresh_undo_actions()

    def _ensure_selection(self):
        # Keep Properties sliders alive: if nothing is selected but objects
        # exist (startup, after delete/undo), select the first one.
        # Deliberate click-empty deselect is untouched (it doesn't call this).
        if self.view.selected is None and self.view.scene.objects:
            self.view.select(self.view.scene.objects[0])
            self.refresh_list()

    def _add_modeling(self, kind: str, mesh: Mesh):
        self._add(kind, modeling_mesh_to_viewport(mesh))

    def _duplicate_selected(self):
        src = self.view.selected
        if src is None:
            return
        dup = self.view.duplicate_selected()
        if dup is not None:
            saved = self._snapshot_object(dup)
            nbytes = self._mesh_dict_bytes(saved["mesh"]) if saved else 0

            def _do(s=saved):
                if self.view.scene.find_by_id(s["id"]) is None:
                    self._reinsert_object(s)
                    self.refresh_list()

            def _undo(oid=dup.id):
                self._remove_object_by_id(oid)
                self.refresh_list()

            self.undo_stack.push(f"Duplicate {src.name}", _do, _undo,
                                 byte_size=nbytes)
            self.refresh_list()
            self._refresh_undo_actions()

    def _delete_selected(self):
        o = self.view.selected
        if o is None:
            return
        saved = self._snapshot_object(o)
        idx = saved["index"] if saved else 0
        if self.view.delete_selected():
            try:
                self._rig.pop(saved["id"], None)
            except (AttributeError, KeyError, TypeError):
                pass
            nbytes = self._mesh_dict_bytes(saved["mesh"]) if saved else 0

            def _do(oid=saved["id"]):
                self._remove_object_by_id(oid)
                self.refresh_list()

            def _undo(s=saved):
                if self.view.scene.find_by_id(s["id"]) is None:
                    self._reinsert_object(s)
                    self.refresh_list()

            self.undo_stack.push(f"Delete {saved['name']}", _do, _undo,
                                 byte_size=nbytes)
            self._ensure_selection()
            self.refresh_list()
            self._refresh_undo_actions()

    def _toggle_edit_mode(self, on: bool):
        if self.view.edit_mode != bool(on):
            self.view.set_edit_mode(bool(on))
        else:
            self._on_edit_mode(bool(on))
        self._update_face_label(len(self.view.get_selected_faces()))

    # -- sculpt mode (brush dock + undoable strokes) --
    def _toggle_sculpt_mode(self, on: bool):
        on = bool(on)
        if on and self.view.edit_mode:
            self.view.set_edit_mode(False)
        self.view.set_sculpt_mode(on)
        self.statusBar().showMessage("Sculpt mode" if on else "Object mode", 2000)

    def _apply_brush_type(self, text: str):
        self.view.set_sculpt_brush(str(text).lower())

    def _apply_brush_params(self):
        try:
            r = self._radius_slider.value() / 100.0  # 0.1 - 2.0
            s = self._strength_slider.value() / 100.0  # 0.05 - 1.0
        except (AttributeError, RuntimeError):
            return
        self.view.set_sculpt_brush(radius=r, strength=s)

    def _on_sculpt_started(self, obj_id: int):
        o = self.view.scene.find_by_id(int(obj_id))
        self._sculpt_obj_id = int(obj_id)
        self._sculpt_before = self._copy_mesh_dict(o.mesh) \
            if o is not None and o.mesh is not None else None
        self._sculpt_count += 1
        self._sculpt_key = f"sculpt-{int(obj_id)}-{self._sculpt_count}"

    def _on_sculpt_updated(self, obj_id: int):
        o = self.view.scene.find_by_id(int(obj_id))
        if (o is None or o.mesh is None or self._sculpt_before is None
                or self._sculpt_obj_id != int(obj_id)):
            return
        after = self._copy_mesh_dict(o.mesh)
        try:
            same = np.array_equal(np.asarray(self._sculpt_before["positions"]),
                                  np.asarray(after["positions"]))
        except (KeyError, TypeError, ValueError):
            same = False
        if same:
            return
        try:
            btype = str(self.view.sculpt_brush.get("type", "brush"))
        except AttributeError:
            btype = "brush"
        self._undo_push_mesh(int(obj_id), f"Sculpt {btype}",
                             self._sculpt_before, after,
                             coalesce_key=self._sculpt_key)

    def _on_sculpt_finished(self, obj_id: int):
        try:
            self._on_sculpt_updated(int(obj_id))  # final coalesced state
        finally:
            self._sculpt_before = None
            self._sculpt_obj_id = None
            self._sculpt_key = None
        self.refresh_list()

    def _delete_faces(self):
        o = self.view.selected
        if o is None or o.mesh is None:
            self.statusBar().showMessage("delete faces: nothing selected", 3000)
            self._update_face_label(0)
            return
        before = self._copy_mesh_dict(o.mesh)
        faces = sorted(self.view.get_selected_faces())
        n = self.view.delete_selected_faces()
        if n:
            after = self._copy_mesh_dict(self.view.selected.mesh) \
                if self.view.selected is not None and self.view.selected.mesh is not None \
                else self._copy_mesh_dict(o.mesh)
            # o may have been mutated in place; after is current mesh
            try:
                cur = self.view.scene.find_by_id(o.id)
                after = self._copy_mesh_dict(cur.mesh) if cur is not None else after
            except (AttributeError, TypeError):
                pass
            self._undo_push_mesh(o.id, f"Delete {n} face(s)", before, after)
            self.refresh_list()
            self.statusBar().showMessage(f"deleted {n} face(s)", 3000)
        else:
            self.statusBar().showMessage("delete faces: nothing selected", 3000)
        self._update_face_label(0)

    def _extrude_faces(self, dist: float = 0.2):
        o = self.view.selected
        if o is None or o.mesh is None:
            self.statusBar().showMessage("extrude: nothing selected", 3000)
            return
        faces = sorted(self.view.get_selected_faces())
        if not faces:
            self.statusBar().showMessage("extrude: no faces selected", 3000)
            return
        before = self._copy_mesh_dict(o.mesh)
        try:
            from modeling.operators import extrude_faces as _ext
            m = viewport_mesh_to_modeling(before, o.name)
            _ext(m, faces, float(dist))
            after = modeling_mesh_to_viewport(m)
        except (TypeError, ValueError) as e:
            self.statusBar().showMessage(f"extrude FAILED: {e}", 3000)
            return
        self.view.update_object_mesh(o.id, self._copy_mesh_dict(after))
        self._undo_push_mesh(o.id, f"Extrude {len(faces)} face(s)", before, after)
        self.refresh_list()
        self.statusBar().showMessage(f"extruded {len(faces)} face(s)", 3000)

    def _inset_faces(self, t: float = 0.2):
        o = self.view.selected
        if o is None or o.mesh is None:
            self.statusBar().showMessage("inset: nothing selected", 3000)
            return
        faces = sorted(self.view.get_selected_faces())
        if not faces:
            self.statusBar().showMessage("inset: no faces selected", 3000)
            return
        before = self._copy_mesh_dict(o.mesh)
        try:
            from modeling.operators import inset_faces as _ins
            m = viewport_mesh_to_modeling(before, o.name)
            _ins(m, faces, float(t))
            after = modeling_mesh_to_viewport(m)
        except (TypeError, ValueError) as e:
            self.statusBar().showMessage(f"inset FAILED: {e}", 3000)
            return
        self.view.update_object_mesh(o.id, self._copy_mesh_dict(after))
        self._undo_push_mesh(o.id, f"Inset {len(faces)} face(s)", before, after)
        self.refresh_list()
        self.statusBar().showMessage(f"inset {len(faces)} face(s)", 3000)

    def _on_faces(self, count: int):
        self._update_face_label(int(count))

    def _on_edit_mode(self, on: bool):
        try:
            self._edit_action.blockSignals(True)
            self._edit_action.setChecked(bool(on))
        finally:
            self._edit_action.blockSignals(False)
        mode = "Edit" if on else "Object"
        self.statusBar().showMessage(f"{mode} mode", 2000)
        self._update_face_label(len(self.view.get_selected_faces()))

    def _update_face_label(self, count: int):
        mode = "Edit" if self.view.edit_mode else "Object"
        try:
            self._face_label.setText(f"{mode} | faces: {int(count)}")
        except (AttributeError, RuntimeError):
            pass

    # -- file I/O --
    def _scene_as_mesh_list(self) -> list:
        items = []
        for o in self.view.scene.objects:
            if o.mesh is None:
                continue
            items.append((o.name, viewport_mesh_to_modeling(o.mesh, o.name)))
        return items

    def _save_scene_dialog(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save Scene",
                                              "scene.blendclone",
                                              "BlendClone (*.blendclone *.json)")
        if not path:
            return
        try:
            self._shading_store_current()
            try:
                shading = self.shading_dock.graph_dict()
            except (AttributeError, RuntimeError):
                shading = None
            graphs = {}
            try:
                for o in self.view.scene.objects:
                    if o.id in self._node_graphs:
                        graphs[o.name] = self._node_graphs[o.id]
            except (AttributeError, TypeError):
                graphs = {}
            with open(path, "w", encoding="utf-8") as f:
                f.write(save_scene({"meshes": self._scene_as_mesh_list(),
                                    "clip": self.clip.to_dict(),
                                    "shading": shading, "graphs": graphs}))
            self.statusBar().showMessage(f"saved {path}", 3000)
        except Exception as e:
            self.statusBar().showMessage(f"save FAILED: {e}", 4000)

    def _open_scene_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open Scene", "",
                                              "BlendClone (*.blendclone *.json)")
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                data = load_scene(f.read())
            self.view.scene.clear()
            self.view.select(None)
            for m in data.get("meshes", []):
                self._counters[m.name.split(".")[0]] = \
                    self._counters.get(m.name.split(".")[0], 0) + 1
                self.view.add_object(modeling_mesh_to_viewport(m), m.name or "mesh")
            self.refresh_list()
            try:
                clip_d = data.get("clip")
                self.clip = Clip.from_dict(clip_d) if clip_d else Clip(fps=24)
            except (TypeError, ValueError, KeyError, AttributeError):
                self.clip = Clip(fps=24)
            self._clip_frame = 1
            try:
                self.timeline.set_frame(1)
            except (AttributeError, RuntimeError):
                pass
            self._apply_clip(1)
            try:
                sh = data.get("shading", data.get("node_graph"))
                if sh is not None:
                    self.shading_dock.set_graph_dict(sh)
                saved_graphs = data.get("graphs") or {}
                if isinstance(saved_graphs, dict):
                    self._node_graphs = {}
                    by_name = {o.name: o for o in self.view.scene.objects}
                    for nm, gd in saved_graphs.items():
                        if nm in by_name:
                            self._node_graphs[by_name[nm].id] = gd
                self._shading_obj_id = (self.view.selected.id
                                        if self.view.selected else None)
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass
            self.statusBar().showMessage(f"opened {path}", 3000)
        except Exception as e:
            self.statusBar().showMessage(f"open FAILED: {e}", 4000)

    def _export_obj_dialog(self):
        o = self.view.selected
        if o is None or o.mesh is None:
            self.statusBar().showMessage("export: nothing selected", 3000)
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export OBJ",
                                              f"{o.name}.obj", "OBJ (*.obj)")
        if not path:
            return
        try:
            m = viewport_mesh_to_modeling(o.mesh, o.name)
            with open(path, "w", encoding="utf-8") as f:
                f.write(export_obj(m, o.name))
            self.statusBar().showMessage(f"exported {path}", 3000)
        except Exception as e:
            self.statusBar().showMessage(f"export FAILED: {e}", 4000)

    def _import_obj_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import OBJ", "",
                                              "OBJ (*.obj)")
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                m = import_obj(f.read())
            self._add_modeling(m.name or "OBJ", m)
            self.statusBar().showMessage(f"imported {path}", 3000)
        except Exception as e:
            self.statusBar().showMessage(f"import FAILED: {e}", 4000)

    # -- mesh-space transforms via modeling.transform --
    def _push_mesh(self, mesh: Mesh) -> bool:
        o = self.view.selected
        if o is None:
            return False
        ok = self.view.update_object_mesh(o.id, modeling_mesh_to_viewport(mesh))
        self.refresh_list()
        return ok

    def _selected_as_mesh(self) -> Mesh | None:
        o = self.view.selected
        if o is None or o.mesh is None:
            return None
        return viewport_mesh_to_modeling(o.mesh, o.name)

    def _apply_translate_ui(self):
        o = self.view.selected
        if o is None or o.mesh is None:
            return
        before = self._copy_mesh_dict(o.mesh)
        m = viewport_mesh_to_modeling(before, o.name)
        mtransform.translate(m, self._spins["X"].value(),
                             self._spins["Y"].value(), self._spins["Z"].value())
        after = modeling_mesh_to_viewport(m)
        self._undo_push_mesh(o.id, "Translate", before, after)
        self.statusBar().showMessage("translate applied", 2000)

    def _apply_rotate_y_ui(self):
        o = self.view.selected
        if o is None or o.mesh is None:
            return
        before = self._copy_mesh_dict(o.mesh)
        m = viewport_mesh_to_modeling(before, o.name)
        mtransform.rotate_y(m, math.radians(15.0))
        after = modeling_mesh_to_viewport(m)
        self._undo_push_mesh(o.id, "Rotate Y +15°", before, after)
        self.statusBar().showMessage("rotate Y applied", 2000)

    def _scale_grab_anchor(self):
        self._scale_anchor = self._selected_as_mesh()
        o = self.view.selected
        self._scale_obj_id = o.id if o is not None else None
        self._scale_before = self._copy_mesh_dict(o.mesh) \
            if o is not None and o.mesh is not None else None

    def _scale_release_anchor(self):
        try:
            o = self.view.selected
            if (self._scale_before is not None and o is not None
                    and self._scale_obj_id == o.id and o.mesh is not None):
                before = self._scale_before
                after = self._copy_mesh_dict(o.mesh)
                # Only push if geometry actually changed.
                try:
                    changed = not (
                        np.array_equal(np.asarray(before["positions"]),
                                       np.asarray(after["positions"])))
                except (KeyError, TypeError, ValueError):
                    changed = True
                if changed:
                    self._undo_push_mesh(o.id, "Scale",
                                         before, after,
                                         coalesce_key=f"scale-{o.id}")
        finally:
            self._scale_anchor = None
            self._scale_before = None
            self._scale_obj_id = None
            # Reset slider to 100% without re-applying.
            try:
                self._scale_slider.blockSignals(True)
                self._scale_slider.setValue(100)
                self._scale_slider.blockSignals(False)
            except (AttributeError, RuntimeError):
                pass
        self._refresh_undo_actions()

    def _apply_scale_ui(self):
        o = self.view.selected
        if o is None or o.mesh is None:
            return
        if self._scale_anchor is None:
            self._scale_grab_anchor()
            if self._scale_anchor is None:
                return
        factor = self._scale_slider.value() / 100.0
        m = self._scale_anchor.clone()
        mtransform.scale(m, factor)
        self.view.update_object_mesh(o.id, modeling_mesh_to_viewport(m))

    # -- rig dock (Armature/skin MVP; PySide6 only here, core in rig/armature.py) --
    def _build_rig_dock(self):
        dock = QDockWidget("Rig", self)
        panel = QWidget()
        lay = QVBoxLayout(panel)
        self._rig_label = QLabel("no armature")
        lay.addWidget(self._rig_label)
        b_add = QPushButton("Add Armature 2-bone")
        b_add.clicked.connect(self._rig_add_armature)
        lay.addWidget(b_add)
        b_bind = QPushButton("Bind Selected")
        b_bind.clicked.connect(self._rig_bind_selected)
        lay.addWidget(b_bind)
        w_pose, self._rig_slider = _slider("Pose Bone0", -90, 90, 0,
                                           lambda v: self._rig_preview(v))
        lay.addWidget(w_pose)
        self._rig_slider.sliderPressed.connect(self._rig_grab_anchor)
        self._rig_slider.sliderReleased.connect(self._rig_release_anchor)
        b_apply = QPushButton("Apply")
        b_apply.clicked.connect(self._rig_apply)
        lay.addWidget(b_apply)
        lay.addStretch(1)
        dock.setWidget(panel)
        self.addDockWidget(Qt.RightDockWidgetArea, dock)
        self._rig_refresh_label()

    def _rig_add_armature(self):
        arm = Armature()
        arm.add_bone(Bone("L", (-1.0, 0.0, 0.0), (0.0, 0.0, 0.0)))
        arm.add_bone(Bone("R", (0.0, 0.0, 0.0), (1.0, 0.0, 0.0)))
        self._rig_template = arm
        self._rig_refresh_label()
        self.statusBar().showMessage("rig: 2-bone armature ready — Bind Selected", 3000)

    def _rig_bind_selected(self):
        o = self.view.selected
        if o is None or o.mesh is None:
            self.statusBar().showMessage("rig bind: nothing selected", 3000)
            return
        arm = getattr(self, "_rig_template", None)
        if arm is None:
            self._rig_add_armature()
            arm = self._rig_template
        try:
            pos = np.asarray(o.mesh["positions"], np.float32).reshape(-1, 3)
            w = arm.auto_weights_from_x(pos, split_x=0.0)
        except (TypeError, ValueError) as e:
            self.statusBar().showMessage(f"rig bind FAILED: {e}", 3000)
            return
        bound = Armature.from_dict(arm.to_dict())  # per-object copy
        self._rig[o.id] = {"armature": bound, "weights": w,
                           "base": self._copy_mesh_dict(o.mesh)}
        try:
            self._rig_slider.blockSignals(True)
            self._rig_slider.setValue(0)
        finally:
            self._rig_slider.blockSignals(False)
        self._rig_refresh_label()
        self.statusBar().showMessage(
            f"rig: bound {o.name} ({pos.shape[0]} verts)", 3000)

    def _rig_preview(self, deg):
        o = self.view.selected
        if o is None:
            return
        binding = self._rig.get(o.id)
        if binding is None:
            return
        base = binding["base"]
        w = binding["weights"]
        try:
            n = int(np.asarray(o.mesh["positions"]).reshape(-1, 3).shape[0])
            nbase = int(np.asarray(base["positions"]).reshape(-1, 3).shape[0])
        except (KeyError, TypeError, ValueError):
            return
        if w.shape[0] != n or nbase != n:
            self.statusBar().showMessage("rig: mesh changed — rebind", 3000)
            return
        arm = binding["armature"]
        names = arm.bone_names()
        if not names:
            return
        arm.set_pose(names[0], (0.0, 0.0, 0.0),
                     (0.0, 0.0, math.radians(float(deg))))
        try:
            rest = np.asarray(base["positions"], np.float32).reshape(-1, 3)
            deformed = arm.skin(rest, w)
        except (KeyError, TypeError, ValueError):
            return
        preview = self._copy_mesh_dict(base)
        preview["positions"] = np.ascontiguousarray(deformed, np.float32)
        self.view.update_object_mesh(o.id, preview)

    def _rig_grab_anchor(self):
        o = self.view.selected
        self._rig_obj_id = o.id if o is not None else None
        self._rig_before = self._copy_mesh_dict(o.mesh) \
            if o is not None and o.mesh is not None else None

    def _rig_release_anchor(self):
        try:
            o = self.view.selected
            if (self._rig_before is not None and o is not None
                    and self._rig_obj_id == o.id and o.mesh is not None):
                before = self._rig_before
                after = self._copy_mesh_dict(o.mesh)
                try:
                    changed = not np.array_equal(
                        np.asarray(before["positions"]),
                        np.asarray(after["positions"]))
                except (KeyError, TypeError, ValueError):
                    changed = True
                if changed:
                    self._undo_push_mesh(o.id, "Rig pose", before, after,
                                         coalesce_key=f"rig-{o.id}")
        finally:
            self._rig_before = None
            self._rig_obj_id = None
        self._refresh_undo_actions()

    def _rig_apply(self):
        o = self.view.selected
        if o is None or o.mesh is None:
            self.statusBar().showMessage("rig apply: nothing selected", 3000)
            return
        binding = self._rig.get(o.id)
        if binding is None:
            self.statusBar().showMessage("rig apply: bind selected first", 3000)
            return
        before = binding["base"]
        after = self._copy_mesh_dict(o.mesh)
        try:
            same = bool(np.array_equal(np.asarray(before["positions"]),
                                       np.asarray(after["positions"])))
        except (KeyError, TypeError, ValueError):
            same = False
        if same:
            self.statusBar().showMessage("rig: no pose change", 2000)
            return
        self._undo_push_mesh(o.id, "Rig pose", before, after,
                             coalesce_key=f"rig-{o.id}")
        self.statusBar().showMessage("rig pose applied", 2000)

    def _rig_refresh_label(self):
        try:
            tmpl = getattr(self, "_rig_template", None)
            o = self.view.selected
            if tmpl is None:
                txt = "no armature"
            else:
                txt = "bones: " + ",".join(tmpl.bone_names())
                b = self._rig.get(o.id) if o is not None else None
                if b is not None:
                    txt += f" | bound: {o.name} ({b['weights'].shape[0]} verts)"
                else:
                    txt += " | unbound"
            self._rig_label.setText(txt)
        except (AttributeError, RuntimeError):
            pass

    # -- animation clip (transform-only playback) --
    def _on_clip_frame(self, frame: int) -> None:
        self._clip_frame = int(frame)
        self._apply_clip(int(frame))

    def _apply_clip(self, frame: int) -> None:
        for o in self.view.scene.objects:
            try:
                v = self.clip.eval(o.id, int(frame))
            except (TypeError, ValueError):
                continue
            if v is None:
                continue
            pos, rot, scl = v
            o.transform.pos[:] = np.asarray(pos, dtype=np.float32).reshape(3)
            o.transform.rot_euler[:] = np.asarray(rot, dtype=np.float32).reshape(3)
            o.transform.scale[:] = np.asarray(scl, dtype=np.float32).reshape(3)
            o.transform.update_matrix()
        self.view.update()
        try:
            total = sum(len(t.keyframes) for t in self.clip.tracks.values())
            here = sum(1 for t in self.clip.tracks.values()
                       for k in t.keyframes if k.frame == int(frame))
            self.timeline.set_info(f"frame {int(frame)} | keys here: {here} | total: {total}")
        except (AttributeError, RuntimeError):
            pass

    def _on_add_key(self, frame: int) -> None:
        o = self.view.selected
        if o is None:
            self.statusBar().showMessage("add key: nothing selected", 3000)
            return
        self.clip.set_key(o.id, int(frame), o.transform)
        self._apply_clip(int(frame))  # pose unchanged; refreshes key counts
        self.statusBar().showMessage(f"key: {o.name} @ frame {int(frame)}", 3000)

    def refresh_list(self):
        self.obj_list.clear()
        for o in self.view.scene.objects:
            mark = "● " if o.selected else ""
            self.obj_list.addItem(f"{mark}{o.name}  (id={o.id})")
            if o.selected:
                self.obj_list.setCurrentRow(self.obj_list.count() - 1)
        self._load_selected_props()
        self._refresh_undo_actions()
        self._rig_refresh_label()

    def _shading_store_current(self):
        try:
            if (self._shading_obj_id is not None
                    and hasattr(self, "shading_dock")):
                self._node_graphs[self._shading_obj_id] = \
                    self.shading_dock.graph_dict()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass

    def _shading_load_for_selected(self):
        try:
            o = self.view.selected
            oid = o.id if o is not None else None
            if o is not None and oid in getattr(self, "_node_graphs", {}):
                self.shading_dock.set_graph_dict(self._node_graphs[oid])
            self._shading_obj_id = oid
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass

    def _on_node_material(self, mat):
        o = self.view.selected
        if o is None or mat is None:
            return
        try:
            base = np.asarray(mat.base_color, dtype=np.float32).ravel()[:3]
            met = float(mat.metallic)
            rou = float(mat.roughness)
            emi = np.asarray(getattr(mat, "emissive", (0, 0, 0)),
                             dtype=np.float32).ravel()[:3].copy()
        except (TypeError, ValueError, AttributeError):
            return
        before = self._mat_snapshot(o)
        o.color[:] = np.asarray(base, dtype=np.float32).ravel()[:3]
        o.metallic = float(met)
        o.roughness = float(rou)
        try:
            o.emissive = np.asarray(emi, dtype=np.float32).copy()
        except (TypeError, ValueError):
            pass
        after = self._mat_snapshot(o)
        self._load_selected_props()
        self.view.update()
        try:
            self._node_graphs[o.id] = self.shading_dock.graph_dict()
            self._shading_obj_id = o.id
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass
        try:
            same = (np.allclose(before[0], after[0])
                    and before[1] == after[1]
                    and before[2] == after[2]
                    and np.allclose(before[3], after[3]))
        except (TypeError, ValueError):
            same = False
        if not same:
            self._undo_push_material(o.id, "Node material", before, after)
        self.refresh_list()

    def _on_gl_select(self, _id):
        self._shading_store_current()
        self._scale_anchor = None
        self._scale_before = None
        self._mat_anchor = None
        self.refresh_list()
        self._shading_load_for_selected()

    def _on_list_click(self, item):
        self._shading_store_current()
        row = self.obj_list.row(item)
        objs = self.view.scene.objects
        if 0 <= row < len(objs):
            self._scale_anchor = None
            self._scale_before = None
            self._mat_anchor = None
            self.view.select(objs[row])
            self.refresh_list()
        self._shading_load_for_selected()

    def _mat_snapshot(self, o):
        try:
            em = np.asarray(getattr(o, "emissive", (0, 0, 0)),
                            dtype=np.float32).ravel()[:3].copy()
        except (TypeError, ValueError):
            em = np.zeros(3, dtype=np.float32)
        return (np.asarray(o.color, dtype=np.float32).copy(),
                float(o.metallic), float(o.roughness), em)

    def _mat_restore(self, obj_id: int, snap):
        o = self.view.scene.find_by_id(obj_id)
        if o is None or snap is None:
            return
        col, met, rou, em = snap
        o.color[:] = np.asarray(col, dtype=np.float32).ravel()[:3]
        o.metallic = float(met)
        o.roughness = float(rou)
        try:
            o.emissive = np.asarray(em, dtype=np.float32).copy()
        except (TypeError, ValueError):
            pass
        self._load_selected_props()
        self.view.update()

    def _undo_push_material(self, obj_id: int, label: str, before, after,
                            coalesce_key=None):
        b = (np.asarray(before[0]).copy(), float(before[1]),
             float(before[2]), np.asarray(before[3]).copy())
        a = (np.asarray(after[0]).copy(), float(after[1]),
             float(after[2]), np.asarray(after[3]).copy())

        def _do(oid=obj_id, snap=a):
            self._mat_restore(oid, snap)
            self.refresh_list()

        def _undo(oid=obj_id, snap=b):
            self._mat_restore(oid, snap)
            self.refresh_list()

        if coalesce_key is not None:
            self.undo_stack.push_coalesce(coalesce_key, label, _do, _undo,
                                          byte_size=32)
        else:
            self.undo_stack.push(label, _do, _undo, byte_size=32)
        self._refresh_undo_actions()

    def _mat_grab_anchor(self):
        o = self.view.selected
        if o is None:
            self._mat_anchor = None
            self._mat_obj_id = None
            return
        self._mat_anchor = self._mat_snapshot(o)
        self._mat_obj_id = o.id

    def _mat_release_anchor(self):
        try:
            o = self.view.selected
            if (self._mat_anchor is None or o is None
                    or self._mat_obj_id != o.id):
                return
            before = self._mat_anchor
            after = self._mat_snapshot(o)
            try:
                same = (np.allclose(before[0], after[0])
                        and before[1] == after[1]
                        and before[2] == after[2]
                        and np.allclose(before[3], after[3]))
            except (TypeError, ValueError):
                same = False
            if not same:
                self._undo_push_material(o.id, "Material change",
                                         before, after,
                                         coalesce_key=f"mat-{o.id}")
        finally:
            self._mat_anchor = None
            self._mat_obj_id = None

    def _load_selected_props(self):
        o = self.view.selected
        for ch, s in zip("RGB", (self._sliders["R"], self._sliders["G"], self._sliders["B"])):
            s.blockSignals(True)
            s.setValue(int((o.color["RGB".index(ch)] if o is not None else 0.55) * 255))
            s.blockSignals(False)
        if o is not None:
            self._sliders["Metallic"].blockSignals(True)
            self._sliders["Metallic"].setValue(int(o.metallic * 100))
            self._sliders["Metallic"].blockSignals(False)
            self._sliders["Roughness"].blockSignals(True)
            self._sliders["Roughness"].setValue(int(o.roughness * 100))
            self._sliders["Roughness"].blockSignals(False)
            try:
                em = float(np.asarray(getattr(o, "emissive", (0, 0, 0)),
                                      dtype=float).ravel()[:3].mean())
            except (TypeError, ValueError):
                em = 0.0
            self._sliders["Emissive"].blockSignals(True)
            self._sliders["Emissive"].setValue(int(round(max(0.0, min(1.0, em)) * 100)))
            self._sliders["Emissive"].blockSignals(False)

    def _apply_color(self):
        o = self.view.selected
        if o is None:
            return
        if self._mat_anchor is None or self._mat_obj_id != o.id:
            self._mat_grab_anchor()
        o.color[:] = [self._sliders[c].value() / 255.0 for c in "RGB"]
        self.view.update()

    def _apply_pbr(self):
        o = self.view.selected
        if o is None:
            return
        if self._mat_anchor is None or self._mat_obj_id != o.id:
            self._mat_grab_anchor()
        o.metallic = self._sliders["Metallic"].value() / 100.0
        o.roughness = self._sliders["Roughness"].value() / 100.0
        self.view.update()

    def _apply_emissive(self):
        o = self.view.selected
        if o is None:
            return
        if self._mat_anchor is None or self._mat_obj_id != o.id:
            self._mat_grab_anchor()
        e = self._sliders["Emissive"].value() / 100.0
        try:
            o.emissive = np.array([e, e, e], dtype=np.float32)
        except (TypeError, ValueError):
            pass
        self.view.update()

    def _apply_preset(self, name: str):
        o = self.view.selected
        if o is None:
            self.statusBar().showMessage("preset: nothing selected", 3000)
            return
        presets = {
            "Plastic Red": ((0.8, 0.08, 0.08), 0.0, 0.4, (0.0, 0.0, 0.0)),
            "Metal Gold": ((1.0, 0.76, 0.34), 1.0, 0.25, (0.0, 0.0, 0.0)),
            "Matte Gray": ((0.5, 0.5, 0.5), 0.0, 0.9, (0.0, 0.0, 0.0)),
            "Emissive": ((0.2, 0.2, 0.2), 0.0, 0.5, (1.0, 0.55, 0.15)),
        }
        p = presets.get(name)
        if p is None:
            return
        before = self._mat_snapshot(o)
        bc, met, rou, em = p
        o.color[:] = np.asarray(bc, dtype=np.float32)
        o.metallic = float(met)
        o.roughness = float(rou)
        try:
            o.emissive = np.asarray(em, dtype=np.float32).copy()
        except (TypeError, ValueError):
            pass
        after = self._mat_snapshot(o)
        self._load_selected_props()
        self.view.update()
        self._undo_push_material(o.id, f"Preset {name}", before, after)
        self.refresh_list()
        self.statusBar().showMessage(f"preset {name} applied", 2000)

    def _snapshot(self):
        path = f"snapshot_{time.strftime('%Y%m%d_%H%M%S')}.png"
        ok = self.view.grabFramebuffer().save(path, "PNG")
        self.statusBar().showMessage(f"snapshot {'saved ' + path if ok else 'FAILED'}", 3000)

    def _open_render(self):
        proxies = []
        for o in self.view.scene.objects:
            if o.mesh is None:
                continue
            try:
                b = mesh_bounds(o.mesh)
                m4 = o.transform.update_matrix()
                c = (m4 @ np.append(np.asarray(b["center"], float), 1.0))[:3]
                r = float(b["radius"]) * float(np.abs(np.asarray(o.transform.scale, float)).max())
                proxies.append({"center": c, "radius": r,
                                "color": np.asarray(o.color, float).ravel()[:3]})
            except (KeyError, TypeError, ValueError):
                continue
        from render.dialog import RenderDialog as _RD
        _RD(self, proxies).exec()  # uses top-level RenderDialog (local alias, small diff)

    def _tick_fps(self):
        n = len(self.view.scene.objects)
        sel = self.view.selected.name if self.view.selected else "none"
        try:
            nf = len(self.view.get_selected_faces())
        except (AttributeError, TypeError):
            nf = 0
        mode = "Sculpt" if self.view.sculpt_mode else \
            ("Edit" if self.view.edit_mode else self.view.mode)
        self.statusBar().showMessage(
            f"{self.view.fps:.1f} fps | {mode} | objects={n} | selected={sel} | faces={nf}")
        self._update_face_label(nf)


def main():
    app = QApplication(sys.argv)
    win = BlendClone()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
