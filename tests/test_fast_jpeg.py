"""JPEG fast path: orientation + dimensions come off the marker stream,
so the common orientation-neutral case never decodes a pixel; plus
vendor-based RAW detection from MakerNotes for extensionless RAWs."""

import io

import exifwipe
from helpers import (assert_jpeg_clean, dng_fixture, jpeg_with_exif,
                     nef_like_fixture)
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
