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


@pytest.fixture
def tricky(tmp_path):
    """Cas vus sur de vrais GDTF : variantes par mode, enveloppes de références, connecteurs."""
    wraps = "".join(f'<Geometry Name="Group_{i}"><GeometryReference Name="Px_{i}" Geometry="Px"/></Geometry>'
                    for i in range(1, 4))
    geos = (f'<Geometry Name="Base">{wraps}'
            '<WiringObject Name="DMX 5Pin IN"/><WiringObject Name="DMX 3Pin IN"/></Geometry>'
            '<Beam Name="Px"/>'
            '<Geometry Name="Head Mode 1"><Beam Name="Lens"/></Geometry>'
            '<Geometry Name="Head Mode 2"><Beam Name="Lens2"/></Geometry>')
    wrap_chans = "".join(channel(f"Group_{i}", a, 3 * (i - 1) + k)
                         for i in range(1, 4) for k, a in enumerate(("ColorAdd_R", "ColorAdd_G", "ColorAdd_B"), 1))
    modes = (f'<DMXMode Name="A" Geometry="Base"><DMXChannels>{wrap_chans}</DMXChannels></DMXMode>'
             f'<DMXMode Name="M1" Geometry="Head Mode 1"><DMXChannels>{channel("Head Mode 1", "Dimmer", 1)}</DMXChannels></DMXMode>'
             f'<DMXMode Name="M2" Geometry="Head Mode 2"><DMXChannels>{channel("Head Mode 2", "Dimmer", 1)}'
             f'{channel("Lens2", "Shutter1", 2)}</DMXChannels></DMXMode>')
    return write_gdtf(tmp_path / "Test@Tricky.gdtf", fixture_xml("Tricky", geos, modes))


@pytest.fixture(autouse=True)
def _qt_cleanup():
    """Détruit les fenêtres Qt à la fin de chaque test : sinon Python les libère dans le
    désordre à la sortie et le processus plante (code de sortie non nul malgré les tests verts)."""
    yield
    try:
        from PySide6.QtCore import QCoreApplication, QEvent
        from PySide6.QtWidgets import QApplication
    except ImportError:
        return
    app = QApplication.instance()
    if app is None:
        return
    for w in app.topLevelWidgets():
        w.close()
        w.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()
