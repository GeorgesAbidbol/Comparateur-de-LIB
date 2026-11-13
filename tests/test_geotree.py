import pytest
from conftest import channel, fixture_xml, write_gdtf

from ma3lib import compare, gdtf, geotree


def _ft(tmp_path):
    """Module > Seg (maître) et, à côté, un groupe de 3 pixels : comme le JDC d'origine."""
    refs = "".join(f'<GeometryReference Name="Px {i}" Geometry="Px"><Break DMXOffset="{i + 1}" DMXBreak="1"/>'
                   "</GeometryReference>" for i in range(1, 4))
    geos = (f'<Geometry Name="Root"><Geometry Name="Module"><Beam Name="Seg"/>'
            f'<Geometry Name="Pixels">{refs}</Geometry></Geometry></Geometry><Beam Name="Px"/>')
    chans = channel("Seg", "Dimmer", 1) + channel("Px", "ColorAdd_R", 1, "Overwrite")
    return gdtf.load(write_gdtf(tmp_path / "t.gdtf", fixture_xml(
        "T", geos, f'<DMXMode Name="M" Geometry="Root"><DMXChannels>{chans}</DMXChannels></DMXMode>')))


def _ids(ft):
    return [(i.ident, i.name) for i in compare.flatten(compare.instances(ft, ft.modes[0]))]


def test_nest_pixels_under_master(tmp_path):
    ft = _ft(tmp_path)
    assert _ids(ft)[:3] == [("1", "Root"), ("1.1", "Seg"), ("1.2", "Px 1")]
    seg, pixels = ft.geometry("Seg"), ft.geometry("Pixels")
    u = geotree.move(ft, list(pixels.children), seg, 0)
    assert _ids(ft) == [("1", "Root"), ("1.1", "Seg"), ("1.1.1", "Px 1"), ("1.1.2", "Px 2"), ("1.1.3", "Px 3")]
    # l'XML suit (avec les Break des références)
    seg_el = geotree.element_of(ft, seg)
    assert [c.get("Name") for c in seg_el] == ["Px 1", "Px 2", "Px 3"]
    assert seg_el[0].find("Break").get("DMXOffset") == "2"
    assert len(geotree.element_of(ft, pixels)) == 0
    geotree.undo(ft, u)
    assert [c.name for c in pixels.children] == ["Px 1", "Px 2", "Px 3"]
    assert [c.get("Name") for c in geotree.element_of(ft, pixels)] == ["Px 1", "Px 2", "Px 3"]


def test_reorder_and_refuse(tmp_path):
    ft = _ft(tmp_path)
    pixels = ft.geometry("Pixels")
    p3 = ft.geometry("Px 3")
    u = geotree.move(ft, [p3], pixels, 0)
    assert [c.name for c in pixels.children] == ["Px 3", "Px 1", "Px 2"]
    geotree.undo(ft, u)
    assert [c.name for c in pixels.children] == ["Px 1", "Px 2", "Px 3"]
    p1 = ft.geometry("Px 1")
    geotree.move(ft, [p1], pixels, 3)  # vers la fin
    assert [c.name for c in pixels.children] == ["Px 2", "Px 3", "Px 1"]
    with pytest.raises(geotree.MoveError):
        geotree.move(ft, [ft.geometry("Module")], pixels, 0)  # dans sa descendance
    with pytest.raises(geotree.MoveError):
        geotree.move(ft, [ft.geometry("Seg")], p1, 0)  # sous une référence


