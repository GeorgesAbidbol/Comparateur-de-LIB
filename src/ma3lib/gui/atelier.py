"""Étape 3 : atelier géométries.

L'arbre complet des géométries d'un mode, avec ce que le diagnostic de l'étape 1 y trouve
(géométries 3D seules, modèles en double), et le panneau des paramètres de la géométrie
choisie (nom, type, modèle de référence, adresse, grille ; bouton « Appliquer »).

Glisser-déposer : lâcher sur le milieu d'une ligne = la géométrie devient son enfant,
sur le haut ou le bas = avant ou après elle. Ctrl/Maj pour en prendre plusieurs.
Les numéros 1.x.x.x se recalculent en direct. Ctrl+Z annule.
Lancer : `python -m ma3lib.gui.atelier fichier.gdtf [mode]`.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import QMimeData, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QDrag, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
                               QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox, QPushButton,
                               QAbstractItemView, QHeaderView, QScrollArea, QSpinBox, QSplitter, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from .. import charte_dmx, compare, diagnostic, gdtf, geotree
from ..gdtf import FixtureType, Geometry
from . import theme
from .. import APP_NAME, __version__

TITLE = f"{APP_NAME} v{__version__} · Atelier géométries"

ROW_H = 30
GAP_Y = 4
INDENT = 20
MARGIN = 12
TYPES = ["Geometry", "Beam", "Axis", "GeometryReference", "FilterColor", "FilterGobo", "Display"]
BADGE = {"Geometry": "GEO", "Beam": "BEAM", "Axis": "AXIS", "GeometryReference": "RÉF"}
PIECE_MIME = "application/x-banane-pot-geometrie"  # glisser une géométrie disponible dans l'arbre


@dataclass
class _Row:
    geo: Geometry
    depth: int
    rect: QRectF
    flag: str  # "", "3d" (aucun canal dans aucun mode), "double" (modèle en double)


class GeoTree(QWidget):
    selected = Signal(object)
    dropped = Signal(list, object, int)  # géométries, nouveau parent, rang
    menuAsked = Signal(object)  # position globale du clic droit
    editAsked = Signal(object)  # double-clic : popup des paramètres
    pieceDropped = Signal(int, object, int)  # géométrie disponible n°, parent, rang

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.root: Optional[Geometry] = None
        self.models: list[Geometry] = []  # modèles référencés par le mode, rangeables eux aussi
        self.model_uses: dict[str, int] = {}
        self._models_y = 0.0
        self.useless: set[str] = set()
        self.doubles: set[str] = set()
        self.collapsed: set[str] = set()  # noms des géométries repliées
        self.current: Optional[Geometry] = None
        self.idents: dict[str, str] = {}
        self.copies: dict[str, int] = {}
        self._rows: list[_Row] = []
        self._hover: Optional[_Row] = None
        self.selection: list[Geometry] = []
        self._anchor: Optional[Geometry] = None
        self._press: Optional[QPointF] = None
        self._press_row: Optional[_Row] = None
        self._dragging = False
        self._drop: Optional[tuple[_Row, str]] = None  # (ligne visée, "avant" / "dans" / "après")
        self._drag_label = ""  # nom affiché pendant un glisser venu de la zone de droite
        self.setAcceptDrops(True)

    def set_root(self, root, useless: set[str], doubles: set[str],
                 idents: Optional[dict[str, str]] = None, copies: Optional[dict[str, int]] = None,
                 models: Optional[list[Geometry]] = None) -> None:
        self.root, self.useless, self.doubles = root, useless, doubles
        self._set_models(root, models or [])
        self.idents = idents or {}  # nom de géométrie -> numéro de sélection MA3 (1.x.x.x)
        self.copies = copies or {}  # nom -> taille du groupe de copies identiques
        self.collapsed = set()
        self.current = root
        self.selection = [root] if root else []
        self._relayout()
        self.selected.emit(root)

    def _set_models(self, root, models: list[Geometry]) -> None:
        self.models = models
        self.model_uses = {}
        for g in (root.walk() if root else []):
            if g.is_reference:
                self.model_uses[g.reference] = self.model_uses.get(g.reference, 0) + 1

    def refresh(self, root, useless: set[str], doubles: set[str], idents: dict[str, str],
                copies: Optional[dict[str, int]] = None, models: Optional[list[Geometry]] = None) -> None:
        """Après une modification (le fixture a pu être relu) : mêmes lignes repliées,
        même sélection, retrouvées par leur nom."""
        names = [g.name for g in self.selection]
        cur = self.current.name if self.current else ""
        self.root, self.useless, self.doubles, self.idents = root, useless, doubles, idents
        self.copies = copies or {}
        self._set_models(root, models or [])
        by_name = {g.name: g for t in ([root] if root else []) + self.models for g in t.walk()}
        self.selection = [by_name[n] for n in names if n in by_name]
        self.current = by_name.get(cur) or (self.selection[0] if self.selection else root)
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
            if not flag and g.name in self.copies:
                flag = "copie"
            if not flag and g.parent is None and g.name in self.model_uses:
                flag = "modele"
            if flag == "double":
                key = g.reference or g.name
                flag = "double-vu" if key in seen else "double"
                seen.add(key)
            ind = depth * INDENT
            self._rows.append(_Row(g, depth, QRectF(MARGIN + ind, y, w - ind, ROW_H), flag))
            y += ROW_H + GAP_Y
            if g.name not in self.collapsed:
                for c in g.children:
                    add(c, depth + 1)

        if self.root:
            add(self.root, 0)
        if self.models:
            y += 26  # titre « Modèles »
            self._models_y = y - 22
            for m in self.models:
                add(m, 0)
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
                           "▸" if g.name in self.collapsed else "▾")
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
            if g.children and g.name in self.collapsed:
                name += f"   ({len(g.children)})"
            right = r.rect.right() - 12
            p.drawText(QRectF(x, r.rect.top(), right - x - 300, ROW_H), Qt.AlignVCenter | Qt.AlignLeft,
                       p.fontMetrics().elidedText(name, Qt.ElideRight, int(right - x - 300)))
            # à droite : adresse et étiquette
            p.setFont(theme.font(9))
            info = f"@ {g.breaks[0].dmx_offset}" if g.breaks else ""
            tag, color = {"3d": ("3D seul", theme.TEXT_DIM), "double": ("modèle en double", theme.STATUS["jaune"]),
                          "double-vu": ("●", theme.STATUS["jaune"]),
                          "copie": (f"copie ×{self.copies.get(g.name, 0)}", theme.STATUS["orange"]),
                          "modele": (f"modèle ×{self.model_uses.get(g.name, 0)}", theme.STATUS["bleu"])}\
                .get(r.flag, ("", theme.TEXT_DIM))
            p.setPen(theme.TEXT_DIM)
            p.drawText(QRectF(right - 60, r.rect.top(), 60, ROW_H), Qt.AlignVCenter | Qt.AlignRight, info)
            if r.flag == "double" and g.parent is None and g.name in self.model_uses:
                tag = f"modèle ×{self.model_uses[g.name]} · en double"
            p.setPen(color)
            p.drawText(QRectF(right - 290, r.rect.top(), 220, ROW_H), Qt.AlignVCenter | Qt.AlignRight, tag)

        if self.models:
            p.setPen(theme.TEXT_DIM)
            p.setFont(theme.font(9, True))
            p.drawText(QRectF(MARGIN, self._models_y, self.width(), 20), Qt.AlignLeft | Qt.AlignVCenter,
                       "MODÈLES  —  ce qu'on range ici vaut pour toutes leurs références")
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
            label = self._drag_label or (f"{n} géométrie(s)" if n > 1 else self.selection[0].name)
            p.drawText(self._drag_pos + QPointF(14, -6), label)

    def _row_at(self, pos) -> Optional[_Row]:
        return next((r for r in self._rows if r.rect.contains(pos)), None)

    def _visible(self) -> list[Geometry]:
        return [r.geo for r in self._rows]

    def mousePressEvent(self, e):
        r = self._row_at(e.position())
        if r and e.button() == Qt.RightButton:
            if not any(r.geo is x for x in self.selection):
                self.selection = [r.geo]
                self.current = r.geo
                self.selected.emit(r.geo)
            self.update()
            self.menuAsked.emit(e.globalPosition().toPoint())
            return
        if not r or e.button() != Qt.LeftButton:
            return
        if r.geo.children and e.position().x() < r.rect.left() + 24:
            self.collapsed.symmetric_difference_update({r.geo.name})
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

    def mouseDoubleClickEvent(self, e):
        r = self._row_at(e.position())
        if r and e.button() == Qt.LeftButton and e.position().x() >= r.rect.left() + 24:
            self.editAsked.emit(r.geo)

    def _drop_at(self, pos, geos: Optional[list] = None) -> Optional[tuple[_Row, str]]:
        r = self._row_at(pos) or next((x for x in self._rows
                                        if x.rect.top() - GAP_Y <= pos.y() <= x.rect.bottom() + GAP_Y), None)
        if r is None:
            return None
        rel = (pos.y() - r.rect.top()) / ROW_H
        zone = "avant" if rel < 0.28 else ("après" if rel > 0.72 else "dans")
        if r.geo.parent is None or (zone == "dans" and r.geo.is_reference):
            zone = "dans"
        parent, _ = self._target(r, zone)
        moving = self.selection if geos is None else geos
        if parent is None or parent.is_reference or any(geotree.check(g, parent) for g in moving):
            return None
        return r, zone

    # glisser une géométrie disponible (zone de droite) dans l'arbre
    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat(PIECE_MIME):
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if not e.mimeData().hasFormat(PIECE_MIME):
            return
        self._drop = self._drop_at(e.position(), [])
        self._dragging = self._drop is not None
        self._drag_pos = e.position()
        self._drag_label = e.mimeData().text()
        e.setAccepted(self._drop is not None)
        self.update()

    def dragLeaveEvent(self, e):
        self._dragging, self._drop, self._drag_label = False, None, ""
        self.update()

    def dropEvent(self, e):
        drop = self._drop_at(e.position(), []) if e.mimeData().hasFormat(PIECE_MIME) else None
        self._dragging, self._drop, self._drag_label = False, None, ""
        self.update()
        if drop is None:
            return
        row, zone = drop
        parent, index = self._target(row, zone)
        if zone == "dans":
            self.collapsed.discard(row.geo.name)
        e.acceptProposedAction()
        self.pieceDropped.emit(int(bytes(e.mimeData().data(PIECE_MIME)).decode()), parent, index)

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
                self.collapsed.discard(row.geo.name)
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


def grid_place(g: Geometry, ft=None) -> tuple[int, int]:
    """Place dans la grille : celle écrite dans le fichier, sinon celle proposée."""
    el = geotree.element_of(ft, g) if ft is not None else None
    gx, gy = (el.get("GridX"), el.get("GridY")) if el is not None else (None, None)
    if gx is not None and gy is not None:
        return int(gx), int(gy)
    return geotree.grid_proposal(g, ft)


def grid_auto(g: Geometry, ft=None) -> bool:
    """GridAuto : « Auto » (ou absent) = la console place la géométrie dans la grille."""
    el = geotree.element_of(ft, g) if ft is not None else None
    return el is None or el.get("GridAuto", "Auto") != "Manual"


def _auto_box(spins) -> "QCheckBox":
    """Case « Auto » de la grille : cochée, X/Y/Z sont grisés (la console place)."""
    box = QCheckBox("Auto")
    box.setToolTip("Cochée : la console place la géométrie dans la grille (GridAuto=Auto).\n"
                   "Décochée : X, Y, Z à la main (GridAuto=Manual).")
    box.toggled.connect(lambda on: [s.setEnabled(not on) for s in spins])
    return box


def grid_z(g: Geometry, ft=None) -> int:
    """GridZ écrit dans le fichier (0 sinon) : la grille MA3 a trois axes."""
    el = geotree.element_of(ft, g) if ft is not None else None
    try:
        return int(el.get("GridZ") or 0) if el is not None else 0
    except ValueError:
        return 0


class MiniGrid(QWidget):
    """Grille façon Fixture Hero : les géométries sœurs à leur vraie place, la choisie en jaune.
    16 pixels en ligne = une seule ligne de 16 (Jo, 11/11/2026), jamais de retour à la ligne."""

    placed = Signal(int, int)  # case jaune glissée : nouvelle place X, Y

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cells: list[tuple[int, int]] = []
        self.current: Optional[tuple[int, int]] = None
        self._hold: Optional[tuple[int, int]] = None  # case visée pendant le glisser
        self.setMinimumHeight(170)
        self.setToolTip("Glisse la case jaune pour placer la géométrie (grille à la main)")

    def set(self, geo: Optional[Geometry], ft=None) -> None:
        sibs = geo.parent.children if geo and geo.parent else ([geo] if geo else [])
        self.cells = [grid_place(g, ft) for g in sibs]
        self.current = grid_place(geo, ft) if geo else None
        self.update()

    def layout(self) -> tuple[int, int, float]:
        """Colonnes, lignes et taille d'une case : les cases rétrécissent pour tout faire tenir.
        Une colonne et une ligne vides en plus, pour pouvoir y glisser la case jaune."""
        cols = max(x for x, _ in self.cells) + 2
        rows = max(y for _, y in self.cells) + 2
        size = min(26.0, (self.width() - 20) / cols, (self.height() - 20) / rows)
        return cols, rows, max(size, 2.0)

    def _origin(self) -> tuple[float, float, float]:
        cols, rows, size = self.layout()
        return (self.width() - cols * size) / 2, (self.height() - rows * size) / 2, size

    def _cell_at(self, pos) -> Optional[tuple[int, int]]:
        if not self.cells:
            return None
        cols, rows, _ = self.layout()
        x0, y0, size = self._origin()
        cx, cy = int((pos.x() - x0) // size), int((pos.y() - y0) // size)
        return (cx, cy) if 0 <= cx < cols and 0 <= cy < rows else None

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self.current is not None and self._cell_at(e.position()) == self.current:
            self._hold = self.current
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, e):
        if self._hold is not None:
            self._hold = self._cell_at(e.position()) or self._hold
            self.update()

    def mouseReleaseEvent(self, e):
        if self._hold is not None:
            cell, self._hold = self._hold, None
            self.unsetCursor()
            if cell != self.current:
                self.current = cell
                self.placed.emit(*cell)
            self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), theme.PANEL)
        if not self.cells:
            return
        cols, rows, size = self.layout()
        gap = 3 if size >= 10 else 1
        x0, y0, size = self._origin()
        for cell in sorted(set(self.cells), key=lambda c: c == self.current):
            on = cell == self.current
            p.setPen(QPen(theme.ACCENT if on else theme.ROW_HOVER, 2 if size >= 10 else 1))
            p.setBrush(theme.ACCENT if on else theme.BG)
            p.drawRect(QRectF(x0 + cell[0] * size, y0 + cell[1] * size, size - gap, size - gap))
        if self._hold is not None and self._hold != self.current:  # où la case jaune va tomber
            p.setPen(QPen(theme.ACCENT, 2, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawRect(QRectF(x0 + self._hold[0] * size, y0 + self._hold[1] * size, size - gap, size - gap))


NEW_MODEL = "Nouveau modèle…"
NO_MESH = "aucun"
OTHER_GDTF = "Prendre dans un autre GDTF…"
REF = "GeometryReference"


class Params(QWidget):
    """Paramètres de la géométrie choisie : nom, type, modèle de référence, adresse, grille.
    « Appliquer » écrit ce qui a changé (signal `applied`)."""

    applied = Signal()
    channelAsked = Signal(str, str)  # « add » / « edit » / « remove », attribut du canal

    def __init__(self, parent=None):
        super().__init__(parent)
        self.geo: Optional[Geometry] = None
        self.place = (0, 0, 0)
        self._auto0 = True
        self.title = QLabel()
        self.title.setFont(theme.font(12, True))
        self.name = QLineEdit()
        self.name.returnPressed.connect(lambda: self.applied.emit())
        self.kind = QComboBox()
        self.kind.currentTextChanged.connect(self._kind_changed)
        self.model = QComboBox()
        self.model.setPlaceholderText("pour le type GeometryReference")
        self.model.setToolTip("Le modèle que la référence répète. « Nouveau modèle… » le crée "
                              "à partir de cette géométrie.")
        self.mesh = QComboBox()
        self.mesh.setToolTip("La forme 3D de la géométrie : un mesh du fixture, ou un cube ou un "
                             "cylindre de la console.")
        self.address = QSpinBox()
        self.address.setRange(1, 512)
        self.brk = QLabel()
        self.brk.setObjectName("dim")
        self.gx, self.gy, self.gz = QSpinBox(), QSpinBox(), QSpinBox()
        for s in (self.gx, self.gy, self.gz):
            s.setRange(0, 999)
        self.auto = _auto_box((self.gx, self.gy, self.gz))
        self.grid = MiniGrid()
        self.grid.placed.connect(self._placed)
        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setObjectName("dim")
        # charte DMX de la géométrie dans le mode en cours (Jo, 11/11/2026)
        self.chan_title = QLabel("Canaux dans ce mode")
        self.chan_title.setFont(theme.font(10, True))
        self.channels = QListWidget()
        self.channels.setFixedHeight(230)
        self.channels.itemDoubleClicked.connect(lambda _: self._chan("edit"))
        self.channels.itemSelectionChanged.connect(self._chan_buttons)
        self.chan_add = QPushButton("+ Canal")
        self.chan_edit = QPushButton("Modifier…")
        self.chan_del = QPushButton("Retirer")
        self.chan_add.clicked.connect(lambda: self.channelAsked.emit("add", ""))
        self.chan_edit.clicked.connect(lambda: self._chan("edit"))
        self.chan_del.clicked.connect(lambda: self._chan("remove"))
        self.button = QPushButton("Appliquer")
        self.button.setFont(theme.font(10, True))
        self.button.clicked.connect(lambda: self.applied.emit())

        form = QFormLayout()
        form.setVerticalSpacing(10)
        form.addRow("Nom", self.name)
        form.addRow("Type", self.kind)
        form.addRow("Référence", self.model)
        form.addRow("Mesh", self.mesh)
        addr = QHBoxLayout()
        addr.addWidget(self.address, 2)
        addr.addSpacing(8)
        addr.addWidget(self.brk, 1)
        form.addRow("Adresse", addr)
        grid = QHBoxLayout()
        grid.addWidget(self.auto)
        grid.addSpacing(6)
        grid.addWidget(QLabel("X"))
        grid.addWidget(self.gx)
        grid.addSpacing(8)
        grid.addWidget(QLabel("Y"))
        grid.addWidget(self.gy)
        grid.addSpacing(8)
        grid.addWidget(QLabel("Z"))
        grid.addWidget(self.gz)
        form.addRow("Grille", grid)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(12)
        lay.addWidget(self.title)
        lay.addLayout(form)
        lay.addWidget(self.button, 0, Qt.AlignRight)
        lay.addSpacing(4)
        lay.addWidget(self.chan_title)
        lay.addWidget(self.channels)
        chan_row = QHBoxLayout()
        chan_row.addWidget(self.chan_add)
        chan_row.addStretch(1)
        chan_row.addWidget(self.chan_edit)
        chan_row.addWidget(self.chan_del)
        lay.addLayout(chan_row)
        lay.addWidget(self.grid)
        lay.addWidget(self.note)
        lay.addStretch(1)
        self.setStyleSheet(f"QLineEdit, QSpinBox {{ background: {theme.ROW.name()}; border: none;"
                           f" border-radius: 6px; padding: 6px 24px 6px 10px; }}"
                           f"QSpinBox:disabled {{ color: {theme.TEXT_DIM.name()}; }}"
                           f"QListWidget {{ background: {theme.PANEL.name()}; border: none; border-radius: 8px;"
                           f" padding: 4px; outline: none; }}"
                           f"QListWidget::item {{ padding: 5px 8px; border-radius: 5px; }}"
                           f"QListWidget::item:selected {{ background: {theme.HEADER.name()};"
                           f" color: {theme.TEXT.name()}; }}"
                           f"QPushButton:disabled {{ color: {theme.TEXT_DIM.name()}; }}")
        self._chan_buttons()

    def _chan(self, what: str) -> None:
        item = self.channels.currentItem()
        if item is not None:
            self.channelAsked.emit(what, item.data(Qt.UserRole))

    def _chan_buttons(self) -> None:
        on = bool(self.channels.selectedItems())
        self.chan_edit.setEnabled(on)
        self.chan_del.setEnabled(on)

    def show_channels(self, rows: list, carrier: str, own: bool) -> None:
        """Les canaux de la géométrie ; pour une référence, ceux de son modèle."""
        self.chan_title.setText("Canaux dans ce mode" if own else f"Canaux du modèle « {carrier} »")
        self.channels.clear()
        for r in rows:
            where = "/".join(map(str, r.offsets)) if r.offsets else "virtuel"
            item = QListWidgetItem(f"{where:<8}{r.attribute}     ·  {r.bits} bits"
                                   + (f"  ·  défaut {r.default}" if r.default else ""))
            item.setData(Qt.UserRole, r.attribute)
            self.channels.addItem(item)
        self._chan_buttons()

    def _placed(self, x: int, y: int) -> None:
        """Case jaune glissée dans la petite grille : grille à la main, X/Y, appliqué tout de suite."""
        self.auto.setChecked(False)
        self.gx.setValue(x)
        self.gy.setValue(y)
        self.applied.emit()

    def _kind_changed(self, kind: str) -> None:
        self.model.setEnabled(kind == REF)
        if kind == REF and self.model.currentIndex() < 0:
            self.model.setCurrentIndex(0)

    def show_geo(self, g: Optional[Geometry], flag_3d: bool, ident: str = "", ft=None,
                 models: Optional[list[str]] = None, count: int = 1) -> None:
        if g is None:
            return
        self.geo = g
        title = f"{ident}   {g.name}" if ident else g.name
        self.title.setText(title + (f"   (+{count - 1})" if count > 1 else ""))
        self.name.setText(g.name)
        for w in (self.kind, self.model):
            w.blockSignals(True)
            w.clear()
        self.kind.addItems([REF] + [k for k in geotree.EDITABLE_KINDS if k != REF])
        self.kind.setCurrentText(g.kind)
        self.model.addItems([m for m in (models or []) if m != g.name] + [NEW_MODEL])
        self.model.setCurrentIndex(self.model.findText(g.reference) if g.is_reference else -1)
        for w in (self.kind, self.model):
            w.blockSignals(False)
        self.mesh.clear()
        self.mesh.addItems([NO_MESH] + (geotree.meshes(ft) if ft is not None else []))
        if g.model and self.mesh.findText(g.model) < 0:
            self.mesh.addItem(g.model)
        if ft is not None and ft.format == "gdtf":
            self.mesh.addItem(OTHER_GDTF)
        self.mesh.setCurrentText(g.model or NO_MESH)
        self.mesh.setEnabled(not g.is_reference)
        self.kind.setEnabled(g.parent is not None)  # un modèle ne devient pas une référence
        self.model.setEnabled(g.is_reference)
        b = g.breaks[0] if g.breaks else None
        self.address.setEnabled(b is not None)
        self.address.setVisible(b is not None)  # sans adresse propre : seulement l'explication
        self.address.setValue(b.dmx_offset if b else 1)
        self.brk.setText(f"Break {b.dmx_break}" if b else ("sans adresse" if g.is_reference else
                                                           "patch dans DMX mode"))
        self.brk.setToolTip("" if b else "Seule une référence a sa propre adresse (son Break). Une géométrie "
                            "n'en a pas : ce sont ses canaux qui ont des numéros dans le mode. Pour les décaler, "
                            "double-clic sur la ligne : « premier canal ».")
        self.place = (*grid_place(g, ft), grid_z(g, ft))
        self.gx.setValue(self.place[0])
        self.gy.setValue(self.place[1])
        self.gz.setValue(self.place[2])
        self._auto0 = grid_auto(g, ft)
        self.auto.setChecked(not self._auto0)  # force le signal pour griser X/Y/Z
        self.auto.setChecked(self._auto0)
        self.grid.set(g, ft)
        self.note.setText("Aucun canal dans aucun mode : sert seulement à la 3D, le nettoyeur "
                          "la retirera." if flag_3d else "")

    def edit(self) -> "geotree.Edit":
        """Ce qui a changé dans les champs simples (nom, type, adresse, grille)."""
        g, e = self.geo, geotree.Edit()
        if self.name.text().strip() != g.name:
            e.name = self.name.text().strip()
        if not g.is_reference and self.kind.currentText() not in (g.kind, REF):
            e.kind = self.kind.currentText()
        if g.is_reference and g.breaks and self.address.value() != g.breaks[0].dmx_offset:
            e.breaks = [self.address.value()] + [b.dmx_offset for b in g.breaks[1:]]
        mesh = "" if self.mesh.currentText() == NO_MESH else self.mesh.currentText()
        if not g.is_reference and mesh != g.model and mesh != OTHER_GDTF:
            e.mesh = mesh
        auto = self.auto.isChecked()
        if not auto and (self.gx.value(), self.gy.value(), self.gz.value()) != self.place:
            e.grid = (self.gx.value(), self.gy.value(), self.gz.value())
        if auto != self._auto0:
            e.grid_auto = auto
            if not auto:  # passer à la main écrit la place affichée
                e.grid = (self.gx.value(), self.gy.value(), self.gz.value())
        return e


class ChannelDialog(QDialog):
    """Un canal de la charte DMX : attribut, adresses (coarse, fine…), valeur par défaut."""

    def __init__(self, title: str, attributes: list[str], attribute: str = "", offsets=None,
                 default: str = "", parent=None, ma3: bool = False):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(420)
        self.attribute = QComboBox()
        self.attribute.setEditable(True)
        self.attribute.addItems(attributes)
        self.attribute.setCurrentText(attribute)
        self.offsets = QLineEdit(",".join(map(str, offsets or [])))
        self.offsets.setPlaceholderText("ex. 5   ou   5,6 pour 16 bits   (vide = virtuel)")
        self.default = QLineEdit(default)
        self.default.setPlaceholderText("ex. 80007F (24 bits hexa)   ou   32768/2" if ma3
                                        else "ex. 0/1   ou   32768/2")
        form = QFormLayout(self)
        form.setContentsMargins(18, 16, 18, 14)
        form.setVerticalSpacing(10)
        form.addRow("Attribut", self.attribute)
        form.addRow("Adresses", self.offsets)
        if default or attribute:
            form.addRow("Défaut", self.default)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Appliquer")
        buttons.button(QDialogButtonBox.Cancel).setText("Annuler")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.setStyleSheet(f"QLineEdit {{ background: {theme.ROW.name()}; border: none;"
                           f" border-radius: 6px; padding: 6px 24px 6px 10px; }}")

    def values(self) -> tuple[str, Optional[list[int]], str]:
        """(attribut, adresses ou None si illisibles, défaut)."""
        text = self.offsets.text().replace(";", ",").replace("/", ",").replace(" ", ",")
        parts = [p for p in text.split(",") if p]
        offsets = [int(p) for p in parts] if all(p.isdigit() for p in parts) else None
        return self.attribute.currentText().strip(), offsets, self.default.text().strip()


class DuplicateDialog(QDialog):
    """Combien de copies, et de combien d'adresses décaler chacune (un pas par Break)."""

    def __init__(self, ref: Geometry, steps: list[int], parent=None, users=None):
        super().__init__(parent)
        self.setWindowTitle(f"Dupliquer « {ref.name} »")
        self.count = QSpinBox()
        self.count.setRange(1, 512)
        self.count.setValue(1)
        self.steps = []
        form = QFormLayout(self)
        form.setContentsMargins(18, 16, 18, 14)
        form.setVerticalSpacing(10)
        form.addRow("Copies en plus", self.count)
        for i, (b, step) in enumerate(zip(ref.breaks, steps)):
            spin = QSpinBox()
            spin.setRange(0, 512)
            spin.setValue(step)
            self.steps.append(spin)
            modes = sorted({m.split("-")[0].strip() for m, _ in users[i]}) if users else []
            label = "Pas d'adresse" if len(steps) == 1 else \
                f"Pas pour {', '.join(modes) or 'aucun mode'} (départ {b.dmx_offset})"
            form.addRow(label, spin)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Dupliquer")
        buttons.button(QDialogButtonBox.Cancel).setText("Annuler")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.setStyleSheet(f"QSpinBox {{ background: {theme.ROW.name()}; border: none;"
                           f" border-radius: 6px; padding: 6px 24px 6px 10px; }}")

    def values(self) -> tuple[int, list[int]]:
        return self.count.value(), [s.value() for s in self.steps]


