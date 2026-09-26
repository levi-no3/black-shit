"""Timeline dock (Qt): frame slider 1..250, play/pause, Add Key.

Emits signals only — it never touches the scene. app.py owns the Clip
and applies poses on frameChanged.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QDockWidget, QHBoxLayout, QLabel, QPushButton,
                               QSlider, QVBoxLayout, QWidget)


class TimelineDock(QDockWidget):
    frameChanged = Signal(int)  # new current frame
    addKeyRequested = Signal(int)  # "Add Key" pressed at frame

    def __init__(self, parent=None, fps: int = 24,
                 fmin: int = 1, fmax: int = 250):
        super().__init__("Timeline", parent)
        self._fps = int(fps) or 24
        self._fmin, self._fmax = int(fmin), int(fmax)
        self._frame = self._fmin

        root = QWidget(self)
        lay = QVBoxLayout(root)
        lay.setContentsMargins(6, 4, 6, 4)

        row = QHBoxLayout()
        self._play = QPushButton("Play")
        self._play.setCheckable(True)
        self._play.toggled.connect(self.set_playing)
        row.addWidget(self._play)

        self._slider = QSlider(Qt.Horizontal)
        self._slider.setRange(self._fmin, self._fmax)
        self._slider.setValue(self._frame)
        self._slider.valueChanged.connect(self._on_slider)
        row.addWidget(self._slider, 1)

        self._flabel = QLabel()
        self._flabel.setFixedWidth(90)
        row.addWidget(self._flabel)

        self._key = QPushButton("Add Key")
        self._key.setToolTip("Key selected object at current frame")
        self._key.clicked.connect(lambda: self.addKeyRequested.emit(self._frame))
        row.addWidget(self._key)
        lay.addLayout(row)

        # Onion-ish summary (filled by app.py: keys at current frame).
        self._info = QLabel()
        self._info.setToolTip("Keys on the current frame (set by app).")
        lay.addWidget(self._info)

        self.setWidget(root)

        self._timer = QTimer(self)
        self._timer.setInterval(max(1, int(round(1000.0 / self._fps))))
        self._timer.timeout.connect(self._advance)
        self._refresh_label()
        self.set_info(f"frame {self._frame} | no keys")

    # -- state --
    def frame(self) -> int:
        return self._frame

    def is_playing(self) -> bool:
        return self._timer.isActive()

    def set_frame(self, frame: int, emit: bool = True) -> None:
        f = max(self._fmin, min(self._fmax, int(frame)))
        self._frame = f
        self._slider.blockSignals(True)
        self._slider.setValue(f)
        self._slider.blockSignals(False)
        self._refresh_label()
        if emit:
            self.frameChanged.emit(f)

    def set_playing(self, on: bool) -> None:
        if on and not self._timer.isActive():
            self._timer.start()
        elif not on and self._timer.isActive():
            self._timer.stop()
        if self._play.isChecked() != bool(on):
            self._play.blockSignals(True)
            self._play.setChecked(bool(on))
            self._play.blockSignals(False)
        self._play.setText("Pause" if on else "Play")

    def set_info(self, text: str) -> None:
        self._info.setText(str(text))

    # -- slots --
    def _on_slider(self, v: int) -> None:
        self.set_frame(int(v), emit=True)

    def _advance(self) -> None:
        nxt = self._frame + 1
        if nxt > self._fmax:
            nxt = self._fmin
        self.set_frame(nxt, emit=True)

    def _refresh_label(self) -> None:
        self._flabel.setText(f"{self._frame} / {self._fmax}")
