"""Verification layer: verify_clean() on dirty/clean files, the exiftool
JSON parser, and per-format byte leak detection."""

from PIL import Image

import exifwipe
from helpers import (animated_gif, animated_webp, jpeg_with_exif,
                     png_with_metadata)


def test_verify_clean_flags_dirty_jpeg(tmp_path):
    src = jpeg_with_exif(tmp_path / "dirty.jpg")
    clean, leaks = exifwipe.verify_clean(src)
    assert clean is False
    assert leaks, "dirty jpeg must report leaks"
    assert any("Exif" in l or "GPS" in l or l in ("0th", "1st") for l in leaks)


def test_verify_clean_passes_clean_jpeg(tmp_path):
    src = jpeg_with_exif(tmp_path / "clean.jpg")
    cleaned, _ = exifwipe.strip_image_bytes(src)
    out = tmp_path / "out.jpg"
    out.write_bytes(cleaned)
    clean, leaks = exifwipe.verify_clean(out)
    assert clean is True, f"clean jpeg reported leaks: {leaks}"


def test_verify_bytes_png(tmp_path):
    src = png_with_metadata(tmp_path / "d.png")
    leaks = exifwipe._verify_bytes(src, "png")
    assert "tEXt" in leaks and "iCCP" in leaks


def test_verify_bytes_webp(tmp_path):
    src = animated_webp(tmp_path / "d.webp")
    leaks = exifwipe._verify_bytes(src, "webp")
    assert "EXIF" in leaks and "XMP" in leaks


def test_verify_bytes_gif(tmp_path):
    src = animated_gif(tmp_path / "d.gif")
    leaks = exifwipe._verify_bytes(src, "gif")
    assert "comment-ext" in leaks and "XMP" in leaks


def test_verify_bytes_tiff_clean_passes(tmp_path):
    img = Image.new("RGB", (16, 16))
    src = tmp_path / "t.tiff"
    img.save(src, format="TIFF")
    assert exifwipe._verify_bytes(src, "tiff") == []


def test_parse_exiftool_json_filters_structural():
    text = (
        '[{"SourceFile": "a.jpg", "ExifToolVersion": 12.4, "FileName": "a.jpg",'
        ' "FileSize": 10, "ImageWidth": 100, "JFIF:JFIFVersion": "1.1",'
        ' "ExifIFD:Make": "Acme", "GPS:GPSLatitude": "37",'
        ' "Composite:ImageSize": "100x100"}]'
    )
    leaks = exifwipe._parse_exiftool_json(text)
    assert "ExifIFD:Make" in leaks
    assert "GPS:GPSLatitude" in leaks
    assert not any("JFIF" in l or "Composite" in l or l in
                   ("SourceFile", "FileName", "FileSize") for l in leaks)


def test_parse_exiftool_json_bad_input():
    assert exifwipe._parse_exiftool_json("not json") == []
    assert exifwipe._parse_exiftool_json("[]") == []
    assert exifwipe._parse_exiftool_json('"string"') == []
