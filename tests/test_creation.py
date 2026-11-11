"""Créer un fixture de zéro : du texte de la notice au XML MA3."""
import pytest

from ma3lib import charte, creation, ma3xml, pdfchart
from ma3lib.creation import Canal, Mode, Plage, Projet


@pytest.mark.parametrize("nom,attr", [
    ("Pan", "Pan"), ("Tilt fine", "Tilt"), ("Dimmer intensity", "Dimmer"), ("Shutter / Strobe", "Shutter1"),
    ("Blade 2 swivelling", "Blade2Rot"), ("Blade 3 position", "Blade3A"), ("Frame rotation", "ShaperRot"),
    ("Frame macros speed", "ShaperMacrosSpeed"), ("Ovalizer Index/Rotation", "BeamShaperPos"),
    ("CCT 16 bit", "CTC"), ("GMP", "Tint"), ("Color Wheel", "Color1"), ("Lime", "ColorAdd_GY"),
    ("Gobo 2 rotation", "Gobo2Pos"), ("Gobo", "Gobo1"), ("PWM Adjustment", "LEDFrequency"),
    ("Control (hold 3 seconds)", "Control1"), ("XFade CTC>COLOR", "XFadeCTCCOLOR"), ("Reserved", "NoFeature"),
])
def test_deviner(nom, attr):
    assert creation.deviner(nom) == attr


def test_cyan_soustractif_ou_emetteur():
    assert creation.deviner("Cyan", ["Cyan", "Magenta", "Yellow"]) == "ColorSub_C"
    assert creation.deviner("Cyan", ["Red", "Green", "Blue", "Cyan", "Lime"]) == "ColorAdd_C"


def test_attribuer_sans_doublon():
    mode = Mode("M", [Canal(1, nom="Control"), Canal(2, nom="Reset"), Canal(3, nom="GEL category"),
                      Canal(4, nom="GEL filter")])
    creation.attribuer(mode)
    attrs = [c.attribut for c in mode.canaux]
    assert len(set(attrs)) == 4 and attrs[0] == "Control1"


def _lyre() -> Projet:
    return Projet("Test", "Lyre", "", [
        Mode("Basic", [Canal(1, 2, "Pan", defaut=128), Canal(3, 4, "Tilt", defaut=128), Canal(5, None, "Dimmer"),
                       Canal(6, None, "Shutter", plages=[Plage(0, 9, "Closed"), Plage(10, 255, "Open")])]),
        Mode("RGB", [Canal(1, 2, "Pan"), Canal(3, 4, "Tilt"), Canal(5, None, "Dimmer"),
                     Canal(6, None, "Red"), Canal(7, None, "Green"), Canal(8, None, "Blue")]),
    ])


def test_construire_et_exporter(tmp_path):
    ft = creation.construire(_lyre())
    assert [(m.name, m.footprint) for m in ft.modes] == [("Basic", 6), ("RGB", 8)]
    assert [g.path() for g in ft.all_geometries()] == ["Base", "Base / Yoke", "Base / Yoke / Head"]
    pan = ft.modes[0].channels[0]
    assert (pan.geometry, pan.offset, pan.attribute) == ("Yoke", [1, 2], "Pan")
    out = ma3xml.export(ft, tmp_path)
    text = out.read_text(encoding="utf-8-sig")
    assert out.name == "Test@Lyre.xml" and 'DataVersion="2.3.2.0"' in text
    assert 'Coarse="1" Fine="2"' in text and 'Attribute="ColorRGB_R"' in text
    assert '<ChannelSet Name="Open" DMXFrom="0A0A0A"' in text
    again = creation.ecrire_gdtf(ft, tmp_path / "Test@Lyre.gdtf")
    from ma3lib import gdtf
    assert gdtf.load(again).modes[1].footprint == 8


def test_copies_modele_et_references():
    px = [Canal(2 + i, None, n, geometrie="Pixel", copies=4) for i, n in enumerate(("Red", "Green", "Blue"))]
    projet = Projet("Test", "Barre", "", [Mode("13ch", [Canal(1, None, "Dimmer")] + px)])
    assert projet.modes[0].empreinte == 13
    ft = creation.construire(projet)
    assert ft.top_level("Pixel") is not None
    refs = [g for g in ft.all_geometries() if g.is_reference]
    assert [(r.name, r.breaks[0].dmx_offset) for r in refs] == [("Pixel 1", 2), ("Pixel 2", 5), ("Pixel 3", 8),
                                                                ("Pixel 4", 11)]
    absolute = charte.absolute_channels(ft, ft.modes[0])
    assert [c.addresses[0] for c in absolute] == list(range(1, 14))
    assert absolute[-1].instance == "Pixel 4" and absolute[-1].attributes == ["ColorAdd_B"]


def test_copies_une_base_par_mode():
    def mode(name, n):
        return Mode(name, [Canal(1, None, "Dimmer")]
                    + [Canal(2 + i, None, c, geometrie="Pixel", copies=n) for i, c in enumerate(("Red", "Green", "Blue"))])
    ft = creation.construire(Projet("Test", "Barre", "", [mode("4px", 4), mode("8px", 8)]))
    assert [m.geometry for m in ft.modes] == ["Base 4px", "Base 8px"]
    assert len([g for g in ft.top_level("Base 8px").walk() if g.is_reference]) == 8
    assert [g.name for g in ft.geometries] == ["Base 4px", "Pixel", "Base 8px"]


