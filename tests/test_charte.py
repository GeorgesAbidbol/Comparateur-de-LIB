from ma3lib import charte, gdtf


def write_chart(tmp_path, body):
    p = tmp_path / "c.csv"
    p.write_text("mode;canal;fine;section;fonction\n" + body, encoding="utf-8")
    return charte.load_chart(p)


def test_range_cycles_functions(tmp_path):
    rows = write_chart(tmp_path, "12ch;1-6;;;Red|Green|Blue\n")
    assert [r.function for r in rows] == ["Red", "Green", "Blue"] * 2
    assert [r.coarse for r in rows] == list(range(1, 7))


def test_bad_bar_conforms(tmp_path, bad_bar):
    ft = gdtf.load(bad_bar)
    rows = write_chart(tmp_path, "12ch;1-12;;;Red|Green|Blue\n")
    assert all(m.status == charte.OK for m in charte.compare(ft, ft.modes[0], rows))


def test_differences_found(tmp_path, bad_bar):
    ft = gdtf.load(bad_bar)
    rows = write_chart(tmp_path, "12ch;1;2;;Red\n12ch;3-12;;;Green|Red|Blue\n12ch;13;;;Dimmer\n12ch;14;;;Reserved\n")
    by_addr = {m.address: m for m in charte.compare(ft, ft.modes[0], rows)}
    assert by_addr[1].status == charte.DIFF and "16 bits" in by_addr[1].suggestion
    assert by_addr[2].status == charte.EN_TROP  # la notice en fait le Fine du canal 1
    assert by_addr[3].status == charte.DIFF and "ColorAdd_G" in by_addr[3].suggestion
    assert by_addr[4].status == charte.OK
    assert by_addr[13].status == charte.MANQUANT
    assert by_addr[14].status == charte.IGNORE


def test_references_are_unfolded(good_bar):
    ft = gdtf.load(good_bar)
    chans = charte.absolute_channels(ft, ft.modes[0])
    assert [c.addresses[0] for c in chans] == list(range(1, 13))
    assert chans[3].instance == "Pixel2" and chans[3].attributes == ["ColorAdd_R"]


def test_second_break_follows_first(tmp_path):
    """Mode « 2U » : pixels sur le break 2, que la notice numérote à la suite du break 1."""
    from conftest import channel, fixture_xml, write_gdtf
    refs = "".join(f'<GeometryReference Name="P{i}" Geometry="Pix"><Break DMXOffset="1" DMXBreak="1"/>'
                   f'<Break DMXOffset="{3 * i - 2}" DMXBreak="2"/></GeometryReference>' for i in (1, 2))
    geos = f'<Geometry Name="Body">{refs}</Geometry><Beam Name="Pix"/>'
    chans = (channel("Body", "Dimmer", "1") + channel("Body", "Pan", "2")
             + "".join(channel("Pix", a, str(k), "Overwrite") for k, a in
                       enumerate(("ColorAdd_R", "ColorAdd_G", "ColorAdd_B"), 1)))
    xml = fixture_xml("TwoU", geos, f'<DMXMode Name="2U" Geometry="Body"><DMXChannels>{chans}</DMXChannels></DMXMode>')
    ft = gdtf.load(write_gdtf(tmp_path / "t.gdtf", xml))
    rows = write_chart(tmp_path, "2U;1;;;Dimmer\n2U;2;;;Pan\n2U;3-8;;;Red|Green|Blue\n")
    matches = charte.compare(ft, ft.modes[0], rows)
    assert [m.status for m in matches] == [charte.OK] * 8
    assert "break DMX 2" in matches[2].note


def test_reserved_pair_and_preset_names():
    assert charte.expected_attributes("Colour preset") != charte.expected_attributes("Reset")
    assert charte._attr_matches("Chase fade", ["ChaseFade"], ())
    assert charte._attr_matches("Between colour preset cross fade", ["color crossfade speed"],
                                charte.expected_attributes("Between colour preset cross fade"))
