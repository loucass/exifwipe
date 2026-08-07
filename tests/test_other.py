"""BMP, HEIC/AVIF (optional dep), PDF (optional dep), garbage robustness."""

import io
import os
import random

import pytest
from PIL import Image

import exifwipe
from helpers import assert_jpeg_clean


def test_bmp_stripped(tmp_path):
    img = Image.new("RGB", (24, 18), (9, 8, 7))
    src = tmp_path / "x.bmp"
    img.save(src)
    cleaned, fmt = exifwipe.strip_image_bytes(src)
    assert fmt == "bmp"
    with Image.open(io.BytesIO(cleaned)) as out:
        assert list(out.convert("RGB").getdata()) == list(img.getdata())


def test_garbage_bytes_do_not_crash(tmp_path):
    rng = random.Random(42)
    for i in range(8):
        p = tmp_path / f"garbage_{i}"
        p.write_bytes(bytes(rng.randrange(256) for _ in range(rng.randrange(1, 400))))
        args = exifwipe.build_parser().parse_args([str(p)])
        res = exifwipe.handle_one(p, args)  # must return, never raise
        assert res in (exifwipe.R_SKIP, exifwipe.R_ERR)


def test_truncated_image_is_clean_error_not_hang(tmp_path):
    good = Image.new("RGB", (40, 40))
    buf = io.BytesIO()
    good.save(buf, format="PNG")
    data = buf.getvalue()
    p = tmp_path / "trunc.png"
    p.write_bytes(data[: len(data) // 3])  # png magic intact, chunk cut
    args = exifwipe.build_parser().parse_args([str(p)])
    assert exifwipe.handle_one(p, args) == exifwipe.R_ERR


def test_mutation_fuzz_parsers_never_hang_or_crash(tmp_path):
    """Light mutation fuzz over the untrusted-byte parsers: corrupt a
    valid JPEG/GIF and assert strip/handle_one returns or raises cleanly."""
    import random
    import warnings

    rng = random.Random(1337)
    jpg = Image.new("RGB", (48, 32), (90, 10, 200))
    jbuf = io.BytesIO()
    jpg.save(jbuf, format="JPEG")
    gif = Image.new("RGB", (16, 16), (10, 200, 30))
    gbuf = io.BytesIO()
    gif.save(gbuf, format="GIF")

    for seed_data, name in ((jbuf.getvalue(), "jpeg"), (gbuf.getvalue(), "gif")):
        for trial in range(40):
            data = bytearray(seed_data)
            for _ in range(rng.randint(1, 12)):
                pos = rng.randrange(len(data))
                data[pos] = rng.randrange(256)
            if rng.random() < 0.3:
                data = data[: rng.randrange(len(data))]  # truncate
            p = tmp_path / f"fuzz_{name}_{trial}"
            p.write_bytes(bytes(data))
            args = exifwipe.build_parser().parse_args([str(p)])
            # mutated headers can declare absurd dimensions — that's exactly
            # what we're fuzzing; silence PIL's bomb warning
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", Image.DecompressionBombWarning)
                # must return a status code, never propagate an exception
                assert exifwipe.handle_one(p, args) in (exifwipe.R_OK,
                                                        exifwipe.R_ERR,
                                                        exifwipe.R_SKIP)


@pytest.mark.skipif(not exifwipe.pillow_heif, reason="pillow-heif not installed")
def test_heic_stripped(tmp_path):
    img = Image.new("RGB", (32, 24), (200, 30, 30))
    src = tmp_path / "x.heic"
    img.save(src, format="HEIF")
    cleaned, fmt = exifwipe.strip_image_bytes(src)
    assert fmt in ("heic", "heif")  # Pillow reports the container as HEIF
    with Image.open(io.BytesIO(cleaned)) as out:
        assert list(out.convert("RGB").getdata()) == list(img.getdata())


@pytest.mark.skipif(not exifwipe.pillow_heif, reason="pillow-heif not installed")
def test_avif_single_stripped(tmp_path):
    img = Image.new("RGB", (32, 24), (30, 200, 30))
    src = tmp_path / "x.avif"
    img.save(src, format="HEIF")  # libheif writes AV1 for a .avif target
    cleaned, fmt = exifwipe.strip_image_bytes(src)
    assert fmt in ("heic", "heif")  # plugin may not expose a native AVIF save
    out = tmp_path / "out.avif"
    out.write_bytes(cleaned)
    with Image.open(out) as im:
        im.load()
    clean, leaks = exifwipe.verify_clean(out)
    assert clean, f"avif verify failed: {leaks}"


def test_pdf_strip_and_verify(tmp_path):
    pytest.importorskip("pikepdf")
    import pikepdf

    src = tmp_path / "doc.pdf"
    with pikepdf.new() as pdf:
        pdf.docinfo = pdf.make_indirect(pikepdf.Dictionary({
            "/Title": "Secret Title", "/Author": "Jane Q",
        }))
        pdf.Root.Metadata = pdf.make_indirect(pikepdf.Stream(pdf, b"<x:xmpmeta>leak</x:xmpmeta>"))
        pdf.Root["/Lang"] = "en-US"
        pdf.save(src)

    cleaned = exifwipe.strip_pdf_bytes(src)
    assert cleaned, "pdf strip returned nothing"
    out = tmp_path / "out.pdf"
    out.write_bytes(cleaned)

    with pikepdf.open(out) as pdf:
        assert "/Metadata" not in pdf.Root
        assert "/Lang" not in pdf.Root
        assert pdf.docinfo is None or len(pdf.docinfo) == 0

    clean, leaks = exifwipe.verify_clean(out)
    assert clean, f"pdf verify failed: {leaks}"
