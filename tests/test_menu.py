"""Interactive menu: strip writes, one-shot dry-run does not, and the
inspect action is read-only."""

import exifwipe
from helpers import assert_jpeg_clean, jpeg_with_exif


def _session(answers):
    it = iter(answers)
    exifwipe._menu.prompt_input = lambda label: next(it)
    exifwipe.run_interactive_menu()


def test_menu_strip_writes(tmp_path):
    src = jpeg_with_exif(tmp_path / "t.jpg")
    before = src.read_bytes()
    # 1 = strip, q = quit
    _session(["1", str(src), "q"])
    assert src.read_bytes() != before, "strip must rewrite the file"
    assert_jpeg_clean(src.read_bytes())


def test_one_shot_dry_run_does_not_persist(tmp_path):
    f1 = jpeg_with_exif(tmp_path / "f1.jpg")
    f2 = jpeg_with_exif(tmp_path / "f2.jpg")
    f1_before = f1.read_bytes()
    # 3 = one-shot dry-run f1; then 1 = strip f2; q
    _session(["3", str(f1), "1", str(f2), "q"])
    assert f1.read_bytes() == f1_before, "one-shot dry-run wrote to f1"
    assert f2.read_bytes() != f1_before, "f2 must have been scrubbed by choice 1"
    assert_jpeg_clean(f2.read_bytes())


def test_inspect_does_not_modify(tmp_path, capsys):
    src = jpeg_with_exif(tmp_path / "i.jpg")
    before = src.read_bytes()
    _session(["2", str(src), "q"])
    assert src.read_bytes() == before
    assert "AttackerCam" in capsys.readouterr().out


def test_bad_choice_loops(tmp_path):
    src = jpeg_with_exif(tmp_path / "c.jpg")
    before = src.read_bytes()
    # 9 (invalid), then 1 (strip), then q — must not crash on bad choice
    _session(["9", "1", str(src), "q"])
    assert src.read_bytes() != before