class EditDialog(QDialog):
    """Popup du double-clic : nom, type, adresse, grille d'une géométrie."""

    def __init__(self, ft: FixtureType, g: Geometry, mode: str, parent=None, rows=None, on_channel=None):
        """`rows()` : canaux contenus dans la géométrie (relus après chaque correction) ;
        `on_channel(géométrie, attribut)` : corrige un canal (attribut vide = nouveau canal)."""
        super().__init__(parent)
        self.g, self.mode = g, mode
        self._rows, self._on_channel = rows, on_channel
        self.setWindowTitle(f"Paramètres de « {g.name} »")
        self.setMinimumWidth(520)
        form = QFormLayout(self)
        form.setContentsMargins(18, 16, 18, 14)
        form.setVerticalSpacing(10)

        self.name = QLineEdit(g.name)
        form.addRow("Nom", self.name)
        self.kind = QComboBox()
        if g.is_reference:
            tpl = ft.top_level(g.reference)
            self.kind.addItem(f"{tpl.kind if tpl else '?'} (type du modèle « {g.reference} »)")
            self.kind.setEnabled(False)
        else:
            self.kind.addItems(list(geotree.EDITABLE_KINDS))
            self.kind.setCurrentText(g.kind)
        form.addRow("Type", self.kind)

        # adresse : une par Break pour une référence, sinon le premier canal dans ce mode
        self.breaks: list[QSpinBox] = []
        self.start: Optional[QSpinBox] = None
        self._start0 = None
        if g.is_reference:
            users = geotree._break_users(ft, g)
            for i, b in enumerate(g.breaks):
                spin = QSpinBox()
                spin.setRange(1, 512)
                spin.setValue(b.dmx_offset)
                self.breaks.append(spin)
                modes = sorted({m.split("-")[0].strip() for m, _ in users[i]}) if i < len(users) else []
                label = "Adresse" if len(g.breaks) == 1 else f"Adresse pour {', '.join(modes) or '—'}"
                form.addRow(label, spin)
        else:
            self._start0 = geotree.first_channel(ft, g, mode)
            if self._start0 is not None:
                self.start = QSpinBox()
                self.start.setRange(1, 512)
                self.start.setValue(self._start0)
                form.addRow("Premier canal (ce mode)", self.start)
            else:
                lab = QLabel("pas de canal dans ce mode")
                lab.setObjectName("dim")
                form.addRow("Adresse", lab)

        el = geotree.element_of(ft, g)
        gx, gy = (el.get("GridX"), el.get("GridY")) if el is not None else (None, None)
        px, py = geotree.grid_proposal(g, ft)
        gz = grid_z(g, ft)
        self._grid0 = (int(gx), int(gy), gz) if gx is not None and gy is not None else None
        self.gx, self.gy, self.gz = QSpinBox(), QSpinBox(), QSpinBox()
        for spin, v in ((self.gx, gx if gx is not None else px), (self.gy, gy if gy is not None else py),
                        (self.gz, gz)):
            spin.setRange(0, 999)
            spin.setValue(int(v))
        propose = QPushButton("Proposer")
        propose.setToolTip("Place proposée d'après les positions 3D du GDTF")
        propose.clicked.connect(lambda: (self.auto.setChecked(False), self.gx.setValue(px), self.gy.setValue(py)))
        self.auto = _auto_box((self.gx, self.gy, self.gz))
        self._auto0 = grid_auto(g, ft)
        self.auto.setChecked(not self._auto0)
        self.auto.setChecked(self._auto0)
        grid = QHBoxLayout()
        grid.addWidget(self.auto)
        grid.addSpacing(10)
        grid.addWidget(QLabel("X"))
        grid.addWidget(self.gx, 1)
        grid.addSpacing(10)
        grid.addWidget(QLabel("Y"))
        grid.addWidget(self.gy, 1)
        grid.addSpacing(10)
        grid.addWidget(QLabel("Z"))
        grid.addWidget(self.gz, 1)
        grid.addSpacing(10)
        grid.addWidget(propose)
        form.addRow("Grille", grid)

        # Jo, 13/11/2026 : « double-clic sur Head : accès à tous les canaux de la géométrie »
        self.channels: Optional[QTableWidget] = None
        if rows is not None:
            title = QLabel(f"Canaux dans « {mode} »" + (f" (modèle « {g.reference} »)" if g.is_reference else "")
                           + " — double-clic pour repatcher")
            title.setFont(theme.font(10, True))
            form.addRow(title)
            self.channels = QTableWidget(0, 4)
            self.channels.setHorizontalHeaderLabels(["Canal", "Attribut", "Bits", "Défaut"])
            self.channels.verticalHeader().setVisible(False)
            self.channels.setEditTriggers(QAbstractItemView.NoEditTriggers)
            self.channels.setSelectionBehavior(QAbstractItemView.SelectRows)
            self.channels.setSelectionMode(QAbstractItemView.SingleSelection)
            self.channels.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
            self.channels.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
            self.channels.setMinimumHeight(240)
            self.channels.itemDoubleClicked.connect(self._channel_clicked)
            form.addRow(self.channels)
            row = QHBoxLayout()
            add = QPushButton(f"+ Canal sur « {charte_dmx.carrier(g)} »")
            add.clicked.connect(lambda: self._channel_asked(charte_dmx.carrier(g), ""))
            mod = QPushButton("Modifier…")
            mod.clicked.connect(lambda: self._channel_clicked(self.channels.item(self.channels.currentRow(), 0)))
            row.addWidget(add)
            row.addStretch(1)
            row.addWidget(mod)
            form.addRow(row)
            self._fill_channels()

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Appliquer")
        buttons.button(QDialogButtonBox.Cancel).setText("Fermer" if rows is not None else "Annuler")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.setStyleSheet(f"QLineEdit, QSpinBox {{ background: {theme.ROW.name()}; border: none;"
                           f" border-radius: 6px; padding: 6px 24px 6px 10px; }}")

    def _fill_channels(self) -> None:
        rows = self._rows()
        self.channels.setRowCount(len(rows))
        for i, r in enumerate(rows):
            cells = ["/".join(map(str, r.offsets)) if r.offsets else "virtuel", r.attribute,
                     str(r.bits), r.default]
            for j, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setData(Qt.UserRole, (r.geometry, r.attribute))
                self.channels.setItem(i, j, item)

    def channel_texts(self) -> list[str]:
        """Lignes du tableau en texte (tests)."""
        return ["  ".join(self.channels.item(i, j).text() for j in range(4))
                for i in range(self.channels.rowCount())]

    def _channel_clicked(self, item) -> None:
        if item is not None:
            self._channel_asked(*item.data(Qt.UserRole))

    def _channel_asked(self, geo: str, attribute: str) -> None:
        if self._on_channel is not None and self._on_channel(geo, attribute):
            self._fill_channels()

    def edit(self) -> "geotree.Edit":
        e = geotree.Edit()
        if self.name.text().strip() != self.g.name:
            e.name = self.name.text().strip()
        if self.kind.isEnabled() and self.kind.currentText() != self.g.kind:
            e.kind = self.kind.currentText()
        if self.breaks:
            vals = [s.value() for s in self.breaks]
            if vals != [b.dmx_offset for b in self.g.breaks]:
                e.breaks = vals
        if self.start is not None and self.start.value() != self._start0:
            e.start = (self.mode, self.start.value())
        grid = (self.gx.value(), self.gy.value(), self.gz.value())
        auto = self.auto.isChecked()
        if not auto and grid != self._grid0:
            e.grid = grid
        if auto != self._auto0:
            e.grid_auto = auto
            if not auto:
                e.grid = grid
        return e


