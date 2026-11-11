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
    assert [b.text() for b in win.buttons.buttons()] == ["Atelier", "Comparateur", "Créer", "GDTF Share"]
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


def test_params_panel_makes_references_and_renames(bad_bar, monkeypatch):
    """Jo, 11/11/2026 : choisir le modèle d'une référence, le créer s'il manque, renommer."""
    from PySide6.QtWidgets import QApplication, QInputDialog
    from ma3lib import compare
    from ma3lib.gui import atelier

    def sig(ft):
        return [(i.ident, [(s.attribute, tuple(s.addresses)) for s in i.slots])
                for i in compare.flatten(compare.instances(ft, ft.modes[0]))]

    app = QApplication.instance() or QApplication([])
    win = atelier.AtelierWindow()
    win.load(str(bad_bar))
    before = sig(win.ft)

    def pick(*names):
        win.tree.selection = [win.ft.geometry(n) for n in names]
        win.tree.current = win.tree.selection[0]
        win._select(win.tree.current)

    # 1. le modèle n'existe pas : on le crée depuis le premier pixel
    pick("Pixel1")
    assert win.params.model.count() == 1 and not win.params.model.isEnabled()
    win.params.kind.setCurrentText(atelier.REF)
    assert win.params.model.currentText() == atelier.NEW_MODEL
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Pixel", True))
    win.params.applied.emit()
    assert win.ft.geometry("Pixel1").reference == "Pixel"
    # 2. les autres pixels prennent le modèle qui existe maintenant
    pick("Pixel2", "Pixel3", "Pixel4")
    win.params.kind.setCurrentText(atelier.REF)
    assert win.params.model.currentText() == "Pixel"
    win.params.applied.emit()
    assert [win.ft.geometry(f"Pixel{i}").breaks[0].dmx_offset for i in range(1, 5)] == [1, 4, 7, 10]
    assert sig(win.ft) == before  # mêmes instances, mêmes adresses
    # 3. renommer depuis le panneau
    pick("Pixel3")
    win.params.name.setText("Pix C")
    win.params.applied.emit()
    assert win.ft.geometry("Pix C") is not None and win.ft.geometry("Pixel3") is None
    assert len(win.history) == 3
    # 4. un modèle qui ne colle pas est refusé sans rien abîmer
    pick("Pixel2")
    with __import__("pytest").raises(atelier.geotree.MoveError):
        atelier.geotree.to_reference(win.ft, [win.ft.geometry("Body")], "Pixel")


def test_creer_saisie_a_la_main_puis_atelier():
    """Section « Créer » : canaux saisis à la main, pixels en copies, fixture ouvert dans l'atelier."""
    from PySide6.QtWidgets import QApplication
    from ma3lib.gui import creer
    from ma3lib.gui.app import AppWindow
    app = QApplication.instance() or QApplication([])
    win = AppWindow()
    win.show_section("Créer")
    page = win.creer
    page.build()
    assert "À corriger" in page.status.text() and win.stack.currentWidget() is page
    page.maker.setText("Test")
    page.name.setText("Barre")
    page.rename_mode("13ch")
    for name in ("Dimmer", "Red", "Green", "Blue"):
        page.add_channel()
        page.table.item(page.table.rowCount() - 1, creer.C_NAME).setText(name)
    assert [c.attribut for c in page.mode.canaux] == ["Dimmer", "ColorAdd_R", "ColorAdd_G", "ColorAdd_B"]
    for row in (1, 2, 3):
        page.table.item(row, creer.C_GEO).setText("Pixel")
    page.table.item(1, creer.C_COPIES).setText("4")
    assert [c.copies for c in page.mode.canaux] == [1, 4, 4, 4]
    assert "13 adresses" in page.count.text()
    page.table.selectRow(0)
    page.add_range()
    assert page.table.item(0, creer.C_RANGES).text() == "1"
    page.duplicate_mode("copie")
    page.delete_mode()
    assert [m.nom for m in page.projet.modes] == ["13ch"]
    page.grab()
    page.build()
    app.processEvents()
    assert win.stack.currentWidget() is win.atelier
    assert win.atelier.ft.name == "Barre"
    assert len([g for g in win.atelier.ft.all_geometries() if g.is_reference]) == 4
    win.close()


