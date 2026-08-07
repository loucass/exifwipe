"""Black-hoodie mutation fuzzing.

Throw byte-flips, truncations, insertions and zeroing runs at the
parsers and assert the invariants that make exifwipe trustworthy:
  * no uncaught exceptions (the documented RuntimeError refusal is fine)
  * a surgery that returns bytes is length-preserving AND actually clean
  * the walkers never hang on hostile input (bounded loops, tested by
    the corpus mutations + a wall-clock sanity cap)
  * verify_clean never crashes, even on garbage

Seeded RNGs -> deterministic CI runs, reproducible failures.
"""

import random
import time

import exifwipe
from helpers import build_tiff, cr2_fixture, dng_fixture, heic_fixture


def _mutate(data: bytes, rng) -> bytes:
    b = bytearray(data)
    if not b:
        return bytes(b)
    op = rng.randrange(4)
    if op == 0:                                   # single bit flip
        i = rng.randrange(len(b))
        b[i] ^= 1 << rng.randrange(8)
    elif op == 1:                                 # truncation
        b = b[: rng.randrange(len(b))]
    elif op == 2:                                 # insert garbage
        i = rng.randrange(len(b) + 1)
        junk = bytes(rng.randrange(256) for _ in range(rng.randrange(1, 12)))
        b[i:i] = junk
    elif op == 3 and len(b) > 4:                  # zero a run
        i = rng.randrange(len(b) - 4)
        j = min(len(b), i + rng.randrange(1, 16))
        b[i:j] = b"\x00" * (j - i)
    return bytes(b)


def test_tiff_surgery_fuzz_invariants(tmp_path):
    rng = random.Random(0xC0FFEE)
    seeds = [
        cr2_fixture(tmp_path / "c.cr2").read_bytes(),
        dng_fixture(tmp_path / "d.dng").read_bytes(),
        build_tiff([(0x010F, 2, "FuzzCam"), (0x8769, 4, ("ref", "exif")),
                    (0x8825, 4, ("ref", "gps"))],
                   exif=[(0x9003, 2, "2020:01:01 00:00:00"),
                         (0x927C, 7, b"MAKERNOTE-FUZZ")],
                   gps=[(0x0001, 2, "N")],
                   pixels=b"\x01\x02\x03" * 64),
    ]
    t0 = time.monotonic()
    for i in range(250):
        mut = _mutate(rng.choice(seeds), rng)
        try:
            out = exifwipe._tiff_strip_lossless(mut)
        except RuntimeError:
            continue                    # documented refusal — fine
        except Exception as e:          # pragma: no cover
            raise AssertionError(
                f"uncaught {type(e).__name__} on mutation {i}: {e}")
        if out is not None:
            assert len(out) == len(mut), \
                f"surgery changed file length on mutation {i}"
            assert exifwipe._tiff_find_identifying(out) == [], \
                f"leak after surgery on mutation {i}"
            hdr = exifwipe._tiff_parse_header(out)
            assert hdr is not None and exifwipe._tiff_structure_ok(out, *hdr), \
                f"structure broken on mutation {i}"
    # the whole battery must finish fast — hostile files can't hang us
    assert time.monotonic() - t0 < 30, "fuzz battery took too long (hang?)"


def test_tiff_walker_never_hangs_on_hostile_counts(tmp_path):
    """A giant entry-count field must not make the walker iterate forever."""
    base = bytearray(cr2_fixture(tmp_path / "h.cr2").read_bytes())
    # IFD0 entry count = 0xFFFFFFFF (classic TIFF: 2 bytes, so 0xFFFF)
    ifd0 = int.from_bytes(base[4:8], "little")
    base[ifd0:ifd0 + 2] = b"\xff\xff"
    hostile = bytes(base)
    t0 = time.monotonic()
    try:
        exifwipe._tiff_strip_lossless(hostile)
    except (RuntimeError, Exception):
        pass                                # any outcome except a hang
    assert time.monotonic() - t0 < 5, "hostile entry count hung the walker"


def test_byte_strippers_never_crash_on_garbage(tmp_path):
    rng = random.Random(0xBADC0DE)
    corpus = [
        b"", b"\xff\xd8", b"GIF89a", b"\x89PNG\r\n\x1a\n",
        b"RIFF\x10\x00\x00\x00WEBP",
        b"FUJIFILMCCD-RAW " + bytes(0x100),
    ]
    h = heic_fixture(tmp_path / "f.heic")
    if h is not None:
        corpus.append(h.read_bytes())
    for i in range(300):
        src = bytearray(rng.choice(corpus))
        for _ in range(rng.randrange(1, 5)):
            src = bytearray(_mutate(bytes(src), rng))
        for fn in (exifwipe._strip_jpeg_lossless, exifwipe._strip_gif_lossless,
                   exifwipe._strip_png_lossless, exifwipe._strip_heif_lossless,
                   exifwipe._strip_raf_lossless, exifwipe._sniff_bytes):
            try:
                fn(bytes(src))
            except Exception as e:          # pragma: no cover
                raise AssertionError(
                    f"{fn.__name__} crashed on mutation {i}: {type(e).__name__}: {e}")


def test_verify_never_crashes_on_garbage(tmp_path):
    rng = random.Random(0xFEED)
    base = dng_fixture(tmp_path / "v.dng").read_bytes()
    for i in range(60):
        f = tmp_path / f"m{i}.bin"
        f.write_bytes(_mutate(base, rng))
        try:
            exifwipe.verify_clean(f)
        except Exception as e:              # pragma: no cover
            raise AssertionError(
                f"verify_clean crashed on mutation {i}: {type(e).__name__}: {e}")