# --------------------------------------------------------------------------
# Zone de droite : géométries disponibles (Jo, 13/11/2026) — créées (nom + type) ou importées
# d'un autre fichier, à glisser dans l'arbre.

@dataclass
class Piece:
    name: str
    kind: str
    source: str  # « nouvelle » ou « importée · <fixture> »
    build: object  # fonction (fixture) -> (élément XML, mesh) au format de ce fixture
    count: int = 1  # géométries dans le sous-arbre


class PieceList(QWidget):
    """Les géométries disponibles, en lignes comme l'arbre ; on les glisse dans l'arbre."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pieces: list[Piece] = []
        self.current = -1
        self._press: Optional[QPointF] = None
        self.setMinimumHeight(60)

    def set_pieces(self, pieces: list[Piece]) -> None:
        self.pieces = pieces
        self.current = min(self.current, len(pieces) - 1)
        self.setMinimumHeight(max(60, len(pieces) * 34 + 8))
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), theme.BG)
        if not self.pieces:
            p.setPen(theme.TEXT_DIM)
            p.setFont(theme.font(9))
            p.drawText(self.rect(), Qt.AlignCenter, "Crée ou importe une géométrie")
            return
        for i, pc in enumerate(self.pieces):
            r = QRectF(4, 4 + i * 34, self.width() - 8, 30)
            sel = i == self.current
            p.setPen(Qt.NoPen)
            p.setBrush(theme.HEADER if sel else theme.ROW)
            p.drawRoundedRect(r, 5, 5)
            badge = BADGE.get(pc.kind, pc.kind[:4].upper())
            p.setFont(theme.font(7, True))
            bw = p.fontMetrics().horizontalAdvance(badge) + 12
            br = QRectF(r.left() + 10, r.center().y() - 9, bw, 18)
            p.setBrush(theme.STATUS["bleu"] if pc.kind == "Beam" else theme.ROW_HOVER)
            p.drawRoundedRect(br, 9, 9)
            p.setPen(theme.TEXT)
            p.drawText(br, Qt.AlignCenter, badge)
            p.setFont(theme.font(10, sel))
            name = pc.name + (f"  ({pc.count})" if pc.count > 1 else "")
            src_w = int(r.width() * 0.45)
            p.drawText(QRectF(br.right() + 10, r.top(), r.right() - br.right() - src_w - 20, 30),
                       Qt.AlignVCenter, name)
            p.setFont(theme.font(9))
            p.setPen(theme.TEXT_DIM)
            p.drawText(QRectF(r.right() - src_w - 10, r.top(), src_w, 30), Qt.AlignVCenter | Qt.AlignRight,
                       p.fontMetrics().elidedText(pc.source, Qt.ElideLeft, src_w))

    def _index_at(self, pos) -> int:
        i = int((pos.y() - 4) // 34)
        return i if 0 <= i < len(self.pieces) else -1

    def mousePressEvent(self, e):
        self.current = self._index_at(e.position())
        self._press = e.position() if self.current >= 0 else None
        self.update()

    def mouseMoveEvent(self, e):
        if self._press is None or not (e.buttons() & Qt.LeftButton):
            return
        if (e.position() - self._press).manhattanLength() < 8:
            return
        self._press = None
        data = QMimeData()
        data.setData(PIECE_MIME, str(self.current).encode())
        data.setText(self.pieces[self.current].name)
        drag = QDrag(self)
        drag.setMimeData(data)
        drag.exec(Qt.CopyAction)


class GeoBank(QWidget):
    """Créer une géométrie (nom, type, modèle, mesh) ou en importer ; « Géométries disponibles »."""

    importAsked = Signal()
    addAsked = Signal(int)  # « Ajouter sous la sélection »

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pieces: list[Piece] = []
        title = QLabel("Géométries")
        title.setFont(theme.font(12, True))
        hint = QLabel("Crée ou importe des géométries, puis glisse-les dans l'arbre.")
        hint.setObjectName("dim")
        hint.setWordWrap(True)
        self.name = QLineEdit()
        self.name.setPlaceholderText("ex. Pixel")
        self.kind = QComboBox()
        self.kind.addItems(list(geotree.NEW_KINDS))
        self.kind.setCurrentText("Beam")
        self.kind.currentTextChanged.connect(self._kind_changed)
        self.model = QComboBox()
        self.model.setPlaceholderText("pour une référence")
        self.mesh = QComboBox()
        self.create = QPushButton("+ Créer")
        self.create.setFont(theme.font(10, True))
        self.create.clicked.connect(self._create)
        self.name.returnPressed.connect(self._create)
        self.list = PieceList()
        imp = QPushButton("Importer d'un fichier…")
        imp.setToolTip("Prendre des géométries (avec leurs enfants) dans un GDTF ou un XML de la console")
        imp.clicked.connect(lambda: self.importAsked.emit())
        add = QPushButton("Ajouter sous la sélection")
        add.clicked.connect(lambda: self.addAsked.emit(self.list.current) if self.list.current >= 0 else None)
        rem = QPushButton("Retirer")
        rem.setToolTip("Retire de la liste (pas de l'arbre)")
        rem.clicked.connect(self._remove)
        self.message = QLabel()
        self.message.setObjectName("dim")
        self.message.setWordWrap(True)

        def section(text):
            lab = QLabel(text)
            lab.setFont(theme.font(9, True))
            lab.setObjectName("dim")
            return lab

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 10)
        lay.setSpacing(8)
        lay.addWidget(title)
        lay.addWidget(hint)
        lay.addSpacing(4)
        lay.addWidget(section("NOUVELLE GÉOMÉTRIE"))
        form = QFormLayout()
        form.setHorizontalSpacing(14)
        form.addRow("Nom", self.name)
        form.addRow("Type", self.kind)
        form.addRow("Modèle", self.model)
        form.addRow("Mesh", self.mesh)
        lay.addLayout(form)
        row = QHBoxLayout()
        row.addWidget(self.message, 1)
        row.addWidget(self.create)
        lay.addLayout(row)
        lay.addSpacing(8)
        lay.addWidget(section("GÉOMÉTRIES DISPONIBLES  —  à glisser dans l'arbre"))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.list)
        scroll.setMinimumHeight(150)
        lay.addWidget(scroll, 1)
        buttons = QHBoxLayout()
        for b in (imp, add, rem):
            buttons.addWidget(b)
        lay.addLayout(buttons)
        tip = QLabel("Glisser sur une ligne = enfant de cette ligne · entre deux lignes = à cette place.\n"
                     "Une géométrie posée arrive sans canal.")
        tip.setObjectName("dim")
        tip.setWordWrap(True)
        lay.addWidget(tip)
        self._kind_changed(self.kind.currentText())
        self.ft: Optional[FixtureType] = None

    def set_fixture(self, ft: Optional[FixtureType]) -> None:
        """Modèles (pour une référence) et meshes de ce fixture."""
        self.ft = ft
        for combo, items in ((self.model, geotree.models(ft) if ft else []),
                             (self.mesh, [NO_MESH] + (geotree.meshes(ft) if ft else []))):
            cur = combo.currentText()
            combo.clear()
            combo.addItems(items)
            if cur and combo.findText(cur) >= 0:
                combo.setCurrentText(cur)
        if self.model.currentIndex() < 0 and self.model.count():
            self.model.setCurrentIndex(0)
        self._kind_changed(self.kind.currentText())

    def _kind_changed(self, kind: str) -> None:
        ref = kind == "GeometryReference"
        self.model.setEnabled(ref)
        self.mesh.setEnabled(not ref)  # une référence prend le mesh de son modèle

    def _create(self) -> None:
        name, kind = self.name.text().strip(), self.kind.currentText()
        model = self.model.currentText() if kind == "GeometryReference" else ""
        mesh = "" if kind == "GeometryReference" or self.mesh.currentText() in ("", NO_MESH) else self.mesh.currentText()
        if self.ft is not None:  # vérifié tout de suite : nom, modèle
            try:
                geotree.new_geometry(self.ft, name, kind, model)
            except geotree.MoveError as exc:
                self.message.setText(f"Impossible : {exc}")
                QMessageBox.warning(self, "Impossible", str(exc)[:1].upper() + str(exc)[1:])
                return
        label = f"{name}  → {model}" if model else name
        self.add(Piece(label, kind, "nouvelle",
                       lambda ft, n=name, k=kind, m=model, me=mesh: (geotree.new_geometry(ft, n, k, m), me)))
        self.message.setText("")
        self.name.clear()

    def add(self, piece: Piece) -> None:
        self.pieces.append(piece)
        self.list.current = len(self.pieces) - 1
        self.list.set_pieces(self.pieces)

    def _remove(self) -> None:
        i = self.list.current
        if 0 <= i < len(self.pieces):
            del self.pieces[i]
            self.list.set_pieces(self.pieces)


class ImportDialog(QDialog):
    """Choisir les géométries à prendre dans un autre fichier (arbre indenté, plusieurs à la fois)."""

    def __init__(self, other: FixtureType, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Importer de « {other.manufacturer} - {other.name} »")
        self.resize(520, 560)
        self.items: list[Geometry] = []
        self.list = QListWidget()
        self.list.setSelectionMode(QListWidget.ExtendedSelection)

        def add(g: Geometry, depth: int) -> None:
            badge = BADGE.get(g.kind, g.kind[:4].upper())
            extra = f"  → {g.reference}" if g.is_reference else (f"   ({len(list(g.walk())) - 1} enfants)"
                                                                  if g.children else "")
            self.list.addItem(QListWidgetItem("      " * depth + f"[{badge}]  {g.name}{extra}"))
            self.items.append(g)
            for c in g.children:
                add(c, depth + 1)

        for top in other.geometries:
            add(top, 0)
        info = QLabel("Choisis une ou plusieurs géométries (Ctrl / Maj). Chacune arrive avec ses enfants ; "
                      "une référence arrive comme une copie de son modèle. Aucun canal n'est copié.")
        info.setWordWrap(True)
        info.setObjectName("dim")
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Importer")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(info)
        lay.addWidget(self.list, 1)
        lay.addWidget(buttons)

    def chosen(self) -> list[Geometry]:
        return [self.items[self.list.row(it)] for it in self.list.selectedItems()]


class AtelierWindow(QMainWindow):
    shareAsked = Signal()  # l'appli ouvre l'explorateur GDTF Share
    compareAsked = Signal(str)  # « source » ou « cible » : l'appli pose le fixture dans le comparateur

    def __init__(self):
        super().__init__()
        self.setWindowTitle(TITLE)
        self.resize(1300, 820)
        self.ft: Optional[FixtureType] = None

        self.open = QPushButton("Fixture : ouvrir…")
        self.open.setFont(theme.font(10, True))
        source = QMenu(self.open)  # d'où vient le fixture : le PC, ou la banque GDTF Share
        source.addAction("Sur ce PC…", self.choose)
        source.addAction("Dans GDTF Share (fabricants)…", lambda: self.shareAsked.emit())
        self.open.setMenu(source)
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
        self.tree.menuAsked.connect(self._menu)
        self.tree.editAsked.connect(self._edit)
        self.history: list[bytes] = []  # XML avant chaque modification (Ctrl+Z le relit)
        QShortcut(QKeySequence.Undo, self, activated=self.undo)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.tree)
        self.params = Params()
        self.params.setFixedWidth(400)
        self.params.applied.connect(self._apply_params)
        self.params.channelAsked.connect(self._channel)
        self.tree.pieceDropped.connect(self._place_piece)
        self.bank = GeoBank()
        self.bank.importAsked.connect(self._import_pieces)
        self.bank.addAsked.connect(self._add_piece_here)
        left = QWidget()
        lh = QHBoxLayout(left)
        lh.setContentsMargins(0, 0, 0, 0)
        lh.setSpacing(0)
        lh.addWidget(scroll, 1)
        lh.addWidget(self.params)
        # Jo, 13/11/2026 : création à droite, avec son séparateur vertical
        self.split = QSplitter(Qt.Horizontal)
        self.split.setHandleWidth(8)
        self.split.setChildrenCollapsible(False)
        self.split.addWidget(left)
        self.split.addWidget(self.bank)
        self.split.setStretchFactor(0, 3)
        self.split.setStretchFactor(1, 1)
        self.split.setStyleSheet(f"QSplitter::handle {{ background: {theme.PANEL.name()}; "
                                 f"border-left: 1px solid {theme.ROW_HOVER.name()}; "
                                 f"border-right: 1px solid {theme.ROW_HOVER.name()}; }}")
        mid = QHBoxLayout()
        mid.setSpacing(0)
        mid.addWidget(self.split, 1)

        self.summary = QLabel()
        self.summary.setFont(theme.font(10))
        self.status = QLabel()
        self.status.setObjectName("dim")
        self.status.setFont(theme.font(9))
        self.split_button = QPushButton("Une base par mode")
        self.split_button.setEnabled(False)
        self.split_button.setToolTip("Sépare un arbre partagé par plusieurs modes : chaque mode reçoit sa base,"
                                     " avec les mêmes modèles. Les adresses ne bougent pas. Ctrl+Z annule.")
        self.split_button.clicked.connect(self.split_per_mode)
        self.strip_button = QPushButton("Retirer la 3D")
        self.strip_button.setEnabled(False)
        self.strip_button.setToolTip("Supprime toutes les géométries sans canal (Beams, câblage, références"
                                     " 3D), dans tous les modes. Les adresses ne bougent pas. Ctrl+Z annule.")
        self.strip_button.clicked.connect(self.strip_3d)
        self.compare_button = QPushButton("Comparer")
        self.compare_button.setEnabled(False)
        self.compare_button.setToolTip("Envoie ce fixture, avec ses modifications, dans le comparateur")
        compare_menu = QMenu(self.compare_button)
        compare_menu.addAction("comme source (à gauche)", lambda: self.compareAsked.emit("source"))
        compare_menu.addAction("comme cible (à droite)", lambda: self.compareAsked.emit("cible"))
        self.compare_button.setMenu(compare_menu)
        self.export_button = QPushButton("Exporter…")
        self.export_button.setEnabled(False)
        self.export_button.setToolTip("Enregistrer en XML MA3 2.3.2.0 (onPC, clé USB ou dossier)")
        self.export_button.clicked.connect(self.export)
        foot = QHBoxLayout()
        foot.setContentsMargins(14, 6, 14, 6)
        foot.addWidget(self.summary)
        foot.addSpacing(24)
        foot.addWidget(self.status, 1)
        foot.addWidget(self.split_button)
        foot.addWidget(self.strip_button)
        foot.addWidget(self.compare_button)
        foot.addWidget(self.export_button)

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
        self.set_fixture(gdtf.load(path), mode)

    def set_fixture(self, ft: FixtureType, mode: str = "") -> None:
        """Ouvre un fixture déjà en mémoire (ex. celui que la section « Créer » vient de fabriquer)."""
        self.ft = ft
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
        self.export_button.setEnabled(True)
        self.compare_button.setEnabled(True)
        self.bank.set_fixture(self.ft)
        self.split_button.setEnabled(True)  # toujours cliquables : un refus s'explique (Jo, 13/11/2026)
        self.strip_button.setEnabled(True)
        self._mode_changed()

    def split_per_mode(self) -> None:
        if not self.ft:
            return
        current = self.modes.currentText()
        if not geotree.shared_trees(self.ft):
            self._tell("Chaque mode a déjà sa propre base (ou aucun mode n'a plusieurs instances) : rien à séparer")
            return
        if self._apply(geotree.split_per_mode):
            self._select_mode(current)
            self._after_change(f"{self._last}   ·   Ctrl+Z pour annuler")

    def _select_mode(self, name: str) -> None:
        self.modes.blockSignals(True)
        self.modes.clear()
        self.modes.addItems([m.name for m in self.ft.modes])
        self.modes.setCurrentText(name)
        self.modes.blockSignals(False)

    def strip_3d(self) -> None:
        if not self.ft:
            return
        current = self.modes.currentText()
        mode = self.ft.mode(current)
        hidden = geotree.hidden_3d(self.ft, mode) if mode else []
        if hidden and geotree.shared_trees(self.ft):
            names = ", ".join(g.name for g in hidden[:4]) + ("…" if len(hidden) > 4 else "")
            ok = QMessageBox.question(
                self, "Retirer la 3D",
                f"Dans le mode « {current} », {len(hidden)} géométrie(s) n'ont aucun canal ({names}), "
                "mais un autre mode les utilise : tous les modes partagent le même arbre.\n\n"
                "Donner d'abord à chaque mode sa propre base, puis retirer la 3D ?\n"
                "(Les adresses ne bougent pas, Ctrl+Z annule.)")
            if ok != QMessageBox.Yes:
                return
            if self._apply(geotree.split_then_strip):
                self._select_mode(current)
                self._after_change(f"{self._last}   ·   Ctrl+Z pour annuler")
            return
        if not geotree.channel_less(self.ft):
            self._tell("Rien à retirer : toutes les géométries portent des canaux")
            return
        if self._apply(geotree.strip_3d):
            self._after_change(f"{self._last}   ·   Ctrl+Z pour annuler")

    def export(self) -> None:
        if not self.ft:
            return
        from .export import ExportDialog
        dlg = ExportDialog(self.ft, self)
        if dlg.exec() and dlg.written:
            self.status.setText(f"Exporté : {dlg.written}")

    def _mode_changed(self) -> None:
        if not self.ft:
            return
        mode = self.ft.mode(self.modes.currentText())
        root = self.ft.top_level(mode.geometry) if mode else None
        self._diagnose()
        self.tree.set_root(root, self.useless, self.doubles, self._idents(), self.copies,
                           self._models(root))
        self._summary()

    def _models(self, root) -> list[Geometry]:
        """Modèles référencés par l'arbre du mode (et par leurs propres références)."""
        out, todo = [], [root] if root else []
        while todo:
            for g in todo.pop().walk():
                if g.is_reference and (tpl := self.ft.top_level(g.reference)) and all(tpl is not x for x in out):
                    out.append(tpl)
                    todo.append(tpl)
        return out

    def _diagnose(self) -> None:
        # tout ce qui ne porte aucun canal, Beams compris (Jo, 10/11/2026 : la 3D ne l'intéresse pas)
        # par mode : un arbre partagé garde des géométries sans canal dans ce mode
        mode = self.ft.mode(self.modes.currentText()) if self.modes.count() else None
        self.useless = {g.name for g in geotree.channel_less(self.ft)}
        if mode is not None:
            self.useless |= {g.name for g in geotree.channel_less(self.ft, mode)}
        self.doubles = {n for grp in diagnostic.duplicate_templates(self.ft) for n in grp}
        self.copies = {n: len(g.names) for g in diagnostic.find_instance_groups(self.ft)
                       if not g.per_mode_variants for n in g.names}

    def _idents(self) -> dict[str, str]:
        mode = self.ft.mode(self.modes.currentText()) if self.ft else None
        inst = compare.instances(self.ft, mode) if mode else None
        return {i.name: i.ident for i in compare.flatten(inst)}

    def _after_change(self, message: str) -> None:
        self._diagnose()
        self.bank.set_fixture(self.ft)  # nouveaux modèles / meshes
        mode = self.ft.mode(self.modes.currentText())
        root = self.ft.top_level(mode.geometry) if mode else None
        self.tree.refresh(root, self.useless, self.doubles, self._idents(), self.copies,
                          self._models(root))
        self._summary()
        if self.tree.current is not None:
            self._select(self.tree.current)
        self.status.setText(message)
        self.setWindowTitle(TITLE + (" •" if self.history else ""))

    def _refuse(self, reason: str) -> None:
        """Refus expliqué dans une fenêtre (Jo, 13/11/2026 : « pas de message quand ça refuse »)."""
        self.status.setText(f"Impossible : {reason}")
        QMessageBox.warning(self, "Impossible", reason[:1].upper() + reason[1:])

    def _tell(self, text: str) -> None:
        """Opération sans effet : on le dit aussi dans une fenêtre."""
        self.status.setText(text)
        QMessageBox.information(self, APP_NAME, text)

    def _apply(self, action, *args) -> bool:
        """Lance une opération de geotree, garde de quoi annuler, affiche le résultat."""
        before = geotree.snapshot(self.ft)
        try:
            result = action(self.ft, *args)
        except geotree.MoveError as exc:
            self._refuse(str(exc))
            return False
        if isinstance(result, tuple):  # opérations qui relisent le fixture
            self.ft, message = result
        else:
            message = ""
        self.history.append(before)
        self._last = message
        return True

    def _place_piece(self, i: int, parent: Geometry, index: int) -> None:
        """Une géométrie disponible lâchée dans l'arbre : posée sans canal, Ctrl+Z annule."""
        if not self.ft or not 0 <= i < len(self.bank.pieces):
            return
        piece = self.bank.pieces[i]

        def place(ft):
            el, mesh = piece.build(ft)
            return geotree.add_geometry(ft, el, parent, index, mesh)

        if self._apply(place):
            self._after_change(f"{self._last}   ·   Ctrl+Z pour annuler")

    def _add_piece_here(self, i: int) -> None:
        """« Ajouter sous la sélection » : en dernier enfant de la ligne choisie ; sur une
        référence (qui n'a pas d'enfant), juste après elle."""
        g = self.tree.current
        if g is None:
            self._refuse("choisis d'abord une ligne dans l'arbre")
            return
        if g.is_reference:
            self._place_piece(i, g.parent, g.parent.children.index(g) + 1)
        else:
            self._place_piece(i, g, len(g.children))

    def _import_pieces(self) -> None:
        if not self.ft:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Importer des géométries", "",
                                              "Fixtures (*.gdtf *.xml);;GDTF (*.gdtf);;XML MA3 (*.xml)")
        if not path:
            return
        try:
            other = geotree.importable(path)
        except geotree.MoveError as exc:
            self._refuse(str(exc))
            return
        dlg = ImportDialog(other, self)
        if dlg.exec() != QDialog.Accepted:
            return
        for g in dlg.chosen():
            kind = (other.top_level(g.reference).kind if g.is_reference and other.top_level(g.reference)
                    else g.kind)
            self.bank.add(Piece(g.name, kind, f"importée · {other.name}",
                                lambda ft, o=other, x=g: (geotree.take_geometry(o, x, ft), ""),
                                len(list(g.walk()))))
        self.status.setText(f"{len(dlg.chosen())} géométrie(s) de « {other.name} » ajoutée(s) aux disponibles")

    def _move(self, geos: list, parent: Geometry, index: int) -> None:
        if self._apply(geotree.move, geos, parent, index):
            what = f"{len(geos)} géométries" if len(geos) > 1 else f"« {geos[0].name} »"
            self._after_change(f"{what} → sous « {parent.name} »   ·   Ctrl+Z pour annuler")

    def _menu(self, where) -> None:
        sel = list(self.tree.selection)
        menu = QMenu(self)
        if sel and all(g.parent is not None and not g.is_reference for g in sel):
            menu.addAction(f"Regrouper en modèle + {len(sel)} référence(s)…", lambda: self._group(sel))
        elif len(sel) == 1 and sel[0].name in self.copies:
            same = next(gr for gr in diagnostic.find_instance_groups(self.ft) if sel[0].name in gr.names)
            geos = [self.ft.geometry(n) for n in same.names]
            menu.addAction(f"Regrouper les {len(geos)} copies en modèle + références…",
                           lambda: self._group(geos))
        if len(sel) == 1 and sel[0].is_reference and sel[0].parent is not None:
            menu.addAction(f"Dupliquer « {sel[0].name} »…", lambda: self._duplicate(sel[0]))
        refs = {g.reference for g in sel if g.is_reference}
        for grp in diagnostic.duplicate_templates(self.ft):
            if refs & set(grp):
                menu.addAction(f"Fusionner les {len(grp)} modèles en double (« {grp[0]} »)",
                               lambda grp=grp: self._merge(grp))
        if menu.isEmpty():
            menu.addAction("Sélectionne au moins deux géométries identiques").setEnabled(False)
        menu.exec(where)

    def _group(self, geos: list) -> None:
        name, ok = QInputDialog.getText(self, "Regrouper", "Nom du modèle :",
                                        text=geotree.suggested_model_name(self.ft, geos))
        if ok and self._apply(geotree.group, geos, name.strip()):
            self._after_change(f"{self._last}   ·   Ctrl+Z pour annuler")

    def _duplicate(self, ref: Geometry) -> None:
        dlg = DuplicateDialog(ref, geotree.duplicate_steps(self.ft, ref), self,
                              geotree._break_users(self.ft, ref))
        if dlg.exec() == QDialog.Accepted:
            count, steps = dlg.values()
            if self._apply(geotree.duplicate, ref, count, steps):
                self._after_change(f"{self._last}   ·   Ctrl+Z pour annuler")

    def _edit(self, g: Geometry) -> None:
        mode = self.modes.currentText()
        name = g.name
        rows = lambda: charte_dmx.lignes(self.ft, mode, self.ft.geometry(name) or g)
        dlg = EditDialog(self.ft, g, mode, self, rows, self._edit_channel)
        if dlg.exec() == QDialog.Accepted:
            edit = dlg.edit()
            g = self.ft.geometry(name) or g  # le fixture a pu être relu (canaux corrigés)
            if any(v is not None for v in vars(edit).values()) and self._apply(geotree.apply_edit, g, edit):
                self._after_change(f"{self._last}   ·   Ctrl+Z pour annuler")

    def _merge(self, names: list) -> None:
        if self._apply(geotree.merge_models, [self.ft.top_level(n) for n in names]):
            self._after_change(f"{self._last}   ·   Ctrl+Z pour annuler")

    def undo(self) -> None:
        if self.ft and self.history:
            self.ft = geotree.restore(self.ft, self.history.pop())
            self._after_change("Annulé")

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
                             self.tree.idents.get(g.name, "") if g is not None else "", self.ft,
                             geotree.models(self.ft) if self.ft else [], len(self.tree.selection))
        if g is not None and self.ft is not None:
            self.params.show_channels(charte_dmx.lignes(self.ft, self.modes.currentText(), g),
                                      charte_dmx.carrier(g), not g.is_reference)

    def _channel(self, what: str, attribute: str) -> None:
        """Correction de la charte DMX depuis le panneau : ajouter, modifier, retirer un canal."""
        g = self.params.geo
        if self.ft is None or g is None:
            return
        self._edit_channel(charte_dmx.carrier(g), attribute, what)

    def _edit_channel(self, geo: str, attribute: str, what: str = "") -> bool:
        """Ajoute (attribut vide), modifie ou retire un canal de `geo` dans le mode affiché."""
        mode = self.modes.currentText()
        what = what or ("edit" if attribute else "add")
        ok = False
        if what == "remove":
            ok = self._apply(charte_dmx.retirer, mode, geo, attribute)
        else:
            known = charte_dmx.attributs_connus(self.ft)
            if what == "add":
                try:
                    free = [charte_dmx.libre(self.ft, mode, geo)]
                except geotree.MoveError as exc:
                    self._refuse(str(exc))
                    return False
                dlg = ChannelDialog(f"Nouveau canal sur « {geo} »", known, "", free, "", self)
            else:
                row = next((r for r in charte_dmx.lignes(self.ft, mode, self.ft.geometry(geo))
                            if r.attribute == attribute), None)
                if row is None:
                    self._refuse(f"canal « {geo}_{attribute} » introuvable dans « {mode} »")
                    return False
                dlg = ChannelDialog(f"Canal « {geo}_{attribute} »", known, attribute, row.offsets,
                                    row.default, self, self.ft.format == "ma3")
            if dlg.exec() != QDialog.Accepted:
                return False
            new, offsets, default = dlg.values()
            if offsets is None:
                self._refuse("adresses illisibles (attendu 5 ou 5,6)")
                return False
            if what == "add":
                ok = self._apply(charte_dmx.ajouter, mode, geo, new, offsets)
            else:
                ok = self._apply(charte_dmx.modifier, mode, geo, attribute, offsets, new, default or None)
        if ok:
            self._after_change(f"{self._last}   ·   Ctrl+Z pour annuler")
        return ok

    def _apply_params(self) -> None:
        """Bouton « Appliquer » du panneau : référence (modèle choisi ou créé), puis nom, type,
        adresse, grille. Une seule annulation pour le tout."""
        p, g = self.params, self.params.geo
        if self.ft is None or g is None:
            return
        sel = [x for x in self.tree.selection if x.parent is not None] or [g]
        if not any(x is g for x in sel):
            sel = [g]
        edit, kind, model = p.edit(), p.kind.currentText(), p.model.currentText()
        before, done = geotree.snapshot(self.ft), []
        try:
            if p.mesh.currentText() == OTHER_GDTF and not g.is_reference:
                path, _ = QFileDialog.getOpenFileName(self, "GDTF où prendre le mesh", "", "GDTF (*.gdtf)")
                if not path:
                    return
                names = geotree.foreign_meshes(path)
                if not names:
                    raise geotree.MoveError("ce GDTF ne contient aucun mesh")
                name, ok = QInputDialog.getItem(self, "Mesh", "Mesh à copier :", names, 0, False)
                if not ok:
                    return
                self.ft, edit.mesh = geotree.import_mesh(self.ft, path, name)
                done.append(f"mesh « {edit.mesh} » copié")
            if kind == REF and model == NEW_MODEL:
                if any(x.is_reference for x in sel):
                    raise geotree.MoveError("c'est déjà une référence : choisis un modèle de la liste")
                name, ok = QInputDialog.getText(self, "Nouveau modèle", "Nom du modèle :",
                                                text=geotree.suggested_model_name(self.ft, sel))
                if not ok:
                    return
                self.ft, msg = geotree.group(self.ft, sel, name.strip())
                done.append(msg)
            elif kind == REF and model and (not g.is_reference or model != g.reference):
                self.ft, msg = geotree.to_reference(self.ft, sel, model)
                done.append(msg)
            elif kind != REF and g.is_reference:
                raise geotree.MoveError("une référence ne redevient pas une géométrie ici : Ctrl+Z, "
                                        "ou change le type de son modèle")
            edit.kind = None if done else edit.kind
            if any(v is not None for v in vars(edit).values()):
                self.ft, msg = geotree.apply_edit(self.ft, self.ft.geometry(g.name), edit)
                done.append(msg)
        except geotree.MoveError as exc:
            self.ft = geotree.restore(self.ft, before) if done else self.ft
            self._after_change(f"Impossible : {exc}")
            self._refuse(str(exc))
            return
        if not done:
            self._tell("Rien à changer")
            return
        self.history.append(before)
        self._after_change("   ·   ".join(done) + "   ·   Ctrl+Z pour annuler")


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
