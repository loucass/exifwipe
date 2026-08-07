"""--report: print exactly which metadata fields were removed per file —
the tag/chunk level, not just a count."""

import exifwipe
from helpers import cr2_fixture, jpeg_with_exif, png_with_metadata


def test_report_jpeg_lists_segments_and_tags(tmp_path):
    src = jpeg_with_exif(tmp_path / "r.jpg")
    report = []
    exifwipe.strip_image_bytes(src, report=report)
    joined = "\n".join(report)
    assert "APP1:Exif" in joined
    assert "EXIF:0th Make (0x010F)" in joined   # friendly name + id
    assert "EXIF:0th Orientation (0x0112)" in joined
    assert "EXIF:GPS" in joined


def test_report_png_lists_chunks(tmp_path):
    src = png_with_metadata(tmp_path / "r.png")
    report = []
    exifwipe.strip_image_bytes(src, report=report)
    joined = "\n".join(report)
    for chunk in ("tEXt", "iTXt", "eXIf", "iCCP"):
        assert chunk in joined, f"{chunk} missing from report:\n{joined}"


def test_report_tiff_inventory(tmp_path):
    src = cr2_fixture(tmp_path / "r.cr2")
    inv = exifwipe._tiff_inventory(src.read_bytes())
    joined = "\n".join(inv)
    assert "Make (0x010F)" in joined
    assert "Model (0x0110)" in joined
    assert "ExifIFD block (destroyed)" in joined
    assert "GPSInfo block (destroyed)" in joined


def test_report_tiff_orientation_only_when_dropped(tmp_path):
    from helpers import tiff_with_orientation
    src = tiff_with_orientation(tmp_path / "o.tiff", orient=6)
    inv = exifwipe._tiff_inventory(src.read_bytes())
    assert not any("Orientation" in n for n in inv), \
        "orientation is NOT reported when kept"
    dropped = exifwipe._tiff_inventory(src.read_bytes(), drop_orientation=True)
    assert any("Orientation (0x0112)" in n for n in dropped)


def test_report_cli_flag(tmp_path, capsys):
    src = jpeg_with_exif(tmp_path / "r2.jpg")
    assert exifwipe.main([str(src), "--report"]) == 0
    out = capsys.readouterr().out
    assert "[report]" in out
    assert "0x010F" in out


def test_report_dry_run_shows_what_would_be_removed(tmp_path, capsys):
    src = jpeg_with_exif(tmp_path / "r3.jpg")
    before = src.read_bytes()
    assert exifwipe.main([str(src), "--dry-run", "--report"]) == 0
    assert src.read_bytes() == before, "dry-run must not write"
    out = capsys.readouterr().out
    assert "[report]" in out
    assert "APP1:Exif" in out
