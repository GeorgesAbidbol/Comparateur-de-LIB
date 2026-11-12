"""Fenêtre « Exporter pour grandMA3 » : nom, note, GUID, destination (onPC, clé USB, dossier)."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
                               QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QRadioButton, QWidget)

from .. import ma3_paths, ma3xml
from ..gdtf import FixtureType
from . import theme

OTHER = "Choisir un dossier…"


class ExportDialog(QDialog):
    def __init__(self, ft: FixtureType, parent=None, targets: Optional[list[ma3_paths.Target]] = None,
                 folder: Optional[Path] = None):
        super().__init__(parent)
        self.ft = ft
        self.written: Optional[Path] = None
        self.setWindowTitle("Exporter pour grandMA3 2.3.2.0")
        self.setMinimumWidth(560)
        form = QFormLayout(self)
        form.setContentsMargins(20, 18, 20, 14)
        form.setVerticalSpacing(12)
        form.setHorizontalSpacing(16)

        node = ft.xml_root.find("FixtureType") if ft.xml_root is not None else None
        self.name = QLineEdit(ft.name)
        self.name.textChanged.connect(self._name_changed)
        form.addRow("Nom", self.name)
        self.note = QLineEdit(node.get("Note", "") if node is not None else "")
        self.note.setPlaceholderText("ex. JO")
        form.addRow("Note", self.note)

        self.keep = QRadioButton("garder celui d'origine")
        self.renew = QRadioButton("nouveau (fixture distinct)")
        self.keep.setChecked(True)
        group = QButtonGroup(self)
        group.addButton(self.keep)
        group.addButton(self.renew)
        guid = QWidget()
        row = QHBoxLayout(guid)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.keep)
        row.addSpacing(12)
        row.addWidget(self.renew)
        row.addStretch(1)
        self.renew.toggled.connect(self._update_file)
        form.addRow("GUID", guid)

        self.dest = QComboBox()
        self.targets = ma3_paths.find_targets() if targets is None else targets
        for t in self.targets:
            self.dest.addItem(t.label, str(t.fixture_dir))
        if folder is not None:
            self.dest.addItem(str(folder), str(folder))
        elif ft.source is not None:
            self.dest.addItem(f"À côté de l'original ({ft.source.parent})", str(ft.source.parent))
        self.dest.addItem(OTHER, "")
        self.dest.activated.connect(self._dest_chosen)
        self.dest.currentIndexChanged.connect(self._update_file)
        form.addRow("Destination", self.dest)

        self.file = QLabel()
        self.file.setObjectName("dim")
        self.file.setTextInteractionFlags(Qt.TextSelectableByMouse)
        form.addRow("Fichier", self.file)
        hint = QLabel("Format XML MA3 2.3.2.0, comme un export « User » de la console.")
        hint.setObjectName("dim")
        hint.setFont(theme.font(9))
        form.addRow("", hint)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Exporter")
        buttons.button(QDialogButtonBox.Cancel).setText("Annuler")
        buttons.accepted.connect(self.export)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.setStyleSheet(f"QLineEdit {{ background: {theme.ROW.name()}; border: none;"
                           f" border-radius: 6px; padding: 7px 10px; }}"
                           f"QRadioButton::indicator {{ width: 12px; height: 12px; border-radius: 7px;"
                           f" border: 2px solid {theme.TEXT_DIM.name()}; }}"
                           f"QRadioButton::indicator:checked {{ background: {theme.ACCENT.name()};"
                           f" border-color: {theme.ACCENT.name()}; }}")
        self._update_file()

    # ------------------------------------------------------------------
    def _name_changed(self) -> None:
        # un autre nom = un autre fixture type : la console ne doit pas le confondre avec l'original
        if self.name.text().strip() != self.ft.name:
            self.renew.setChecked(True)
        self._update_file()

    def _dest_chosen(self, index: int) -> None:
        if self.dest.itemData(index):
            return
        path = QFileDialog.getExistingDirectory(self, "Dossier de destination")
        if path:
            self.dest.insertItem(index, path, path)
            self.dest.setCurrentIndex(index)
        else:
            self.dest.setCurrentIndex(0 if index else -1)

    def folder(self) -> Optional[Path]:
        data = self.dest.currentData()
        return Path(data) if data else None

    def path(self) -> Optional[Path]:
        folder = self.folder()
        if folder is None:
            return None
        return folder / ma3xml.file_name(self.ft.manufacturer, self.name.text().strip() or self.ft.name)

    def _update_file(self) -> None:
        p = self.path()
        self.file.setText(p.name if p else "choisis un dossier")
        self.file.setToolTip(str(p) if p else "")

    def options(self) -> dict:
        name = self.name.text().strip() or self.ft.name
        return {"name": name, "guid": ma3xml.new_guid() if self.renew.isChecked() else None,
                "note": self.note.text().strip()}

    def export(self) -> None:
        folder, dest = self.folder(), self.path()
        if folder is None or dest is None:
            QMessageBox.information(self, "Destination", "Choisis d'abord un dossier.")
            return
        overwrite = False
        if dest.exists():
            ok = QMessageBox.question(self, "Remplacer ?", f"{dest.name} existe déjà dans\n{folder}\n\nLe remplacer ?")
            if ok != QMessageBox.Yes:
                return
            overwrite = True
        opts = self.options()
        try:
            self.written = ma3xml.export(self.ft, folder, name=opts["name"], guid=opts["guid"],
                                         note=opts["note"], overwrite=overwrite)
        except (OSError, ma3xml.ExportError) as exc:
            QMessageBox.warning(self, "Export impossible", str(exc))
            return
        self.accept()
