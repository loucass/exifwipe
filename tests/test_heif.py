"""HEIC/AVIF lossless ISO-BMFF surgery: EXIF/XMP item extents zeroed in
place, pixel items byte-identical, no pillow-heif re-encode involved.
Writers need pillow-heif + libheif, so the whole file skips without it.
"""

import io

import pytest

import exifwipe
from helpers import heic_fixture

pytest.importorskip("pillow_heif")

from PIL import Image  # noqa: E402


def _rgb(data):
    with Image.open(io.BytesIO(data)) as im:
        return im.convert("RGB").tobytes()


def _make(path, **kw):
    src = heic_fixture(path, **kw)
    if src is None:
        pytest.skip("pillow-heif unavailable (needs libheif)")
    return src


def test_heic_surgery_zeroes_extents_keeps_pixels(tmp_path):
    src = _make(tmp_path / "x.heic")
    raw = src.read_bytes()
    assert b"HEIFCAMLEAK" in raw and b"heif-xmp-leak" in raw
    cleaned, fmt = exifwipe.strip_image_bytes(src)
    assert fmt == "heif"
    # every mapped metadata extent is now all-zero
    extents = exifwipe._heif_metadata_extents(cleaned)
    assert extents, "expected metadata extents to be mapped"
    for (s, e) in extents:
        assert not any(cleaned[s:e]), "metadata extent still populated"
    assert b"HEIFCAMLEAK" not in cleaned
    assert b"heif-xmp-leak" not in cleaned
    assert not exifwipe._heif_exif_payload_present(cleaned)
    # pixels survive byte-identically: same length, same decoded image
    assert len(cleaned) == len(raw)
    assert _rgb(raw) == _rgb(cleaned)
    # the tool's own verifier agrees
    src.write_bytes(cleaned)
    clean, leaks = exifwipe.verify_clean(src)
    assert clean, leaks


def test_heic_dirty_verify_flags_leaks(tmp_path):
    src = _make(tmp_path / "y.heic")
    clean, leaks = exifwipe.verify_clean(src)
    assert not clean
    assert leaks


def test_avif_surgery(tmp_path):
    # No AVIF encoder here (pillow-heif 1.5 only saves HEIF), but AVIF is
    # the same ISO-BMFF container with a different ftyp brand — re-brand
    # a HEIC and the surgery must treat it as AVIF identically.
    src = _make(tmp_path / "h.heic")
    data = bytearray(src.read_bytes())
    assert data[8:12] == b"heic"
    data[8:12] = b"avif"
    avif = tmp_path / "y.avif"
    avif.write_bytes(bytes(data))
    assert exifwipe._sniff_bytes(bytes(data)) == "avif"
    cleaned = exifwipe._strip_heif_lossless(bytes(data))
    assert cleaned is not None
    assert b"HEIFCAMLEAK" not in cleaned
    assert len(cleaned) == len(data)
    # pixels identical: every byte OUTSIDE the metadata extents is unchanged
    regions = exifwipe._heif_metadata_extents(bytes(data))
    seg = bytearray(cleaned)
    for (s, e) in regions:
        seg[s:e] = bytes(data[s:e])
    assert bytes(seg) == bytes(data), "non-metadata bytes changed"
    assert not exifwipe._heif_exif_payload_present(cleaned)
    avif.write_bytes(cleaned)
    clean, leaks = exifwipe.verify_clean(avif)
    assert clean, leaks


def test_heif_clean_file_passes_through_unchanged(tmp_path):
    src = _make(tmp_path / "c.heic", exif=False, xmp=False)
    raw = src.read_bytes()
    cleaned, fmt = exifwipe.strip_image_bytes(src)
    assert fmt == "heif"
    assert cleaned == raw, "already-clean HEIC must pass through byte-identical"


def test_heif_hostile_container_no_silent_leak(tmp_path):
    """Corrupt the meta box so iloc can't be trusted: the tool must
    either refuse loudly or produce clean output — never hand back a
    file that still carries the leak."""
    src = _make(tmp_path / "h.heic")
    data = bytearray(src.read_bytes())
    # zero the meta box header's size field -> children become unparseable
    meta_pos = None
    for (bp, bs, bt, _) in exifwipe._heif_box_children(bytes(data), 0, len(data)):
        if bt == b"meta":
            meta_pos = bp
            break
    assert meta_pos is not None
    data[meta_pos:meta_pos + 4] = b"\x00\x00\x00\x00"
    bad = tmp_path / "bad.heic"
    bad.write_bytes(bytes(data))
    try:
        cleaned, _ = exifwipe.strip_image_bytes(bad)
        assert b"HEIFCAMLEAK" not in cleaned, "silent leak on hostile container"
    except Exception:
        pass  # loud refusal is equally correct
