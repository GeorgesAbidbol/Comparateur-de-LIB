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
