"""Vue attributs d'une liaison : source à gauche, cible à droite, une ligne par attribut.
Les attributs identiques sont en face (vert), les autres restent seuls (orange)."""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from .. import compare
from ..compare import Instance, Row, Slot
from . import theme

ROW_H = 46
GAP = 6
MID = 60
MARGIN = 14


class _Rows(QWidget):
    def __init__(self, rows: list[Row], parent=None):
        super().__init__(parent)
        self.rows = rows
        self.setMinimumHeight(MARGIN * 2 + len(rows) * (ROW_H + GAP))

    def sizeHint(self) -> QSize:
        return QSize(900, self.minimumHeight())

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), theme.BG)
        w = (self.width() - 2 * MARGIN - MID) / 2
        for i, row in enumerate(self.rows):
            y = MARGIN + i * (ROW_H + GAP)
            left = QRectF(MARGIN, y, w, ROW_H)
            right = QRectF(MARGIN + w + MID, y, w, ROW_H)
            color = theme.STATUS[row.status]
            if row.source:
                self._slot(p, left, row.source, row.status)
            if row.target:
                self._slot(p, right, row.target, row.status)
            if row.source and row.target and row.status != "orange":
                p.setPen(QPen(color, 2))
                p.drawLine(left.right() + 4, left.center().y(), right.left() - 4, right.center().y())

    def _slot(self, p: QPainter, r: QRectF, slot: Slot, status: str) -> None:
        p.setPen(Qt.NoPen)
        p.setBrush(theme.ROW)
        p.drawRoundedRect(r, 6, 6)
        # pastille numérotée (canal coarse), couleur de l'état
        dot = QRectF(r.left() + 10, r.center().y() - 13, 26, 26)
        p.setBrush(theme.STATUS[status])
        p.drawEllipse(dot)
        p.setPen(theme.BG)
        p.setFont(theme.font(8, True))
        p.drawText(dot, Qt.AlignCenter, "V" if slot.virtual else str(slot.coarse))

        x = dot.right() + 12
        p.setPen(theme.TEXT)
        p.setFont(theme.font(10, True))
        p.drawText(QRectF(x, r.top() + 5, r.width() * 0.55, 20), Qt.AlignLeft | Qt.AlignVCenter, slot.short)
        p.setPen(theme.TEXT_DIM)
        p.setFont(theme.font(8))
        feature = slot.feature.split(".")[0].upper() if slot.feature else "?"
        p.drawText(QRectF(x, r.top() + 23, r.width() * 0.6, 18), Qt.AlignLeft | Qt.AlignVCenter,
                   f"{feature} - {slot.attribute.upper()}")
        if slot.virtual:
            dmx = "Virtuel"
        else:
            dmx = f"Coarse: {slot.coarse}" + (f"  |  Fine: {slot.fine}" if slot.fine else "")
        p.setFont(theme.font(9))
        p.drawText(QRectF(r.left(), r.top(), r.width() - 12, ROW_H), Qt.AlignRight | Qt.AlignVCenter, dmx)


def side_by_side(rows: list[Row]) -> list[Row]:
    """Les orange seuls de chaque côté se partagent les mêmes lignes (sans trait entre eux)."""
    linked = [r for r in rows if r.source and r.target]
    lost = [r.source for r in rows if r.target is None]
    absent = [r.target for r in rows if r.source is None]
    n = max(len(lost), len(absent))
    lone = [Row(lost[i] if i < len(lost) else None, absent[i] if i < len(absent) else None, "orange")
            for i in range(n)]
    return linked + lone


class PairDialog(QDialog):
    def __init__(self, source: Instance, target: Instance, source_title: str, target_title: str,
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{source.ident} {source.name}  →  {target.ident} {target.name}")
        self.resize(980, 640)
        rows = compare.pair_rows(source, target)
        counts = {s: sum(r.status == s for r in rows) for s, _ in theme.LEGEND}
        rows = side_by_side(rows)

        head = QHBoxLayout()
        for title, inst in ((source_title, source), (target_title, target)):
            lab = QLabel(f"<b>{title}</b><br><span style='color:{theme.TEXT_DIM.name()}'>"
                         f"Instance {inst.ident} : {inst.name}</span>")
            lab.setFont(theme.font(10))
            head.addWidget(lab, 1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(_Rows(rows))

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 12)
        lay.addLayout(head)
        lay.addWidget(scroll, 1)
        lay.addWidget(legend(counts)[0])


def legend(counts: dict[str, int] | None = None) -> tuple[QWidget, QLabel]:
    """Ligne de légende des couleurs ; renvoie aussi le libellé de droite (compteur)."""
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(14, 4, 14, 4)
    lay.setSpacing(18)
    for status, label in theme.LEGEND:
        n = f" ({counts[status]})" if counts is not None else ""
        lab = QLabel(f"<span style='color:{theme.STATUS[status].name()}; font-size:16px'>●</span> {label}{n}")
        lab.setFont(theme.font(9))
        lay.addWidget(lab)
    lay.addStretch(1)
    extra = QLabel("")
    extra.setObjectName("dim")
    extra.setFont(theme.font(9))
    lay.addWidget(extra)
    return w, extra
