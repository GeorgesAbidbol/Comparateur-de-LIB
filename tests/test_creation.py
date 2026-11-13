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


# ------------------------------------------------- physique, émetteurs, roues

@pytest.mark.parametrize("texte,attr,attendu", [
    ("Swivelling from -25° towards 0°", "Blade1Rot", (-25, 0)), ("0 degrees to +60 degrees", "ShaperRot", (0, 60)),
    ("Linear from 2.200K to 15.000K", "CTC", (2200, 15000)), ("15.000k", "CTC", (15000, 15000)),
    ("Dimmer intensity 0 – 100%", "Dimmer", (0, 1)), ("-99% to -1%", "Tint", (-0.99, -0.01)),
    ("Open", "Shutter1", (1, 1)), ("Close", "Shutter1", (0, 0)), ("Max to min diameter", "Iris", (1, 0)),
    ("Linear 0.000 to 0.735", "CIE_X", (0, 0.735)), ("Strobe 1 Hz to 25 Hz", "Shutter1Strobe", (1, 25)),
    ("Macro 12", "ShaperMacros", None),
])
def test_physique(texte, attr, attendu):
    assert creation.physique(texte, attr) == attendu


@pytest.mark.parametrize("attr,texte,attendu", [
    ("Shutter1", "Strobe from slow to fast", "Shutter1Strobe"), ("Shutter1", "Open", "Shutter1"),
    ("Shutter1", "Pulse in from slow to fast", "Shutter1StrobePulseOpen"),
    ("Shutter1", "Random from slow to fast", "Shutter1StrobeRandom"),
    ("Color1", "Color Wheel Rotation Forward rainbow - Fast to slow", "Color1WheelSpin"),
    ("Color1", "Color Slot Dark Red", "Color1"), ("Gobo1", "Gobo 3 shake slow to fast", "Gobo1SelectShake"),
    ("Iris", "Random pulse closing slow to fast", "IrisRandomPulseClose"),
    ("BeamShaperPos", "Ovalizer Rotation Ovalizer forward rotation fast to slow", "BeamShaperPosRotate"),
    ("BeamShaperPos", "Ovalizer Indexing", "BeamShaperPos"),
])
def test_sous_attribut(attr, texte, attendu):
    assert creation.sous_attribut(attr, texte) == attendu


def _spot() -> Projet:
    return Projet("Test", "Spot", "", [Mode("M", [
        Canal(1, 2, "Pan", phys_de=-270, phys_a=270),
        Canal(3, None, "Shutter", plages=[Plage(0, 9, "Closed"), Plage(10, 200, "Strobe 1 Hz to 25 Hz"),
                                          Plage(201, 255, "Open")]),
        Canal(4, None, "Red"), Canal(5, None, "Lime"),
        Canal(6, None, "Color Wheel", plages=[
            Plage(0, 9, "Open"), Plage(10, 19, "Red"), Plage(20, 29, "Open + Red"), Plage(30, 39, "Congo Blue"),
            Plage(200, 255, "Rainbow slow to fast", "Rotation")]),
        Canal(7, None, "Gobo", plages=[Plage(0, 9, "Open"), Plage(10, 19, "Gobo 1"), Plage(20, 29, "Gobo 2"),
                                       Plage(100, 150, "Gobo 1 shake slow to fast")]),
        Canal(8, None, "Ovalizer", plages=[Plage(0, 29, "Open"), Plage(30, 59, "Ovalizer Indexing (set next ch)"),
                                           Plage(60, 89, "Ovalizer Rotation (set next ch)")]),
        Canal(9, None, "Ovalizer Index/Rotation", plages=[
            Plage(0, 255, "Ovalizer Indexing", "Ovalizer Indexing"),
            Plage(0, 127, "Forward rotation fast to slow", "Ovalizer Rotation"),
            Plage(128, 255, "Backwards rotation slow to fast", "Ovalizer Rotation")]),
    ])])


