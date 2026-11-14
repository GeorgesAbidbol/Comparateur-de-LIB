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


def _png(width: int, height: int, pixels) -> bytes:
    """PNG RGBA minimal (sans Qt : le style est construit avant l'application)."""
    import struct
    import zlib

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    raw = b"".join(b"\0" + bytes(c for x in range(width) for c in pixels(x, y)) for y in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def _arrow_files() -> dict[str, str]:
    """Petits triangles des flèches haut/bas des cases à chiffres (Qt ne les dessine plus dès
    qu'on stylise la case). Écrits une fois dans le dossier temporaire."""
    import os
    import tempfile
    folder = os.path.join(tempfile.gettempdir(), "banane-pot-ui")
    os.makedirs(folder, exist_ok=True)
    w, h = 20, 12  # dessinés en double taille, affichés en 10x6
    out = {}
    for name, color in (("", TEXT), ("_off", TEXT_DIM)):
        rgb = (color.red(), color.green(), color.blue())
        for way in ("up", "down"):
            def px(x, y, way=way):
                row = (h - 1 - y) if way == "up" else y  # 0 = côté large
                half = (w / 2) * (1 - row / h)
                inside = abs(x + 0.5 - w / 2) <= half
                return (*rgb, 255 if inside else 0)
            path = os.path.join(folder, f"{way}{name}.png")
            try:
                with open(path, "wb") as f:
                    f.write(_png(w, h, px))
            except OSError:
                pass
            out[way + name] = path.replace("\\", "/")
    return out


_ARROWS = _arrow_files()

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
QAbstractSpinBox {{ padding-right: 24px; }}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{
    subcontrol-origin: border; width: 22px; border: none; background: {ROW_HOVER.name()}; }}
QAbstractSpinBox::up-button {{ subcontrol-position: top right; border-top-right-radius: 6px; }}
QAbstractSpinBox::down-button {{ subcontrol-position: bottom right; border-bottom-right-radius: 6px; }}
QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover {{ background: {HEADER.name()}; }}
QAbstractSpinBox::up-arrow {{ image: url({_ARROWS["up"]}); width: 10px; height: 6px; }}
QAbstractSpinBox::down-arrow {{ image: url({_ARROWS["down"]}); width: 10px; height: 6px; }}
QAbstractSpinBox::up-arrow:disabled, QAbstractSpinBox::up-arrow:off {{ image: url({_ARROWS["up_off"]}); }}
QAbstractSpinBox::down-arrow:disabled, QAbstractSpinBox::down-arrow:off {{ image: url({_ARROWS["down_off"]}); }}
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
