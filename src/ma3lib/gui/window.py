"""Fenêtre principale : barre légère (Source / Cible + mode), vue instances, légende."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QComboBox, QFileDialog, QHBoxLayout, QMainWindow,
                               QMessageBox, QPushButton, QScrollArea, QVBoxLayout, QWidget)

from .. import __version__, compare, gdtf
from ..gdtf import FixtureType
from . import theme
from .canvas import LinkCanvas
from .pair import PairDialog, legend

FILTER = "Fixture types (*.gdtf *.xml);;Tous les fichiers (*)"


class _Side:
    def __init__(self, side: str, label: str):
        self.side = side
        self.label = label
        self.ft: Optional[FixtureType] = None
        self.button = QPushButton(f"{label} : ouvrir…")
        self.button.setFont(theme.font(10, True))
        self.button.setCursor(Qt.PointingHandCursor)
        self.modes = QComboBox()
        self.modes.setEnabled(False)

    def title(self) -> str:
        if not self.ft:
            return self.label
        return f"{self.ft.manufacturer} - {self.ft.name}  ·  {self.modes.currentText()}"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Comparateur de LIB v{__version__}")
        self.resize(1280, 820)

        self.sides = {"source": _Side("source", "Source"), "cible": _Side("cible", "Cible")}
        self.canvas = LinkCanvas()
        self.canvas.fileDropped = self.load
        self.canvas.pairOpened.connect(self.open_pair)
        self.canvas.linksChanged.connect(self._update_footer)

        bar = QHBoxLayout()
        bar.setContentsMargins(14, 12, 14, 6)
        bar.setSpacing(8)
        for i, side in enumerate(self.sides.values()):
            side.button.clicked.connect(lambda _=False, s=side.side: self.choose(s))
            side.modes.currentIndexChanged.connect(lambda _=0, s=side.side: self._mode_changed(s))
            bar.addWidget(side.button)
            bar.addWidget(side.modes)
            bar.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.canvas)

        self._legend, self._count = legend()

        central = QWidget()
        lay = QVBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 8)
        lay.setSpacing(0)
        lay.addLayout(bar)
        lay.addWidget(scroll, 1)
        lay.addWidget(self._legend)
        self.setCentralWidget(central)
        self._update_footer()

    # ------------------------------------------------------------------ chargement
    def choose(self, side: str) -> None:
        path, _ = QFileDialog.getOpenFileName(self, f"Ouvrir la {side}", "", FILTER)
        if path:
            self.load(side, path)

    def load(self, side: str, path: str, mode: str = "") -> None:
        try:
            ft = gdtf.load(path)
        except (gdtf.GdtfError, OSError) as exc:
            QMessageBox.warning(self, "Fichier illisible", str(exc))
            return
        s = self.sides[side]
        s.ft = ft
        s.button.setText(f"{ft.manufacturer} - {ft.name}")
        s.button.setToolTip(str(Path(path)))
        s.modes.blockSignals(True)
        s.modes.clear()
        s.modes.addItems([m.name for m in ft.modes])
        if mode and ft.mode(mode):
            s.modes.setCurrentText(mode)
        s.modes.setEnabled(bool(ft.modes))
        s.modes.blockSignals(False)
        self._mode_changed(side)

    def _mode_changed(self, side: str) -> None:
        s = self.sides[side]
        mode = s.ft.mode(s.modes.currentText()) if s.ft else None
        self.canvas.set_root(side, compare.instances(s.ft, mode) if mode else None)

    # ------------------------------------------------------------------ vues
    def open_pair(self, source_ident: str, target_ident: str) -> None:
        src = self.canvas.instance("source", source_ident)
        tgt = self.canvas.instance("cible", target_ident)
        if src and tgt:
            PairDialog(src, tgt, self.sides["source"].title(), self.sides["cible"].title(), self).exec()

    def _update_footer(self) -> None:
        linked, total = self.canvas.counts()
        self._count.setText(f"{linked} / {total} instances cible branchées" if total else "")


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setStyle("Fusion")
    app.setPalette(theme.palette())
    app.setStyleSheet(theme.STYLE)
    app.setFont(theme.font(10))
    win = MainWindow()
    # ma3lib-gui [source [cible]] : pratique pour ouvrir directement deux fichiers
    for side, path in zip(("source", "cible"), argv):
        win.load(side, path)
    win.show()
    return app.exec()
