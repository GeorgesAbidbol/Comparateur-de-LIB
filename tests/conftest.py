"""Fabrique de petits fichiers GDTF synthétiques pour les tests."""

import zipfile
from pathlib import Path

import pytest

HEADER = '<?xml version="1.0" encoding="UTF-8"?>\n<GDTF DataVersion="1.2">'
ATTRS = """
<AttributeDefinitions><Attributes>
  <Attribute Name="Dimmer" Pretty="Dim" Feature="Dimmer.Dimmer"/>
  <Attribute Name="ColorAdd_R" Pretty="R" Feature="Color.RGB"/>
  <Attribute Name="ColorAdd_G" Pretty="G" Feature="Color.RGB"/>
  <Attribute Name="ColorAdd_B" Pretty="B" Feature="Color.RGB"/>
  <Attribute Name="Shutter1" Pretty="Sh1" Feature="Beam.Beam"/>
</Attributes></AttributeDefinitions>"""


def channel(geo, attr, offset, brk=None):
    b = f' DMXBreak="{brk}"' if brk else ""
    off = f' Offset="{offset}"' if offset else ' Offset="None"'
    return (f'<DMXChannel Geometry="{geo}"{off}{b}><LogicalChannel Attribute="{attr}">'
            f'<ChannelFunction Name="{attr} 1" Attribute="{attr}" DMXFrom="0/1"/>'
            f"</LogicalChannel></DMXChannel>")


def fixture_xml(name, geometries, modes):
    return (f'{HEADER}<FixtureType Name="{name}" Manufacturer="Test" ShortName="{name}" '
            f'FixtureTypeID="00000000-0000-0000-0000-000000000000">{ATTRS}'
            f"<Geometries>{geometries}</Geometries><DMXModes>{modes}</DMXModes></FixtureType></GDTF>")


def write_gdtf(path: Path, xml: str) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("description.xml", xml)
    return path


@pytest.fixture
def bad_bar(tmp_path):
    """Barre 4 pixels « mal faite » : pixels copiés, pas de références, pas de dimmer."""
    pixels = "".join(f'<Beam Name="Pixel{i}" Model="Pixel"/>' for i in range(1, 5))
    chans = "".join(channel(f"Pixel{i}", a, 3 * (i - 1) + k)
                    for i in range(1, 5) for k, a in enumerate(("ColorAdd_R", "ColorAdd_G", "ColorAdd_B"), 1))
    xml = fixture_xml("BadBar", f'<Geometry Name="Body" Model="Body">{pixels}</Geometry>',
                      f'<DMXMode Name="12ch" Geometry="Body"><DMXChannels>{chans}</DMXChannels></DMXMode>')
    return write_gdtf(tmp_path / "Test@BadBar.gdtf", xml)


@pytest.fixture
def good_bar(tmp_path):
    """Même barre, faite proprement : 1 modèle Pixel + 4 références + dimmer virtuel."""
    refs = "".join(f'<GeometryReference Name="Pixel{i}" Geometry="Pixel"><Break DMXOffset="{3 * (i - 1) + 1}" DMXBreak="1"/>'
                   f"</GeometryReference>" for i in range(1, 5))
    geos = f'<Geometry Name="Body" Model="Body">{refs}</Geometry><Beam Name="Pixel" Model="Pixel"/>'
    chans = channel("Body", "Dimmer", None) + "".join(
        channel("Pixel", a, k, "Overwrite") for k, a in enumerate(("ColorAdd_R", "ColorAdd_G", "ColorAdd_B"), 1))
    rel = "".join(f'<Relation Name="VirtualDimmer" Master="Body_Dimmer" Follower="Pixel_{a}.{a}.{a} 1" Type="Multiply"/>'
                  for a in ("ColorAdd_R", "ColorAdd_G", "ColorAdd_B"))
    xml = fixture_xml("GoodBar", geos,
                      f'<DMXMode Name="12ch" Geometry="Body"><DMXChannels>{chans}</DMXChannels>'
                      f"<Relations>{rel}</Relations></DMXMode>")
    return write_gdtf(tmp_path / "Test@GoodBar.gdtf", xml)


@pytest.fixture
def broken(tmp_path):
    """Erreurs de structure : référence cassée, nom dupliqué, canal orphelin."""
    geos = ('<Geometry Name="Body"><Geometry Name="Head"/><Geometry Name="Head"/>'
            '<GeometryReference Name="R1" Geometry="Nope"/></Geometry><Geometry Name="Unused"/>')
    xml = fixture_xml("Broken", geos,
                      f'<DMXMode Name="M" Geometry="Body"><DMXChannels>{channel("Ghost", "Dimmer", 1)}'
                      f"</DMXChannels></DMXMode>")
    return write_gdtf(tmp_path / "Test@Broken.gdtf", xml)
