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
    rows = write_chart(tmp_path, "12ch;1;2;;Red\n12ch;3-12;;;Blue|Red|Green\n12ch;13;;;Dimmer\n12ch;14;;;Reserved\n")
    by_addr = {m.address: m for m in charte.compare(ft, ft.modes[0], rows)}
    assert by_addr[1].status == charte.DIFF and "16 bits" in by_addr[1].suggestion
    assert by_addr[2].status == charte.EN_TROP  # la notice en fait le Fine du canal 1
    assert by_addr[4].status == charte.DIFF and "ColorAdd_R" in by_addr[4].suggestion
    assert by_addr[13].status == charte.MANQUANT
    assert by_addr[14].status == charte.IGNORE


def test_references_are_unfolded(good_bar):
    ft = gdtf.load(good_bar)
    chans = charte.absolute_channels(ft, ft.modes[0])
    assert [c.addresses[0] for c in chans] == list(range(1, 13))
    assert chans[3].instance == "Pixel2" and chans[3].attributes == ["ColorAdd_R"]
