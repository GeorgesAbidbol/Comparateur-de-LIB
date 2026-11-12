"""Section « GDTF Share » : se connecter à son compte, puis parcourir la banque comme dans
l'explorateur de fichiers (Jo, 11/11/2026) : les fabricants à gauche comme des dossiers, leurs
fixtures à droite, uniquement les fichiers envoyés par les fabricants. Le fixture choisi est
téléchargé et ouvert dans l'atelier ou le comparateur.

Le compte peut être retenu dans le coffre de Windows (case « Rester connecté », voir
`ma3lib.coffre`) : jamais dans un fichier de l'appli.
Les fichiers téléchargés vont dans Documents/Banane Pot/GDTF Share.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QApplication, QCheckBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMenu, QPushButton, QVBoxLayout, QWidget)

from .. import APP_NAME, coffre, gdtf_share
from . import theme

STYLE = f"""
QLineEdit {{ background: {theme.ROW.name()}; border: none; border-radius: 6px; padding: 8px 12px;
            font-size: 13px; }}
QLineEdit:disabled {{ color: {theme.TEXT_DIM.name()}; }}
QListWidget {{ background: {theme.PANEL.name()}; border: none; border-radius: 10px; padding: 6px;
              font-size: 13px; outline: none; }}
QListWidget::item {{ padding: 8px 10px; border-radius: 6px; }}
QListWidget::item:hover {{ background: {theme.ROW.name()}; }}
QListWidget::item:selected {{ background: {theme.HEADER.name()}; color: {theme.TEXT.name()}; }}
QPushButton:disabled {{ color: {theme.TEXT_DIM.name()}; }}
"""


def download_dir() -> Path:
    return Path.home() / "Documents" / APP_NAME / "GDTF Share"


class SharePage(QWidget):
    openAsked = Signal(str)          # chemin du GDTF téléchargé, à ouvrir dans l'atelier
    compareAsked = Signal(str, str)  # côté (« source » / « cible »), chemin

    def __init__(self, client_factory=gdtf_share.GdtfShareClient, folder: Optional[Path] = None,
                 vault=None):
        super().__init__()
        self.vault = vault  # coffre des identifiants (None = celui du système)
        self._tried_saved = False
        self.setStyleSheet(STYLE)
        self._factory = client_factory
        self.folder = folder
        self.client = None
        self.entries: list[gdtf_share.ShareEntry] = []

        self.user = QLineEdit()
        self.user.setPlaceholderText("E-mail du compte GDTF Share")
        self.password = QLineEdit()
        self.password.setPlaceholderText("Mot de passe")
        self.password.setEchoMode(QLineEdit.Password)
        self.password.returnPressed.connect(lambda: self.connect_account())
        self.remember = QCheckBox("Rester connecté")
        self.remember.setChecked(True)
        self.remember.setToolTip("Garde le compte dans le coffre de Windows (Gestionnaire "
                                 "d'identifiants), chiffré par Windows. Jamais dans un fichier de l'appli.")
        self.remember.setVisible(coffre.available(vault))
        self.login = QPushButton("Se connecter")
        self.login.setFont(theme.font(10, True))
        self.login.clicked.connect(lambda: self.disconnect_account() if self.client else self.connect_account())
        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(self.user, 2)
        top.addWidget(self.password, 1)
        top.addWidget(self.remember)
        top.addWidget(self.login)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Filtrer : fabricant, nom du projecteur…")
        self.search.setEnabled(False)
        self.search.textChanged.connect(lambda _: self.refresh())
        self.makers = QListWidget()  # les « dossiers »
        self.makers.setFixedWidth(300)
        self.makers.currentItemChanged.connect(lambda *_: self._show_fixtures())
        self.results = QListWidget()
        self.results.itemSelectionChanged.connect(self._selection_changed)
        self.results.itemDoubleClicked.connect(lambda _: self.open_in_atelier())
        browser = QHBoxLayout()
        browser.setSpacing(10)
        browser.addWidget(self.makers)
        browser.addWidget(self.results, 1)

        self.status = QLabel("Connecte ton compte pour chercher dans GDTF Share.")
        self.status.setObjectName("dim")
        self.to_atelier = QPushButton("Ouvrir dans l'atelier")
        self.to_atelier.clicked.connect(lambda: self.open_in_atelier())
        self.to_compare = QPushButton("Comparer")
        menu = QMenu(self.to_compare)
        menu.addAction("comme source", lambda: self.send_to_compare("source"))
        menu.addAction("comme cible", lambda: self.send_to_compare("cible"))
        self.to_compare.setMenu(menu)
        for b in (self.to_atelier, self.to_compare):
            b.setEnabled(False)
        foot = QHBoxLayout()
        foot.addWidget(self.status, 1)
        foot.addWidget(self.to_atelier)
        foot.addWidget(self.to_compare)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 14, 14, 10)
        lay.setSpacing(10)
        lay.addLayout(top)
        lay.addWidget(self.search)
        lay.addLayout(browser, 1)
        lay.addLayout(foot)

    # ------------------------------------------------------------------
    def _busy(self, text: str) -> None:
        self.status.setText(text)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        QApplication.processEvents()

    def connect_account(self) -> bool:
        """Connexion puis liste complète des fixtures (une seule fois par session)."""
        user, password = self.user.text().strip(), self.password.text()
        if not user or not password:
            self.status.setText("Il faut l'e-mail et le mot de passe du compte GDTF Share.")
            return False
        self._busy("Connexion à GDTF Share…")
        try:
            client = self._factory(user, password)
            client.login()
            self.status.setText("Connecté. Chargement de la liste des fixtures…")
            QApplication.processEvents()
            self.entries = client.list()
        except gdtf_share.ShareError as exc:
            self.status.setText(f"Impossible : {exc}")
            return False
        except Exception as exc:  # pas de réseau, pare-feu…
            self.status.setText(f"GDTF Share injoignable : {type(exc).__name__}")
            return False
        finally:
            QApplication.restoreOverrideCursor()
        self.client = client
        if self.remember.isChecked():
            coffre.save(user, password, self.vault)
        else:
            coffre.forget(self.vault)
        self.password.clear()  # plus besoin : la session garde la connexion
        self.password.setPlaceholderText("connecté")
        for w in (self.user, self.password, self.remember):
            w.setEnabled(False)
        self.login.setText("Se déconnecter")
        self.search.setEnabled(True)
        self.search.setFocus()
        self.refresh()
        return True

    def disconnect_account(self) -> None:
        """Oublie la connexion et le compte retenu dans le coffre."""
        coffre.forget(self.vault)
        self.client, self.entries = None, []
        for w in (self.user, self.password, self.remember):
            w.setEnabled(True)
        self.password.setPlaceholderText("Mot de passe")
        self.login.setText("Se connecter")
        self.search.clear()
        self.search.setEnabled(False)
        self.makers.clear()
        self.results.clear()
        self._selection_changed()
        self.status.setText("Déconnecté. Le compte n'est plus retenu.")

    def showEvent(self, e):
        """Première ouverture de la section : reconnexion avec le compte retenu."""
        super().showEvent(e)
        if self._tried_saved or self.client is not None:
            return
        self._tried_saved = True
        saved = coffre.load(self.vault)
        if saved:
            self.user.setText(saved[0])
            self.password.setText(saved[1])
            self.connect_account()

    def refresh(self) -> None:
        """Dossiers des fabricants (fichiers officiels seulement), filtrés par la recherche."""
        self.found = gdtf_share.latest(gdtf_share.search(gdtf_share.official(self.entries), self.search.text()))
        keep = self.makers.currentItem().data(Qt.UserRole) if self.makers.currentItem() else None
        counts: dict[str, int] = {}
        for e in self.found:
            counts[e.manufacturer] = counts.get(e.manufacturer, 0) + 1
        self.makers.blockSignals(True)
        self.makers.clear()
        for maker in sorted(counts, key=str.lower):
            item = QListWidgetItem(f"{maker}   ({counts[maker]})")
            item.setData(Qt.UserRole, maker)
            self.makers.addItem(item)
            if maker == keep:
                self.makers.setCurrentItem(item)
        if self.makers.currentItem() is None and self.makers.count():
            self.makers.setCurrentRow(0)
        self.makers.blockSignals(False)
        self._show_fixtures()

    def _show_fixtures(self) -> None:
        item = self.makers.currentItem()
        maker = item.data(Qt.UserRole) if item else None
        self.results.clear()
        for e in getattr(self, "found", []):
            if e.manufacturer != maker:
                continue
            modes = f"{len(e.modes)} mode{'s' if len(e.modes) > 1 else ''}"
            row = QListWidgetItem(f"{e.fixture}     ·  {e.revision or 'sans révision'}  ·  {modes}")
            row.setData(Qt.UserRole, e)
            row.setToolTip("\n".join(e.modes))
            self.results.addItem(row)
        total = len(getattr(self, "found", []))
        self.status.setText(f"{self.makers.count()} fabricant(s), {total} fixture(s) officiel(s)"
                            if total else "Aucun fixture ne correspond.")
        self._selection_changed()

    def _selection_changed(self) -> None:
        on = self.results.currentItem() is not None and bool(self.results.selectedItems())
        for b in (self.to_atelier, self.to_compare):
            b.setEnabled(on)

    def download(self) -> Optional[Path]:
        item = self.results.currentItem()
        if item is None or self.client is None:
            return None
        entry = item.data(Qt.UserRole)
        self._busy(f"Téléchargement de {entry.fixture}…")
        try:
            path = self.client.download(entry, self.folder or download_dir())
        except gdtf_share.ShareError as exc:
            self.status.setText(f"Impossible : {exc}")
            return None
        except Exception as exc:
            self.status.setText(f"GDTF Share injoignable : {type(exc).__name__}")
            return None
        finally:
            QApplication.restoreOverrideCursor()
        self.status.setText(f"Téléchargé : {path}")
        return path

    def open_in_atelier(self) -> None:
        path = self.download()
        if path:
            self.openAsked.emit(str(path))

    def send_to_compare(self, side: str) -> None:
        path = self.download()
        if path:
            self.compareAsked.emit(side, str(path))
