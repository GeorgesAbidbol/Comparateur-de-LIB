"""Couleurs et polices : gris sombres façon grandMA3, pastilles Fixture Fix."""

from PySide6.QtGui import QColor, QFont, QPalette

BG = QColor("#1b1b1d")
PANEL = QColor("#242427")
ROW = QColor("#3a3a3f")
ROW_HOVER = QColor("#4a4a50")
ROW_DROP = QColor("#2f4f86")
HEADER = QColor("#2a4b8d")  # bleu de l'en-tête « Fixture Types » MA3
TEXT = QColor("#e6e6e6")
TEXT_DIM = QColor("#9b9ba3")
ACCENT = QColor("#f2c500")  # jaune MA3

STATUS = {
    "vert": QColor("#3fb56b"),
    "orange": QColor("#f08a24"),
    "jaune": QColor("#e8c51c"),
    "bleu": QColor("#3d8ef0"),
}
LEGEND = [
    ("vert", "Identique"),
    ("orange", "Perdu / absent"),
    ("jaune", "Remplacé"),
    ("bleu", "Virtuel"),
]

STYLE = f"""
QWidget {{ background: {BG.name()}; color: {TEXT.name()}; }}
QPushButton {{ background: {ROW.name()}; border: none; border-radius: 6px;
              padding: 8px 16px; font-size: 13px; }}
QPushButton:hover {{ background: {ROW_HOVER.name()}; }}
QComboBox {{ background: {ROW.name()}; border: none; border-radius: 6px;
            padding: 7px 12px; min-width: 220px; font-size: 13px; }}
QComboBox:disabled {{ color: {TEXT_DIM.name()}; }}
QComboBox QAbstractItemView {{ background: {ROW.name()}; selection-background-color: {HEADER.name()}; }}
QScrollArea {{ border: none; }}
QScrollBar:vertical {{ background: {BG.name()}; width: 10px; }}
QScrollBar::handle:vertical {{ background: {ROW_HOVER.name()}; border-radius: 5px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QLabel#dim {{ color: {TEXT_DIM.name()}; }}
QMenu {{ background: {ROW.name()}; padding: 4px; }}
QMenu::item:selected {{ background: {HEADER.name()}; }}
"""


def font(size: int = 10, bold: bool = False) -> QFont:
    f = QFont()
    f.setFamilies(["Segoe UI", "Inter", "Helvetica Neue", "Arial"])
    f.setPointSize(size)
    f.setBold(bold)
    return f


def palette() -> QPalette:
    p = QPalette()
    p.setColor(QPalette.Window, BG)
    p.setColor(QPalette.Base, PANEL)
    p.setColor(QPalette.Text, TEXT)
    p.setColor(QPalette.WindowText, TEXT)
    p.setColor(QPalette.Button, ROW)
    p.setColor(QPalette.ButtonText, TEXT)
    p.setColor(QPalette.Highlight, HEADER)
    return p
