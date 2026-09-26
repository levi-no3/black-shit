"""Diagnostic: REAL Qt event delivery via QTest (not direct handler calls)."""
import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer, QPoint, Qt
from PySide6.QtTest import QTest

app = QApplication(sys.argv)
from app import BlendClone
w = BlendClone()
w.show()
app.processEvents()
v = w.view
v.setFocus()
out = []

def step1():
    cx, cy = int(v.width() / 2), int(v.height() / 2)
    th0 = v.camera.theta
    QTest.mousePress(v, Qt.LeftButton, Qt.NoModifier, QPoint(cx, cy))
    QTest.mouseMove(v, QPoint(cx + 60, cy + 20))
    QTest.mouseRelease(v, Qt.LeftButton, Qt.NoModifier, QPoint(cx + 60, cy + 20))
    app.processEvents()
    out.append(("real-drag-orbit", v.camera.theta != th0, th0, v.camera.theta))

def step2():
    v.select(None)
    app.processEvents()
    QTest.mouseClick(v, Qt.LeftButton, Qt.NoModifier,
                     QPoint(int(v.width() / 2), int(v.height() / 2)))
    app.processEvents()
    sel = v.selected.name if v.selected else None
    out.append(("real-click-select", sel is not None, sel))

def finish():
    for row in out:
        print(*row, flush=True)
    app.quit()

QTimer.singleShot(1200, step1)
QTimer.singleShot(1800, step2)
QTimer.singleShot(2400, finish)
sys.exit(app.exec())
