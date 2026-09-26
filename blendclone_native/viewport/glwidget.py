"""Native Qt OpenGL viewport — fixed-function-free, ANGLE/Adreno safe.

Uses QOpenGLShaderProgram + QOpenGLBuffer + VAO only (no PyOpenGL).
Shaders are `#version 300 es` (accepted by desktop GL and ANGLE), highp,
<100 ALU. Wireframe is emulated with GL_LINES (no glPolygonMode, which
does not exist on ES/ANGLE).
"""
from __future__ import annotations

import time

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMatrix4x4, QVector3D, QVector4D
from PySide6.QtOpenGL import (QOpenGLBuffer, QOpenGLShader,
                              QOpenGLShaderProgram, QOpenGLVertexArrayObject)
from PySide6.QtOpenGLWidgets import QOpenGLWidget

from viewport.camera import OrbitCamera
from viewport.picking import apply_face_click, clear_faces, raycast_mesh
from sculpt.brush import grab_brush, inflate_brush, smooth_brush
from viewport.scene import (Object3D, Scene, make_cube_mesh, make_grid_mesh,
                            mesh_bounds)

GL_TRIANGLES, GL_LINES = 0x0004, 0x0001
GL_UNSIGNED_INT, GL_FLOAT = 0x1405, 0x1406
GL_DEPTH_TEST, GL_COLOR_BIT, GL_DEPTH_BIT = 0x0B71, 0x4000, 0x0100

VS = """#version 330
layout(location=0) in vec3 aPos;
layout(location=1) in vec3 aNormal;
uniform mat4 uMVP; uniform mat4 uModel;
out vec3 vN; out vec3 vW;
void main(){vec4 w=uModel*vec4(aPos,1.0);vW=w.xyz;vN=mat3(uModel)*aNormal;
gl_Position=uMVP*vec4(aPos,1.0);}
"""
FS = """#version 330
in vec3 vN; in vec3 vW;
uniform vec3 uColor; uniform vec3 uLightDir;
uniform vec3 uCamPos; uniform int uMode;
uniform float uMetallic; uniform float uRough;
uniform vec4 uBlob; uniform int uShadowOn; uniform int uIsGrid; // M3-approx blob, no FBO
out vec4 fragColor;
void main(){vec3 N=normalize(vN+vec3(1e-5));vec3 L=normalize(uLightDir);
float dif=max(dot(N,L),0.0);vec3 V=normalize(uCamPos-vW);
vec3 H=normalize(L+V);
float spec=pow(max(dot(N,H),0.0),mix(64.0,8.0,uRough))*(1.0-uRough*0.7)*(1.0-uMetallic*0.3);
vec3 col=uColor*(0.28+0.72*dif)+vec3(spec)*(uMode==2?1.0:0.6);
if(uMode==2){col=mix(col,vec3(dot(col,vec3(0.333))),0.15)+vec3(0.05);}
if(uIsGrid==1&&uShadowOn==1){float d=distance(vW.xz,uBlob.xy);float k=1.0-smoothstep(0.0,uBlob.z,d);col*=1.0-uBlob.w*k;}
fragColor=vec4(col,1.0);}
"""
MODES = ("wire", "solid", "studio")


