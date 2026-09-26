"""BlendClone NATIVE render/dialog.py — CPU pathtrace render dialog (numpy+PySide6, no GL)."""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (QComboBox, QDialog, QFileDialog, QHBoxLayout,
                               QLabel, QPushButton, QVBoxLayout)

from render.color import float_to_uint8
from render.pathtracer import render_tile

_SIZES = ("64", "128", "256")
_SPPS = ("1", "4")


def proxies_to_spheres(proxies) -> list:
    """Convert lightweight {center,radius,color} proxies to pathtracer spheres."""
    out = []
    for p in (proxies or []):
        try:
            c = np.asarray(p.get("center", (0, 0, 0)), dtype=float).ravel()[:3]
            r = float(p.get("radius", 0.5))
            col = np.asarray(p.get("color", (0.8, 0.8, 0.8)), dtype=float).ravel()[:3]
            if not np.all(np.isfinite(c)) or not np.isfinite(r) or r <= 0:
                continue
            out.append({"center": c, "radius": r,
                        "material": {"base_color": np.clip(col, 0.0, 1.0)}})
        except (TypeError, ValueError, AttributeError):
            continue
    if not out:  # fallback so empty scene still shows something
        out = [{"center": np.array([0.0, 0.0, -2.5]),
                "radius": 0.7, "material": {"base_color": np.array([0.8, 0.2, 0.2])}}]
    return out


def spheres_to_qimage(u8: np.ndarray) -> QImage:
    """Contiguous (h,w,3) uint8 RGB -> QImage copy (safe lifetime)."""
    a = np.ascontiguousarray(u8, dtype=np.uint8)
    h, w, _ = a.shape
    return QImage(a.data, w, h, w * 3, QImage.Format_RGB888).copy()


class RenderDialog(QDialog):
    """Modal CPU render dialog. Synchronous render + progress label (no freeze >~30s @128px)."""

    def __init__(self, parent=None, proxies=None):
        super().__init__(parent)
        self.setWindowTitle("Render with CPU")
        self.setModal(True)
        self._proxies = list(proxies) if proxies else []
        self._u8: np.ndarray | None = None
        lay = QVBoxLayout(self)
        row = QHBoxLayout()
        row.addWidget(QLabel("Size:"))
        self.size_combo = QComboBox()
        self.size_combo.addItems(list(_SIZES))
        self.size_combo.setCurrentText("128")
        row.addWidget(self.size_combo)
        row.addWidget(QLabel("SPP:"))
        self.spp_combo = QComboBox()
        self.spp_combo.addItems(list(_SPPS))
        row.addWidget(self.spp_combo)
        self.render_btn = QPushButton("Render")
        self.render_btn.clicked.connect(self._render)
        row.addWidget(self.render_btn)
        self.save_btn = QPushButton("Save PNG")
        self.save_btn.setEnabled(False)
        self.save_btn.clicked.connect(self._save)
        row.addWidget(self.save_btn)
        lay.addLayout(row)
        self.status = QLabel("Ready")
        lay.addWidget(self.status)
        self.view = QLabel("No render yet")
        self.view.setAlignment(Qt.AlignCenter)
        self.view.setMinimumSize(260, 260)
        self.view.setScaledContents(True)
        lay.addWidget(self.view, 1)

    def _render(self):
        try:
            n = int(self.size_combo.currentText())
        except ValueError:
            n = 128
        try:
            spp = int(self.spp_combo.currentText())
        except ValueError:
            spp = 1
        self.status.setText(f"Rendering {n}x{n} spp={spp}...")
        self.status.repaint()
        spheres = proxies_to_spheres(self._proxies)
        tgt = np.mean([s["center"] for s in spheres], axis=0)
        eye = np.asarray(tgt, float).ravel() + np.array([0.0, 1.2, 3.5])
        cam = {"pos": eye, "target": np.asarray(tgt, float).ravel()}
        img = render_tile(spheres, cam, n, n, spp=spp)  # deterministic seed 1337
        self._u8 = np.ascontiguousarray(float_to_uint8(img), dtype=np.uint8)
        self.view.setPixmap(QPixmap.fromImage(spheres_to_qimage(self._u8)))
        self.save_btn.setEnabled(True)
        self.status.setText(f"Done {n}x{n} spp={spp}")

    def _save(self):
        if self._u8 is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save PNG", "render.png", "PNG (*.png)")
        if path:
            spheres_to_qimage(self._u8).save(path, "PNG")
            self.status.setText(f"Saved {path}")