def test_emetteurs_roues_physique_dans_le_fixture(tmp_path):
    projet = _spot()
    ft = creation.construire(projet)
    assert creation.emetteurs(projet) == ["Red", "Lime"]
    assert creation.roues(projet) == {"ColorWheel 1": ["Open", "Red", "Congo Blue"],
                                      "GoboWheel 1": ["Open", "Gobo 1", "Gobo 2"]}
    x = ft.xml_root
    assert [e.get("Name") for e in x.iter("Emitter")] == ["Red", "Lime"]
    assert x.find(".//ColorSpace").get("Mode") == "sRGB"
    assert [s.get("Name") for s in x.findall(".//Wheel[@Name='ColorWheel 1']/Slot")] == ["Open", "Red", "Congo Blue"]
    fns = {cf.get("Name"): cf for cf in x.iter("ChannelFunction")}
    assert (fns["Pan"].get("PhysicalFrom"), fns["Pan"].get("PhysicalTo")) == ("-270", "270")
    strobe = fns["Strobe 1 Hz to 25 Hz"]
    assert (strobe.get("Attribute"), strobe.get("DMXFrom"), strobe.get("PhysicalFrom"), strobe.get("PhysicalTo")) == (
        "Shutter1Strobe", "10/1", "1", "25")
    assert fns["Red"].get("Emitter") == "Red" and fns["Lime"].get("Emitter") == "Lime"
    wheel = fns["Color Wheel"]
    assert wheel.get("Wheel") == "ColorWheel 1"
    assert [cs.get("WheelSlotIndex") for cs in wheel] == ["1", "2", None, "3"]
    assert fns["Rainbow slow to fast"].get("Attribute") == "Color1WheelSpin"
    assert fns["Gobo 1 shake slow to fast"].get("Attribute") == "Gobo1SelectShake"
    index, rot = fns["Ovalizer Indexing"], fns["Ovalizer Rotation"]
    assert (index.get("ModeMaster"), index.get("ModeFrom"), index.get("ModeTo")) == ("Head_BeamShaper", "30/1", "59/1")
    assert (rot.get("Attribute"), rot.get("ModeFrom"), rot.get("ModeTo")) == ("BeamShaperPosRotate", "60/1", "89/1")
    names = {a.get("Name"): a for a in x.iter("Attribute")}
    assert names["Shutter1Strobe"].get("MainAttribute") == "Shutter1"
    text = ma3xml.export(ft, tmp_path).read_text(encoding="utf-8-sig")
    assert '<Emitter Name="Lime"' in text and 'Emitter="Red"' in text and "<ColorSpaceData" in text
    assert 'WheelSlotIndex="2"' in text and 'ModeMaster="Head_BeamShaper"' in text
    assert 'Attribute="Shutter1Strobe" OriginalAttribute="Shutter" DMXFrom="0A0A0A"' in text
    assert Projet.from_json(projet.to_json()) == projet


def test_lire_grilles_sections_annexe_et_valeur_fusionnee():
    detail = pdfchart.Grille(HEAD + [
        ["1", "1", "1", "Pan", "Pan movement", "0", "255", "128"],
        ["2", "2", "2", "Zoom", "Zoom from min to max beam angle", "0", "255", "0"],
        ["3", "3", "3", "Color Wheel", "Color Positioning", "", "", "0"],
        [None, None, None, None, "Open", "0", "", None],
        [None, None, None, None, "Open + Red", "1", "25", None],
        [None, None, None, None, "Red", "2", "6", None],  # « 26 » coupé par le bord de colonne
        [None, None, None, None, "Color Wheel Rotation", "", "", None],
        [None, None, None, None, "Forward rainbow", "200", "255", None],
        ["4", "4", "4", "Control", "No function", "0", "1", "0"],
        [None, None, None, None, "(See full list)", "2", "3", None],
        ["5", "5", "5", "Dimmer", "Dimmer intensity 0 – 100%", "0", "255", "0"],
    ])
    annexe = pdfchart.Grille([["Function", "", "From", "To", "Note"], ["NO FUNCTION", "", "0", "1", ""],
                              ["PAN", "REVERSE ON", "2", "3", ""], [None, "REVERSE OFF", "4", "5", ""],
                              ["RESET", "ALL", "200", "201", ""], [None, "ZOOM", "202", "203", ""]],
                             title="Control Channel")
    modes = pdfchart.lire_grilles([detail, annexe])
    projet = Projet("T", "X", "", modes)
    pdfchart.appliquer_faits(projet, "Pan movement range: 540°\n10°-60° zoom with 200mm lens")
    raw = {c.nom: c for c in modes[2].canaux}
    assert (raw["Pan"].phys_de, raw["Pan"].phys_a) == (-270, 270)
    assert (raw["Zoom"].phys_de, raw["Zoom"].phys_a) == (10, 60)
    assert (raw["Dimmer"].phys_de, raw["Dimmer"].phys_a) == (0, 1)
    wheel = raw["Color Wheel"].plages
    assert [(p.debut, p.fin, p.groupe, p.attribut) for p in wheel] == [
        (0, 0, "Color Positioning", "Color1"), (1, 25, "Color Positioning", "Color1"),
        (26, 26, "Color Positioning", "Color1"), (200, 255, "Color Wheel Rotation", "Color1WheelSpin")]
    assert [p.nom for p in raw["Control"].plages] == ["NO FUNCTION", "PAN REVERSE ON", "PAN REVERSE OFF",
                                                      "RESET ALL", "RESET ZOOM"]


