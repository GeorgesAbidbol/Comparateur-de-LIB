"""Étape 3 (maquette) : atelier géométries.

Affichage seulement pour l'instant : l'arbre complet des géométries d'un mode, avec ce que
le diagnostic de l'étape 1 y trouve (géométries 3D seules, modèles en double), et le panneau
des paramètres de la géométrie choisie (adresse, grille, type). Rien n'est encore modifié.
Lancer : `python -m ma3lib.gui.atelier fichier.gdtf [mode]`.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import (QApplication, QComboBox, QFileDialog, QFormLayout, QHBoxLayout,
                               QLabel, QLineEdit, QMainWindow, QPushButton, QScrollArea, QSpinBox,
                               QVBoxLayout, QWidget)

from .. import diagnostic, gdtf
from ..gdtf import FixtureType, Geometry
from . import theme

ROW_H = 30
GAP_Y = 4
INDENT = 20
MARGIN = 12
TYPES = ["Geometry", "Beam", "Axis", "GeometryReference", "FilterColor", "FilterGobo", "Display"]
BADGE = {"Geometry": "GEO", "Beam": "BEAM", "Axis": "AXIS", "GeometryReference": "RÉF"}


@dataclass
class _Row:
    geo: Geometry
    depth: int
    rect: QRectF
    flag: str  # "", "3d" (aucun canal dans aucun mode), "double" (modèle en double)


class GeoTree(QWidget):
    selected = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.root: Optional[Geometry] = None
        self.useless: set[str] = set()
        self.doubles: set[str] = set()
        self.collapsed: set[int] = set()
        self.current: Optional[Geometry] = None
        self._rows: list[_Row] = []
        self._hover: Optional[_Row] = None

    def set_root(self, root, useless: set[str], doubles: set[str]) -> None:
        self.root, self.useless, self.doubles = root, useless, doubles
        self.collapsed = set()
        self.current = root
        self._relayout()
        self.selected.emit(root)

    def _relayout(self) -> None:
        self._rows = []
        y = MARGIN
        w = self.width() - 2 * MARGIN
        seen: set[str] = set()  # « modèle en double » écrit une seule fois par modèle, ensuite un point

        def add(g: Geometry, depth: int) -> None:
            nonlocal y
            flag = "3d" if g.name in self.useless else ("double" if g.reference in self.doubles
                                                         or g.name in self.doubles else "")
            if flag == "double":
                key = g.reference or g.name
                flag = "double-vu" if key in seen else "double"
                seen.add(key)
            ind = depth * INDENT
            self._rows.append(_Row(g, depth, QRectF(MARGIN + ind, y, w - ind, ROW_H), flag))
            y += ROW_H + GAP_Y
            if id(g) not in self.collapsed:
                for c in g.children:
                    add(c, depth + 1)

        if self.root:
            add(self.root, 0)
        self.setMinimumHeight(int(y + MARGIN))
        self.update()

    def resizeEvent(self, e):
        self._relayout()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), theme.BG)
        for r in self._rows:
            g = r.geo
            sel = g is self.current
            fill = theme.HEADER if sel else (theme.ROW_HOVER if r is self._hover else theme.ROW)
            if r.flag == "3d" and not sel:
                fill = theme.PANEL
            p.setPen(Qt.NoPen)
            p.setBrush(fill)
            p.drawRoundedRect(r.rect, 5, 5)
            x = r.rect.left() + 8
            if g.children:
                p.setPen(theme.TEXT)
                p.setFont(theme.font(9, True))
                p.drawText(QRectF(x - 2, r.rect.top(), 14, ROW_H), Qt.AlignCenter,
                           "▸" if id(g) in self.collapsed else "▾")
            x += 16
            # pastille de type
            badge = BADGE.get(g.kind, g.kind[:4].upper())
            p.setFont(theme.font(7, True))
            bw = p.fontMetrics().horizontalAdvance(badge) + 12
            br = QRectF(x, r.rect.center().y() - 9, bw, 18)
            p.setBrush(theme.STATUS["bleu"] if g.kind == "Beam" else theme.ROW_HOVER)
            p.drawRoundedRect(br, 9, 9)
            p.setPen(theme.TEXT)
            p.drawText(br, Qt.AlignCenter, badge)
            x = br.right() + 10
            # nom (+ modèle pour une référence)
            dim = r.flag == "3d"
            p.setFont(theme.font(10, r.depth == 0))
            p.setPen(theme.TEXT_DIM if dim else theme.TEXT)
            name = g.name + (f"  → {g.reference}" if g.is_reference else "")
            if g.children and id(g) in self.collapsed:
                name += f"   ({len(g.children)})"
            right = r.rect.right() - 12
            p.drawText(QRectF(x, r.rect.top(), right - x - 220, ROW_H), Qt.AlignVCenter | Qt.AlignLeft,
                       p.fontMetrics().elidedText(name, Qt.ElideRight, int(right - x - 220)))
            # à droite : adresse et étiquette
            p.setFont(theme.font(9))
            info = f"@ {g.breaks[0].dmx_offset}" if g.breaks else ""
            tag, color = {"3d": ("3D seul", theme.TEXT_DIM), "double": ("modèle en double", theme.STATUS["jaune"]),
                          "double-vu": ("●", theme.STATUS["jaune"])}.get(r.flag, ("", theme.TEXT_DIM))
            p.setPen(theme.TEXT_DIM)
            p.drawText(QRectF(right - 60, r.rect.top(), 60, ROW_H), Qt.AlignVCenter | Qt.AlignRight, info)
            p.setPen(color)
            p.drawText(QRectF(right - 210, r.rect.top(), 140, ROW_H), Qt.AlignVCenter | Qt.AlignRight, tag)

    def _row_at(self, pos) -> Optional[_Row]:
        return next((r for r in self._rows if r.rect.contains(pos)), None)

    def mousePressEvent(self, e):
        r = self._row_at(e.position())
        if not r:
            return
        if r.geo.children and e.position().x() < r.rect.left() + 24:
            self.collapsed.symmetric_difference_update({id(r.geo)})
            self._relayout()
            return
        self.current = r.geo
        self.selected.emit(r.geo)
        self.update()

    def mouseMoveEvent(self, e):
        r = self._row_at(e.position())
        if r is not self._hover:
            self._hover = r
            self.update()


class MiniGrid(QWidget):
    """Grille façon Fixture Hero : les géométries sœurs, la choisie en jaune."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cells: list[str] = []
        self.current = ""
        self.setMinimumHeight(170)

    def set(self, geo: Optional[Geometry]) -> None:
        sibs = geo.parent.children if geo and geo.parent else ([geo] if geo else [])
        self.cells = [g.name for g in sibs]
        self.current = geo.name if geo else ""
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), theme.PANEL)
        n = len(self.cells)
        if not n:
            return
        cols = min(n, 12)
        size = min(26.0, (self.width() - 20) / cols)
        rows = (n + cols - 1) // cols
        x0 = (self.width() - cols * size) / 2
        y0 = max(10.0, (self.height() - rows * size) / 2)
        for i, name in enumerate(self.cells):
            r = QRectF(x0 + (i % cols) * size, y0 + (i // cols) * size, size - 3, size - 3)
            p.setPen(QPen(theme.ACCENT if name == self.current else theme.ROW_HOVER, 2))
            p.setBrush(theme.ACCENT if name == self.current else theme.BG)
            p.drawRect(r)


class Params(QWidget):
    """Paramètres de la géométrie choisie : nom, type, modèle, adresse, grille (maquette)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.title = QLabel()
        self.title.setFont(theme.font(12, True))
        self.name = QLineEdit()
        self.kind = QComboBox()
        self.kind.addItems(TYPES)
        self.model = QLabel()
        self.model.setObjectName("dim")
        self.address = QSpinBox()
        self.address.setRange(1, 512)
        self.brk = QSpinBox()
        self.brk.setRange(1, 8)
        self.gx, self.gy = QSpinBox(), QSpinBox()
        for s in (self.gx, self.gy):
            s.setRange(0, 999)
        self.grid = MiniGrid()
        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setObjectName("dim")

        form = QFormLayout()
        form.setVerticalSpacing(10)
        form.addRow("Nom", self.name)
        form.addRow("Type", self.kind)
        form.addRow("Modèle", self.model)
        addr = QHBoxLayout()
        addr.addWidget(self.address, 2)
        addr.addSpacing(8)
        addr.addWidget(QLabel("Break"))
        addr.addWidget(self.brk, 1)
        form.addRow("Adresse", addr)
        grid = QHBoxLayout()
        grid.addWidget(QLabel("X"))
        grid.addWidget(self.gx)
        grid.addSpacing(8)
        grid.addWidget(QLabel("Y"))
        grid.addWidget(self.gy)
        form.addRow("Grille", grid)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(12)
        lay.addWidget(self.title)
        lay.addLayout(form)
        lay.addWidget(self.grid)
        lay.addWidget(self.note)
        lay.addStretch(1)
        self.setStyleSheet(f"QLineEdit, QSpinBox {{ background: {theme.ROW.name()}; border: none;"
                           f" border-radius: 6px; padding: 6px 10px; }}")

    def show_geo(self, g: Optional[Geometry], flag_3d: bool) -> None:
        if g is None:
            return
        self.title.setText(g.name)
        self.name.setText(g.name)
        self.kind.setCurrentText(g.kind if g.kind in TYPES else "Geometry")
        self.model.setText(g.reference or g.model or "—")
        b = g.breaks[0] if g.breaks else None
        for w in (self.address, self.brk):
            w.setEnabled(b is not None)
        if b:
            self.address.setValue(b.dmx_offset)
            self.brk.setValue(b.dmx_break)
        idx = g.parent.children.index(g) if g.parent else 0
        self.gx.setValue(idx)
        self.gy.setValue(0)
        self.grid.set(g)
        self.note.setText("Aucun canal dans aucun mode : sert seulement à la 3D, le nettoyeur "
                          "la retirera." if flag_3d else "")


class AtelierWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Comparateur de LIB · Atelier géométries")
        self.resize(1300, 820)
        self.ft: Optional[FixtureType] = None

        self.open = QPushButton("Fixture : ouvrir…")
        self.open.setFont(theme.font(10, True))
        self.open.clicked.connect(self.choose)
        self.modes = QComboBox()
        self.modes.setEnabled(False)
        self.modes.currentIndexChanged.connect(self._mode_changed)
        bar = QHBoxLayout()
        bar.setContentsMargins(14, 12, 14, 6)
        bar.addWidget(self.open)
        bar.addWidget(self.modes)
        bar.addStretch(1)

        self.tree = GeoTree()
        self.tree.selected.connect(self._select)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.tree)
        self.params = Params()
        self.params.setFixedWidth(400)
        mid = QHBoxLayout()
        mid.setSpacing(0)
        mid.addWidget(scroll, 1)
        mid.addWidget(self.params)

        self.summary = QLabel()
        self.summary.setFont(theme.font(10))
        self.clean = QPushButton("Nettoyer…")
        self.clean.setEnabled(False)
        self.clean.setToolTip("Arrive avec les fonctions de l'étape 3")
        foot = QHBoxLayout()
        foot.setContentsMargins(14, 6, 14, 6)
        foot.addWidget(self.summary, 1)
        foot.addWidget(self.clean)

        central = QWidget()
        lay = QVBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 6)
        lay.setSpacing(0)
        lay.addLayout(bar)
        lay.addLayout(mid, 1)
        lay.addLayout(foot)
        self.setCentralWidget(central)

    def choose(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Ouvrir un fixture", "",
                                              "Fixture types (*.gdtf *.xml);;Tous les fichiers (*)")
        if path:
            self.load(path)

    def load(self, path: str, mode: str = "") -> None:
        self.ft = gdtf.load(path)
        self.useless = {g.name for g in diagnostic.geometries_3d_only(self.ft)}
        self.doubles = {n for grp in diagnostic.duplicate_templates(self.ft) for n in grp}
        self.open.setText(f"{self.ft.manufacturer} - {self.ft.name}")
        self.modes.blockSignals(True)
        self.modes.clear()
        self.modes.addItems([m.name for m in self.ft.modes])
        if mode:
            self.modes.setCurrentText(mode)
        self.modes.setEnabled(True)
        self.modes.blockSignals(False)
        self._mode_changed()

    def _mode_changed(self) -> None:
        if not self.ft:
            return
        mode = self.ft.mode(self.modes.currentText())
        root = self.ft.top_level(mode.geometry) if mode else None
        self.tree.set_root(root, self.useless, self.doubles)
        names = {g.name for g in root.walk()} if root else set()
        n3d = len(names & self.useless)
        refs = {g.reference for g in root.walk() if g.is_reference} if root else set()
        ndbl = len((names | refs) & self.doubles)
        dot = lambda c: f"<span style='color:{c}; font-size:15px'>●</span>"
        self.summary.setText(
            f"Nettoyage proposé pour ce mode :  {dot(theme.TEXT_DIM.name())} {n3d} géométrie(s) 3D seule(s)"
            f"   {dot(theme.STATUS['jaune'].name())} {ndbl} modèle(s) en double")

    def _select(self, g) -> None:
        self.params.show_geo(g, g is not None and g.name in self.useless)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setStyle("Fusion")
    app.setPalette(theme.palette())
    app.setStyleSheet(theme.STYLE)
    app.setFont(theme.font(10))
    win = AtelierWindow()
    if argv:
        win.load(argv[0], argv[1] if len(argv) > 1 else "")
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
