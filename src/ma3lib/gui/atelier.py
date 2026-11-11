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
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
                               QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMainWindow, QMenu, QPushButton,
                               QScrollArea, QSpinBox, QVBoxLayout, QWidget)

from .. import compare, diagnostic, gdtf, geotree
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
            p.drawText(self._drag_pos + QPointF(14, -6), f"{n} géométrie(s)" if n > 1 else self.selection[0].name)

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


class MiniGrid(QWidget):
    """Grille façon Fixture Hero : les géométries sœurs à leur vraie place, la choisie en jaune.
    16 pixels en ligne = une seule ligne de 16 (Jo, 11/11/2026), jamais de retour à la ligne."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cells: list[tuple[int, int]] = []
        self.current: Optional[tuple[int, int]] = None
        self.setMinimumHeight(170)

    def set(self, geo: Optional[Geometry], ft=None) -> None:
        sibs = geo.parent.children if geo and geo.parent else ([geo] if geo else [])
        self.cells = [grid_place(g, ft) for g in sibs]
        self.current = grid_place(geo, ft) if geo else None
        self.update()

    def layout(self) -> tuple[int, int, float]:
        """Colonnes, lignes et taille d'une case : les cases rétrécissent pour tout faire tenir."""
        cols = max(x for x, _ in self.cells) + 1
        rows = max(y for _, y in self.cells) + 1
        size = min(26.0, (self.width() - 20) / cols, (self.height() - 20) / rows)
        return cols, rows, max(size, 2.0)

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), theme.PANEL)
        if not self.cells:
            return
        cols, rows, size = self.layout()
        gap = 3 if size >= 10 else 1
        x0 = (self.width() - cols * size) / 2
        y0 = (self.height() - rows * size) / 2
        for cell in sorted(set(self.cells), key=lambda c: c == self.current):
            on = cell == self.current
            p.setPen(QPen(theme.ACCENT if on else theme.ROW_HOVER, 2 if size >= 10 else 1))
            p.setBrush(theme.ACCENT if on else theme.BG)
            p.drawRect(QRectF(x0 + cell[0] * size, y0 + cell[1] * size, size - gap, size - gap))


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

    def show_geo(self, g: Optional[Geometry], flag_3d: bool, ident: str = "", ft=None) -> None:
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
        x, y = grid_place(g, ft)
        self.gx.setValue(x)
        self.gy.setValue(y)
        self.grid.set(g, ft)
        self.note.setText("Aucun canal dans aucun mode : sert seulement à la 3D, le nettoyeur "
                          "la retirera." if flag_3d else "")


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
                           f" border-radius: 6px; padding: 6px 10px; }}")

    def values(self) -> tuple[int, list[int]]:
        return self.count.value(), [s.value() for s in self.steps]


class EditDialog(QDialog):
    """Popup du double-clic : nom, type, adresse, grille d'une géométrie."""

    def __init__(self, ft: FixtureType, g: Geometry, mode: str, parent=None):
        super().__init__(parent)
        self.g, self.mode = g, mode
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
        self._grid0 = (int(gx), int(gy)) if gx is not None and gy is not None else None
        self.gx, self.gy = QSpinBox(), QSpinBox()
        for spin, v in ((self.gx, gx if gx is not None else px), (self.gy, gy if gy is not None else py)):
            spin.setRange(0, 999)
            spin.setValue(int(v))
        propose = QPushButton("Proposer")
        propose.setToolTip("Place proposée d'après les positions 3D du GDTF")
        propose.clicked.connect(lambda: (self.gx.setValue(px), self.gy.setValue(py)))
        grid = QHBoxLayout()
        grid.addWidget(QLabel("X"))
        grid.addWidget(self.gx, 1)
        grid.addSpacing(10)
        grid.addWidget(QLabel("Y"))
        grid.addWidget(self.gy, 1)
        grid.addSpacing(10)
        grid.addWidget(propose)
        form.addRow("Grille", grid)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Appliquer")
        buttons.button(QDialogButtonBox.Cancel).setText("Annuler")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.setStyleSheet(f"QLineEdit, QSpinBox {{ background: {theme.ROW.name()}; border: none;"
                           f" border-radius: 6px; padding: 6px 10px; }}")

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
        grid = (self.gx.value(), self.gy.value())
        if grid != self._grid0:
            e.grid = grid
        return e


