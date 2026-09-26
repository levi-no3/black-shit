"""Diagnostic: open BlendClone window, grab viewport pixels, save + analyze, exit."""
import sys
import numpy as np
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer

app = QApplication(sys.argv)
from app import BlendClone
w = BlendClone()
w.show()
app.processEvents()

def check():
    try:
        w.view.update()
        app.processEvents()
        img = w.view.grabFramebuffer()
        path = "diag_view.png"
        img.save(path, "PNG")
        print("GRABBED", img.width(), "x", img.height())
    except Exception as e:
        print("GRAB-FAIL", type(e).__name__, e)

QTimer.singleShot(1500, check)
QTimer.singleShot(2500, app.quit)
sys.exit(app.exec())
