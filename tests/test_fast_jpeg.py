"""JPEG fast path: orientation + dimensions come off the marker stream,
so the common orientation-neutral case never decodes a pixel; vendor-
based RAW detection from MakerNotes; and --drop-orientation for the
TIFF family."""

import io

import exifwipe
from helpers import (assert_jpeg_clean, dng_fixture, jpeg_with_exif,
                     nef_like_fixture, tiff_with_orientation)
from PIL import Image


def test_jpeg_fast_path_parsers(tmp_path):
    neutral = jpeg_with_exif(tmp_path / "n.jpg", orient=1)
    rotated = jpeg_with_exif(tmp_path / "r.jpg", orient=6)
    nd, rd = neutral.read_bytes(), rotated.read_bytes()
    assert exifwipe._jpeg_orientation_from_bytes(nd) == 1
    assert exifwipe._jpeg_orientation_from_bytes(rd) == 6
    assert exifwipe._jpeg_sof_size(nd) == (96, 64)
    assert exifwipe._jpeg_orientation_from_bytes(b"not a jpeg") is None


def test_rotated_jpeg_bakes_orientation(tmp_path):
    src = jpeg_with_exif(tmp_path / "rot.jpg", orient=6)
    clean, fmt = exifwipe.strip_image_bytes(src)
    assert fmt == "jpeg"
    assert_jpeg_clean(clean)
    with Image.open(io.BytesIO(clean)) as im:
        assert im.size == (64, 96), "orientation 6 must be baked into pixels"


def test_neutral_jpeg_fast_path_keeps_entropy_bytes(tmp_path):
    src = jpeg_with_exif(tmp_path / "q.jpg", orient=1)
    clean, _ = exifwipe.strip_image_bytes(src)
    # lossless marker rewrite: the entropy-coded pixel bytes after the
    # first SOS must be byte-identical to the original's
    orig = src.read_bytes()

    def entropy(d):
        i, n = 2, len(d)
        while i + 4 <= n:
            if d[i] != 0xFF:
                break
            while i < n and d[i] == 0xFF:
                i += 1
            if i >= n:
                break
            marker = d[i]
            i += 1
            if marker == 0xD8:
                continue            # SOI — standalone, no length field
            if marker == 0xDA:
                seg_len = int.from_bytes(d[i:i + 2], "big")
                return d[i + 2 + seg_len:]
            if 0xD0 <= marker <= 0xD7 or marker == 0x01:
                continue            # RSTn / TEM — standalone
            if marker == 0xD9:
                break               # EOI
            seg_len = int.from_bytes(d[i:i + 2], "big")
            i += seg_len
        return b""
    assert entropy(clean) == entropy(orig), \
        "fast path must not re-encode pixels"
    with Image.open(io.BytesIO(clean)) as im:
        assert im.size == (96, 64)


# -- vendor-based RAW detection ---------------------------------------------- #
def test_extensionless_nef_detected_by_makernote(tmp_path):
    src = nef_like_fixture(tmp_path / "camera.bin")
    assert exifwipe._sniff_format(src) == "nef", \
        "MakerNote must identify the RAW family with no extension"
    args = exifwipe.build_parser().parse_args([str(src)])
    assert exifwipe.handle_one(src, args) == exifwipe.R_OK
    out = src.read_bytes()
    assert b"NIKON D850" not in out
    assert b"SerialVendor" not in out
    assert exifwipe._tiff_find_identifying(out) == []


def test_dng_without_extension_still_dng(tmp_path):
    src = dng_fixture(tmp_path / "photo.bin")
    assert exifwipe._sniff_format(src) == "dng", \
        "DNGVersion tag must identify DNG without an extension"


def test_plain_tiff_untouched_by_vendor_detection(tmp_path):
    from helpers import multipage_tiff
    src = multipage_tiff(tmp_path / "scan.bin")
    assert exifwipe._sniff_format(src) == "tiff"


# -- --drop-orientation ------------------------------------------------------ #
def test_drop_orientation(tmp_path):
    src = tiff_with_orientation(tmp_path / "o.tiff", orient=6)
    raw = src.read_bytes()
    kept = exifwipe._tiff_strip_lossless(raw)
    dropped = exifwipe._tiff_strip_lossless(raw, drop_orientation=True)
    assert kept != dropped
    bo, magic = exifwipe._tiff_parse_header(kept)

    def ori_bytes(d, b, m):
        for (p, tag, typ, cnt, vf) in exifwipe._iter_tiff_entries(d, b, m):
            if tag == 0x0112:
                return d[vf:vf + 2]
        return None
    assert ori_bytes(kept, bo, magic) == (6).to_bytes(2, "little"), \
        "orientation kept by default"
    dv = ori_bytes(dropped, bo, magic)
    assert dv is not None and all(x in (32, 0) for x in dv), \
        "orientation blanked with --drop-orientation"
    # wipe is still complete either way
    assert exifwipe._tiff_find_identifying(dropped) == []


def test_drop_orientation_cli(tmp_path):
    src = tiff_with_orientation(tmp_path / "o2.tiff", orient=6)
    args = exifwipe.build_parser().parse_args([str(src), "--drop-orientation"])
    assert exifwipe.handle_one(src, args) == exifwipe.R_OK
    out = src.read_bytes()
    bo, magic = exifwipe._tiff_parse_header(out)
    for (p, tag, typ, cnt, vf) in exifwipe._iter_tiff_entries(out, bo, magic):
        if tag == 0x0112:
            assert all(x in (32, 0) for x in out[vf:vf + 2])
            break
