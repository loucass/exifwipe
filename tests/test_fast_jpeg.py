"""JPEG fast path: orientation + dimensions come off the marker stream,
so the common orientation-neutral case never decodes a pixel."""

import io

import exifwipe
from helpers import assert_jpeg_clean, jpeg_with_exif
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
