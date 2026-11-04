import zipfile

import pytest

from ma3lib import gdtf


def test_load_bad_bar(bad_bar):
    ft = gdtf.load(bad_bar)
    assert (ft.manufacturer, ft.name, ft.data_version) == ("Test", "BadBar", "1.2")
    assert set(ft.attributes) >= {"Dimmer", "ColorAdd_R"}
    assert [g.name for g in ft.geometries] == ["Body"]
    assert [c.name for c in ft.geometries[0].children] == ["Pixel1", "Pixel2", "Pixel3", "Pixel4"]
    mode = ft.mode("12ch")
    assert len(mode.channels) == 12
    assert mode.footprint == 12
    assert mode.channels[0].name == "Pixel1_ColorAdd_R"


def test_references_and_virtual(good_bar):
    ft = gdtf.load(good_bar)
    body = ft.top_level("Body")
    refs = [g for g in body.children if g.is_reference]
    assert len(refs) == 4 and all(r.reference == "Pixel" for r in refs)
    assert refs[2].breaks[0].dmx_offset == 7
    assert refs[2].path() == "Body / Pixel3"
    mode = ft.modes[0]
    assert mode.channels[0].is_virtual and mode.channels[0].resolution == 0
    assert mode.channels[1].dmx_break == "Overwrite"
    assert len(mode.relations) == 3


def test_not_a_gdtf(tmp_path):
    p = tmp_path / "x.gdtf"
    p.write_text("pas un zip")
    with pytest.raises(gdtf.GdtfError):
        gdtf.load(p)
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("autre.xml", "<a/>")
    with pytest.raises(gdtf.GdtfError):
        gdtf.load(p)


MA3_XML = """<?xml version="1.0" encoding="UTF-8"?>
<GMA3 DataVersion="2.3.2.0">
  <FixtureType Name="Bar" Guid="AA 47 6C 50 FE 73 43 7F 9B 4C 1B 3A 77 16 45 25" ShortName="Bar" Manufacturer="Test">
    <AttributeDefinitions><Attributes>
      <Attribute Name="Dimmer" Feature="Dimmer.Dimmer"/><Attribute Name="ColorRGB_R" Feature="Color.RGB"/>
    </Attributes></AttributeDefinitions>
    <Geometries>
      <Geometry Name="Body"><Beam Name="Seg">
        <GeometryReference Name="Px 1" Geometry="Px"><Break/></GeometryReference>
        <GeometryReference Name="Px 2" Geometry="Px"><Break DMXPatch="4"/></GeometryReference>
      </Beam></Geometry>
      <Beam Name="Px"/>
    </Geometries>
    <DMXModes><DMXMode Name="M JO" Geometry="Body" XYZ="No" DiveInto="Yes"><DMXChannels>
      <DMXChannel Coarse="1" Fine="2" DefaultChannelFunction="Dimmer.Dimmer" Geometry="Body.Seg">
        <LogicalChannel Attribute="Dimmer"><ChannelFunction Name="Dimmer" Attribute="Dimmer" Default="000000"/></LogicalChannel>
      </DMXChannel>
      <DMXChannel DefaultChannelFunction="Dimmer.Dimmer" Geometry="Px">
        <LogicalChannel Attribute="Dimmer"><ChannelFunction Name="Dimmer" Attribute="Dimmer"/></LogicalChannel>
      </DMXChannel>
      <DMXChannel Coarse="3" Geometry="Px">
        <LogicalChannel Attribute="ColorRGB_R"><ChannelFunction Name="R" Attribute="ColorRGB_R"/></LogicalChannel>
      </DMXChannel>
    </DMXChannels></DMXMode></DMXModes>
  </FixtureType>
</GMA3>"""


def test_load_ma3_xml(tmp_path):
    p = tmp_path / "test bar.xml"
    p.write_text(MA3_XML, encoding="utf-8")
    ft = gdtf.load(p)
    assert ft.format == "ma3" and ft.data_version == "2.3.2.0"
    assert ft.fixture_type_id == "AA476C50-FE73-437F-9B4C-1B3A77164525"
    ch = ft.modes[0].channels
    assert ch[0].offset == [1, 2] and ch[0].geometry == "Seg" and ch[0].geometry_path == "Body.Seg"
    assert ch[1].is_virtual
    assert [b.dmx_offset for r in ft.geometry("Seg").children for b in r.breaks] == [1, 4]
