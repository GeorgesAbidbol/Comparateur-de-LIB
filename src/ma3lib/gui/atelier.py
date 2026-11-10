"""Étape 3 : atelier géométries.

L'arbre complet des géométries d'un mode, avec ce que le diagnostic de l'étape 1 y trouve
(géométries 3D seules, modèles en double), et le panneau des paramètres de la géométrie
choisie (adresse, grille, type ; encore en lecture seule).

Glisser-déposer : lâcher sur le milieu d'une ligne = la géométrie devient son enfant,
sur le haut ou le bas = avant ou après elle. Ctrl/Maj pour en prendre plusieurs.
Les numéros 1.x.x.x se recalculent en direct. Ctrl+Z annule.
Lancer : `python -m ma3lib.gui.atelier fichier.gdtf [mode]`.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtWidgets import (QApplication, QComboBox, QFileDialog, QFormLayout, QHBoxLayout,
                               QLabel, QLineEdit, QMainWindow, QPushButton, QScrollArea, QSpinBox,
                               QVBoxLayout, QWidget)

from .. import compare, diagnostic, gdtf, geotree
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
    dropped = Signal(list, object, int)  # géométries, nouveau parent, rang

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.root: Optional[Geometry] = None
        self.useless: set[str] = set()
        self.doubles: set[str] = set()
        self.collapsed: set[int] = set()
        self.current: Optional[Geometry] = None
        self.idents: dict[str, str] = {}
        self._rows: list[_Row] = []
        self._hover: Optional[_Row] = None
        self.selection: list[Geometry] = []
        self._anchor: Optional[Geometry] = None
        self._press: Optional[QPointF] = None
        self._press_row: Optional[_Row] = None
        self._dragging = False
        self._drop: Optional[tuple[_Row, str]] = None  # (ligne visée, "avant" / "dans" / "après")

    def set_root(self, root, useless: set[str], doubles: set[str],
                 idents: Optional[dict[str, str]] = None) -> None:
        self.root, self.useless, self.doubles = root, useless, doubles
        self.idents = idents or {}  # nom de géométrie -> numéro de sélection MA3 (1.x.x.x)
        self.collapsed = set()
        self.current = root
        self.selection = [root] if root else []
        self._relayout()
        self.selected.emit(root)

    def refresh(self, useless: set[str], doubles: set[str], idents: dict[str, str]) -> None:
        """Après un déplacement : mêmes lignes repliées, même sélection."""
        self.useless, self.doubles, self.idents = useless, doubles, idents
        self._relayout()

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
            sel = any(g is x for x in self.selection)
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
            # numéro de sélection MA3 : seules les géométries qui portent des canaux en ont un
            ident = self.idents.get(g.name, "")
            p.setFont(theme.font(9, True))
            p.setPen(theme.ACCENT if ident and not sel else theme.TEXT)
            p.drawText(QRectF(x, r.rect.top(), 74, ROW_H), Qt.AlignVCenter | Qt.AlignLeft, ident)
            x += 76
            # pastille de type
            badge = BADGE.get(g.kind, g.kind[:4].upper())
            p.setFont(theme.font(7, True))
            bw = p.fontMetrics().horizontalAdvance(badge) + 12
            br = QRectF(x, r.rect.center().y() - 9, bw, 18)
            p.setPen(Qt.NoPen)
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

        if self._dragging and self._drop:
            row, zone = self._drop
            p.setBrush(Qt.NoBrush)
            if zone == "dans":
                p.setPen(QPen(theme.ACCENT, 2))
                p.drawRoundedRect(row.rect.adjusted(1, 1, -1, -1), 5, 5)
            else:
                y = row.rect.top() - GAP_Y / 2 if zone == "avant" else row.rect.bottom() + GAP_Y / 2
                p.setPen(QPen(theme.ACCENT, 3))
                p.drawLine(QPointF(row.rect.left(), y), QPointF(row.rect.right(), y))
            n = len(self.selection)
            p.setPen(theme.ACCENT)
            p.setFont(theme.font(9, True))
            p.drawText(self._drag_pos + QPointF(14, -6), f"{n} géométrie(s)" if n > 1 else self.selection[0].name)

    def _row_at(self, pos) -> Optional[_Row]:
        return next((r for r in self._rows if r.rect.contains(pos)), None)

    def _visible(self) -> list[Geometry]:
        return [r.geo for r in self._rows]

    def mousePressEvent(self, e):
        r = self._row_at(e.position())
        if not r or e.button() != Qt.LeftButton:
            return
        if r.geo.children and e.position().x() < r.rect.left() + 24:
            self.collapsed.symmetric_difference_update({id(r.geo)})
            self._relayout()
            return
        mods = e.modifiers()
        if mods & Qt.ControlModifier:
            if any(r.geo is x for x in self.selection):
                self.selection = [x for x in self.selection if x is not r.geo]
            else:
                self.selection.append(r.geo)
            self._anchor = r.geo
        elif mods & Qt.ShiftModifier and self._anchor is not None:
            vis = self._visible()
            ia, ib = _index(vis, self._anchor), _index(vis, r.geo)
            a, b = sorted((ia, ib)) if ia >= 0 else (ib, ib)
            self.selection = vis[a:b + 1]
        elif not any(r.geo is x for x in self.selection):
            self.selection = [r.geo]
            self._anchor = r.geo
        self._press, self._press_row = e.position(), r
        self.current = r.geo
        self.selected.emit(r.geo)
        self.update()

    def _drop_at(self, pos) -> Optional[tuple[_Row, str]]:
        r = self._row_at(pos) or next((x for x in self._rows
                                        if x.rect.top() - GAP_Y <= pos.y() <= x.rect.bottom() + GAP_Y), None)
        if r is None:
            return None
        rel = (pos.y() - r.rect.top()) / ROW_H
        zone = "avant" if rel < 0.28 else ("après" if rel > 0.72 else "dans")
        if r.geo.parent is None or (zone == "dans" and r.geo.is_reference):
            zone = "dans"
        parent, _ = self._target(r, zone)
        if parent is None or any(geotree.check(g, parent) for g in self.selection):
            return None
        return r, zone

    @staticmethod
    def _target(r: _Row, zone: str) -> tuple[Optional[Geometry], int]:
        if zone == "dans":
            return r.geo, len(r.geo.children)
        parent = r.geo.parent
        if parent is None:
            return None, 0
        i = parent.children.index(r.geo)
        return parent, i if zone == "avant" else i + 1

    def mouseMoveEvent(self, e):
        pos = e.position()
        if self._press is not None and (e.buttons() & Qt.LeftButton):
            if not self._dragging and (pos - self._press).manhattanLength() > 8 and self.selection:
                self._dragging = True
            if self._dragging:
                self._drag_pos = pos
                self._drop = self._drop_at(pos)
                self.setCursor(Qt.ClosedHandCursor if self._drop else Qt.ForbiddenCursor)
                self.update()
                return
        r = self._row_at(pos)
        if r is not self._hover:
            self._hover = r
            self.update()

    def mouseReleaseEvent(self, e):
        if self._dragging and self._drop:
            row, zone = self._drop
            parent, index = self._target(row, zone)
            vis = self._visible()  # garder l'ordre affiché quand on en déplace plusieurs
            geos = sorted(self.selection, key=lambda g: _index(vis, g))
            if zone == "dans":
                self.collapsed.discard(id(row.geo))
            self.dropped.emit(geos, parent, index)
        elif self._press_row is not None and not (e.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier)):
            self.selection = [self._press_row.geo]
            self._anchor = self._press_row.geo
        self._press = self._press_row = None
        self._dragging = False
        self._drop = None
        self.unsetCursor()
        self.update()


def _index(items: list[Geometry], g: Optional[Geometry]) -> int:
    """Rang par identité (l'égalité des dataclasses comparerait des sous-arbres entiers)."""
    return next((i for i, x in enumerate(items) if x is g), -1)


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

    def show_geo(self, g: Optional[Geometry], flag_3d: bool, ident: str = "") -> None:
        if g is None:
            return
        self.title.setText(f"{ident}   {g.name}" if ident else g.name)
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
        self.tree.dropped.connect(self._move)
        self.history: list[geotree.Undo] = []
        QShortcut(QKeySequence.Undo, self, activated=self.undo)
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
        self.status = QLabel()
        self.status.setObjectName("dim")
        self.status.setFont(theme.font(9))
        self.clean = QPushButton("Nettoyer…")
        self.clean.setEnabled(False)
        self.clean.setToolTip("Arrive avec les fonctions de l'étape 3")
        foot = QHBoxLayout()
        foot.setContentsMargins(14, 6, 14, 6)
        foot.addWidget(self.summary)
        foot.addSpacing(24)
        foot.addWidget(self.status, 1)
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
        self.history = []
        self.status.setText("")
        self._diagnose()
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
        self.tree.set_root(root, self.useless, self.doubles, self._idents())
        self._summary()

    def _diagnose(self) -> None:
        self.useless = {g.name for g in diagnostic.geometries_3d_only(self.ft)}
        self.doubles = {n for grp in diagnostic.duplicate_templates(self.ft) for n in grp}

    def _idents(self) -> dict[str, str]:
        mode = self.ft.mode(self.modes.currentText()) if self.ft else None
        inst = compare.instances(self.ft, mode) if mode else None
        return {i.name: i.ident for i in compare.flatten(inst)}

    def _after_change(self, message: str) -> None:
        self._diagnose()
        self.tree.refresh(self.useless, self.doubles, self._idents())
        self._summary()
        if self.tree.current is not None:
            self._select(self.tree.current)
        self.status.setText(message)
        self.setWindowTitle("Comparateur de LIB · Atelier géométries" + (" •" if self.history else ""))

    def _move(self, geos: list, parent: Geometry, index: int) -> None:
        try:
            self.history.append(geotree.move(self.ft, geos, parent, index))
        except geotree.MoveError as exc:
            self.status.setText(str(exc))
            return
        what = f"{len(geos)} géométries" if len(geos) > 1 else f"« {geos[0].name} »"
        self._after_change(f"{what} → sous « {parent.name} »   ·   Ctrl+Z pour annuler")

    def undo(self) -> None:
        if self.ft and self.history:
            geotree.undo(self.ft, self.history.pop())
            self._after_change("Déplacement annulé")

    def _summary(self) -> None:
        mode = self.ft.mode(self.modes.currentText())
        root = self.ft.top_level(mode.geometry) if mode else None
        names = {g.name for g in root.walk()} if root else set()
        n3d = len(names & self.useless)
        refs = {g.reference for g in root.walk() if g.is_reference} if root else set()
        ndbl = len((names | refs) & self.doubles)
        dot = lambda c: f"<span style='color:{c}; font-size:15px'>●</span>"
        self.summary.setText(
            f"Nettoyage proposé pour ce mode :  {dot(theme.TEXT_DIM.name())} {n3d} géométrie(s) 3D seule(s)"
            f"   {dot(theme.STATUS['jaune'].name())} {ndbl} modèle(s) en double")

    def _select(self, g) -> None:
        self.params.show_geo(g, g is not None and g.name in self.useless,
                             self.tree.idents.get(g.name, "") if g is not None else "")


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