def test_ma3_paths_follow(tmp_path):
    xml = ('<?xml version="1.0"?><GMA3 DataVersion="2.3.2.0"><FixtureType Name="T" Manufacturer="M">'
           '<Geometries><Geometry Name="Base"><Geometry Name="Body"><Beam Name="Plate"><Beam Name="Px"/>'
           '</Beam></Geometry><Geometry Name="Other"/></Geometry></Geometries><DMXModes>'
           '<DMXMode Name="M" Geometry="Base"><DMXChannels>'
           '<DMXChannel Geometry="Base.Body.Plate.Px" Coarse="1"><LogicalChannel Attribute="Dimmer"/></DMXChannel>'
           '</DMXChannels></DMXMode></DMXModes></FixtureType></GMA3>')
    path = tmp_path / "t.xml"
    path.write_text(xml)
    ft = gdtf.load(path)
    geotree.move(ft, [ft.geometry("Plate")], ft.geometry("Other"), 0)
    assert ft.xml_root.find(".//DMXChannel").get("Geometry") == "Base.Other.Plate.Px"
    assert ft.modes[0].channels[0].geometry_path == "Base.Other.Plate.Px"


def _addresses(ft):
    return [(i.ident, i.name, [(s.attribute, s.addresses) for s in i.slots])
            for i in compare.flatten(compare.instances(ft, ft.modes[0]))]


def test_group_copies_into_model_and_references(bad_bar):
    """Barre aux 4 pixels copiés -> 1 modèle + 4 références, mêmes instances, mêmes adresses."""
    ft = gdtf.load(bad_bar)
    before = _addresses(ft)
    pixels = list(ft.geometry("Body").children)
    assert geotree.suggested_model_name(ft, pixels) == "Pixel"
    new, msg = geotree.group(ft, pixels, "Pixel")
    assert "4 références" in msg
    assert _addresses(new) == before
    assert [g.kind for g in new.geometry("Body").children] == ["GeometryReference"] * 4
    model = new.top_level("Pixel")
    assert model is not None and model.kind == "Beam"
    assert [b.dmx_offset for g in new.geometry("Body").children for b in g.breaks] == [1, 4, 7, 10]
    chans = new.modes[0].channels
    assert [(c.geometry, c.offset) for c in chans] == [("Pixel", [1]), ("Pixel", [2]), ("Pixel", [3])]


def test_group_refuses_different_channels(tmp_path):
    from conftest import channel, fixture_xml, write_gdtf
    geos = '<Geometry Name="Body"><Beam Name="P1"/><Beam Name="P2"/></Geometry>'
    chans = channel("P1", "Dimmer", 1) + channel("P2", "Shutter1", 2)
    ft = gdtf.load(write_gdtf(tmp_path / "d.gdtf", fixture_xml(
        "D", geos, f'<DMXMode Name="M" Geometry="Body"><DMXChannels>{chans}</DMXChannels></DMXMode>')))
    with pytest.raises(geotree.MoveError, match="mêmes canaux"):
        geotree.group(ft, list(ft.geometry("Body").children), "P")


def test_duplicate_reference(good_bar):
    """GoodBar : 4 pixels RGB en références (pas de 3) -> 2 de plus à 13 et 16."""
    ft = gdtf.load(good_bar)
    p4 = ft.geometry("Pixel4")
    assert geotree.duplicate_steps(ft, p4) == [3]
    new, msg = geotree.duplicate(ft, p4, 2)
    body = new.geometry("Body")
    assert [g.name for g in body.children] == [f"Pixel{i}" for i in range(1, 7)]
    assert [g.breaks[0].dmx_offset for g in body.children] == [1, 4, 7, 10, 13, 16]
    inst = compare.instances(new, new.modes[0])
    assert [s.coarse for s in inst.children[5].slots] == [16, 17, 18]
    assert "attention" not in msg
    new2, msg2 = geotree.duplicate(new, new.geometry("Pixel2"), 1)  # tombe sur Pixel3
    assert "attention" in msg2


