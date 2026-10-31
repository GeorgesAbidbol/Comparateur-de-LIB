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
