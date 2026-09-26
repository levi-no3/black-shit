"""Diagnostic: synthetic mouse/key/toolbar input, verify state changes + pixels, exit."""
import sys
import numpy as np
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer, QPointF, QEvent
from PySide6.QtGui import QMouseEvent
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

app = QApplication(sys.argv)
from app import BlendClone
w = BlendClone()
w.show()
app.processEvents()
v = w.view
out = []

def grab():
    a = v.grabFramebuffer()
    a.save("diag_a.png", "PNG")
    return True

def step1():
    th0 = (v.camera.theta, v.camera.phi, v.camera.radius)
    cx, cy = v.width() / 2, v.height() / 2
    # drag: press at center then move +60px
    press = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(cx, cy),
                        Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    v.mousePressEvent(press)
    mv = QMouseEvent(QEvent.Type.MouseMove, QPointF(cx + 60, cy + 20),
                     Qt.NoButton, Qt.LeftButton, Qt.NoModifier)
    v.mouseMoveEvent(mv)
    rel = QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(cx + 60, cy + 20),
                      Qt.LeftButton, Qt.NoButton, Qt.NoModifier)
    v.mouseReleaseEvent(rel)
    app.processEvents()
    th1 = (v.camera.theta, v.camera.phi, v.camera.radius)
    out.append(("orbit-changed", th0 != th1, th0, th1))

def step2():
    n0 = len(v.scene.objects)
    # find Add Cube action and trigger
    found = False
    for tb in w.findChildren(type(w.view)):
        pass
    for act in w.actions() + [a for tb2 in w.findChildren(object) for a in []]:
        pass
    from PySide6.QtWidgets import QToolBar
    for tb in w.findChildren(QToolBar):
        for act in tb.actions():
            if act.text() == "Add Cube":
                act.trigger()
                found = True
    app.processEvents()
    out.append(("add-cube", found and len(v.scene.objects) == n0 + 1, n0, len(v.scene.objects)))

def step3():
    v.update(); app.processEvents()
    a = v.grabFramebuffer(); a.save("diag_a.png", "PNG")
    v.camera.orbit(0.6, 0.2)
    v.update(); app.processEvents()
    b = v.grabFramebuffer(); b.save("diag_b.png", "PNG")
    import hashlib
    ha = hashlib.md5(bytes(a.bits())).hexdigest()
    hb = hashlib.md5(bytes(b.bits())).hexdigest()
    out.append(("pixels-change", ha != hb, ha[:8], hb[:8]))

def step4():
    from PySide6.QtGui import QKeyEvent
    m0 = v.mode
    ev = QKeyEvent(QEvent.Type.KeyPress, Qt.Key_1, Qt.NoModifier)
    v.keyPressEvent(ev)
    out.append(("key-wire", v.mode == "wire", m0, v.mode))

def finish():
    for row in out:
        print(*row)
    print("MODE", v.mode, "FPS", round(v.fps, 1))
    app.quit()

QTimer.singleShot(1200, step1)
QTimer.singleShot(1600, step2)
QTimer.singleShot(2000, step3)
QTimer.singleShot(2200, step4)
QTimer.singleShot(2600, finish)
sys.exit(app.exec())
