import zipfile

import pytest

from conftest import fixture_xml, write_gdtf
from ma3lib import attributs, diagnostic, gdtf, remap

ATTR_DEFS = """<AttributeDefinitions>
<ActivationGroups><ActivationGroup Name="PanTilt"/></ActivationGroups>
<FeatureGroups><FeatureGroup Name="Dimmer"><Feature Name="Dimmer"/></FeatureGroup>
<FeatureGroup Name="Color"><Feature Name="Color"/></FeatureGroup></FeatureGroups>
<Attributes>
  <Attribute Name="Dimmer" Pretty="Dim" Feature="Dimmer.Dimmer"/>
  <Attribute Name="Led Control" Pretty="Led Control" Feature="Dimmer.Dimmer"/>
  <Attribute Name="color fade" Pretty="Fade" Feature="Color.Color" ActivationGroup="PanTilt"/>
</Attributes></AttributeDefinitions>"""


def _chan(geo, attr, offset, function_attr=None, extra=""):
    fa = function_attr or attr
    return (f'<DMXChannel Geometry="{geo}" Offset="{offset}" '
            f'InitialFunction="{geo}_{attr}.{attr}.Mode 1"{extra}>'
            f'<LogicalChannel Attribute="{attr}"><ChannelFunction Name="Mode 1" Attribute="{fa}"/>'
            f"</LogicalChannel></DMXChannel>")


@pytest.fixture
def custom(tmp_path):
    chans = (_chan("Body", "Dimmer", "1") + _chan("Body", "Led Control", "2", "LEDZoneMode")
             + _chan("Body", "color fade", "3"))
    rel = '<Relations><Relation Name="r" Master="Body_Led Control" Follower="Body_Dimmer.Dimmer.Mode 1" Type="Multiply"/></Relations>'
    xml = fixture_xml("Custom", '<Geometry Name="Body"/>',
                      f'<DMXMode Name="M" Geometry="Body"><DMXChannels>{chans}</DMXChannels>{rel}</DMXMode>')
    xml = xml.replace(xml[xml.index("<AttributeDefinitions>"):xml.index("</AttributeDefinitions>") + 23], ATTR_DEFS)
    path = write_gdtf(tmp_path / "custom.gdtf", xml)
    with zipfile.ZipFile(path, "a") as zf:
        zf.writestr("models/3ds/body.3ds", b"maillage")
    return path


def test_reference_tables():
    assert attributs.gdtf_standard("Gobo3")["name"] == "Gobo(n)"
    assert attributs.gdtf_standard("ColorRGB_R")["feature"] == "Color.RGB"
    assert attributs.gdtf_standard("Led Control") is None
    assert attributs.ma3_name("ColorSub_C") == "ColorRGB_R"
    assert attributs.ma3_known("ColorSub_C") is not None


def test_detects_misfiled(custom):
    issues = {i.attribute: i for i in attributs.check(gdtf.load(custom))}
    assert issues["Led Control"].level == "alerte" and issues["Led Control"].rename == "LEDZoneMode"
    assert issues["color fade"].level == "alerte" and issues["color fade"].new_group == ""
    assert "Dimmer" not in issues
    codes = [f.code for f in diagnostic.diagnose(gdtf.load(custom))]
    assert "attributs_mal_ranges" in codes


def test_remap_renames_channels_and_links(custom, tmp_path):
    ft = gdtf.load(custom)
    log = remap.apply(ft, remap.rules_from_issues(attributs.check(ft)))
    assert any("renommé" in l for l in log)
    out = remap.save(ft, tmp_path / "out.gdtf")
    ft2 = gdtf.load(out)
    assert [i for i in attributs.check(ft2) if i.level == "alerte"] == []
    assert ft2.attributes["LEDZoneMode"].feature == "Control.Control"
    assert "Led Control" not in ft2.attributes
    assert "ActivationGroup" not in ft2.xml_root.find(".//Attribute[@Name='color fade']").attrib
    xml = zipfile.ZipFile(out).read("description.xml").decode()
    assert 'Master="Body_LEDZoneMode"' in xml
    assert 'InitialFunction="Body_LEDZoneMode.LEDZoneMode.Mode 1"' in xml
    assert "Led Control" not in xml
    assert zipfile.ZipFile(out).read("models/3ds/body.3ds") == b"maillage"


def test_remap_refuses_collision_and_overwrite(custom, tmp_path):
    ft = gdtf.load(custom)
    with pytest.raises(remap.RemapError):
        remap.apply(ft, [remap.Rule("Led Control", rename="Dimmer")])
    with pytest.raises(remap.RemapError):
        remap.save(gdtf.load(custom), custom)


def test_rules_csv(tmp_path):
    p = tmp_path / "r.csv"
    p.write_text("attribut;nouveau_nom;feature;groupe\n# commentaire\nLed Control;LEDZoneMode;;\n"
                 "color fade;;Control.Control;-\n", encoding="utf-8")
    r = remap.load_rules(p)
    assert r[0].rename == "LEDZoneMode" and r[0].feature is None and r[0].activation_group is None
    assert r[1].feature == "Control.Control" and r[1].activation_group == ""


def test_remap_ma3_xml(tmp_path):
    from test_gdtf import MA3_XML
    src = tmp_path / "bar.xml"
    src.write_text(MA3_XML.replace("</DMXChannels>", "</DMXChannels><Relations><Relation Name=\"r\" "
                                   "Master=\"Seg_Dimmer\" Follower=\"Px_ColorRGB_R.ColorRGB_R.R\" "
                                   "Type=\"Multiply\"/></Relations>"), encoding="utf-8")
    ft = gdtf.load(src)
    remap.apply(ft, [remap.Rule("Dimmer", rename="BackgroundDimmer", feature="Dimmer.Dimmer")])
    out = remap.save(ft, tmp_path / "bar_remap.xml")
    text = out.read_text(encoding="utf-8")
    assert text.count('DefaultChannelFunction="BackgroundDimmer.Dimmer"') == 2
    assert 'Master="Seg_BackgroundDimmer"' in text
    ft2 = gdtf.load(out)
    assert ft2.format == "ma3" and ft2.data_version == "2.3.2.0"
    assert ft2.modes[0].channels[0].attribute == "BackgroundDimmer"


def test_equivalents_for_custom_attributes():
    assert attributs.candidates("Chase Speed")[0] == "Effects1Rate"
    assert attributs.candidates("color crossfade speed", "Color.Color")[0] == "ColorMixMSpeed"
    assert "Effects1Fade" in attributs.candidates("ChaseFade")
