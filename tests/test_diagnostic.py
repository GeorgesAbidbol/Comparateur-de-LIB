from ma3lib import diagnostic, gdtf


def codes(path):
    return {f.code: f for f in diagnostic.diagnose(gdtf.load(path))}


def test_bad_bar_flags_instances_and_dimmer(bad_bar):
    c = codes(bad_bar)
    assert c["instances_sans_reference"].level == diagnostic.ALERTE
    assert "4 instances" in c["instances_sans_reference"].message
    assert c["dimmer_virtuel_possible"].level == diagnostic.ALERTE
    assert len(c["dimmer_virtuel_possible"].details) == 4


def test_instance_group_detail(bad_bar):
    groups = diagnostic.find_instance_groups(gdtf.load(bad_bar))
    assert len(groups) == 1
    assert groups[0].names == ["Pixel1", "Pixel2", "Pixel3", "Pixel4"]
    assert groups[0].convertible


def test_good_bar_is_clean(good_bar):
    c = codes(good_bar)
    assert not any(f.level == diagnostic.ERREUR for f in c.values())
    assert "instances_sans_reference" not in c
    assert "dimmer_virtuel_possible" not in c
    assert "geometrie_orpheline" not in c
    assert "canaux_virtuels" in c and "references" in c


def test_broken(broken):
    c = codes(broken)
    assert c["noms_dupliques"].details == ["Head"]
    assert c["reference_cassee"].level == diagnostic.ERREUR
    assert c["canal_sans_geometrie"].details == ["Ghost"]
    assert c["geometrie_orpheline"].details == ["Unused"]


def test_tricky_real_world_patterns(tricky):
    c = codes(tricky)
    # enveloppes Group_N autour d'une référence décorative
    assert "Px" in c["references_sans_canaux"].message
    assert "instances_sans_reference" not in c
    # Head Mode 1 / Head Mode 2 : une copie par mode, pas des instances
    assert c["variantes_par_mode"].level == diagnostic.INFO
    assert "instances_similaires" not in c
    # connecteurs DMX 5Pin / 3Pin sans canaux : pas pris pour des instances
    for code in ("instances_sans_reference", "instances_similaires", "references_sans_canaux"):
        assert not any("Pin" in d for d in c.get(code, diagnostic.Finding("", "", "")).details)


def test_3d_only_geometries(tricky, good_bar, bad_bar):
    ft = gdtf.load(tricky)
    removable = {g.name for g in diagnostic.geometries_3d_only(ft)}
    # références décoratives, leur modèle, connecteurs, lentille sans canal
    assert removable == {"Px_1", "Px_2", "Px_3", "DMX 5Pin IN", "DMX 3Pin IN", "Px", "Lens"}
    # les enveloppes qui portent les canaux et les racines de mode restent
    assert {"Group_1", "Base", "Head Mode 1", "Lens2"} <= diagnostic.useful_geometries(ft)
    assert "geometries_3d_seulement" in codes(tricky)
    # fixtures sans 3D superflue : rien à supprimer
    assert diagnostic.geometries_3d_only(gdtf.load(good_bar)) == []
    assert diagnostic.geometries_3d_only(gdtf.load(bad_bar)) == []


def test_duplicate_templates(tmp_path):
    from conftest import channel, fixture_xml, write_gdtf
    refs = lambda tpl, n: "".join(f'<GeometryReference Name="{tpl}_{i}" Geometry="{tpl}"/>' for i in range(n))
    geos = (f'<Geometry Name="Root M1">{refs("RGB Pix Mode 1", 2)}</Geometry>'
            f'<Geometry Name="Root M2">{refs("RGB Pix Mode 2", 2)}</Geometry>'
            '<Beam Name="RGB Pix Mode 1"/><Beam Name="RGB Pix Mode 2"/>')
    rgb = lambda tpl: "".join(channel(tpl, a, k, "Overwrite") for k, a in enumerate(("ColorAdd_R", "ColorAdd_G", "ColorAdd_B"), 1))
    modes = (f'<DMXMode Name="M1" Geometry="Root M1"><DMXChannels>{rgb("RGB Pix Mode 1")}</DMXChannels></DMXMode>'
             f'<DMXMode Name="M2" Geometry="Root M2"><DMXChannels>{rgb("RGB Pix Mode 2")}</DMXChannels></DMXMode>')
    ft = gdtf.load(write_gdtf(tmp_path / "t.gdtf", fixture_xml("Dup", geos, modes)))
    assert diagnostic.duplicate_templates(ft) == [["RGB Pix Mode 1", "RGB Pix Mode 2"]]
    assert "modeles_en_double" in {f.code for f in diagnostic.diagnose(ft)}


def test_same_mode_twin_templates_are_intentional(tmp_path):
    """JDC Line = 2 modules JDC 500 : RGB Pix A et RGB Pix B dans le même mode, voulu."""
    from conftest import channel, fixture_xml, write_gdtf
    geos = ('<Geometry Name="Root"><GeometryReference Name="A1" Geometry="RGB Pix A"/>'
            '<GeometryReference Name="B1" Geometry="RGB Pix B"/></Geometry>'
            '<Beam Name="RGB Pix A"/><Beam Name="RGB Pix B"/>')
    chans = channel("RGB Pix A", "ColorAdd_R", 1) + channel("RGB Pix B", "ColorAdd_R", 2)
    ft = gdtf.load(write_gdtf(tmp_path / "t.gdtf", fixture_xml(
        "Twin", geos, f'<DMXMode Name="M" Geometry="Root"><DMXChannels>{chans}</DMXChannels></DMXMode>')))
    assert diagnostic.duplicate_templates(ft) == []