class ViewportGL(QOpenGLWidget):
    selectionChanged = Signal(int)  # selected object id, -1 = none
    faceSelectionChanged = Signal(int)  # selected face count
    editModeChanged = Signal(bool)
    sculptStrokeStarted = Signal(int)  # sculpt stroke anchor (obj id)
    sculptStrokeUpdated = Signal(int)  # sculpt dab applied (obj id)
    sculptStrokeFinished = Signal(int)  # sculpt stroke end (obj id)

    def _ilog(self, msg: str) -> None:
        # Temporary real-input diagnostic: append to cwd log, never raise.
        try:
            with open("blendclone_input.log", "a", encoding="utf-8") as f:
                f.write(f"{time.perf_counter():.2f} {msg}\n")
        except OSError:
            pass

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)
        self.camera = OrbitCamera()
        self.scene = Scene()
        self.scene.add(Object3D(make_cube_mesh(), name="Cube"))
        self.grid = make_grid_mesh()
        self.mode = "solid"
        self.edit_mode = False
        self.sculpt_mode = False
        self.sculpt_brush = {"type": "grab", "radius": 0.5, "strength": 0.5}
        self._sculpting = False
        self._sculpt_obj_id = None
        self._sculpt_last = None  # last hit center, mesh-local (N,3) point
        self.shadow_on = True  # M3-approx blob toggle (key 4 / toolbar)
        self.selected: Object3D | None = None
        self.fps = 0.0
        self._prog: QOpenGLShaderProgram | None = None
        self._vao: QOpenGLVertexArrayObject | None = None
        self._gpu: dict = {}
        self._funcs = None
        self._last = None
        self._moved = 0
        self._frames = 0
        self._t0 = time.perf_counter()

    # -- public API used by app.py --
    def set_mode(self, mode: str) -> None:
        if mode in MODES:
            self.mode = mode
            self.update()

    def set_shadow(self, on: bool) -> None:
        self.shadow_on = bool(on)
        self.update()

    def add_object(self, mesh: dict, name: str) -> Object3D:
        obj = self.scene.add(Object3D(mesh, name=name))
        self.select(obj)
        self.update()
        return obj

    def select(self, obj: Object3D | None) -> None:
        for o in self.scene.objects:
            o.selected = (o is obj)
        self.selected = obj
        self._ilog(f"select -> {(obj.name if obj is not None else 'none')}")
        self.selectionChanged.emit(obj.id if obj is not None else -1)
        self.update()

    # -- edit mode (face picking) --
    def set_edit_mode(self, on: bool) -> None:
        self.edit_mode = bool(on)
        self.editModeChanged.emit(self.edit_mode)
        self.update()

    # -- sculpt mode (surface brushes, left-drag) --
    def set_sculpt_mode(self, on: bool) -> None:
        self.sculpt_mode = bool(on)
        if not self.sculpt_mode:
            self._sculpting = False
            self._sculpt_obj_id = None
            self._sculpt_last = None
        self.update()

    def set_sculpt_brush(self, brush_type=None, radius=None,
                         strength=None) -> None:
        if brush_type in ("grab", "smooth", "inflate"):
            self.sculpt_brush["type"] = brush_type
        if radius is not None:
            try:
                if float(radius) > 0:
                    self.sculpt_brush["radius"] = float(radius)
            except (TypeError, ValueError):
                pass
        if strength is not None:
            try:
                self.sculpt_brush["strength"] = float(strength)
            except (TypeError, ValueError):
                pass

    def _sculpt_ray(self, x, y):
        """Raycast selected mesh; return (obj, hit_local) or None.

        hit_local is the surface point in mesh-local space (brush space).
        Reuses the edit-mode raycast_mesh path.
        """
        o = self.selected
        if o is None or o.mesh is None or o.mesh.get("lines"):
            return None
        w, h = max(1, self.width()), max(1, self.height())
        ro, rd = self.camera.get_ray(2 * x / w - 1, 1 - 2 * y / h, w / h)
        try:
            pos = np.asarray(o.mesh["positions"], np.float32).reshape(-1, 3)
            idx = np.asarray(o.mesh["indices"], np.uint32).reshape(-1)
        except (KeyError, TypeError, ValueError):
            return None
        m = o.transform.update_matrix()
        f, t = raycast_mesh(pos, idx, ro, rd, m)
        if f is None:
            return None
        hit_w = np.asarray(ro, np.float64) + np.asarray(rd, np.float64) * float(t)
        try:
            inv = np.linalg.inv(np.asarray(m, np.float64).reshape(4, 4))
        except np.linalg.LinAlgError:
            return None
        hw = np.append(hit_w.reshape(3), 1.0)
        loc = (inv @ hw)[:3]
        w4 = float((inv @ hw)[3])
        if abs(w4) > 1e-12 and np.isfinite(w4):
            loc = loc / w4
        return o, np.asarray(loc, np.float64)

    def _sculpt_dab(self, o, center_local) -> bool:
        """Apply one brush dab at a mesh-local center. One call per event
        (rate-limit). Pushes the VBO update via update_object_mesh."""
        mesh = o.mesh
        if mesh is None:
            return False
        try:
            pos = np.asarray(mesh["positions"], np.float32).reshape(-1, 3)
        except (KeyError, TypeError, ValueError):
            return False
        if pos.shape[0] == 0:
            return False
        b = self.sculpt_brush
        try:
            r = max(1e-6, float(b.get("radius", 0.5)))
            s = float(b.get("strength", 0.5))
        except (TypeError, ValueError):
            return False
        t = str(b.get("type", "grab"))
        if t == "grab":
            if self._sculpt_last is None:
                return False
            delta = (np.asarray(center_local, np.float64).reshape(3)
                     - np.asarray(self._sculpt_last, np.float64).reshape(3))
            if float(np.linalg.norm(delta)) < 1e-9:
                return False
            new_pos = grab_brush(pos, center_local, delta, r)
        elif t == "smooth":
            try:
                idx = np.asarray(mesh["indices"], np.uint32).reshape(-1)
            except (KeyError, TypeError, ValueError):
                return False
            new_pos = smooth_brush(pos, idx, center_local, r, s)
        else:  # inflate (also covers unknown types defensively)
            nrm = mesh.get("normals")
            if nrm is not None:
                try:
                    nrm = np.asarray(nrm, np.float32).reshape(-1, 3)
                except (TypeError, ValueError):
                    nrm = None
            if nrm is None:
                nrm = np.zeros_like(pos)
            new_pos = inflate_brush(pos, nrm, center_local, r, s)
        try:
            if np.array_equal(np.asarray(new_pos), pos):
                return False
        except (TypeError, ValueError):
            pass
        mesh["positions"] = np.ascontiguousarray(new_pos, np.float32)
        self.update_object_mesh(o.id, mesh)
        return True

    def get_selected_faces(self) -> set:
        o = self.selected
        if o is None:
            return set()
        return set(getattr(o, "selected_faces", set()))

    def clear_face_selection(self) -> None:
        o = self.selected
        if o is not None and getattr(o, "selected_faces", None):
            o.selected_faces.clear()
            old_hl = o.__dict__.pop("_hl_mesh", None)
            o.__dict__.pop("_hl_key", None)
            if old_hl is not None:
                for key in [k for k in list(self._gpu.keys())
                            if k[0] == id(old_hl)]:
                    self._gpu.pop(key, None)
        self.faceSelectionChanged.emit(0)
        self.update()

    def delete_selected_faces(self) -> int:
        o = self.selected
        if o is None or o.mesh is None:
            return 0
        faces = sorted(self.get_selected_faces())
        if not faces:
            return 0
        old = o.mesh
        old_hl = o.__dict__.get("_hl_mesh")
        # Route through the modeling operator (Mesh round-trip) so the
        # delete path stays valid even though viewport meshes are dicts.
        from modeling.mesh import Mesh as _Mesh
        from modeling.operators import delete_faces as _del
        pos = np.asarray(old["positions"], np.float32).reshape(-1, 3).copy()
        idx = np.asarray(old["indices"], np.uint32).reshape(-1).copy()
        nrm = None
        if old.get("normals") is not None:
            nrm = np.asarray(old["normals"], np.float32).reshape(-1, 3).copy()
        m = _Mesh(pos, idx, nrm if nrm is not None else np.zeros_like(pos))
        _del(m, faces)
        new_normals = m.normals if m.normals is not None else np.zeros_like(m.positions)
        o.mesh = {"positions": np.ascontiguousarray(m.positions, np.float32),
                  "normals": np.ascontiguousarray(new_normals, np.float32),
                  "indices": np.ascontiguousarray(m.indices, np.uint32)}
        if old.get("lines"):
            o.mesh["lines"] = True
        for key in [k for k in list(self._gpu.keys())
                    if k[0] in (id(old), id(old_hl))]:
            self._gpu.pop(key, None)
        o.selected_faces.clear()
        o.__dict__.pop("_hl_key", None)
        o.__dict__.pop("_hl_mesh", None)
        n = len(faces)
        self.faceSelectionChanged.emit(0)
        self.update()
        return n

    def update_object_mesh(self, obj_id: int, mesh_dict: dict) -> bool:
        """Re-upload buffers for one object (modeling.transform push path)."""
        obj = self.scene.find_by_id(obj_id)
        if obj is None or mesh_dict is None:
            return False
        old = obj.mesh
        old_hl = obj.__dict__.get("_hl_mesh")
        if old is not None:
            for key in [k for k in list(self._gpu.keys())
                        if k[0] in (id(old), id(old_hl))]:
                self._gpu.pop(key, None)
        obj.mesh = mesh_dict
        if getattr(obj, "selected_faces", None):
            obj.selected_faces.clear()
        obj.__dict__.pop("_hl_key", None)
        obj.__dict__.pop("_hl_mesh", None)
        self.faceSelectionChanged.emit(0)
        self.update()
        return True

    def delete_selected(self) -> bool:
        o = self.selected
        if o is None:
            return False
        old = o.mesh
        old_hl = o.__dict__.get("_hl_mesh")
        if old is not None:
            for key in [k for k in list(self._gpu.keys())
                        if k[0] in (id(old), id(old_hl))]:
                self._gpu.pop(key, None)
        self.scene.remove(o)
        self.select(None)
        self.update()
        return True

    def duplicate_selected(self) -> Object3D | None:
        o = self.selected
        if o is None:
            return None
        mesh = o.mesh
        new_mesh = None
        if mesh is not None:
            new_mesh = {
                "positions": np.asarray(mesh["positions"], np.float32).copy(),
                "normals": np.asarray(mesh["normals"], np.float32).copy(),
                "indices": np.asarray(mesh["indices"], np.uint32).copy(),
            }
            if mesh.get("lines"):
                new_mesh["lines"] = True
        dup = Object3D(new_mesh, name=f"{o.name}.copy")
        dup.color = o.color.copy()
        dup.metallic = float(o.metallic)
        dup.roughness = float(o.roughness)
        try:
            dup.emissive = np.asarray(getattr(o, "emissive", (0, 0, 0)),
                                      dtype=np.float32).copy()
        except (TypeError, ValueError):
            dup.emissive = np.zeros(3, dtype=np.float32)
        dup.transform.pos = o.transform.pos.copy() + np.array([0.5, 0.0, 0.0], np.float32)
        dup.transform.rot_euler = o.transform.rot_euler.copy()
        dup.transform.scale = o.transform.scale.copy()
        self.scene.add(dup)
        self.select(dup)
        self.update()
        return dup

    # -- GL setup --
    def initializeGL(self):
        self._funcs = self.context().functions()
        self._funcs.glClearColor(0.11, 0.12, 0.14, 1.0)
        self._prog = QOpenGLShaderProgram(self)
        self._prog.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Vertex, VS)
        self._prog.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Fragment, FS)
        if not self._prog.link():
            print("shader link failed:", self._prog.log())
        self._vao = QOpenGLVertexArrayObject(self)
        self._vao.create()

    def resizeGL(self, w, h):
        if self._funcs and h > 0:
            self._funcs.glViewport(0, 0, w, h)

    def _loc(self, name):
        # This PySide6 build only exposes location-based setUniformValue
        # overloads (no (str, QVector3D/QMatrix4x4) forms), so all uniform
        # writes go through int locations.
        return int(self._prog.uniformLocation(name))

    def _u1i(self, name, v):
        self._funcs.glUniform1i(self._loc(name), int(v))

    def _u1f(self, name, v):
        self._funcs.glUniform1f(self._loc(name), float(v))

    def _u3f(self, name, x, y, z):
        self._funcs.glUniform3f(self._loc(name), float(x), float(y), float(z))

    def _u4f(self, name, x, y, z, w):
        self._funcs.glUniform4f(self._loc(name), float(x), float(y), float(z), float(w))

    def _uMat4(self, name, m):
        # Row-major numpy + transpose=True == old QMatrix4x4(*ravel) path.
        data = np.asarray(m, np.float32).reshape(-1).tolist()
        self._funcs.glUniformMatrix4fv(self._loc(name), 1, True, data)

    def paintGL(self):
        f = self._funcs
        if f is None or self._prog is None or not self._prog.isLinked():
            return
        f.glClear(GL_COLOR_BIT | GL_DEPTH_BIT)
        f.glEnable(GL_DEPTH_TEST)
        w, h = max(1, self.width()), max(1, self.height())
        aspect = w / h
        view, proj, eye = self.camera.get_view(), self.camera.get_proj(aspect), self.camera.get_eye()
        self._prog.bind()
        self._u3f("uLightDir", 0.5, 0.8, 0.6)
        self._u3f("uCamPos", *[float(v) for v in eye])
        self._u1i("uMode", MODES.index(self.mode))
        # M3-approx blob shadow: centroid XZ + covering radius, no shadowmap FBO.
        pts = [o.transform.pos for o in self.scene.objects if o.mesh is not None]
        if pts:
            xz = np.asarray(pts, np.float32).reshape(-1, 3)[:, [0, 2]]
            cc = xz.mean(axis=0); rr = float(np.abs(xz - cc).max()) + 1.5
        else:
            cc = np.zeros(2, np.float32); rr = 2.0
        self._u4f("uBlob", float(cc[0]), float(cc[1]), rr, 0.45)
        self._u1i("uShadowOn", 1 if self.shadow_on else 0)
        self._draw(proj @ view @ np.eye(4, dtype=np.float32), np.eye(4, dtype=np.float32),
                   (0.32, 0.33, 0.35), self.grid, True)
        for o in self.scene.objects:
            if o.mesh is None:
                continue
            model = o.transform.update_matrix()
            if o.selected:
                col = (1.0, 0.55, 0.15)
            else:
                try:
                    em = np.asarray(getattr(o, "emissive", (0, 0, 0)),
                                    dtype=float).ravel()[:3]
                except (TypeError, ValueError):
                    em = np.zeros(3)
                col = tuple(float(c) + float(e) for c, e in
                            zip(tuple(float(c) for c in o.color), em))
            self._u1f("uMetallic", float(o.metallic))
            self._u1f("uRough", float(o.roughness))
            self._draw(proj @ view @ model, model, col, o.mesh, False)
            # Edit-mode face highlight: second draw call, orange tint,
            # reusing the uColor path (no shader change).
            if self.edit_mode and getattr(o, "selected_faces", None):
                hl = self._highlight_mesh(o)
                if hl is not None:
                    self._draw(proj @ view @ model, model,
                               (1.0, 0.55, 0.15), hl, False)
        self._prog.release()
        self._frames += 1
        now = time.perf_counter()
        if now - self._t0 >= 0.5:
            self.fps = self._frames / (now - self._t0)
            self._frames, self._t0 = 0, now

    def _draw(self, mvp, model, color, mesh, is_grid):
        wire = is_grid or self.mode == "wire"
        vbo, count = self._upload(mesh, wire)
        p = self._prog
        self._u1i("uIsGrid", 1 if is_grid else 0)
        self._uMat4("uMVP", mvp)
        self._uMat4("uModel", model)
        self._u3f("uColor", *color)
        self._vao.bind()
        vbo.bind()
        p.enableAttributeArray(0)
        p.setAttributeBuffer(0, GL_FLOAT, 0, 3, 24)
        p.enableAttributeArray(1)
        p.setAttributeBuffer(1, GL_FLOAT, 12, 3, 24)
        # NOTE: glDrawElements is broken via PySide6's QOpenGLFunctions
        # binding (rejects both 0 and None for the indices offset), so the
        # uploader expands indices to flat verts and we use glDrawArrays.
        self._funcs.glDrawArrays(int(GL_LINES if wire else GL_TRIANGLES), 0, int(count))
        p.disableAttributeArray(0)
        p.disableAttributeArray(1)
        vbo.release()
        self._vao.release()

    def _highlight_mesh(self, o):
        """Cached subset mesh for selected faces (reuses uColor path)."""
        faces = sorted(getattr(o, "selected_faces", set()) or set())
        if not faces or o.mesh is None or o.mesh.get("lines"):
            return None
        key = frozenset(faces)
        if o.__dict__.get("_hl_key") == key and o.__dict__.get("_hl_mesh") is not None:
            return o.__dict__["_hl_mesh"]
        old_hl = o.__dict__.get("_hl_mesh")
        if old_hl is not None:
            for k in [k for k in list(self._gpu.keys()) if k[0] == id(old_hl)]:
                self._gpu.pop(k, None)
        try:
            tri = np.asarray(o.mesh["indices"], np.uint32).reshape(-1, 3)
        except (KeyError, TypeError, ValueError):
            return None
        valid = [f for f in faces if 0 <= f < tri.shape[0]]
        if not valid:
            return None
        hl = {"positions": o.mesh["positions"], "normals": o.mesh["normals"],
              "indices": np.ascontiguousarray(tri[valid].reshape(-1), np.uint32)}
        o.__dict__["_hl_key"] = key
        o.__dict__["_hl_mesh"] = hl
        return hl

    def _upload(self, mesh, wire):
        key = (id(mesh), wire)
        hit = self._gpu.get(key)
        if hit:
            return hit
        pos = np.asarray(mesh["positions"], np.float32).reshape(-1, 3)
        nor = np.asarray(mesh["normals"], np.float32).reshape(-1, 3)
        tri = np.asarray(mesh["indices"], np.uint32).ravel()
        if mesh.get("lines"):
            flat_idx = tri  # already line-list pairs
        elif wire:
            flat_idx = np.ascontiguousarray(
                tri.reshape(-1, 3)[:, [0, 1, 1, 2, 2, 0]].ravel(), np.uint32)
        else:
            flat_idx = tri
        flat_pos = pos[flat_idx]
        flat_nor = nor[flat_idx]
        vbo = QOpenGLBuffer(QOpenGLBuffer.Type.VertexBuffer)
        vbo.create()
        vbo.bind()
        vbo.setUsagePattern(QOpenGLBuffer.UsagePattern.StaticDraw)
        raw = np.ascontiguousarray(np.hstack([flat_pos, flat_nor]), np.float32)
        vbo.allocate(raw.tobytes(), len(raw.tobytes()))
        vbo.release()
        entry = (vbo, int(flat_idx.size))
        self._gpu[key] = entry
        return entry

    # -- interaction: left=orbit, right/shift=pan, wheel=zoom, 1/2/3=mode --
    def mousePressEvent(self, e):
        self._ilog(f"press btn={e.button().value} pos={e.position().x():.0f},{e.position().y():.0f}")
        self._last = (e.position().x(), e.position().y())
        self._moved = 0
        self.setFocus()
        if (self.sculpt_mode and (e.buttons() & Qt.LeftButton)
                and not (e.modifiers() & Qt.ShiftModifier)):
            hit = self._sculpt_ray(e.position().x(), e.position().y())
            if hit is not None:
                o, loc = hit
                self._sculpting = True
                self._sculpt_obj_id = o.id
                self._sculpt_last = np.asarray(loc, np.float64)
                self.sculptStrokeStarted.emit(o.id)
                if self._sculpt_dab(o, loc):
                    self.sculptStrokeUpdated.emit(o.id)

    def mouseMoveEvent(self, e):
        if self._last is None:
            return
        x, y = e.position().x(), e.position().y()
        dx, dy = x - self._last[0], y - self._last[1]
        self._last = (x, y)
        self._moved += abs(dx) + abs(dy)
        btns = e.buttons()
        if self._sculpting and self.sculpt_mode and (btns & Qt.LeftButton):
            # Sculpt drag: one dab per event (rate-limit), no orbit.
            hit = self._sculpt_ray(x, y)
            if hit is not None:
                o, loc = hit
                if o.id == self._sculpt_obj_id:
                    if self._sculpt_dab(o, loc):
                        self.sculptStrokeUpdated.emit(o.id)
                    self._sculpt_last = np.asarray(loc, np.float64)
            self.update()
            return
        if (btns & Qt.RightButton) or (btns & Qt.LeftButton and e.modifiers() & Qt.ShiftModifier):
            self.camera.pan(dx, -dy)
        elif btns & Qt.LeftButton:
            self.camera.orbit(dx, dy)
        self.update()

    def mouseReleaseEvent(self, e):
        self._ilog(f"release moved={self._moved:.0f} pos={e.position().x():.0f},{e.position().y():.0f}")
        if self._sculpting:
            oid = self._sculpt_obj_id
            self._sculpting = False
            self._sculpt_obj_id = None
            self._sculpt_last = None
            self._last = None
            if oid is not None:
                self.sculptStrokeFinished.emit(int(oid))
            return
        if self.sculpt_mode:
            # Sculpt mode: clicks never change selection/pick faces.
            self._last = None
            return
        if self._moved < 6:
            try:
                additive = bool(e.modifiers() & Qt.ShiftModifier)
            except (AttributeError, TypeError):
                additive = False
            if self.edit_mode:
                self._pick_face(e.position().x(), e.position().y(), additive)
            else:
                self._pick(e.position().x(), e.position().y())
        self._last = None

    def wheelEvent(self, e):
        self._ilog(f"wheel delta={e.angleDelta().y()}")
        self.camera.dolly(-e.angleDelta().y() / 1200.0)
        self.update()

    def keyPressEvent(self, e):
        self._ilog(f"key={getattr(e.key(), 'value', e.key())}")
        if e.key() == Qt.Key_1:
            self.set_mode("wire")
        elif e.key() == Qt.Key_2:
            self.set_mode("solid")
        elif e.key() == Qt.Key_3:
            self.set_mode("studio")
        elif e.key() == Qt.Key_4:
            self.set_shadow(not self.shadow_on)
        elif e.key() == Qt.Key_Tab:
            self.set_edit_mode(not self.edit_mode)
            e.accept()
            return
        elif e.key() == Qt.Key_Escape:
            if self.edit_mode and self.get_selected_faces():
                self.clear_face_selection()
                e.accept()
                return

    def _pick_face(self, x, y, additive: bool = False):
        """Edit-mode per-triangle picking in world space on selected object."""
        w, h = max(1, self.width()), max(1, self.height())
        ro, rd = self.camera.get_ray(2 * x / w - 1, 1 - 2 * y / h, w / h)
        targets = []
        if self.selected is not None and self.selected.mesh is not None:
            targets = [self.selected]
        else:
            targets = [o for o in self.scene.objects if o.mesh is not None]
        best_o, best_f, best_t = None, None, float("inf")
        for o in targets:
            if o.mesh is None or o.mesh.get("lines"):
                continue
            try:
                pos = np.asarray(o.mesh["positions"], np.float32).reshape(-1, 3)
                idx = np.asarray(o.mesh["indices"], np.uint32).reshape(-1)
            except (KeyError, TypeError, ValueError):
                continue
            m = o.transform.update_matrix()
            f, t = raycast_mesh(pos, idx, ro, rd, m)
            if f is not None and t < best_t:
                best_o, best_f, best_t = o, f, t
        if best_o is None:
            if not additive:
                self.clear_face_selection()
            return
        if best_o is not self.selected:
            self.select(best_o)
        if getattr(best_o, "selected_faces", None) is None:
            best_o.selected_faces = set()
        apply_face_click(best_o.selected_faces, int(best_f), additive)
        best_o.__dict__.pop("_hl_key", None)
        # old highlight mesh GPU entry is stale; drop it lazily
        old_hl = best_o.__dict__.pop("_hl_mesh", None)
        if old_hl is not None:
            for k in [k for k in list(self._gpu.keys()) if k[0] == id(old_hl)]:
                self._gpu.pop(k, None)
        self.faceSelectionChanged.emit(len(best_o.selected_faces))
        self.update()

    def _pick(self, x, y):
        w, h = max(1, self.width()), max(1, self.height())
        ro, rd = self.camera.get_ray(2 * x / w - 1, 1 - 2 * y / h, w / h)
        best, best_t = None, float("inf")
        for o in self.scene.objects:
            if o.mesh is None:
                continue
            b = mesh_bounds(o.mesh)
            m = o.transform.update_matrix()
            c = (m @ np.append(b["center"], 1.0))[:3]
            r = b["radius"] * float(np.abs(o.transform.scale).max())
            oc = c - ro
            t = float(oc @ rd)
            if t > 0 and float(oc @ oc - t * t) < r * r and t < best_t:
                best, best_t = o, t
        self.select(best)
