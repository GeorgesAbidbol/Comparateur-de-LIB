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
