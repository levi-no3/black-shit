"""Diagnostic: slider behavior headless."""
import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer

app = QApplication(sys.argv)
from app import BlendClone
w = BlendClone()
w.show()
app.processEvents()

def run():
    sel = w.view.selected
    print("startup-selected:", sel.name if sel else None, flush=True)
    print("n-objects:", len(w.view.scene.objects), flush=True)
    if sel is not None:
        print("color-before:", list(sel.color), flush=True)
    # drag R slider to max
    w._sliders["R"].setValue(255)
    app.processEvents()
    sel = w.view.selected
    print("color-after-R255:", list(sel.color) if sel else None, flush=True)
    # metallic slider
    w._sliders["Metallic"].setValue(100)
    app.processEvents()
    print("metallic-after:", sel.metallic if sel else None, flush=True)
    # sculpt sliders exist?
    print("has-sculpt-dock:", hasattr(w, "_sculpt_radius"), flush=True)
    # timeline slider
    print("timeline-frame:", w.timeline.frame() if hasattr(w.timeline, "frame") else "no-frame-api", flush=True)
    app.quit()

QTimer.singleShot(1200, run)
sys.exit(app.exec())