def test_duplicate_two_breaks_like_itetra(tmp_path):
    """Deux Break (RGBW pas 4 en DMXBreak=1, RGB pas 3 en Overwrite) : chacun garde son pas."""
    from conftest import channel, fixture_xml, write_gdtf
    ref = ('<GeometryReference Name="P01" Geometry="Px"><Break DMXOffset="1" DMXBreak="1"/>'
           '<Break DMXOffset="1" DMXBreak="1"/></GeometryReference>')
    geos = f'<Geometry Name="Body">{ref}</Geometry><Beam Name="Px"/>'
    rgbw = "".join(channel("Px", a, k, "1") for k, a in enumerate(("ColorAdd_R", "ColorAdd_G", "ColorAdd_B", "Dimmer"), 1))
    rgb = "".join(channel("Px", a, k, "Overwrite") for k, a in enumerate(("ColorAdd_R", "ColorAdd_G", "ColorAdd_B"), 1))
    modes = (f'<DMXMode Name="RGBW" Geometry="Body"><DMXChannels>{rgbw}</DMXChannels></DMXMode>'
             f'<DMXMode Name="RGB" Geometry="Body"><DMXChannels>{rgb}</DMXChannels></DMXMode>')
    ft = gdtf.load(write_gdtf(tmp_path / "i.gdtf", fixture_xml("I", geos, modes)))
    assert geotree.duplicate_steps(ft, ft.geometry("P01")) == [4, 3]
    new, _ = geotree.duplicate(ft, ft.geometry("P01"), 2)
    assert [[b.dmx_offset for b in g.breaks] for g in new.geometry("Body").children] == [[1, 1], [5, 4], [9, 7]]
    assert [g.name for g in new.geometry("Body").children] == ["P01", "P02", "P03"]


def test_arrange_inside_model(tmp_path):
    """Masters A/B = 2 références au même modèle ; ranger les pixels sous le segment dans le
    modèle les range pour A et pour B (sous-instances 1.1.x et 1.2.x)."""
    from conftest import channel, fixture_xml, write_gdtf
    model = ('<Geometry Name="Section"><Beam Name="Seg"/><Geometry Name="Pixels">'
             '<Beam Name="Px1"/><Beam Name="Px2"/></Geometry></Geometry>')
    refs = ''.join(f'<GeometryReference Name="{n}" Geometry="Section"><Break DMXOffset="{o}" DMXBreak="1"/>'
                   '</GeometryReference>' for n, o in (("A", 1), ("B", 4)))
    geos = f'<Geometry Name="Root">{refs}</Geometry>{model}'
    chans = (channel("Seg", "Dimmer", 1, "Overwrite") + channel("Px1", "ColorAdd_R", 2, "Overwrite")
             + channel("Px2", "ColorAdd_R", 3, "Overwrite"))
    ft = gdtf.load(write_gdtf(tmp_path / "s.gdtf", fixture_xml(
        "S", geos, f'<DMXMode Name="M" Geometry="Root"><DMXChannels>{chans}</DMXChannels></DMXMode>')))
    assert [i for i, _ in _ids(ft)] == ["1", "1.1", "1.2", "1.3", "1.4", "1.5", "1.6"]
    seg = ft.geometry("Seg")
    geotree.move(ft, list(ft.geometry("Pixels").children), seg, 0)
    tree = compare.instances(ft, ft.modes[0])
    assert [(i.ident, i.name, [s.coarse for s in i.slots]) for i in tree.walk()] == [
        ("1", "Root", []), ("1.1", "Seg", [1]), ("1.1.1", "Px1", [2]), ("1.1.2", "Px2", [3]),
        ("1.2", "Seg", [4]), ("1.2.1", "Px1", [5]), ("1.2.2", "Px2", [6])]
    with pytest.raises(geotree.MoveError, match="même arbre"):
        geotree.move(ft, [seg], ft.geometry("Root"), 0)


def test_edit_rename_kind_address(good_bar):
    ft = gdtf.load(good_bar)
    new, msg = geotree.apply_edit(ft, ft.geometry("Pixel2"), geotree.Edit(breaks=[20]))
    assert new.geometry("Pixel2").breaks[0].dmx_offset == 20
    # renommer le modèle : références, canaux et relations suivent
    new, msg = geotree.apply_edit(new, new.top_level("Pixel"), geotree.Edit(name="Px", kind="Geometry"))
    assert new.top_level("Px").kind == "Geometry"
    assert {g.reference for g in new.geometry("Body").children} == {"Px"}
    assert {c.geometry for c in new.modes[0].channels} == {"Body", "Px"}
    assert all(r.follower.startswith("Px_") for r in new.modes[0].relations)
    assert [s.coarse for s in compare.instances(new, new.modes[0]).children[1].slots] == [20, 21, 22]
    with pytest.raises(geotree.MoveError):
        geotree.apply_edit(new, new.geometry("Pixel1"), geotree.Edit(kind="Beam"))  # référence