class AtelierWindow(QMainWindow):
    compareAsked = Signal(str)  # « source » ou « cible » : l'appli pose le fixture dans le comparateur

    def __init__(self):
        super().__init__()
        self.setWindowTitle(TITLE)
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
        self.tree.menuAsked.connect(self._menu)
        self.tree.editAsked.connect(self._edit)
        self.history: list[bytes] = []  # XML avant chaque modification (Ctrl+Z le relit)
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
        self.export_button.setEnabled(True)
        self.compare_button.setEnabled(True)
        self._mode_changed()

    def split_per_mode(self) -> None:
        if not self.ft:
            return
        current = self.modes.currentText()
        if self._apply(geotree.split_per_mode):
            self.modes.setCurrentText(current)
            self._after_change(f"{self._last}   ·   Ctrl+Z pour annuler")

    def strip_3d(self) -> None:
        if self.ft and self._apply(geotree.strip_3d):
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
        self.useless = {g.name for g in geotree.channel_less(self.ft)}
        self.doubles = {n for grp in diagnostic.duplicate_templates(self.ft) for n in grp}
        self.copies = {n: len(g.names) for g in diagnostic.find_instance_groups(self.ft)
                       if not g.per_mode_variants for n in g.names}

    def _idents(self) -> dict[str, str]:
        mode = self.ft.mode(self.modes.currentText()) if self.ft else None
        inst = compare.instances(self.ft, mode) if mode else None
        return {i.name: i.ident for i in compare.flatten(inst)}

    def _after_change(self, message: str) -> None:
        self._diagnose()
        mode = self.ft.mode(self.modes.currentText())
        root = self.ft.top_level(mode.geometry) if mode else None
        self.tree.refresh(root, self.useless, self.doubles, self._idents(), self.copies,
                          self._models(root))
        self._summary()
        if self.tree.current is not None:
            self._select(self.tree.current)
        self.status.setText(message)
        self.setWindowTitle(TITLE + (" •" if self.history else ""))

    def _apply(self, action, *args) -> bool:
        """Lance une opération de geotree, garde de quoi annuler, affiche le résultat."""
        before = geotree.snapshot(self.ft)
        try:
            result = action(self.ft, *args)
        except geotree.MoveError as exc:
            self.status.setText(f"Impossible : {exc}")
            return False
        if isinstance(result, tuple):  # opérations qui relisent le fixture
            self.ft, message = result
        else:
            message = ""
        self.history.append(before)
        self._last = message
        return True

    def _move(self, geos: list, parent: Geometry, index: int) -> None:
        if self._apply(geotree.move, geos, parent, index):
            what = f"{len(geos)} géométries" if len(geos) > 1 else f"« {geos[0].name} »"
            self._after_change(f"{what} → sous « {parent.name} »   ·   Ctrl+Z pour annuler")

    def _menu(self, where) -> None:
        sel = list(self.tree.selection)
        menu = QMenu(self)
        if len(sel) >= 2 and all(g.parent is not None and not g.is_reference for g in sel):
            menu.addAction(f"Regrouper en modèle + {len(sel)} références…", lambda: self._group(sel))
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
        dlg = EditDialog(self.ft, g, mode, self)
        if dlg.exec() == QDialog.Accepted:
            edit = dlg.edit()
            if self._apply(geotree.apply_edit, g, edit):
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
        self.strip_button.setEnabled(bool(self.useless))
        self.split_button.setEnabled(self.ft.format == "gdtf" and bool(geotree.shared_trees(self.ft)))
        dot = lambda c: f"<span style='color:{c}; font-size:15px'>●</span>"
        self.summary.setText(
            f"Nettoyage proposé pour ce mode :  {dot(theme.TEXT_DIM.name())} {n3d} géométrie(s) 3D seule(s)"
            f"   {dot(theme.STATUS['jaune'].name())} {ndbl} modèle(s) en double")

    def _select(self, g) -> None:
        self.params.show_geo(g, g is not None and g.name in self.useless,
                             self.tree.idents.get(g.name, "") if g is not None else "", self.ft)


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