# ---------------------------------------------------------------- images des roues

def _projet_gobos():
    return Projet("Test", "Gobos", "", [Mode("M", [
        Canal(1, nom="Rotating gobo wheel", attribut="Gobo1",
              plages=[Plage(0, 9, "Open")] + [Plage(10 + k * 10, 19 + k * 10, f"Gobo {k + 1}") for k in range(6)]
              + [Plage(200, 255, "Rotation")]),
        Canal(2, nom="Static gobo wheel", attribut="Gobo2",
              plages=[Plage(0, 9, "Open"), Plage(10, 19, "Dots"), Plage(20, 29, "Bars")]),
        Canal(3, nom="Dimmer", attribut="Dimmer")])])


_PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010802000000907753de"
                     "0000000c4944415408d763f8ffff3f0005fe02fedccc59e70000000049454e44ae426082")


def test_image_d_emplacement_dans_le_fixture_et_l_export(tmp_path):
    import zipfile
    from ma3lib import ma3xml
    p = _projet_gobos()
    p.definir_image("GoboWheel 1", "Gobo 3", _PNG)
    p = Projet.from_json(p.to_json())  # les images suivent le projet enregistré
    assert p.image("GoboWheel 1", "gobo 3") == _PNG
    ft = creation.construire(p)
    slot = ft.xml_root.find(".//Wheel[@Name='GoboWheel 1']/Slot[@Name='Gobo 3']")
    assert ft.extra_files[f"wheels/{slot.get('MediaFileName')}.png"] == _PNG
    assert ft.xml_root.find(".//Slot[@Name='Gobo 2']").get("MediaFileName") is None
    creation.ecrire_gdtf(ft, tmp_path / "g.gdtf")
    assert f"wheels/{slot.get('MediaFileName')}.png" in zipfile.ZipFile(tmp_path / "g.gdtf").namelist()
    out = ma3xml.convert(ft)
    images = out.findall(".//GoboImage")
    assert len(images) == 1 and images[0].find("FileContent/Block").get("Base64")
    p.definir_image("GoboWheel 1", "Gobo 3", None)
    assert not p.images


def test_rattacher_les_images_aux_emplacements():
    from ma3lib import pdfimages
    slots = ["Open", "Gobo 1", "Gobo 2", "Gobo 12"]
    ims = [{"label": " Gobo 12"}, {"label": "2"}, {"label": ""}]
    got = pdfimages.rattacher(ims, slots)
    assert got["Gobo 12"] is ims[0] and got["Gobo 2"] is ims[1] and got["Gobo 1"] is ims[2] and "Open" not in got
    assert pdfimages.rattacher([{"label": ""}], slots) == {}  # pas autant d'images que d'emplacements
    noms = {"GoboWheel 1": "Rotating gobo wheel", "GoboWheel 2": "Static gobo wheel", "ColorWheel 1": "Colour wheel"}
    assert pdfimages.choisir_roue("STATIC GOBO WHEEL", noms) == "GoboWheel 2"
    assert pdfimages.choisir_roue("Rotating gobos", noms) == "GoboWheel 1"
    assert pdfimages.choisir_roue("14 - COLOR WHEEL", noms) == "ColorWheel 1"