def test_edit_shift_channels_and_grid(bad_bar):
    ft = gdtf.load(bad_bar)
    new, _ = geotree.apply_edit(ft, ft.geometry("Pixel1"), geotree.Edit(start=("12ch", 13), grid=(0, 0)))
    assert [c.offset for c in new.modes[0].channels if c.geometry == "Pixel1"] == [[13], [14], [15]]
    el = geotree.element_of(new, new.geometry("Pixel1"))
    assert (el.get("GridAuto"), el.get("GridX"), el.get("GridZ")) == ("Manual", "0", "0")
    assert geotree.grid_proposal(new.geometry("Pixel3")) == (2, 0)  # pas de position : dans l'ordre


def test_strip_3d_per_mode(tmp_path):
    """Nando 502 : les références LED portent des canaux en mode Pixel, pas en mode Standard
    (la tête porte tout). On ne les retire que là où elles ne servent pas."""
    from conftest import channel, fixture_xml, write_gdtf
    refs = lambda t: "".join(f'<GeometryReference Name="L{i} {t}" Geometry="LED"><Break DMXOffset="{i + 1}" DMXBreak="1"/>'
                             "</GeometryReference>" for i in range(1, 4))
    geos = (f'<Geometry Name="Base Px"><Axis Name="Head Px">{refs("Px")}</Axis></Geometry>'
            f'<Geometry Name="Base Std"><Axis Name="Head Std">{refs("Std")}<Beam Name="Lens Std"/></Axis>'
            '<Geometry Name="Pigtail Std"><WiringObject Name="DMX IN"/></Geometry></Geometry>'
            '<Beam Name="LED"/><Geometry Name="Unused"/>')
    px = channel("Head Px", "Dimmer", 1) + channel("LED", "ColorAdd_R", 1, "Overwrite")
    std = channel("Head Std", "Dimmer", 1)
    modes = (f'<DMXMode Name="Pixel" Geometry="Base Px"><DMXChannels>{px}</DMXChannels></DMXMode>'
             f'<DMXMode Name="Standard" Geometry="Base Std"><DMXChannels>{std}</DMXChannels></DMXMode>')
    ft = gdtf.load(write_gdtf(tmp_path / "n.gdtf", fixture_xml("N", geos, modes)))
    gone = {g.name for g in geotree.channel_less(ft)}
    assert gone == {"L1 Std", "L2 Std", "L3 Std", "Lens Std", "Pigtail Std", "Unused"}
    before = {m.name: compare.instances(ft, m) for m in ft.modes}
    ft2, msg = geotree.strip_3d(ft)
    assert "7 géométries" in msg
    assert ft2.geometry("L1 Px") is not None and ft2.top_level("LED") is not None
    for m in ft2.modes:
        a = [(i.ident, [(s.attribute, s.addresses) for s in i.slots]) for i in compare.flatten(before[m.name])]
        b = [(i.ident, [(s.attribute, s.addresses) for s in i.slots])
             for i in compare.flatten(compare.instances(ft2, m))]
        assert a == b
    assert geotree.strip_3d(ft2)[1].startswith("Rien")


