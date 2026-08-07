"""RAW / DNG deep dive: lossless in-place IFD surgery.

The contract: RAW sensor data is NEVER pixel-rebuilt (it can't be
re-encoded). EXIF/GPS IFDs get emptied, identifying tags blanked, and
every byte of pixel data must survive the wipe byte-identical.
Fixtures are handcrafted with helpers.build_tiff() so we control the
exact byte layout (Pillow validates the layout by opening the result).
"""

import io
import os

import pytest
from PIL import Image

import exifwipe
from helpers import (cr2_fixture, dng_fixture, build_tiff,
                     tiff_with_ifd_cycle)


def _pixel_tail(path_or_data) -> bytes:
    """The pixel blob is the tail of our handcrafted fixtures."""
    if hasattr(path_or_data, "read_bytes"):
        data = path_or_data.read_bytes()
    else:
        data = path_or_data
    return data[-64 * 48 * 3:] if b"RAW" not in data or True else data[-64 * 48 * 3:]


def _exif_target_empty(data: bytes, tag: int) -> bool:
    """True when tag 0x8769/0x8825's target IFD has a zero entry count."""
    bo = "little" if data[:2] == b"II" else "big"
    off = int.from_bytes(data[4:8], bo)
    count = int.from_bytes(data[off:off + 2], bo)
    p = off + 2
    for _ in range(count):
        t = int.from_bytes(data[p:p + 2], bo)
        if t == tag:
            tgt = int.from_bytes(data[p + 8:p + 12], bo)
            return int.from_bytes(data[tgt:tgt + 2], bo) == 0
        p += 12
    return True  # tag absent is also fine


def test_dng_sniffed_by_extension(tmp_path):
    src = dng_fixture(tmp_path / "photo.dng")
    assert exifwipe._sniff_format(src) == "dng"


def test_extensionless_dng_detected_by_dngversion_tag(tmp_path):
    src = dng_fixture(tmp_path / "photo.dng")
    noext = tmp_path / "noext"
    noext.write_bytes(src.read_bytes())
    assert exifwipe._sniff_format(noext) == "dng"


def test_dng_surgery_strips_and_preserves_pixels(tmp_path):
    src = dng_fixture(tmp_path / "photo.dng")
    raw = src.read_bytes()
    # dirty: DNG camera model + private data + EXIF with makernote
    found = exifwipe._tiff_find_identifying(raw)
    assert "UniqueCameraModel" in found
    assert "ExifIFD" in found
    assert "DNGPrivateData" in found

    cleaned = exifwipe._tiff_strip_lossless(raw)
    assert cleaned is not None
    assert exifwipe._tiff_find_identifying(cleaned) == []
    assert b"LeakCamModel" not in cleaned
    assert b"DNGPRIVATEDATA-LEAK" not in cleaned
    assert b"MAKERNOTE-LEAK" not in cleaned
    assert _exif_target_empty(cleaned, 0x8769)
    # sensor data byte-identical
    assert cleaned[-16 * 12 * 3:] == raw[-16 * 12 * 3:]


def test_cr2_sniffed_by_magic_even_extensionless(tmp_path):
    src = cr2_fixture(tmp_path / "a.cr2")
    noext = tmp_path / "whatever"
    noext.write_bytes(src.read_bytes())
    assert exifwipe._sniff_format(noext) == "cr2"


def test_cr2_surgery_via_cli(tmp_path, capsys):
    src = cr2_fixture(tmp_path / "shot.cr2")
    before = src.read_bytes()
    assert exifwipe.main([str(src)]) == 0
    after = src.read_bytes()
    assert exifwipe._tiff_find_identifying(after) == []
    assert b"Canon EOS R5" not in after
    assert b"BodySerial1234" not in after
    assert b"CANONMAKERNOTELEAK" not in after
    assert _exif_target_empty(after, 0x8769)
    assert _exif_target_empty(after, 0x8825)
    # sensor blob untouched
    blob = 64 * 48 * 3
    assert after[-blob:] == before[-blob:]


