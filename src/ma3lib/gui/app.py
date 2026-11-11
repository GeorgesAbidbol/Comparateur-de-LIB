"""L'appli : une seule fenêtre, une section par outil (Jo, 11/11/2026 : « tout en une seule
plateforme, pas un comparateur séparé de l'atelier, séparé du constructeur de lib… »).

Chaque section est une page de la même fenêtre ; les prochains outils (créer un fixture,
GDTF Share) viendront s'ajouter ici comme sections, pas comme programmes à part.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QApplication, QButtonGroup, QHBoxLayout, QLabel, QMainWindow,
                               QPushButton, QStackedWidget, QVBoxLayout, QWidget)

from .. import APP_NAME, __version__
from . import theme
from .atelier import AtelierWindow
from .creer import CreerPage
from .share import SharePage
from .window import MainWindow

NAV_STYLE = f"""
QPushButton#nav {{ background: transparent; border: none; border-radius: 0; padding: 10px 18px;
                  color: {theme.TEXT_DIM.name()}; font-size: 14px;
                  border-bottom: 3px solid transparent; }}
QPushButton#nav:hover {{ color: {theme.TEXT.name()}; }}
QPushButton#nav:checked {{ color: {theme.TEXT.name()}; border-bottom: 3px solid {theme.ACCENT.name()}; }}
QWidget#navbar {{ background: {theme.PANEL.name()}; }}
QWidget#navbar QLabel {{ background: transparent; }}
"""


class AppWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{__version__}")
        self.resize(1360, 880)
        self.atelier = AtelierWindow()
        self.comparateur = MainWindow()
        self.atelier.compareAsked.connect(self.compare)
        self.creer = CreerPage()
        self.creer.created.connect(self.open_created)
        self.share = SharePage()
        self.atelier.shareAsked.connect(lambda: self.show_section("GDTF Share"))
        self.share.openAsked.connect(self.open_downloaded)
        self.share.compareAsked.connect(self.compare_downloaded)
        self.sections = [("Atelier", self.atelier), ("Comparateur", self.comparateur), ("Créer", self.creer),
                         ("GDTF Share", self.share)]

        self.stack = QStackedWidget()
        navbar = QWidget()
        navbar.setObjectName("navbar")
        nav = QHBoxLayout(navbar)
        nav.setContentsMargins(16, 0, 16, 0)
        nav.setSpacing(4)
        name = QLabel(APP_NAME)
        name.setFont(theme.font(11, True))
        nav.addWidget(name)
        nav.addSpacing(28)
        self.buttons = QButtonGroup(self)
        for i, (label, page) in enumerate(self.sections):
            page.setWindowFlags(Qt.Widget)  # une page de la fenêtre, plus une fenêtre à part
            self.stack.addWidget(page)
            b = QPushButton(label)
            b.setObjectName("nav")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            self.buttons.addButton(b, i)
            nav.addWidget(b)
        nav.addStretch(1)
        version = QLabel(f"v{__version__}")
        version.setObjectName("dim")
        version.setFont(theme.font(9))
        nav.addWidget(version)
        self.buttons.idClicked.connect(self.stack.setCurrentIndex)
        self.buttons.button(0).setChecked(True)

        central = QWidget()
        lay = QVBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(navbar)
        lay.addWidget(self.stack, 1)
        self.setCentralWidget(central)
        self.setStyleSheet(NAV_STYLE)

    def compare(self, side: str) -> None:
        """Le fixture de l'atelier (modifications comprises) part dans le comparateur."""
        if self.atelier.ft is None:
            return
        self.comparateur.set_fixture(side, self.atelier.ft, self.atelier.modes.currentText(),
                                     "depuis l'atelier")
        self.show_section("Comparateur")

    def open_created(self, ft) -> None:
        """Le fixture fabriqué dans « Créer » s'ouvre dans l'atelier (géométries, export)."""
        self.atelier.set_fixture(ft)
        self.show_section("Atelier")

    def open_downloaded(self, path: str) -> None:
        """Un GDTF pris sur GDTF Share s'ouvre dans l'atelier."""
        self.atelier.load(path)
        self.show_section("Atelier")

    def compare_downloaded(self, side: str, path: str) -> None:
        self.comparateur.load(side, path)
        self.show_section("Comparateur")

    def show_section(self, label: str) -> None:
        for i, (name, _) in enumerate(self.sections):
            if name == label:
                self.buttons.button(i).setChecked(True)
                self.stack.setCurrentIndex(i)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setStyle("Fusion")
    app.setPalette(theme.palette())
    app.setStyleSheet(theme.STYLE)
    app.setFont(theme.font(10))
    icon = Path(__file__).resolve().parent.parent / "data" / "banane-pot.ico"
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))
    win = AppWindow()
    if argv and argv[0] == "--selftest":  # contrôle de l'exe à la fabrication : la fenêtre se construit
        win.show()
        app.processEvents()
        win.close()
        return 0
    if argv and argv[0].lower().endswith(".pdf"):  # une notice glissée sur le lanceur : section « Créer »
        win.show_section("Créer")
        win.creer.load_pdf(argv[0])
    elif argv:  # un fixture glissé sur le lanceur s'ouvre dans l'atelier
        win.atelier.load(argv[0], argv[1] if len(argv) > 1 else "")
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