def test_split_per_mode_itetra_style(tmp_path):
    """Un arbre pour deux modes, deux Breaks par référence (RGBW au pas de 4, RGB en Overwrite
    au pas de 3) : chaque mode reçoit sa base et chaque référence ne garde que son Break."""
    refs = "".join(f'<GeometryReference Name="P{i}" Geometry="Px"><Break DMXOffset="{4 * i - 2}" DMXBreak="1"/>'
                   f'<Break DMXOffset="{3 * i - 1}" DMXBreak="1"/></GeometryReference>' for i in range(1, 4))
    geos = f'<Geometry Name="Base">{refs}</Geometry><Beam Name="Px"/>'
    rgbw = channel("Base", "Dimmer", 1) + "".join(
        channel("Px", a, k, "1") for k, a in enumerate(("ColorAdd_R", "ColorAdd_G", "ColorAdd_B", "Shutter1"), 1))
    rgb = channel("Base", "Dimmer", 1) + "".join(
        channel("Px", a, k, "Overwrite") for k, a in enumerate(("ColorAdd_R", "ColorAdd_G", "ColorAdd_B"), 1))
    rel = '<Relations><Relation Name="r" Master="Base_Dimmer" Follower="Px_ColorAdd_R.ColorAdd_R.ColorAdd_R 1" Type="Multiply"/></Relations>'
    modes = (f'<DMXMode Name="RGBW" Geometry="Base"><DMXChannels>{rgbw}</DMXChannels>{rel}</DMXMode>'
             f'<DMXMode Name="RGB" Geometry="Base"><DMXChannels>{rgb}</DMXChannels>{rel}</DMXMode>')
    ft = gdtf.load(write_gdtf(tmp_path / "t.gdtf", fixture_xml("T", geos, modes)))
    assert geotree.shared_trees(ft) == {"Base": ["RGBW", "RGB"]}
    sig = lambda f, m: [(i.ident, [(s.attribute, s.addresses) for s in i.slots])
                        for i in compare.flatten(compare.instances(f, m))]
    before = {m.name: sig(ft, m) for m in ft.modes}
    ft2, msg = geotree.split_per_mode(ft)
    assert msg.startswith("1 base")
    assert [m.geometry for m in ft2.modes] == ["Base RGBW", "Base RGB"]
    assert [[b.dmx_offset for b in g.breaks] for g in ft2.top_level("Base RGBW").children] == [[2], [6], [10]]
    assert [[b.dmx_offset for b in g.breaks] for g in ft2.top_level("Base RGB").children] == [[2], [5], [8]]
    assert {m.name: sig(ft2, m) for m in ft2.modes} == before
    rel2 = ft2.xml_root.findall(".//DMXMode")[1].find("Relations/Relation")
    assert rel2.get("Master") == "Base RGB_Dimmer" and rel2.get("Follower").startswith("Px_ColorAdd_R")
    assert geotree.split_per_mode(ft2)[1].startswith("Chaque mode")


def _ma3_wash(tmp_path):
    """Lyre wash MA3 façon Quantum Wash : 3 anneaux RGB (adresses à l'envers) + dimmer virtuel,
    un mode Basic sans canal sur les anneaux, un mode Extended avec."""
    def ch(geo, attr, coarse=None):
        c = f' Coarse="{coarse}"' if coarse else ""
        return (f'<DMXChannel{c} Geometry="{geo}"><LogicalChannel Attribute="{attr}">'
                f'<ChannelFunction Name="{attr}" Attribute="{attr}"/></LogicalChannel></DMXChannel>')
    head = "Base.Yoke.Head"
    rings = "".join(f'<Geometry Name="Ring {i}" GridAuto="Manual" GridX="0" GridY="{i - 1}" GridZ="0"/>'
                    for i in (1, 2, 3))
    ext = ch("Base", "Dimmer", 1) + ch("Base.Yoke", "Pan", 2) + ch(head, "Tilt", 3)
    rel = ""
    for i, start in ((3, 4), (2, 7), (1, 10)):
        ext += ch(f"{head}.Ring {i}", "Dimmer") + "".join(
            ch(f"{head}.Ring {i}", a, start + k) for k, a in enumerate(("ColorRGB_R", "ColorRGB_G", "ColorRGB_B")))
        rel += f'<Relation Name="R{i}" Master="Ring {i}_Dimmer" Follower="Ring {i}_ColorRGB_R.ColorRGB_R.ColorRGB_R" Type="Multiply"/>'
    basic = ch(head, "Dimmer", 1) + ch("Base.Yoke", "Pan", 2) + ch(head, "Tilt", 3)
    defs = "".join(f'<Attribute Name="{a}" Pretty="{a}" Feature="{f}"/>' for a, f in (
        ("Dimmer", "Dimmer.Dimmer"), ("Pan", "Position.PanTilt"), ("Tilt", "Position.PanTilt"),
        ("ColorRGB_R", "Color.RGB"), ("ColorRGB_G", "Color.RGB"), ("ColorRGB_B", "Color.RGB")))
    xml = ('<GMA3 DataVersion="2.3.2.0"><FixtureType Name="Wash" Manufacturer="T">'
           f'<AttributeDefinitions><FeatureGroups/><Attributes>{defs}</Attributes></AttributeDefinitions>'
           '<Geometries>'
           '<Geometry Name="Base" Model="Base"><Geometry Name="Yoke" PosZ="-0.1000">'
           f'<Geometry Name="Head" PosZ="-0.2800">{rings}</Geometry></Geometry></Geometry></Geometries>'
           f'<DMXModes><DMXMode Name="Basic" Geometry="Base"><DMXChannels>{basic}</DMXChannels></DMXMode>'
           f'<DMXMode Name="Extended" Geometry="Base"><DMXChannels>{ext}</DMXChannels>'
           f'<Relations>{rel}</Relations></DMXMode></DMXModes></FixtureType></GMA3>')
    path = tmp_path / "wash.xml"
    path.write_text(xml, encoding="utf-8")
    return gdtf.load(path)