def test_params_panel_chooses_mesh(bad_bar, tmp_path):
    """Jo, 11/11/2026 : « je ne peux pas choisir le mesh de la géométrie »."""
    from PySide6.QtWidgets import QApplication
    from ma3lib import gdtf, ma3xml
    from ma3lib.gui import atelier

    app = QApplication.instance() or QApplication([])
    win = atelier.AtelierWindow()
    win.load(str(bad_bar))
    g = win.ft.geometry("Body")
    win.tree.selection, win.tree.current = [g], g
    win._select(g)
    items = [win.params.mesh.itemText(i) for i in range(win.params.mesh.count())]
    assert items[0] == atelier.NO_MESH and "Cube" in items and "Cylinder" in items
    win.params.mesh.setCurrentText("Cylinder")
    win.params.applied.emit()
    assert win.ft.geometry("Body").model == "Cylinder"
    model = [m for m in win.ft.xml_root.iterfind("FixtureType/Models/Model") if m.get("Name") == "Cylinder"]
    assert len(model) == 1 and model[0].get("PrimitiveType") == "Cylinder"
    # à l'export, la console reçoit son propre cylindre
    node = ma3xml.convert(win.ft).find("FixtureType")
    out = [m for m in node.iterfind("Models/Model") if m.get("Name") == "Cylinder"]
    assert out[0].get("File") == "MESH/gdtf_generic/cylinder.3ds"
    assert node.find("Geometries/Geometry").get("Model") == "Cylinder"
    # et on peut le retirer
    g = win.ft.geometry("Body")
    win.tree.selection, win.tree.current = [g], g
    win._select(g)
    win.params.mesh.setCurrentText(atelier.NO_MESH)
    win.params.applied.emit()
    assert win.ft.geometry("Body").model == ""


def test_mesh_bank_and_mesh_from_another_gdtf(bad_bar, good_bar, tmp_path, monkeypatch):
    """Jo, 11/11/2026 : une banque de formes simples, et reprendre un mesh d'un autre GDTF."""
    import zipfile
    from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog
    from ma3lib import ma3xml, meshbank
    from ma3lib.gui import atelier

    for name in meshbank.names():  # chaque forme est un glb valide en apparence
        data = meshbank.glb(name)
        assert data[:4] == b"glTF" and int.from_bytes(data[8:12], "little") == len(data)

    app = QApplication.instance() or QApplication([])
    win = atelier.AtelierWindow()
    win.load(str(bad_bar))

    def pick(name):
        g = win.ft.geometry(name)
        win.tree.selection, win.tree.current = [g], g
        win._select(g)

    # 1. une forme de la banque
    pick("Body")
    win.params.mesh.setCurrentText("Barre")
    win.params.applied.emit()
    assert win.ft.geometry("Body").model == "Barre"
    node = ma3xml.convert(win.ft).find("FixtureType")
    barre = next(m for m in node.iterfind("Models/Model") if m.get("Name") == "Barre")
    assert barre.get("File") == "USERMESH/BadBar_bananepot_barre.glb" and barre.findall(".//Block")
    assert barre.get("Length") == "1.0000"

    # 2. un mesh pris dans un autre GDTF
    other = tmp_path / "autre.gdtf"
    with zipfile.ZipFile(good_bar) as zin, zipfile.ZipFile(other, "w") as zout:
        xml = zin.read("description.xml").decode().replace(
            "<Geometries>", '<Models><Model Name="Lyre" File="lyre" Length="0.4" Width="0.2" Height="0.5"/>'
                            '<Model Name="Sans fichier" PrimitiveType="Cube"/></Models><Geometries>')
        zout.writestr("description.xml", xml)
        zout.writestr("models/gltf/lyre.glb", b"glTF" + bytes(2000))
    assert atelier.geotree.foreign_meshes(other) == ["Lyre"]
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(other), ""))
    monkeypatch.setattr(QInputDialog, "getItem", lambda *a, **k: ("Lyre", True))
    pick("Pixel1")
    win.params.mesh.setCurrentText(atelier.OTHER_GDTF)
    win.params.applied.emit()
    assert win.ft.geometry("Pixel1").model == "Lyre"
    assert win.ft.extra_files["models/gltf/lyre.glb"].startswith(b"glTF")
    node = ma3xml.convert(win.ft).find("FixtureType")
    lyre = next(m for m in node.iterfind("Models/Model") if m.get("Name") == "Lyre")
    assert lyre.get("File") == "USERMESH/BadBar_lyre.glb" and len(lyre.findall(".//Block")) == 2
    win.undo()  # une seule annulation pour la copie et le choix
    assert win.ft.geometry("Pixel1").model == "Pixel"