def test_verifier_signale_les_erreurs():
    projet = Projet("Test", "", "", [Mode("M", [Canal(1, None, "Dimmer"), Canal(1, None, "Red"), Canal(4, None, "Blue")])])
    with pytest.raises(creation.CreationError) as exc:
        creation.construire(projet)
    text = str(exc.value)
    assert "nom du fixture" in text and "adresse 1" in text and "sans canal (2, 3)" in text


def test_projet_json_aller_retour():
    projet = _lyre()
    assert Projet.from_json(projet.to_json()) == projet


def test_cmy_et_rgb_partagent_colorrgb(tmp_path):
    """Un mode CMY et un mode RGB : la console n'a qu'un ColorRGB_R (inversé pour le cyan)."""
    projet = Projet("Test", "Mix", "", [
        Mode("CMY", [Canal(1, None, "Cyan"), Canal(2, None, "Magenta"), Canal(3, None, "Yellow")]),
        Mode("RGB", [Canal(1, None, "Red"), Canal(2, None, "Green"), Canal(3, None, "Blue")]),
    ])
    text = ma3xml.export(creation.construire(projet), tmp_path).read_text(encoding="utf-8-sig")
    assert text.count('<Attribute Name="ColorRGB_R"') == 1 and "ColorSub" not in text.replace("OriginalAttribute", "")
    assert text.count('DMXInvert="Yes"') == 3


# ---------------------------------------------------------------- charte PDF

HEAD = [["DMX MODE", "", "", "Name", "Function", "DMX", "", "Default"],
        ["BASIC", "STD", "RAW", "", "", "FROM", "TO", ""],
        ["5", "7", "9", "", "", "", "", ""]]


def test_lire_grilles_resume_et_detail():
    resume = pdfchart.Grille([["Function", "DMX MODE", "", ""], ["", "BASIC", "STD", "RAW"], ["", "5", "7", "9"],
                              ["Pan", "1", "1", "1"], ["Pan fine", "2", "2", "2"], ["Dimmer", "3", "3", "3"],
                              ["Red", "-", "4", "4"], ["Red fine", "-", "-", "5"], ["Green", "-", "5", "6"],
                              ["Shutter", "4", "6", "7"], ["CCT 16 bit", "-", "-", "8"], [None, "-", "-", "9"],
                              ["Control", "5", "7", "-"]])
    detail = pdfchart.Grille(HEAD + [
        ["1", "1", "1", "Pan", "Pan movement", "0", "255", "128"],
        ["4", "6", "7", "Shutter", "Closed", "0", "9", "0"],
        [None, None, None, None, "Strobe slow to fast", "10", "250", None],
        [None, None, None, None, "Open", "251", "255", None],
    ])
    suite = pdfchart.Grille(HEAD + [  # page suivante : le même canal continue
        ["4", "6", "7", "Shutter", "Open", "251", "255", None],
        ["5", "7", "-", "Control", "No function", "0", "", "0"],
        [None, None, None, None, "Reset", "200", "255", None],
    ])
    modes = pdfchart.lire_grilles([resume, detail, suite])
    assert [(m.nom, m.empreinte) for m in modes] == [("BASIC", 5), ("STD", 7), ("RAW", 9)]
    raw = {c.nom: c for c in modes[2].canaux}
    assert (raw["Pan"].adresse, raw["Pan"].fine, raw["Pan"].defaut) == (1, 2, 128)
    assert (raw["Red"].fine, raw["Green"].fine) == (5, None)
    assert (raw["CCT 16 bit"].adresse, raw["CCT 16 bit"].fine, raw["CCT 16 bit"].attribut) == (8, 9, "CTC")
    assert [(p.debut, p.fin, p.nom) for p in raw["Shutter"].plages] == [
        (0, 9, "Closed"), (10, 250, "Strobe slow to fast"), (251, 255, "Open")]
    basic = {c.nom: c for c in modes[0].canaux}
    assert [(p.debut, p.fin) for p in basic["Control"].plages] == [(0, 0), (200, 255)]
    assert creation.construire(Projet("T", "X", "", modes)).modes[2].footprint == 9


def test_lire_grilles_un_tableau_par_mode():
    def table(title, names):
        return pdfchart.Grille([["Channel", "Function", "Value"]] + [[str(i), n, "000-255"] for i, n in enumerate(names, 1)],
                               title=title)
    modes = pdfchart.lire_grilles([table("Mode 1 (4 ch)", ["Dimmer", "Red", "Green", "Blue"]),
                                   table("Mode 2 (3 ch)", ["Red", "Green", "Blue"]),
                                   pdfchart.Grille([["Value", "Colour"], ["0", "Red"], ["2", "Green"], ["4", "Blue"]])])
    assert [(m.nom, len(m.canaux)) for m in modes] == [("Mode 1 (4 ch)", 4), ("Mode 2 (3 ch)", 3)]