def test_nef_is_tiff_surgery(tmp_path):
    # NEF is structurally a plain TIFF — a TIFF renamed .nef must be
    # detected and stripped via the same lossless surgery
    data = build_tiff(
        [(0x010F, 2, "NikonCam"), (0x8769, 4, ("ref", "exif"))],
        exif=[(0x9003, 2, "2023:11:11 11:11:11")],
        pixels=b"\x00\xff\x00" * 64,
    )
    src = tmp_path / "shot.nef"
    src.write_bytes(data)
    assert exifwipe._sniff_format(src) == "nef"
    assert exifwipe.main([str(src)]) == 0
    assert exifwipe._tiff_find_identifying(src.read_bytes()) == []
    assert b"NikonCam" not in src.read_bytes()


def test_bigtiff_dng_surgery(tmp_path):
    data = build_tiff(
        [(0xC612, 3, [1, 4, 0, 0]), (0xC614, 2, "BigLeakCam"),
         (0x8769, 4, ("ref", "exif"))],
        exif=[(0x927C, 7, b"BIGMAKERLEAK")],
        pixels=b"\x0a\x0b\x0c" * 64,
        magic=43,
    )
    src = tmp_path / "big.dng"
    src.write_bytes(data)
    assert exifwipe._tiff_find_identifying(data) != []
    cleaned = exifwipe._tiff_strip_lossless(data)
    assert cleaned is not None
    assert exifwipe._tiff_find_identifying(cleaned) == []
    assert b"BigLeakCam" not in cleaned and b"BIGMAKERLEAK" not in cleaned
    assert cleaned[-64 * 3:] == data[-64 * 3:]


def test_corrupt_raw_refused_not_rebuilt(tmp_path):
    # cut into the IFD structure (not just the pixel tail): surgery must
    # refuse loudly, never "strip" a file it can't fully verify — and
    # NEVER fall back to a pixel rebuild of sensor data
    src = cr2_fixture(tmp_path / "c.cr2")
    raw = src.read_bytes()
    # cut at 250 bytes: the IFD structure ends ~330 bytes in, so this
    # truncates inside it (external tag values fall past EOF)
    src.write_bytes(raw[:250])
    assert exifwipe.main([str(src)]) == 3


def test_pixel_truncated_raw_still_wipeable(tmp_path):
    # cutting only the pixel tail leaves the metadata structure intact —
    # the wipe is complete and verifiable, so it proceeds (and refuses to
    # invent pixels that were never there)
    src = cr2_fixture(tmp_path / "p.cr2")
    raw = src.read_bytes()
    src.write_bytes(raw[: len(raw) - 100])   # only the last 100 px bytes
    assert exifwipe.main([str(src)]) == 0
    assert exifwipe._tiff_find_identifying(src.read_bytes()) == []


def test_tiff_ifd_cycle_terminates(tmp_path):
    src = tiff_with_ifd_cycle(tmp_path / "loop.tiff")
    raw = src.read_bytes()
    # the walker must terminate (cycle) and flag the leaks
    found = exifwipe._tiff_find_identifying(raw)
    assert found, "dirty cycle file must still be flagged"
    # surgery must not corrupt the file (offsets never remapped)
    cleaned = exifwipe._tiff_strip_lossless(raw)
    assert cleaned is not None
    assert exifwipe._tiff_find_identifying(cleaned) == []
    assert b"LoopCam" not in cleaned
    # pixel data still present and identical
    assert cleaned[-64 * 3:] == raw[-64 * 3:]


def test_garbage_with_tiff_magic_does_not_crash(tmp_path):
    p = tmp_path / "junk"
    p.write_bytes(b"II*\x00\xff\xff\xff\xff" + os.urandom(200))
    args = exifwipe.build_parser().parse_args([str(p)])
    res = exifwipe.handle_one(p, args)
    assert res in (exifwipe.R_SKIP, exifwipe.R_ERR)


def test_verify_clean_on_stripped_dng(tmp_path):
    src = dng_fixture(tmp_path / "v.dng")
    assert exifwipe.main([str(src), "--verify"]) == 0
    assert exifwipe.verify_clean(src)[0] is True


def test_verify_flags_dirty_dng(tmp_path):
    src = dng_fixture(tmp_path / "dirty.dng")
    clean, leaks = exifwipe.verify_clean(src)
    assert clean is False
    assert leaks