def test_share_section_searches_and_opens_in_atelier(good_bar, tmp_path):
    """Jo, 11/11/2026 : connecter son compte GDTF Share et aller chercher les GDTF dans l'appli."""
    import shutil
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt
    from ma3lib import coffre, gdtf_share
    from ma3lib.gui.app import AppWindow
    from ma3lib.gui.share import SharePage

    class FakeClient:
        def __init__(self, user, password):
            self.ok = (user, password) == ("jo@example.org", "secret")

        def login(self):
            if not self.ok:
                raise gdtf_share.ShareError("connexion refusée")

        def list(self):
            rows = [{"rid": 1, "manufacturer": "Test", "fixture": "GoodBar", "revision": "v1", "modes": [{"name": "12ch"}],
                     "uploader": "Manuf."},
                    {"rid": 2, "manufacturer": "Robe", "fixture": "Esprite", "revision": "v3", "modes": [],
                     "uploader": "Manuf.", "lastModified": "20"},
                    {"rid": 3, "manufacturer": "Robe", "fixture": "Esprite", "revision": "v2", "modes": [],
                     "uploader": "Manuf.", "lastModified": "10"},
                    {"rid": 4, "manufacturer": "Bricolo", "fixture": "Truc", "revision": "x", "modes": [],
                     "uploader": "User"}]
            return [gdtf_share.ShareEntry.from_json(r) for r in rows]

        def download(self, entry, dest_dir):
            dest_dir.mkdir(parents=True, exist_ok=True)
            return Path(shutil.copy(good_bar, dest_dir / "Test@GoodBar@v1.gdtf"))

    from pathlib import Path
    app = QApplication.instance() or QApplication([])
    win = AppWindow()
    assert [name for name, _ in win.sections][-1] == "GDTF Share"
    class Vault(dict):  # remplace le Gestionnaire d'identifiants de Windows
        def get_password(self, service, name):
            return self.get((service, name))

        def set_password(self, service, name, value):
            self[(service, name)] = value

        def delete_password(self, service, name):
            del self[(service, name)]

    vault = Vault()
    page = win.share
    page._factory, page.folder, page.vault = FakeClient, tmp_path / "share", vault
    page.user.setText("jo@example.org")
    page.password.setText("faux")
    assert not page.connect_account() and "refusée" in page.status.text()
    assert not page.search.isEnabled() and not vault
    page.password.setText("secret")
    assert page.connect_account()
    assert coffre.load(vault) == ("jo@example.org", "secret")  # retenu dans le coffre, pas ailleurs
    # comme un explorateur : les fabricants en dossiers, sans les envois d'utilisateurs
    assert page.password.text() == ""
    assert [page.makers.item(i).data(Qt.UserRole) for i in range(page.makers.count())] == ["Robe", "Test"]
    assert page.results.count() == 1 and "v3" in page.results.item(0).text()  # dernière révision seulement
    page.makers.setCurrentRow(1)
    assert "GoodBar" in page.results.item(0).text()
    page.search.setText("good")
    assert page.makers.count() == 1 and page.results.count() == 1
    page.results.setCurrentRow(0)
    assert page.to_atelier.isEnabled()
    page.open_in_atelier()
    assert win.stack.currentWidget() is win.atelier and win.atelier.ft.name == "GoodBar"
    page.send_to_compare("cible")
    assert win.stack.currentWidget() is win.comparateur and win.comparateur.sides["cible"].ft.name == "GoodBar"
    # au lancement suivant, la section se reconnecte toute seule ; « Se déconnecter » oublie le compte
    again = SharePage(FakeClient, tmp_path / "share", vault)
    again.show()
    app.processEvents()
    assert again.client is not None and again.makers.count() == 2
    again.disconnect_account()
    assert coffre.load(vault) is None and again.client is None and not again.search.isEnabled()
