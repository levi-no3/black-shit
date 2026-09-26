"""List-based node editor — Full QGraphicsView canvas is OUT OF SCOPE.

Minimal dock: node list + Add buttons + link via two combo boxes +
evaluate preview swatch. Emits materialChanged(Material) on any change.
"""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QComboBox, QDockWidget, QHBoxLayout, QLabel,
                               QListWidget, QPushButton, QVBoxLayout, QWidget)

from shading.nodes import INPUTS, OUTPUTS, NodeGraph


class NodeDock(QDockWidget):
    materialChanged = Signal(object)

    def __init__(self, parent=None):
        super().__init__("Shading", parent)
        self._graph = NodeGraph()
        self._loading = False
        root = QWidget()
        lay = QVBoxLayout(root)
        lay.setContentsMargins(4, 4, 4, 4)
        self._list = QListWidget()
        lay.addWidget(self._list, 1)
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        for t in ("Principled", "Mix", "Output", "Value", "RGB", "ColorRamp"):
            b = QPushButton(f"+{t[:4]}")
            b.setToolTip(f"Add {t}")
            b.clicked.connect(lambda _c, t=t: self._add(t))
            rl.addWidget(b)
        lay.addWidget(row)
        linkrow = QWidget()
        ll = QHBoxLayout(linkrow)
        ll.setContentsMargins(0, 0, 0, 0)
        self._src = QComboBox()
        self._dst = QComboBox()
        b_link = QPushButton("Link")
        b_link.clicked.connect(self._link_ui)
        b_clear = QPushButton("Clear")
        b_clear.clicked.connect(self._clear)
        ll.addWidget(self._src, 1)
        ll.addWidget(self._dst, 1)
        ll.addWidget(b_link)
        ll.addWidget(b_clear)
        lay.addWidget(linkrow)
        prow = QWidget()
        pl = QHBoxLayout(prow)
        pl.setContentsMargins(0, 0, 0, 0)
        self._swatch = QLabel("preview")
        self._swatch.setFixedHeight(28)
        self._swatch.setStyleSheet("background:#888888")
        b_eval = QPushButton("Evaluate")
        b_eval.clicked.connect(self._reevaluate)
        pl.addWidget(self._swatch, 1)
        pl.addWidget(b_eval)
        lay.addWidget(prow)
        lay.addWidget(QLabel("List editor only: no canvas (see docstring)."))
        self.setWidget(root)
        self._seed()
        self._refresh()

    def _seed(self):
        if not self._graph.nodes:
            p = self._graph.add_node("Principled",
                                     {"baseColor": [0.8, 0.08, 0.08],
                                      "metallic": 0.0, "roughness": 0.4,
                                      "emissive": [0.0, 0.0, 0.0]})
            o = self._graph.add_node("Output")
            try:
                self._graph.link(p, "shader", o, "surface")
            except ValueError:
                pass

    # -- public --
    def graph(self) -> NodeGraph:
        return self._graph

    def graph_dict(self) -> dict:
        return self._graph.to_dict()

    def set_graph(self, g: NodeGraph) -> None:
        self._loading = True
        try:
            self._graph = g if isinstance(g, NodeGraph) else NodeGraph()
            if not self._graph.nodes:
                self._seed()
            self._refresh()
        finally:
            self._loading = False
        self._reevaluate(emit=False)

    def set_graph_dict(self, d: dict | None) -> None:
        try:
            g = NodeGraph.from_dict(d) if isinstance(d, dict) else NodeGraph()
        except (TypeError, ValueError, KeyError, AttributeError):
            g = NodeGraph()
        self.set_graph(g)

    # -- ui --
    def _add(self, ntype: str):
        try:
            self._graph.add_node(ntype)
        except ValueError:
            return
        self._refresh()
        self._reevaluate()

    def _link_ui(self):
        s, d = self._src.currentText(), self._dst.currentText()
        try:
            sn, ss = s.rsplit(".", 1)
            dn, ds = d.rsplit(".", 1)
            self._graph.link(sn, ss, dn, ds)
        except (ValueError, AttributeError):
            return
        self._refresh()
        self._reevaluate()

    def _clear(self):
        self._graph.links.clear()
        self._refresh()
        self._reevaluate()

    def _outputs(self) -> list[str]:
        out = []
        for nid in sorted(self._graph.nodes):
            for s in OUTPUTS.get(self._graph.nodes[nid].type, ()):
                out.append(f"{nid}.{s}")
        return out

    def _inputs(self) -> list[str]:
        out = []
        for nid in sorted(self._graph.nodes):
            for s in INPUTS.get(self._graph.nodes[nid].type, ()):
                out.append(f"{nid}.{s}")
        return out

    def _refresh(self):
        self._list.clear()
        for nid in sorted(self._graph.nodes):
            n = self._graph.nodes[nid]
            self._list.addItem(f"{nid} [{n.type}] links="
                               f"{sum(1 for (t, _) in self._graph.links if t == nid)}")
        cur_s, cur_d = self._src.currentText(), self._dst.currentText()
        self._src.clear()
        self._src.addItems(self._outputs())
        self._dst.clear()
        self._dst.addItems(self._inputs())
        for cb, cur in ((self._src, cur_s), (self._dst, cur_d)):
            i = cb.findText(cur)
            if i >= 0:
                cb.setCurrentIndex(i)

    def _reevaluate(self, emit: bool = True):
        try:
            mat = self._graph.evaluate()
        except (TypeError, ValueError):
            return
        try:
            rgb = (np.asarray(mat.base_color, dtype=float).ravel()[:3] * 255).astype(int)
            self._swatch.setStyleSheet(
                f"background:rgb({int(rgb[0])},{int(rgb[1])},{int(rgb[2])})")
            self._swatch.setText(f"{float(mat.metallic):.2f}/{float(mat.roughness):.2f}")
        except (TypeError, ValueError, AttributeError):
            pass
        if emit and not self._loading:
            try:
                self.materialChanged.emit(mat)
            except RuntimeError:
                pass
