from ma3lib import cli, ma3_paths


def test_find_and_deploy(tmp_path, bad_bar):
    usb = tmp_path / "USB"
    (usb / "grandMA3" / "gma3_library").mkdir(parents=True)
    targets = [t for t in ma3_paths.find_targets(extra_roots=[usb]) if t.kind == "usb"]
    assert len(targets) == 1
    dest = ma3_paths.deploy(bad_bar, targets[0])
    assert dest == usb / "grandMA3" / "gma3_library" / "fixturetypes" / bad_bar.name
    assert dest.exists()


def test_cli(bad_bar, broken, capsys):
    assert cli.main(["info", str(bad_bar)]) == 0
    out = capsys.readouterr().out
    assert "4        Pixel4 [Beam]" in out and "empreinte 12" in out
    assert cli.main(["check", str(bad_bar)]) == 0
    assert cli.main(["check", str(broken)]) == 1
