"""Ouverture de la fenêtre sans écran (Qt offscreen). Ignoré si PySide6 n'est pas installé."""
import os

import pytest

pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_window_loads_two_fixtures(bad_bar, good_bar):
    from PySide6.QtWidgets import QApplication
    from ma3lib.gui.pair import PairDialog
    from ma3lib.gui.window import MainWindow

    app = QApplication.instance() or QApplication([])
    win = MainWindow()
    win.load("source", str(bad_bar))
    win.load("cible", str(good_bar))
    win.resize(1200, 800)
    win.show()
    app.processEvents()
    linked, total = win.canvas.counts()
    assert total == 5 and linked == 5
    assert "5 / 5" in win._count.text()
    win.canvas.grab()
    dlg = PairDialog(win.canvas.instance("source", "1.1"), win.canvas.instance("cible", "1.1"), "S", "C")
    dlg.grab()
    win.close()
