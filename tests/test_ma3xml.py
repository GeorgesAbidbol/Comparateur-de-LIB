"""Export XML MA3 2.3.2.0 (étape 4)."""

import xml.etree.ElementTree as ET
import zipfile

from conftest import channel, fixture_xml, write_gdtf

from ma3lib import cli, compare, gdtf, geotree, ma3xml


def _sig(ft, mode):
    root = compare.instances(ft, mode)
    return [(i.ident, i.name, [(compare._key(s.attribute), tuple(s.addresses)) for s in i.slots])
            for i in compare.flatten(root)]


def test_dmx_values_like_the_console():
    # valeurs relevées dans l'export console de l'iTetra2 et du Color Strike M
    assert ma3xml.dmx_value("32768/2") == "80007F"
    assert ma3xml.dmx_value("32769/2") == "80017F"
    assert ma3xml.dmx_value("6/1") == "060606"
    assert ma3xml.dmx_value("4294967295/4") == "FFFFFF"
    assert ma3xml.dmx_value("1/4") == "000000"
    assert ma3xml.dmx_value("655/2", virtual=True) == "028F5C"
    assert ma3xml.dmx_value("64880/2", virtual=True) == "FD70A2"
    assert ma3xml.guid_ma3("704BDFBC-AE71-4596-8FA0-F5B37D1B0C7A") == "70 4B DF BC AE 71 45 96 8F A0 F5 B3 7D 1B 0C 7A"
    assert ma3xml.color_ma3("0.312700,0.329000,100.000000").startswith("0.99984")
    assert ma3xml.file_name("Robe Lighting", "Robin iTetra2") == "Robe Lighting@Robin iTetra2.xml"


def test_good_bar_converts_with_same_instances(good_bar, tmp_path):
    ft = gdtf.load(good_bar)
    root = ma3xml.convert(ft)
    assert root.tag == "GMA3" and root.get("DataVersion") == "2.3.2.0"
    node = root.find("FixtureType")
    assert node.get("Guid") == "00 " * 15 + "00"
    chans = node.findall("DMXModes/DMXMode/DMXChannels/DMXChannel")
    pix = [c for c in chans if c.get("Geometry") == "Pixel"]
    assert [c.find("LogicalChannel").get("Attribute") for c in pix] == ["ColorRGB_R", "ColorRGB_G", "ColorRGB_B"]
    assert pix[0].get("Coarse") == "1" and "Offset" not in pix[0].attrib
    refs = node.findall(".//GeometryReference")
    assert [b.get("DMXPatch") for r in refs for b in r.findall("Break")] == [None, "4", "7", "10"]
    rel = node.find("DMXModes/DMXMode/Relations/Relation")
    assert rel.get("Follower").startswith("Pixel_ColorRGB_R.ColorRGB_R")
    # la console relit le fichier avec les mêmes instances et adresses
    out = tmp_path / "out.xml"
    out.write_bytes(ma3xml.dumps(root))
    back = gdtf.load(out)
    assert back.format == "ma3"
    for m in ft.modes:
        assert _sig(back, back.mode(m.name)) == _sig(ft, m)


def test_dotted_geometry_paths_and_header(tmp_path):
    geos = ('<Geometry Name="Base" Model="Base" Position="{1,0,0,0}{0,1,0,0}{0,0,1,-0.199}{0,0,0,1}">'
            '<Axis Name="Head"><Beam Name="Beam" BeamAngle="25" FieldAngle="40" LuminousFlux="1000"/></Axis></Geometry>')
    chans = channel("Head", "Shutter1", "1,2") + channel("Beam", "Dimmer", 3)
    xml = fixture_xml("T", geos, f'<DMXMode Name="M" Geometry="Base"><DMXChannels>{chans}</DMXChannels></DMXMode>')
    ft = gdtf.load(write_gdtf(tmp_path / "t.gdtf", xml))
    node = ma3xml.convert(ft).find("FixtureType")
    chs = node.findall(".//DMXChannel")
    assert [(c.get("Geometry"), c.get("Coarse"), c.get("Fine")) for c in chs] == [
        ("Base.Head", "1", "2"), ("Base.Head.Beam", "3", None)]
    base = node.find("Geometries/Geometry")
    assert base.get("PosZ") == "-0.1990" and base.get("GridAuto") == "Auto" and "Position" not in base.attrib
    beam = node.find(".//Beam")
    assert "BeamAngle" not in beam.attrib  # 25° = défaut console, non écrit
    assert beam.get("FieldAngle") == "40.00" and beam.get("LuminousIntensity") == "1000.0"
    assert beam.get("ThrowRatio") == "2.255"
    assert [c.tag for c in node.find("AttributeDefinitions")][0] == "DeactivationGroups"


def test_export_writes_file_and_keeps_atelier_changes(bad_bar, tmp_path):
    ft = gdtf.load(bad_bar)
    pixels = [g for g in ft.all_geometries() if g.name.startswith("Pixel")]
    geotree.group(ft, pixels, "Pixel")
    out = ma3xml.export(ft, tmp_path / "lib", name="BadBar JO", guid=ma3xml.new_guid(), note="JO")
    assert out.name == "Test@BadBar JO.xml"
    data = out.read_bytes()
    assert data.startswith(b"\xef\xbb\xbf<?xml") and b'" />' in data
    back = gdtf.load(out)
    assert back.name == "BadBar JO"
    assert sum(g.is_reference for g in back.all_geometries()) == 4
    assert _sig(back, back.modes[0]) == _sig(ft, ft.modes[0])
    node = ET.fromstring(data.decode("utf-8-sig")).find("FixtureType")
    assert node.get("Note") == "JO" and node.get("Guid") != "00 " * 15 + "00"
    # réécrire un fichier MA3 : arbre gardé, nom changé
    again = ma3xml.export(back, tmp_path / "lib", name="BadBar JO 2")
    assert gdtf.load(again).name == "BadBar JO 2"


def test_meshes_and_thumbnail_are_embedded(good_bar, tmp_path):
    src = tmp_path / "m.gdtf"
    with zipfile.ZipFile(good_bar) as zin, zipfile.ZipFile(src, "w") as zout:
        xml = zin.read("description.xml").decode().replace(
            "<Geometries>", '<Models><Model Name="Body" File="body" Length="1" Width="0.2" Height="0.1"/>'
                            '<Model Name="Pixel" PrimitiveType="Cube" Length="0.1" Width="0.1" Height="0.1"/>'
                            "</Models><Geometries>")
        zout.writestr("description.xml", xml)
        zout.writestr("models/gltf/body.glb", b"glTF" + bytes(3000))
        zout.writestr("thumbnail.png", b"\x89PNG" + bytes(10))
    node = ma3xml.convert(gdtf.load(src)).find("FixtureType")
    assert node.get("MediaFileName") == "USERSYMBOL/GoodBar_thumbnail.png"
    body, pixel = node.findall("Models/Model")
    assert body.get("File") == "USERMESH/GoodBar_body.glb"
    assert len(body.findall(".//Block")) == 3  # 3004 octets en blocs de 1024
    assert pixel.get("File") == "MESH/gdtf_generic/cube.3ds"


def test_cli_export(good_bar, tmp_path, capsys):
    assert cli.main(["export", str(good_bar), "--dossier", str(tmp_path), "--note", "JO"]) == 0
    assert (tmp_path / "Test@GoodBar.xml").exists()
    assert cli.main(["export", str(good_bar), "--dossier", str(tmp_path)]) == 1  # existe déjà
    assert cli.main(["export", str(good_bar), "--dossier", str(tmp_path), "--remplacer"]) == 0
