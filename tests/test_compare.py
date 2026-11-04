from conftest import channel, fixture_xml, write_gdtf

from ma3lib import compare, gdtf


def _bar(tmp_path, name, n, extra=""):
    """Barre n pixels RGB (références) + dimmer sur le corps."""
    refs = "".join(f'<GeometryReference Name="P{i}" Geometry="Px"><Break DMXOffset="{3 * (i - 1) + 2}" DMXBreak="1"/>'
                   "</GeometryReference>" for i in range(1, n + 1))
    geos = f'<Geometry Name="Body">{refs}</Geometry><Beam Name="Px"/>'
    chans = channel("Body", "Dimmer", 1) + extra + "".join(
        channel("Px", a, k, "Overwrite") for k, a in enumerate(("ColorAdd_R", "ColorAdd_G", "ColorAdd_B"), 1))
    xml = fixture_xml(name, geos, f'<DMXMode Name="M" Geometry="Body"><DMXChannels>{chans}</DMXChannels></DMXMode>')
    ft = gdtf.load(write_gdtf(tmp_path / f"{name}.gdtf", xml))
    return compare.instances(ft, ft.modes[0])


def test_instances_have_addresses(tmp_path):
    root = _bar(tmp_path, "A", 3)
    assert [i.ident for i in root.walk()] == ["1", "1.1", "1.2", "1.3"]
    p2 = root.children[1]
    assert [(s.attribute, s.coarse) for s in p2.slots] == [("ColorAdd_R", 5), ("ColorAdd_G", 6), ("ColorAdd_B", 7)]
    assert p2.summary() == "RGB"
    assert root.summary() == "Dim"


def test_axis_merges_into_parent(tmp_path):
    """iTetra2 : Base > Axis Head (Tilt) > Background ; la console montre Tilt sur le fixture."""
    geos = '<Geometry Name="Base"><Axis Name="Head"><Beam Name="Background"/></Axis></Geometry>'
    chans = channel("Head", "Tilt", 1) + channel("Background", "Dimmer", 2)
    ft = gdtf.load(write_gdtf(tmp_path / "t.gdtf", fixture_xml(
        "T", geos, f'<DMXMode Name="M" Geometry="Base"><DMXChannels>{chans}</DMXChannels></DMXMode>')))
    root = compare.instances(ft, ft.modes[0])
    assert [s.attribute for s in root.slots] == ["Tilt"]
    assert [c.name for c in root.children] == ["Background"]


def test_auto_links_by_shared_attributes(tmp_path):
    src = _bar(tmp_path, "S", 4)
    tgt = _bar(tmp_path, "T", 6)
    links = compare.auto_links(src, tgt)
    assert links == {"1": "1", "1.1": "1.1", "1.2": "1.2", "1.3": "1.3", "1.4": "1.4"}  # 1.5 et 1.6 libres
    assert compare.spread(src, tgt)["1.6"] == "1.4"


def test_pair_rows_colors(tmp_path):
    src = _bar(tmp_path, "S", 1, channel("Body", "Shutter1", 9))
    tgt = _bar(tmp_path, "T", 1)
    rows = compare.pair_rows(src, tgt)
    assert [(r.source and r.source.attribute, r.status) for r in rows] == [("Dimmer", "vert"), ("Shutter1", "orange")]
    assert compare.instance_status(src, tgt) == "orange"
    assert compare.instance_status(tgt, src) == "vert"  # un attribut en plus dans la cible ne perd rien
    rows = compare.pair_rows(tgt, src, replaced={"Shutter1": "Dimmer"})
    assert rows[0].status == "vert"
