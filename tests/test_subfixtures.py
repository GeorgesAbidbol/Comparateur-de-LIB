from ma3lib import gdtf, subfixtures


def test_channelless_levels_collapse(tmp_path):
    """Comme le SubfixtureOverview MA3 : un niveau sans canal (Module) disparaît."""
    from conftest import channel, fixture_xml, write_gdtf
    pixels = "".join(f'<GeometryReference Name="Px {i}" Geometry="Px"/>' for i in range(1, 4))
    geos = (f'<Geometry Name="Root"><Geometry Name="Module A"><Beam Name="Seg A">{pixels}</Beam>'
            '<Geometry Name="Deco"/></Geometry></Geometry><Beam Name="Px"/>')
    chans = (channel("Root", "Shutter1", 1) + channel("Seg A", "Dimmer", 2)
             + channel("Px", "ColorAdd_R", 3, "Overwrite"))
    ft = gdtf.load(write_gdtf(tmp_path / "t.gdtf", fixture_xml(
        "Sub", geos, f'<DMXMode Name="M" Geometry="Root"><DMXChannels>{chans}</DMXChannels></DMXMode>')))
    tree = subfixtures.overview(ft, ft.modes[0])
    assert tree.attributes == ["Shutter1"]
    assert [c.name for c in tree.children] == ["Seg A"]  # Module A et Deco ont disparu
    seg = tree.children[0]
    assert seg.attributes == ["Dimmer"]
    assert [p.name for p in seg.children] == ["Px 1", "Px 2", "Px 3"]
    assert seg.children[0].attributes == ["ColorAdd_R"]
    assert subfixtures.lines(tree)[0].startswith("1 (1)    1 ")
    assert "1.1.2" in subfixtures.lines(tree)[3]