def _rings(ft, mode="Extended"):
    m = ft.mode(mode)
    return [(i.name, [(s.attribute, s.addresses) for s in i.slots])
            for i in compare.flatten(compare.instances(ft, m)) if i.name.startswith("Ring")]


def test_group_on_ma3_xml(tmp_path):
    """XML MA3 (fichier venu de la console) : modèle + références, mêmes adresses."""
    ft = _ma3_wash(tmp_path)
    before = _rings(ft)
    rings = [ft.geometry(f"Ring {i}") for i in (1, 2, 3)]
    new, msg = geotree.group(ft, rings, "Ring")
    assert "3 références" in msg and new.format == "ma3"
    assert _rings(new) == before
    node = new.xml_root.find("FixtureType")
    assert node.find("Geometries")[0].get("Name") == "Ring"  # modèles en tête, comme la console
    refs = node.findall(".//GeometryReference")
    assert [(r.get("Name"), r.get("GridY"), [b.attrib for b in r]) for r in refs] == [
        ("Ring 1", "0", [{"DMXPatch": "10"}]), ("Ring 2", "1", [{"DMXPatch": "7"}]),
        ("Ring 3", "2", [{"DMXPatch": "4"}])]
    chans = [(c.get("Geometry"), c.get("Coarse")) for c in node.iterfind(".//DMXMode[@Name='Extended']//DMXChannel")]
    assert chans[3:] == [("Ring", None), ("Ring", "1"), ("Ring", "2"), ("Ring", "3")]
    rels = node.findall(".//DMXMode[@Name='Extended']/Relations/Relation")
    assert [(r.get("Master"), r.get("Follower")) for r in rels] == [("Ring_Dimmer", "Ring_ColorRGB_R.ColorRGB_R.ColorRGB_R")]


def test_new_reference_then_to_reference_on_ma3(tmp_path):
    """« Nouveau modèle… » sur un seul anneau, puis les deux autres pris comme références."""
    ft = _ma3_wash(tmp_path)
    before = _rings(ft)
    ft, _ = geotree.group(ft, [ft.geometry("Ring 1")], "Ring")
    ft, msg = geotree.to_reference(ft, [ft.geometry("Ring 2"), ft.geometry("Ring 3")], "Ring")
    assert "adresses 7, 4" in msg
    assert _rings(ft) == before
    assert [b.dmx_offset for i in (1, 2, 3) for b in ft.geometry(f"Ring {i}").breaks] == [10, 7, 4]


