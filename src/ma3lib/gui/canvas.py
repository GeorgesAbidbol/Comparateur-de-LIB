"""Vue instances : les deux arbres en escalier (style SubfixtureOverview / Fixture Hero)
et les lignes de branchement entre eux.

Souris : tirer une ligne d'une instance source vers une instance cible pour la brancher,
clic sur la flèche pour replier, double-clic sur une instance branchée pour voir ses
attributs, clic droit sur une instance cible pour la débrancher.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QMenu, QWidget

from .. import compare
from ..compare import Instance
from . import theme

ROW_H = 34
GAP_Y = 6
INDENT = 22
LINK_GAP = 170  # largeur de la bande centrale où passent les lignes
MARGIN = 14
PORT_R = 6


@dataclass
class _Row:
    inst: Instance
    rect: QRectF
    side: str  # "source" ou "cible"


class LinkCanvas(QWidget):
    pairOpened = Signal(str, str)  # ident source, ident cible
    linksChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.roots: dict[str, Optional[Instance]] = {"source": None, "cible": None}
        self.collapsed: dict[str, set[str]] = {"source": set(), "cible": set()}
        self.links: dict[str, str] = {}  # ident cible -> ident source
        self._rows: list[_Row] = []
        self._drag_from: Optional[_Row] = None
        self._drag_pos: Optional[QPointF] = None
        self._hover: Optional[_Row] = None
        self.fileDropped = None  # callback(side, path), posé par la fenêtre

    # ------------------------------------------------------------------ données
    def set_root(self, side: str, root: Optional[Instance]) -> None:
        self.roots[side] = root
        self.collapsed[side] = set()
        self.links = compare.auto_links(self.roots["source"], self.roots["cible"])
        self._relayout()
        self.linksChanged.emit()

    def instance(self, side: str, ident: str) -> Optional[Instance]:
        for i in compare.flatten(self.roots[side]):
            if i.ident == ident:
                return i
        return None

    def link_status(self, target_ident: str) -> str:
        s = self.instance("source", self.links.get(target_ident, ""))
        t = self.instance("cible", target_ident)
        return compare.instance_status(s, t)

    def counts(self) -> tuple[int, int]:
        return len(self.links), len(compare.flatten(self.roots["cible"]))

    # ------------------------------------------------------------------ mise en page
    def _col(self, side: str) -> tuple[float, float]:
        w = (self.width() - 2 * MARGIN - LINK_GAP) / 2
        x = MARGIN if side == "source" else MARGIN + w + LINK_GAP
        return x, w

    def _relayout(self) -> None:
        self._rows = []
        height = 0.0
        for side in ("source", "cible"):
            x0, w = self._col(side)
            y = MARGIN

            def add(inst: Instance) -> None:
                nonlocal y
                ind = inst.depth * INDENT
                rect = QRectF(x0 + ind, y, w - ind, ROW_H)
                self._rows.append(_Row(inst, rect, side))
                y += ROW_H + GAP_Y
                if inst.ident not in self.collapsed[side]:
                    for c in inst.children:
                        add(c)

            if self.roots[side]:
                add(self.roots[side])
            height = max(height, y + MARGIN)
        self.setMinimumHeight(int(height))
        self.update()

    def resizeEvent(self, event):
        self._relayout()
        super().resizeEvent(event)

    def sizeHint(self) -> QSize:
        return QSize(1100, 600)

    def _port(self, row: _Row) -> QPointF:
        x0, w = self._col(row.side)
        y = row.rect.center().y()
        return QPointF(x0 + w + 2, y) if row.side == "source" else QPointF(x0 - 2, y)

    def _visible(self, side: str, ident: str) -> Optional[_Row]:
        """Ligne affichée pour `ident`, ou celle de son ancêtre replié."""
        while ident:
            for r in self._rows:
                if r.side == side and r.inst.ident == ident:
                    return r
            ident = ident.rpartition(".")[0]
        return None

    def _row_at(self, pos: QPointF) -> Optional[_Row]:
        for r in self._rows:
            x0, w = self._col(r.side)
            band = QRectF(r.rect.left(), r.rect.top(), x0 + w - r.rect.left() + PORT_R + 4, ROW_H) \
                if r.side == "source" else QRectF(x0 - PORT_R - 4, r.rect.top(), r.rect.right() - x0 + PORT_R + 4, ROW_H)
            if band.contains(pos):
                return r
        return None

    # ------------------------------------------------------------------ dessin
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), theme.BG)

        # deux panneaux bien séparés : source à gauche, cible à droite (Jo, 11/11/2026)
        half = self.width() / 2
        for side, label, x in (("source", "Source", 8.0), ("cible", "Cible", half + 6)):
            zone = QRectF(x, 4, half - 14, self.height() - 8)
            p.setPen(Qt.NoPen)
            p.setBrush(theme.PANEL)
            p.drawRoundedRect(zone, 10, 10)
            if self.roots[side] is None:
                p.setPen(theme.TEXT_DIM)
                p.setFont(theme.font(12))
                p.drawText(QRectF(zone.x(), zone.y(), zone.width(), min(zone.height(), 420.0)),
                           Qt.AlignCenter, f"{label}\n\nglisse un GDTF ou un XML MA3 ici")

        self._paint_links(p)
        for r in self._rows:
            self._paint_row(p, r)
        if self._drag_from and self._drag_pos:
            pen = QPen(theme.ACCENT, 2, Qt.DashLine)
            p.setPen(pen)
            p.drawPath(self._curve(self._port(self._drag_from), self._drag_pos))

    def _curve(self, a: QPointF, b: QPointF) -> QPainterPath:
        path = QPainterPath(a)
        dx = max(40.0, abs(b.x() - a.x()) * 0.5)
        sign = 1 if b.x() >= a.x() else -1
        path.cubicTo(QPointF(a.x() + dx * sign, a.y()), QPointF(b.x() - dx * sign, b.y()), b)
        return path

    def _paint_links(self, p: QPainter) -> None:
        for t_ident, s_ident in self.links.items():
            s = self._visible("source", s_ident)
            t = self._visible("cible", t_ident)
            if not s or not t:
                continue
            folded = s.inst.ident != s_ident or t.inst.ident != t_ident
            color = QColor(theme.STATUS[self.link_status(t_ident)])
            if folded:
                color.setAlpha(110)
            pen = QPen(color, 1.6 if folded else 2.2)
            if folded:
                pen.setStyle(Qt.DashLine)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawPath(self._curve(self._port(s), self._port(t)))

    def _paint_row(self, p: QPainter, r: _Row) -> None:
        inst = r.inst
        drop = self._drag_from is not None and r is self._hover and r.side == "cible"
        fill = theme.ROW_DROP if drop else (theme.ROW_HOVER if r is self._hover else theme.ROW)
        p.setPen(Qt.NoPen)
        p.setBrush(fill)
        p.drawRoundedRect(r.rect, 6, 6)

        x = r.rect.left() + 10
        if inst.children:
            p.setPen(theme.TEXT)
            p.setFont(theme.font(10, True))
            arrow = "▸" if inst.ident in self.collapsed[r.side] else "▾"
            p.drawText(QRectF(x - 4, r.rect.top(), 18, ROW_H), Qt.AlignCenter, arrow)
        x += 18

        p.setFont(theme.font(9))
        p.setPen(theme.TEXT_DIM)
        p.drawText(QRectF(x, r.rect.top(), 64, ROW_H), Qt.AlignVCenter | Qt.AlignLeft, inst.ident)
        x += 66

        name = inst.name if inst.depth == 0 else f"[{inst.name}]"
        p.setFont(theme.font(10, inst.depth == 0))
        p.setPen(theme.TEXT)
        name_w = min(260.0, (r.rect.right() - x) * 0.5)
        p.drawText(QRectF(x, r.rect.top(), name_w, ROW_H), Qt.AlignVCenter | Qt.AlignLeft,
                   p.fontMetrics().elidedText(name, Qt.ElideRight, int(name_w)))
        x += name_w + 10

        p.setFont(theme.font(9))
        p.setPen(theme.TEXT_DIM)
        right = r.rect.right() - 14
        p.drawText(QRectF(x, r.rect.top(), right - x, ROW_H), Qt.AlignVCenter | Qt.AlignLeft,
                   p.fontMetrics().elidedText(inst.summary(), Qt.ElideRight, int(max(0, right - x))))

        # port : couleur de l'état de l'instance
        if r.side == "cible":
            status = self.link_status(inst.ident) if inst.ident in self.links else "orange"
        else:
            linked = [t for t, s in self.links.items() if s == inst.ident]
            status = "orange" if not linked else (
                "vert" if all(self.link_status(t) == "vert" for t in linked) else "orange")
        if not inst.slots:
            status = "vert" if (r.side == "cible" and inst.ident in self.links) or \
                (r.side == "source" and inst.ident in self.links.values()) else "orange"
        port = self._port(r)
        p.setPen(QPen(theme.BG, 2))
        p.setBrush(QBrush(theme.STATUS[status]))
        p.drawEllipse(port, PORT_R, PORT_R)

    # ------------------------------------------------------------------ souris
    def mousePressEvent(self, e):
        pos = e.position()
        r = self._row_at(pos)
        if r is None:
            return
        if e.button() == Qt.RightButton:
            self._context(r, e.globalPosition().toPoint())
            return
        if e.button() != Qt.LeftButton:
            return
        if r.inst.children and pos.x() < r.rect.left() + 28:
            fold = self.collapsed[r.side]
            fold.symmetric_difference_update({r.inst.ident})
            self._relayout()
            return
        if r.side == "source":
            self._drag_from = r
            self._drag_pos = pos

    def mouseMoveEvent(self, e):
        pos = e.position()
        hover = self._row_at(pos)
        if hover is not self._hover:
            self._hover = hover
            self.setCursor(Qt.PointingHandCursor if hover else Qt.ArrowCursor)
        if self._drag_from:
            self._drag_pos = pos
        self.update()

    def mouseReleaseEvent(self, e):
        if self._drag_from:
            r = self._row_at(e.position())
            if r and r.side == "cible":
                self.links[r.inst.ident] = self._drag_from.inst.ident
                self.linksChanged.emit()
        self._drag_from = None
        self._drag_pos = None
        self.update()

    def mouseDoubleClickEvent(self, e):
        r = self._row_at(e.position())
        if r is None:
            return
        if r.side == "cible" and r.inst.ident in self.links:
            self.pairOpened.emit(self.links[r.inst.ident], r.inst.ident)
        elif r.side == "source":
            targets = [t for t, s in self.links.items() if s == r.inst.ident]
            if targets:
                self.pairOpened.emit(r.inst.ident, targets[0])

    def leaveEvent(self, e):
        self._hover = None
        self.update()

    def _context(self, r: _Row, where) -> None:
        menu = QMenu(self)
        if r.side == "cible" and r.inst.ident in self.links:
            menu.addAction("Débrancher", lambda: self._unlink([r.inst.ident]))
        if r.side == "source":
            targets = [t for t, s in self.links.items() if s == r.inst.ident]
            if targets:
                menu.addAction("Débrancher", lambda: self._unlink(targets))
        if not menu.isEmpty():
            menu.exec(where)

    def _unlink(self, targets: list[str]) -> None:
        for t in targets:
            self.links.pop(t, None)
        self.linksChanged.emit()
        self.update()

    # ------------------------------------------------------------------ fichiers glissés
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        urls = e.mimeData().urls()
        if urls and self.fileDropped:
            side = "source" if e.position().x() < self.width() / 2 else "cible"
            self.fileDropped(side, urls[0].toLocalFile())
