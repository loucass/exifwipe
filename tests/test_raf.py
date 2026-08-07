"""Fuji RAF — lossless surgery: header serial/model blanked, embedded
JPEG preview's EXIF losslessly stripped, FujiIFD TIFF block surgically
cleaned. Refuses loudly on anything it can't verify."""

import io

import exifwipe
from helpers import jpeg_segments, raf_fixture
from PIL import Image


def test_raf_surgery_strips_every_carrier(tmp_path):
    src = raf_fixture(tmp_path / "f.raf")
    raw = src.read_bytes()
    assert b"FinePix S3Pro" in raw and b"FA392001" in raw
    out = exifwipe._strip_raf_lossless(raw)
    assert out is not None
    assert out[:16] == b"FUJIFILMCCD-RAW ", "magic must survive"
    # header identity gone
    assert b"FinePix S3Pro" not in out
    assert b"FA392001" not in out
    assert b"FUJI-SW" not in out
    # embedded preview EXIF gone, preview still a decodable JPEG
    jpos = int.from_bytes(out[0x54:0x58], "big")
    jlen = int.from_bytes(out[0x58:0x5c], "big")
    preview = out[jpos:jpos + jlen]
    assert preview[:2] == b"\xff\xd8"
    assert b"FUJICAM" not in preview
    assert exifwipe._jpeg_metadata_segments(preview) == [], \
        "preview must be metadata-free (JFIF APP0 is structural)"
    with Image.open(io.BytesIO(preview)) as im:
        assert im.size == (24, 16)
    # FujiIFD block surgically clean
    foff = int.from_bytes(out[0x64:0x68], "big")
    flen = int.from_bytes(out[0x68:0x6c], "big")
    assert b"FujiCamX" not in out
    assert b"FUJIFILM-MAKERNOTE" not in out
    assert exifwipe._tiff_find_identifying(out[foff:foff + flen]) == []
    # the tool's own verifier agrees
    src.write_bytes(out)
    clean, leaks = exifwipe.verify_clean(src)
    assert clean, leaks


def test_raf_dirty_verify_flags_every_carrier(tmp_path):
    src = raf_fixture(tmp_path / "d.raf")
    clean, leaks = exifwipe.verify_clean(src)
    assert not clean
    joined = "\n".join(leaks)
    assert "header-serial/model" in joined
    assert "preview:" in joined
    assert "fujiifd:" in joined


def test_raf_refuses_when_preview_is_garbage(tmp_path):
    src = raf_fixture(tmp_path / "b.raf")
    raw = bytearray(src.read_bytes())
    # point the preview at non-JPEG bytes and claim it's a preview
    raw[0x54:0x58] = (0x200).to_bytes(4, "big")
    raw[0x58:0x5c] = (16).to_bytes(4, "big")
    assert exifwipe._strip_raf_lossless(bytes(raw)) is None


def test_raf_refuses_when_preview_strip_fails(tmp_path):
    src = raf_fixture(tmp_path / "t.raf")
    raw = bytearray(src.read_bytes())
    # corrupt the embedded preview mid-stream so the lossless strip
    # can't parse it — surgery must refuse, never leave the EXIF in place
    jpos = int.from_bytes(raw[0x54:0x58], "big")
    raw[jpos + 8] ^= 0xFF
    # only if that actually breaks the parse; otherwise the test is void
    out = exifwipe._strip_raf_lossless(bytes(raw))
    assert out is None or b"FUJICAM" not in out


def test_raf_handle_one_end_to_end(tmp_path, capsys):
    src = raf_fixture(tmp_path / "e.raf")
    args = exifwipe.build_parser().parse_args([str(src)])
    assert exifwipe.handle_one(src, args) == exifwipe.R_OK
    out = src.read_bytes()
    assert b"FinePix S3Pro" not in out
    assert b"FA392001" not in out