def test_split_per_mode_on_ma3(tmp_path):
    """Une base par mode sur un XML MA3 : les chemins pointés des canaux suivent."""
    ft = _ma3_wash(tmp_path)
    before = {m.name: _rings(ft, m.name) for m in ft.modes}
    new, msg = geotree.split_per_mode(ft)
    assert "1 base" in msg
    assert [m.geometry for m in new.modes] == ["Base Basic", "Base Extended"]
    paths = {c.get("Geometry") for c in new.xml_root.iter("DMXChannel")}
    assert "Base Extended.Yoke Extended.Head Extended.Ring 2 Extended" in paths
    assert not any(p.startswith("Base.") or p == "Base" for p in paths)
    rings = [new.geometry(f"Ring {i} Extended") for i in (1, 2, 3)]
    grouped, _ = geotree.group(new, rings, "Ring")
    assert [a for _, a in _rings(grouped)] == [a for _, a in before["Extended"]]


def test_ma3_empty_break_gets_dmxpatch(tmp_path):
    """XML MA3 : un <Break/> vide (adresse 1) prend DMXPatch, jamais DMXOffset (attribut GDTF)."""
    ft = _ma3_wash(tmp_path)
    ft, _ = geotree.group(ft, [ft.geometry("Ring 1")], "Ring")
    el = geotree.element_of(ft, ft.geometry("Ring 1")).find("Break")
    el.attrib.clear()  # comme la console : premier pixel en <Break/>
    ft = geotree.restore(ft, geotree.snapshot(ft))
    new, _ = geotree.apply_edit(ft, ft.geometry("Ring 1"), geotree.Edit(breaks=[40]))
    assert geotree.element_of(new, new.geometry("Ring 1")).find("Break").attrib == {"DMXPatch": "40"}
    dup, _ = geotree.duplicate(new, new.geometry("Ring 1"), 1, [4])
    assert not any(b.get("DMXOffset") for b in dup.xml_root.iter("Break"))


def test_grid_z(tmp_path):
    """Jo (13/11/2026) : la grille a aussi un Z."""
    ft = _ma3_wash(tmp_path)
    new, msg = geotree.apply_edit(ft, ft.geometry("Ring 2"), geotree.Edit(grid=(1, 2, 3)))
    el = geotree.element_of(new, new.geometry("Ring 2"))
    assert (el.get("GridAuto"), el.get("GridX"), el.get("GridY"), el.get("GridZ")) == ("Manual", "1", "2", "3")
    assert "grille 1,2,3" in msg


def test_charte_lue_sur_ma3(tmp_path):
    """Le panneau liste les canaux d'un XML de console."""
    from ma3lib import charte_dmx
    ft = _ma3_wash(tmp_path)
    rows = charte_dmx.lignes(ft, "Extended", ft.geometry("Ring 2"))
    assert [(r.attribute, r.offsets) for r in rows] == [
        ("ColorRGB_R", [7]), ("ColorRGB_G", [8]), ("ColorRGB_B", [9]), ("Dimmer", [])]
    assert charte_dmx.libre(ft, "Extended", "Ring 2") == 13


