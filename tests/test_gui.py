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


def test_atelier_shows_3d_only(tricky):
    from PySide6.QtWidgets import QApplication
    from ma3lib.gui.atelier import AtelierWindow

    app = QApplication.instance() or QApplication([])
    win = AtelierWindow()
    win.load(str(tricky))
    win.show()
    app.processEvents()
    assert win.tree._rows and "Nettoyage proposé" in win.summary.text()
    win.grab()
    win.close()


def test_atelier_drag_drop(tmp_path):
    """Glisser les pixels sur le segment maître : ils deviennent ses enfants (1.1.x)."""
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from ma3lib.gui.atelier import AtelierWindow
    from test_geotree import _ft

    app = QApplication.instance() or QApplication([])
    win = AtelierWindow()
    ft = _ft(tmp_path)
    win.load(str(ft.source))
    win.resize(1200, 700)
    win.show()
    app.processEvents()
    tree = win.tree
    row = {r.geo.name: r for r in tree._rows}
    pt = lambda r, f=0.5: QPoint(int(r.rect.left() + 140), int(r.rect.top() + f * r.rect.height()))
    QTest.mouseClick(tree, Qt.LeftButton, Qt.NoModifier, pt(row["Px 1"]))
    QTest.mouseClick(tree, Qt.LeftButton, Qt.ShiftModifier, pt(row["Px 3"]))
    assert [g.name for g in tree.selection] == ["Px 1", "Px 2", "Px 3"]
    QTest.mousePress(tree, Qt.LeftButton, Qt.NoModifier, pt(row["Px 2"]))
    for f in (0.6, 0.7):  # quelques pas pour passer le seuil de glisser
        QTest.mouseMove(tree, pt(row["Seg"], f))
    QTest.mouseMove(tree, pt(row["Seg"]))
    QTest.mouseRelease(tree, Qt.LeftButton, Qt.NoModifier, pt(row["Seg"]))
    app.processEvents()
    assert [c.name for c in win.ft.geometry("Seg").children] == ["Px 1", "Px 2", "Px 3"]
    assert tree.idents["Px 3"] == "1.1.3"
    win.undo()
    assert win.ft.geometry("Seg").children == []
    assert tree.idents["Px 3"] == "1.4"
    win.close()


def test_atelier_group_and_undo(bad_bar, monkeypatch):
    from PySide6.QtWidgets import QApplication, QInputDialog
    from ma3lib.gui.atelier import AtelierWindow

    app = QApplication.instance() or QApplication([])
    win = AtelierWindow()
    win.load(str(bad_bar))
    win.show()
    app.processEvents()
    assert win.tree.copies == {f"Pixel{i}": 4 for i in range(1, 5)}
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Pixel", True))
    win._group([win.ft.geometry(f"Pixel{i}") for i in range(1, 5)])
    assert win.ft.top_level("Pixel") is not None
    assert "4 références" in win.status.text()
    assert win.tree.idents["Pixel3"] == "1.3"
    win.undo()
    assert win.ft.top_level("Pixel") is None and win.ft.geometry("Pixel3").kind == "Beam"
    win.close()


def test_atelier_duplicate(good_bar, monkeypatch):
    from PySide6.QtWidgets import QApplication, QDialog
    from ma3lib.gui import atelier

    app = QApplication.instance() or QApplication([])
    win = atelier.AtelierWindow()
    win.load(str(good_bar))
    win.show()
    monkeypatch.setattr(atelier.DuplicateDialog, "exec", lambda self: QDialog.Accepted)
    monkeypatch.setattr(atelier.DuplicateDialog, "values", lambda self: (3, [3]))
    win._duplicate(win.ft.geometry("Pixel4"))
    assert win.tree.idents["Pixel7"] == "1.7"
    assert "dupliquée 3 fois" in win.status.text()
    win.close()


