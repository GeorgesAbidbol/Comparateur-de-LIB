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