def test_charte_corrigee_sur_ma3(tmp_path):
    """Jo (13/11/2026) : repatcher canal par canal sur les fichiers de la console aussi."""
    from ma3lib import charte_dmx
    ft = _ma3_wash(tmp_path)
    ft, msg = charte_dmx.modifier(ft, "Extended", "Head", "Tilt", offsets=[3, 13], default="128/1")
    ch = next(c for c in ft.xml_root.iterfind(".//DMXMode[@Name='Extended']//DMXChannel")
              if c.get("Geometry") == "Base.Yoke.Head")
    assert (ch.get("Coarse"), ch.get("Fine"), ch.get("Offset")) == ("3", "13", None)
    assert ch.find("LogicalChannel/ChannelFunction").get("Default") == "808080"
    with pytest.raises(geotree.MoveError, match="déjà prise"):
        charte_dmx.modifier(ft, "Extended", "Head", "Tilt", offsets=[4])
    ft, _ = charte_dmx.ajouter(ft, "Extended", "Head", "Zoom", [14])
    z = [c for c in ft.xml_root.iterfind(".//DMXMode[@Name='Extended']//DMXChannel")
         if c.find("LogicalChannel").get("Attribute") == "Zoom"][0]
    assert z.get("Geometry") == "Base.Yoke.Head" and z.get("Coarse") == "14" and z.get("DefaultChannelFunction") == "Zoom.Zoom 1"
    assert [(r.attribute, r.offsets) for r in charte_dmx.lignes(ft, "Extended", ft.geometry("Head"))] == [
        ("Tilt", [3, 13]), ("Zoom", [14])]
    ft, _ = charte_dmx.modifier(ft, "Extended", "Ring 1", "ColorRGB_R", new_attribute="ColorRGB_W")
    rel = ft.xml_root.find(".//DMXMode[@Name='Extended']/Relations/Relation[@Name='R1']")
    assert rel.get("Follower") == "Ring 1_ColorRGB_W.ColorRGB_W.ColorRGB_W"
    ft, msg = charte_dmx.retirer(ft, "Extended", "Head", "Zoom")
    assert "retiré" in msg and charte_dmx.libre(ft, "Extended", "Head") == 14
    with pytest.raises(geotree.MoveError, match="hexa"):
        charte_dmx.modifier(ft, "Extended", "Head", "Tilt", default="zz")


def test_nouvelle_geometrie_posee_dans_l_arbre(tmp_path):
    """Zone « Géométries disponibles » : une géométrie neuve (nom + type) posée dans l'arbre."""
    ft = _ma3_wash(tmp_path)
    head = ft.geometry("Head")
    el = geotree.new_geometry(ft, "Ring 1", "Beam")  # nom déjà pris -> « Ring 1 2 »
    new, msg = geotree.add_geometry(ft, el, head, 1, mesh="Cube")
    assert [g.name for g in new.geometry("Head").children] == ["Ring 1", "Ring 1 2", "Ring 2", "Ring 3"]
    g = new.geometry("Ring 1 2")
    assert g.kind == "Beam" and g.model == "Cube" and "nom déjà pris" in msg
    assert _rings(new) == _rings(ft)  # rien ne bouge sur les canaux
    with pytest.raises(geotree.MoveError, match="modèle"):
        geotree.new_geometry(ft, "R", "GeometryReference")
    grouped, _ = geotree.group(ft, [ft.geometry("Ring 1")], "Ring")
    ref = geotree.new_geometry(grouped, "Ring 4", "GeometryReference", "Ring")
    new2, msg2 = geotree.add_geometry(grouped, ref, grouped.geometry("Head"), 3)
    r4 = new2.geometry("Ring 4")
    assert r4.is_reference and r4.reference == "Ring" and r4.breaks[0].dmx_offset == 1 and "patch" in msg2
    with pytest.raises(geotree.MoveError, match="référence"):
        geotree.add_geometry(new2, geotree.new_geometry(new2, "X", "Beam"), r4, 0)


def test_importer_une_geometrie_d_un_autre_fichier(tmp_path, good_bar):
    """Import d'un GDTF vers un XML MA3 : sous-arbre copié, références recopiées, position convertie."""
    ft = _ma3_wash(tmp_path)
    other = geotree.importable(good_bar)
    body = other.geometry("Body")
    el = geotree.take_geometry(other, body, ft)
    assert [x.tag for x in el] == ["Beam"] * 4  # les 4 références Pixel deviennent des Beams
    assert not list(el.iter("Break"))
    new, msg = geotree.add_geometry(ft, el, ft.geometry("Head"), 0)
    assert [g.name for g in new.geometry("Body").children] == [f"Pixel{i}" for i in range(1, 5)]
    assert "5 géométries" in msg
    one = geotree.take_geometry(other, other.geometry("Pixel2"), ft)  # une référence seule
    assert one.tag == "Beam" and one.get("Name") == "Pixel2"
