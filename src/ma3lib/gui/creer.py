"""Section « Créer » : un fixture de zéro, en glissant la notice PDF ou en saisissant tout à la main.

Le PDF remplit le tableau (modes, canaux, plages) ; tout reste modifiable. « Créer le fixture »
fabrique le fixture et l'ouvre dans l'atelier, où l'arbre de géométries se retravaille et s'exporte.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QComboBox, QCompleter, QFileDialog,
                               QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QPushButton,
                               QStyledItemDelegate, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from .. import attributs, creation
from ..creation import Canal, Mode, Plage, Projet
from . import theme

COLS = ["Canal", "Fine", "Nom (notice)", "Attribut", "Géométrie", "Copies", "Défaut", "Plages"]
C_ADDR, C_FINE, C_NAME, C_ATTR, C_GEO, C_COPIES, C_DEFAULT, C_RANGES = range(8)
TIPS = {
    C_FINE: "Adresse de l'octet Fine (16 bits). Vide = canal 8 bits.",
    C_ATTR: "Attribut grandMA3. Proposé d'après le nom ; tape pour chercher.",
    C_GEO: "Vide = Yoke pour le Pan, Head pour le reste. Donne un nom (Pixel, Tête…) pour une autre géométrie.",
    C_COPIES: "Nombre d'instances identiques de cette géométrie (pixels, têtes…) : un modèle + N références,"
              " aux adresses qui se suivent. Saisis les canaux de la première seulement.",
    C_DEFAULT: "Valeur DMX par défaut (0 à 255).",
    C_RANGES: "Nombre de plages nommées. Sélectionne le canal pour les voir à droite.",
}

STYLE = f"""
QTableWidget {{ background: {theme.PANEL.name()}; gridline-color: {theme.BG.name()}; border: none;
               selection-background-color: {theme.HEADER.name()}; font-size: 13px; }}
QHeaderView::section {{ background: {theme.BG.name()}; color: {theme.TEXT_DIM.name()}; border: none;
                       padding: 6px 8px; font-size: 12px; }}
QTableCornerButton::section {{ background: {theme.BG.name()}; border: none; }}
QLineEdit {{ background: {theme.ROW.name()}; border: none; border-radius: 6px; padding: 7px 10px; font-size: 13px; }}
QTableWidget QLineEdit {{ border-radius: 0; padding: 0 6px; }}
QPushButton#drop {{ border: 2px dashed {theme.TEXT_DIM.name()}; background: transparent; padding: 14px 22px;
                   font-size: 14px; }}
QPushButton#drop:hover {{ border-color: {theme.ACCENT.name()}; }}
QPushButton#go {{ background: {theme.HEADER.name()}; font-weight: bold; }}
QPushButton:disabled {{ color: {theme.TEXT_DIM.name()}; }}
"""


def attribute_names() -> list[str]:
    """Attributs proposés à la saisie : ceux de la console d'abord, puis le standard GDTF."""
    ma3 = sorted(attributs._table("ma3_attributes.json"))
    std = sorted({attributs.ma3_name(k.replace("(n)", "1").replace("(m)", "1"))
                  for k in attributs._table("gdtf_attributes.json") if "=" not in k})
    return ma3 + [n for n in std if n not in ma3]


class _AttrDelegate(QStyledItemDelegate):
    def createEditor(self, parent, option, index):
        edit = QLineEdit(parent)
        comp = QCompleter(attribute_names(), edit)
        comp.setCaseSensitivity(Qt.CaseInsensitive)
        comp.setFilterMode(Qt.MatchContains)
        edit.setCompleter(comp)
        return edit


