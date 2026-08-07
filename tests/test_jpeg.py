"""JPEG stripping: lossless path, rotation rebuild, MPO, trailing
garbage, COM comments, progressive, ICC, pixel preservation."""

import io

import piexif
import pytest
from PIL import Image

import exifwipe
from helpers import (assert_jpeg_clean, jpeg_segments, jpeg_with_exif,
                     mpo_jpeg)


def _insert_com(data: bytes, payload: bytes) -> bytes:
    """Insert a COM (FF FE) segment right before the SOS marker (as one
    unit with its leading FF padding, so the FF DA pair stays intact)."""
    i, n = 2, len(data)
    while i + 4 <= n:
        run_start = i
        while i < n and data[i] == 0xFF:
            i += 1
        if i >= n:
            raise AssertionError("no marker found")
        marker = data[i]
        i += 1
        if marker == 0xDA:
            seg = b"\xff\xfe" + len(payload).to_bytes(2, "big") + payload
            return data[:run_start] + seg + data[run_start:]
        seg_len = int.from_bytes(data[i:i + 2], "big")
        i += seg_len
    raise AssertionError("no SOS found")


def test_lossless_strip_removes_exif(tmp_path):
    src = jpeg_with_exif(tmp_path / "b.jpg", orient=1)
    cleaned, fmt = exifwipe.strip_image_bytes(src)
    assert fmt == "jpeg"
    assert_jpeg_clean(cleaned)
    # entropy-coded pixels are byte-identical: decode both and compare
    with Image.open(src) as a, Image.open(io.BytesIO(cleaned)) as b:
        assert list(a.convert("RGB").getdata()) == list(b.convert("RGB").getdata())


def test_rotation_rebuild_cleans_and_bakes_orientation(tmp_path):
    src = jpeg_with_exif(tmp_path / "a.jpg", orient=6)  # 96x64, rotate 90 CW
    cleaned, fmt = exifwipe.strip_image_bytes(src)
    assert fmt == "jpeg"
    assert_jpeg_clean(cleaned)
    with Image.open(io.BytesIO(cleaned)) as img:
        assert img.size == (64, 96), "orientation 6 must be baked into pixels"
        assert not img.getexif()


def test_mpo_all_frames_scrubbed(tmp_path):
    src = mpo_jpeg(tmp_path / "mpo.jpg")
    cleaned, fmt = exifwipe.strip_image_bytes(src)
    assert fmt == "jpeg"
    assert b"LeakMe2" not in cleaned
    assert b"LeakMe" not in cleaned
    assert cleaned.count(b"\xff\xd8") == 2, "both frames must survive"
    assert_jpeg_clean(cleaned, leak_strings=("Leak",))


def test_trailing_garbage_after_eoi_dropped(tmp_path):
    src = jpeg_with_exif(tmp_path / "trail.jpg")
    raw = src.read_bytes() + b"SUPER_SECRET_TRAILING_PAYLOAD"
    src.write_bytes(raw)
    cleaned, _ = exifwipe.strip_image_bytes(src)
    assert b"SUPER_SECRET_TRAILING_PAYLOAD" not in cleaned
    assert_jpeg_clean(cleaned)


def test_com_comment_segment_dropped(tmp_path):
    src = jpeg_with_exif(tmp_path / "com.jpg")
    src.write_bytes(_insert_com(src.read_bytes(), b"COM_SECRET_COMMENT"))
    cleaned, _ = exifwipe.strip_image_bytes(src)
    assert b"COM_SECRET_COMMENT" not in cleaned
    assert all(m != 0xFE for m, _ in jpeg_segments(cleaned))


def test_progressive_jpeg_cleaned(tmp_path):
    src = jpeg_with_exif(tmp_path / "prog.jpg", progressive=True)
    cleaned, _ = exifwipe.strip_image_bytes(src)
    assert_jpeg_clean(cleaned)
    with Image.open(io.BytesIO(cleaned)) as img:
        img.load()  # must still decode


def test_icc_dropped_by_default_kept_with_flag(tmp_path):
    src = jpeg_with_exif(tmp_path / "icc.jpg", icc=True)
    cleaned, _ = exifwipe.strip_image_bytes(src)
    assert b"ICC_PROFILE\x00" not in cleaned
    kept, _ = exifwipe.strip_image_bytes(src, keep_icc=True)
    assert b"ICC_PROFILE\x00" in kept
    # ICC present but no EXIF / no identifying APP segments besides it
    for marker, name in jpeg_segments(kept):
        if name.startswith("APP0:JFIF") or name.startswith("APP2:ICC_PROF"):
            continue
        assert False, f"metadata segment survived: {name}"
    for s in (b"Leak", b"AttackerCam", b"AcmeFW"):
        assert s not in kept, f"leak string {s!r} still in output"


def test_piexif_roundtrip_output_still_valid(tmp_path):
    src = jpeg_with_exif(tmp_path / "rt.jpg")
    cleaned, _ = exifwipe.strip_image_bytes(src)
    # piexif must still parse the output (proves the marker stream is sane)
    ifd = piexif.load(cleaned)
    assert all(not v or k == "thumbnail" for k, v in ifd.items())


def test_extensionless_jpeg_handled(tmp_path):
    src = jpeg_with_exif(tmp_path / "noext", orient=1)
    args = exifwipe.build_parser().parse_args([str(src)])
    assert exifwipe.handle_one(src, args) == exifwipe.R_OK
    assert_jpeg_clean(src.read_bytes())


def test_unrecognized_file_skipped_not_error(tmp_path):
    p = tmp_path / "notes.txt"
    p.write_text("just a text file")
    args = exifwipe.build_parser().parse_args([str(p)])
    assert exifwipe.handle_one(p, args) == exifwipe.R_SKIP
    assert p.read_text() == "just a text file"