def test_atelier_edit_popup(good_bar):
    from PySide6.QtWidgets import QApplication
    from ma3lib.gui import atelier

    app = QApplication.instance() or QApplication([])
    win = atelier.AtelierWindow()
    win.load(str(good_bar))
    dlg = atelier.EditDialog(win.ft, win.ft.geometry("Pixel2"), "12ch", win)
    dlg.breaks[0].setValue(30)
    dlg.name.setText("Pixel 2")
    e = dlg.edit()
    assert e.breaks == [30] and e.name == "Pixel 2" and e.kind is None
    assert win._apply(atelier.geotree.apply_edit, win.ft.geometry("Pixel2"), e)
    win._after_change(win._last)
    assert win.ft.geometry("Pixel 2").breaks[0].dmx_offset == 30
    assert win.tree.idents["Pixel 2"] == "1.2"
    win.close()


def test_export_dialog(good_bar, tmp_path):
    from ma3lib.gui.export import ExportDialog
    from ma3lib import gdtf
    ft = gdtf.load(good_bar)
    dlg = ExportDialog(ft, targets=[], folder=tmp_path)
    assert dlg.file.text() == "Test@GoodBar.xml"
    assert dlg.keep.isChecked()
    dlg.name.setText("GoodBar JO")
    assert dlg.renew.isChecked()  # un autre nom = un nouveau GUID
    assert dlg.file.text() == "Test@GoodBar JO.xml"
    dlg.note.setText("JO")
    dlg.export()
    assert dlg.written == tmp_path / "Test@GoodBar JO.xml"
    assert gdtf.load(dlg.written).name == "GoodBar JO"


def test_single_app_with_sections(good_bar):
    from PySide6.QtWidgets import QApplication
    from ma3lib.gui.app import AppWindow
    app = QApplication.instance() or QApplication([])
    win = AppWindow()
    assert [b.text() for b in win.buttons.buttons()] == ["Atelier", "Comparateur"]
    win.atelier.load(str(good_bar))
    assert win.stack.currentWidget() is win.atelier
    win.buttons.button(1).click()
    assert win.stack.currentWidget() is win.comparateur
    win.comparateur.load("source", str(good_bar))
    win.show_section("Atelier")
    assert win.stack.currentIndex() == 0 and win.atelier.ft.name == "GoodBar"


def test_atelier_sends_fixture_to_comparator(bad_bar, good_bar):
    from PySide6.QtWidgets import QApplication
    from ma3lib.gui.app import AppWindow
    app = QApplication.instance() or QApplication([])
    win = AppWindow()
    win.atelier.load(str(good_bar))
    win.atelier.strip_3d()
    win.atelier.compareAsked.emit("cible")
    assert win.stack.currentWidget() is win.comparateur
    assert win.comparateur.sides["cible"].ft is win.atelier.ft
    assert win.comparateur.canvas.counts()[1] > 0


def test_mini_grid_keeps_16_pixels_on_one_row(tmp_path):
    """Jo, 11/11/2026 (ACME Pixel Line, 16 pixels en ligne) : l'aperçu coupait à 12 colonnes."""
    from PySide6.QtWidgets import QApplication
    from conftest import channel, fixture_xml, write_gdtf
    from ma3lib import gdtf
    from ma3lib.gui import atelier

    app = QApplication.instance() or QApplication([])
    pix = "".join(f'<Geometry Name="Array {i}"/>' for i in range(109, 125))
    chans = "".join(channel(f"Array {i}", "Dimmer", i - 108) for i in range(109, 125))
    xml = fixture_xml("Line", f'<Geometry Name="Base">{pix}</Geometry>',
                      f'<DMXMode Name="M" Geometry="Base"><DMXChannels>{chans}</DMXChannels></DMXMode>')
    ft = gdtf.load(write_gdtf(tmp_path / "line.gdtf", xml))
    grid = atelier.MiniGrid()
    grid.resize(380, 170)
    grid.set(ft.geometry("Array 120"), ft)
    assert grid.cells == [(i, 0) for i in range(16)] and grid.current == (11, 0)
    cols, rows, size = grid.layout()
    assert (cols, rows) == (16, 1) and cols * size <= 380
    grid.grab()