class CreerPage(QWidget):
    created = Signal(object)  # FixtureType prêt : l'appli l'ouvre dans l'atelier

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setStyleSheet(STYLE)
        self.projet = Projet()
        self._filling = False

        self.drop = QPushButton("Glisse ici la notice PDF du fabricant  (ou clique pour la choisir)")
        self.drop.setObjectName("drop")
        self.drop.setCursor(Qt.PointingHandCursor)
        self.drop.clicked.connect(self.choose_pdf)
        blank = QPushButton("Partir de zéro")
        blank.setToolTip("Vide tout : un mode, aucun canal, tout à saisir à la main")
        blank.clicked.connect(self.new)
        open_ = QPushButton("Ouvrir un projet…")
        open_.clicked.connect(self.open_project)
        save = QPushButton("Enregistrer le projet…")
        save.setToolTip("Garde la saisie en cours dans un fichier, pour la reprendre plus tard")
        save.clicked.connect(self.save_project)
        top = QHBoxLayout()
        top.setContentsMargins(14, 14, 14, 6)
        top.addWidget(self.drop, 1)
        top.addWidget(blank)
        top.addWidget(open_)
        top.addWidget(save)

        self.maker, self.name, self.short = QLineEdit(), QLineEdit(), QLineEdit()
        self.maker.setPlaceholderText("Fabricant")
        self.name.setPlaceholderText("Nom du fixture")
        self.short.setPlaceholderText("Nom court")
        self.short.setMaximumWidth(200)
        ident = QHBoxLayout()
        ident.setContentsMargins(14, 6, 14, 6)
        for label, w in (("Fabricant", self.maker), ("Nom", self.name), ("Nom court", self.short)):
            lab = QLabel(label)
            lab.setObjectName("dim")
            ident.addWidget(lab)
            ident.addWidget(w, 0 if w is self.short else 1)
            w.textEdited.connect(self._ident_changed)

        self.modes = QComboBox()
        self.modes.currentIndexChanged.connect(self._fill)
        self.count = QLabel()
        self.count.setObjectName("dim")
        bar = QHBoxLayout()
        bar.setContentsMargins(14, 6, 14, 6)
        lab = QLabel("Mode")
        lab.setObjectName("dim")
        bar.addWidget(lab)
        bar.addWidget(self.modes)
        for text, slot in (("+ Mode", self.add_mode), ("Dupliquer", self.duplicate_mode),
                           ("Renommer", self.rename_mode), ("Supprimer", self.delete_mode)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            bar.addWidget(b)
        bar.addSpacing(16)
        bar.addWidget(self.count)
        bar.addStretch(1)

        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        for col, tip in TIPS.items():
            self.table.horizontalHeaderItem(col).setToolTip(tip)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setItemDelegateForColumn(C_ATTR, _AttrDelegate(self.table))
        head = self.table.horizontalHeader()
        head.setSectionResizeMode(QHeaderView.Interactive)
        head.setSectionResizeMode(C_NAME, QHeaderView.Stretch)
        for col, width in ((C_ADDR, 64), (C_FINE, 64), (C_ATTR, 190), (C_GEO, 130), (C_COPIES, 70),
                           (C_DEFAULT, 70), (C_RANGES, 70)):
            self.table.setColumnWidth(col, width)
        self.table.itemChanged.connect(self._cell_changed)
        self.table.itemSelectionChanged.connect(self._show_ranges)
        chan_bar = QHBoxLayout()
        for text, slot, tip in (
                ("+ Canal", self.add_channel, "Ajoute un canal après le dernier"),
                ("Supprimer", self.delete_channels, "Supprime les canaux sélectionnés"),
                ("Deviner les attributs", self.guess, "Repropose l'attribut des canaux sélectionnés d'après leur nom")):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(slot)
            chan_bar.addWidget(b)
        chan_bar.addStretch(1)
        left = QVBoxLayout()
        left.addWidget(self.table, 1)
        left.addLayout(chan_bar)

        self.ranges_title = QLabel("Plages du canal")
        self.ranges_title.setFont(theme.font(10, True))
        self.ranges = QTableWidget(0, 3)
        self.ranges.setHorizontalHeaderLabels(["De", "À", "Nom"])
        self.ranges.verticalHeader().setVisible(False)
        self.ranges.setColumnWidth(0, 56)
        self.ranges.setColumnWidth(1, 56)
        self.ranges.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.ranges.itemChanged.connect(self._range_changed)
        add_r = QPushButton("+ Plage")
        add_r.clicked.connect(self.add_range)
        del_r = QPushButton("Supprimer")
        del_r.clicked.connect(self.delete_ranges)
        r_bar = QHBoxLayout()
        r_bar.addWidget(add_r)
        r_bar.addWidget(del_r)
        r_bar.addStretch(1)
        right_box = QWidget()
        right_box.setFixedWidth(400)
        right = QVBoxLayout(right_box)
        right.setContentsMargins(12, 0, 0, 0)
        right.addWidget(self.ranges_title)
        right.addWidget(self.ranges, 1)
        right.addLayout(r_bar)

        mid = QHBoxLayout()
        mid.setContentsMargins(14, 6, 14, 6)
        mid.addLayout(left, 1)
        mid.addWidget(right_box)

        self.status = QLabel()
        self.status.setObjectName("dim")
        self.status.setWordWrap(True)
        self.go = QPushButton("Créer le fixture  →  Atelier")
        self.go.setObjectName("go")
        self.go.setToolTip("Fabrique le fixture et l'ouvre dans l'atelier (géométries, puis export grandMA3)")
        self.go.clicked.connect(self.build)
        foot = QHBoxLayout()
        foot.setContentsMargins(14, 6, 14, 10)
        foot.addWidget(self.status, 1)
        foot.addWidget(self.go)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addLayout(top)
        lay.addLayout(ident)
        lay.addLayout(bar)
        lay.addLayout(mid, 1)
        lay.addLayout(foot)
        self.new()

    # ------------------------------------------------------------------ projet

    def set_projet(self, projet: Projet, message: str = "") -> None:
        self.projet = projet
        if not projet.modes:
            projet.modes.append(Mode("Mode 1"))
        self.maker.setText(projet.fabricant)
        self.name.setText(projet.nom)
        self.short.setText(projet.court)
        self._reload_modes(0)
        self.status.setText(message)

    def new(self) -> None:
        self.set_projet(Projet(modes=[Mode("Mode 1")]),
                        "Glisse une notice PDF, ou ajoute les canaux à la main avec « + Canal ».")

    def choose_pdf(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Notice du fabricant", "", "PDF (*.pdf)")
        if path:
            self.load_pdf(path)

    def load_pdf(self, path: str) -> None:
        from .. import pdfchart
        self.status.setText(f"Lecture de {Path(path).name}…")
        QApplication.setOverrideCursor(Qt.WaitCursor)
        QApplication.processEvents()
        try:
            projet = pdfchart.lire_pdf(path)
        except pdfchart.PdfError as exc:
            self.status.setText(str(exc))
            return
        except Exception as exc:  # un PDF inattendu ne doit pas fermer l'appli
            self.status.setText(f"{Path(path).name} : lecture impossible ({exc}).")
            return
        finally:
            QApplication.restoreOverrideCursor()
        modes = ", ".join(f"{m.nom} ({m.empreinte})" for m in projet.modes)
        notes = ("   ·   À vérifier : " + " ; ".join(projet.notes)) if projet.notes else ""
        self.set_projet(projet, f"Lu dans {Path(path).name} : {len(projet.modes)} mode(s) : {modes}. "
                                f"Vérifie les attributs proposés, puis crée le fixture.{notes}")

    def open_project(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Ouvrir un projet", "", "Projet Banane Pot (*.bpot.json)")
        if path:
            try:
                self.set_projet(Projet.from_json(Path(path).read_text(encoding="utf-8")), f"Projet ouvert : {path}")
            except Exception as exc:
                self.status.setText(f"Projet illisible : {exc}")

    def save_project(self) -> None:
        name = f"{self.projet.fabricant}@{self.projet.nom}".strip("@") or "fixture"
        path, _ = QFileDialog.getSaveFileName(self, "Enregistrer le projet", f"{name}.bpot.json",
                                              "Projet Banane Pot (*.bpot.json)")
        if path:
            Path(path).write_text(self.projet.to_json(), encoding="utf-8")
            self.status.setText(f"Projet enregistré : {path}")

    def _ident_changed(self) -> None:
        self.projet.fabricant = self.maker.text()
        self.projet.nom = self.name.text()
        self.projet.court = self.short.text()

    def dragEnterEvent(self, event) -> None:
        if any(u.toLocalFile().lower().endswith((".pdf", ".json")) for u in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        for u in event.mimeData().urls():
            path = u.toLocalFile()
            if path.lower().endswith(".pdf"):
                self.load_pdf(path)
                return
            if path.lower().endswith(".json"):
                self.set_projet(Projet.from_json(Path(path).read_text(encoding="utf-8")), f"Projet ouvert : {path}")
                return

    # ------------------------------------------------------------------- modes

    @property
    def mode(self) -> Optional[Mode]:
        i = self.modes.currentIndex()
        return self.projet.modes[i] if 0 <= i < len(self.projet.modes) else None

    def _reload_modes(self, index: int) -> None:
        self.modes.blockSignals(True)
        self.modes.clear()
        self.modes.addItems([m.nom for m in self.projet.modes])
        self.modes.setCurrentIndex(max(0, min(index, len(self.projet.modes) - 1)))
        self.modes.blockSignals(False)
        self._fill()

    def _ask_name(self, title: str, text: str = "") -> str:
        name, ok = QInputDialog.getText(self, title, "Nom du mode :", text=text)
        name = name.strip()
        if ok and name and all(m.nom != name for m in self.projet.modes):
            return name
        if ok and name:
            self.status.setText(f"Il y a déjà un mode « {name} ».")
        return ""

    def add_mode(self, name: str = "") -> None:
        name = name or self._ask_name("Nouveau mode", f"Mode {len(self.projet.modes) + 1}")
        if name:
            self.projet.modes.append(Mode(name))
            self._reload_modes(len(self.projet.modes) - 1)

    def duplicate_mode(self, name: str = "") -> None:
        if self.mode is None:
            return
        name = name or self._ask_name("Dupliquer le mode", f"{self.mode.nom} 2")
        if name:
            self.projet.modes.append(Mode(name, copy.deepcopy(self.mode.canaux)))
            self._reload_modes(len(self.projet.modes) - 1)

    def rename_mode(self, name: str = "") -> None:
        if self.mode is None:
            return
        name = name or self._ask_name("Renommer le mode", self.mode.nom)
        if name:
            self.mode.nom = name
            self._reload_modes(self.modes.currentIndex())

    def delete_mode(self) -> None:
        if self.mode is not None and len(self.projet.modes) > 1:
            del self.projet.modes[self.modes.currentIndex()]
            self._reload_modes(self.modes.currentIndex())
        else:
            self.status.setText("Il faut garder au moins un mode.")

    # ------------------------------------------------------------------ canaux

    def _fill(self) -> None:
        mode = self.mode
        self._filling = True
        self.table.setRowCount(0)
        if mode is not None:
            mode.canaux.sort(key=lambda c: c.adresse)
            self.table.setRowCount(len(mode.canaux))
            for r, c in enumerate(mode.canaux):
                self._fill_row(r, c)
        self._filling = False
        self._count()
        self._show_ranges()

    def _fill_row(self, r: int, c: Canal) -> None:
        values = [str(c.adresse), str(c.fine) if c.fine else "", c.nom, c.attribut, c.geometrie,
                  str(c.copies) if c.copies > 1 else "", str(c.defaut), str(len(c.plages)) if c.plages else ""]
        for col, text in enumerate(values):
            item = QTableWidgetItem(text)
            if col in (C_ADDR, C_FINE, C_COPIES, C_DEFAULT, C_RANGES):
                item.setTextAlignment(Qt.AlignCenter)
            if col == C_RANGES:
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(r, col, item)

    def _count(self) -> None:
        mode = self.mode
        if mode is None or not mode.canaux:
            self.count.setText("aucun canal")
        else:
            self.count.setText(f"{len(mode.canaux)} canaux   ·   {mode.empreinte} adresses DMX")

    def _cell_changed(self, item: QTableWidgetItem) -> None:
        if self._filling or self.mode is None:
            return
        r, col, text = item.row(), item.column(), item.text().strip()
        c = self.mode.canaux[r]

        def number(low: int, high: int, empty: Optional[int] = None) -> Optional[int]:
            if not text and empty is not None:
                return empty
            return int(text) if text.isdigit() and low <= int(text) <= high else None

        if col == C_ADDR and (v := number(1, 512)) is not None:
            c.adresse = v
        elif col == C_FINE and (v := number(1, 512, 0)) is not None:
            c.fine = v or None
        elif col == C_NAME:
            c.nom = text
            if not c.attribut:
                creation.attribuer(self.mode)
        elif col == C_ATTR:
            c.attribut = text
        elif col == C_GEO:
            c.geometrie = text
            if not text:
                c.copies = 1
            else:  # rejoint une géométrie déjà multipliée : même nombre de copies
                c.copies = max([o.copies for o in self.mode.canaux if o is not c and o.geometrie == text] + [1])
        elif col == C_COPIES and (v := number(1, 512, 1)) is not None:
            if c.geometrie:
                for o in self.mode.canaux:
                    if o.geometrie == c.geometrie:
                        o.copies = v
            elif v > 1:
                self.status.setText("Donne d'abord un nom de géométrie (ex. Pixel) aux canaux à multiplier.")
        elif col == C_DEFAULT and (v := number(0, 255)) is not None:
            c.defaut = v
        self._filling = True
        for row, canal in enumerate(self.mode.canaux):  # réaffiche (valeur refusée, copies partagées…)
            self._fill_row(row, canal)
        self._filling = False
        self._count()

    def _selected_rows(self) -> list[int]:
        return sorted({i.row() for i in self.table.selectedIndexes()})

    def add_channel(self) -> None:
        if self.mode is None:
            return
        self.mode.canaux.append(Canal(self.mode.empreinte + 1))
        self._fill()
        row = len(self.mode.canaux) - 1
        self.table.setCurrentCell(row, C_NAME)
        self.table.editItem(self.table.item(row, C_NAME))

    def delete_channels(self) -> None:
        if self.mode is None:
            return
        for r in reversed(self._selected_rows()):
            del self.mode.canaux[r]
        self._fill()

    def guess(self) -> None:
        if self.mode is None:
            return
        rows = self._selected_rows() or list(range(len(self.mode.canaux)))
        for r in rows:
            self.mode.canaux[r].attribut = ""
        creation.attribuer(self.mode)
        self._fill()

    # ------------------------------------------------------------------ plages

    def _current(self) -> Optional[Canal]:
        rows = self._selected_rows()
        return self.mode.canaux[rows[0]] if self.mode is not None and len(rows) == 1 else None

    def _show_ranges(self) -> None:
        c = self._current()
        self._filling = True
        self.ranges.setRowCount(0)
        self.ranges_title.setText(f"Plages du canal {c.adresse} : {c.nom or c.attribut}" if c else "Plages du canal")
        if c is not None:
            self.ranges.setRowCount(len(c.plages))
            for r, p in enumerate(c.plages):
                for col, text in enumerate((str(p.debut), str(p.fin), p.nom)):
                    item = QTableWidgetItem(text)
                    if col < 2:
                        item.setTextAlignment(Qt.AlignCenter)
                    self.ranges.setItem(r, col, item)
        self._filling = False

    def _range_changed(self, item: QTableWidgetItem) -> None:
        c = self._current()
        if self._filling or c is None:
            return
        p, text = c.plages[item.row()], item.text().strip()
        if item.column() == 2:
            p.nom = text
        elif text.isdigit() and int(text) <= 255:
            if item.column() == 0:
                p.debut = int(text)
            else:
                p.fin = int(text)
        else:
            self._show_ranges()

    def add_range(self) -> None:
        c = self._current()
        if c is None:
            self.status.setText("Sélectionne d'abord un canal.")
            return
        start = min(255, max((p.fin for p in c.plages), default=-1) + 1)
        c.plages.append(Plage(start, 255, ""))
        self._refresh_range_count()
        self._show_ranges()
        self.ranges.editItem(self.ranges.item(len(c.plages) - 1, 2))

    def delete_ranges(self) -> None:
        c = self._current()
        if c is None:
            return
        for r in sorted({i.row() for i in self.ranges.selectedIndexes()}, reverse=True):
            del c.plages[r]
        self._refresh_range_count()
        self._show_ranges()

    def _refresh_range_count(self) -> None:
        rows = self._selected_rows()
        if rows:
            c = self.mode.canaux[rows[0]]
            self._filling = True
            self.table.item(rows[0], C_RANGES).setText(str(len(c.plages)) if c.plages else "")
            self._filling = False

    # ---------------------------------------------------------------- création

    def build(self) -> None:
        self._ident_changed()
        try:
            ft = creation.construire(self.projet)
        except creation.CreationError as exc:
            problems = str(exc).splitlines()
            more = f"   (+ {len(problems) - 3} autres)" if len(problems) > 3 else ""
            self.status.setText("À corriger avant de créer :  " + "   ·   ".join(problems[:3]) + more)
            self._fill()
            return
        self._fill()
        self.status.setText(f"Fixture créé : {ft.manufacturer} {ft.name}, {len(ft.modes)} mode(s). Ouvert dans l'atelier.")
        self.created.emit(ft)