def test_images_de_gobos_lues_dans_un_pdf(tmp_path):
    pytest.importorskip("pdfplumber")
    rl = pytest.importorskip("reportlab.pdfgen.canvas")
    from PIL import Image
    from reportlab.lib.utils import ImageReader
    from ma3lib import pdfimages
    c = rl.Canvas(str(tmp_path / "g.pdf"), pagesize=(595, 842))
    c.drawString(50, 790, "ROTATING GOBO WHEEL")
    for k in range(6):
        x, y = 50 + (k % 3) * 120, 680 - (k // 3) * 120
        c.drawImage(ImageReader(Image.new("RGB", (40, 40), (40 * k, 0, 0))), x, y, 80, 80)
        c.drawString(x + 25, y - 12, f"Gobo {6 - k}")  # numérotés à rebours : c'est le texte qui décide
    c.drawString(50, 400, "STATIC GOBO WHEEL")
    for k in range(2):
        c.drawImage(ImageReader(Image.new("RGB", (40, 40), (0, 100 * k + 50, 0))), 50 + k * 100, 300, 70, 70)
    c.drawImage(ImageReader(Image.new("RGB", (400, 40), "blue")), 50, 100, 400, 40)  # un bandeau, pas un gobo
    c.save()
    p = _projet_gobos()
    assert pdfimages.images_des_roues(tmp_path / "g.pdf", p) == 8
    import io
    red = Image.open(io.BytesIO(p.image("GoboWheel 1", "Gobo 6"))).convert("RGB").getpixel((5, 5))[0]
    assert red < 20 and p.image("GoboWheel 2", "Bars") and not p.image("GoboWheel 1", "Open")


def test_emplacements_de_roue_physique_fixe_dans_l_export():
    """Comme la console : chaque ChannelSet d'index de roue a une physique 0 à 0 (centre de l'emplacement),
    sinon onPC déduit l'emplacement de la plage DMX et l'image est décalée."""
    from ma3lib import ma3xml
    out = ma3xml.convert(creation.construire(_projet_gobos()))
    cf = next(f for f in out.iter("ChannelFunction") if f.get("Attribute") == "Gobo1")
    sets = cf.findall("ChannelSet")
    assert [s.get("WheelSlotIndex") for s in sets] == [str(i) for i in range(1, 8)]
    assert all(s.get("HasPhysical") == "Yes" and s.get("PhysicalTo") == "0.0000" and s.get("PhysicalFrom") is None
               for s in sets)
    assert list(sets[1].attrib) == ["Name", "DMXFrom", "WheelSlotIndex", "PhysicalTo", "HasPhysical"]


def test_physique_tiree_du_texte_de_la_notice():
    """Course pan/tilt, zoom, angle des couteaux et rotation du module lus dans le texte de la notice
    quand la charte ne les donne pas."""
    p = Projet("T", "F", "", [Mode("M", [Canal(1, nom="Pan", attribut="Pan"), Canal(3, nom="Tilt", attribut="Tilt"),
                                          Canal(5, nom="Zoom", attribut="Zoom", description="Zoom wide to narrow"),
                                          Canal(6, nom="Blade 1 swivel", attribut="Blade1Rot"),
                                          Canal(7, nom="Frame rotation", attribut="ShaperRot"),
                                          Canal(8, nom="Blade 2 swivel", attribut="Blade2Rot",
                                                plages=[Plage(0, 255, "-30° to +30°", phys_de=-30, phys_a=30)])])])
    pdfchart.appliquer_faits(p, "Pan: 0-540°\nTilt movement 265°\nZoom range 4.5° ~ 50°\n"
                                "blade angle adjustment of min. ±25° and a module rotation of min. ±60°")
    got = {c.attribut: (c.phys_de, c.phys_a) for c in p.modes[0].canaux}
    assert got["Pan"] == (-270, 270) and got["Tilt"] == (-132.5, 132.5)
    assert got["Zoom"] == (50, 4.5)
    assert got["Blade1Rot"] == (-25, 25) and got["ShaperRot"] == (-60, 60)
    assert got["Blade2Rot"] == (None, None)  # la charte donne déjà ses degrés
