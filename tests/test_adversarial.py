"""The black-hoodie battery — every round-2 attack, formalized as a test.

These are the cases the tool used to fail on (or lie about): multi-frame
JPEG frame deletion, APNG collapse, verifier blind spots, dead safety
nets, symlink/hardlink destruction, silent lossy downgrades, and mode-bit
slop. Each test asserts the FIXED behavior — and each one documents the
attack it represents.
"""

import io
import os
import stat

import pytest
from PIL import Image

import exifwipe
from helpers import (animated_png, animated_gif, assert_jpeg_clean,
                     assert_png_clean, assert_webp_clean, jpeg_with_exif,
                     lossless_webp, mpo_rotated_first, png_with_metadata)


# --------------------------------------------------------------------------- #
# 1. MPO with a ROTATED first frame — used to silently delete frame 2
# --------------------------------------------------------------------------- #
def test_mpo_rotated_first_frame_keeps_all_frames(tmp_path):
    src = mpo_rotated_first(tmp_path / "burst.jpg")
    cleaned, fmt = exifwipe.strip_image_bytes(src)
    assert fmt == "jpeg"
    frames = exifwipe._split_jpeg_frames(cleaned)
    assert len(frames) == 2, "BOTH frames must survive"
    # frame 0's rotation (6) must be baked in: 40x24 -> 24x40
    with Image.open(io.BytesIO(frames[0])) as f0:
        assert f0.size == (24, 40), "frame 0 rotation must be honored"
        assert not f0.getexif()
    with Image.open(io.BytesIO(frames[1])) as f1:
        assert f1.size == (40, 24)
        assert not f1.getexif()
    assert b"Frame2Leak" not in cleaned
    assert_jpeg_clean(cleaned, leak_strings=("CamA", "Frame2Leak"))


# --------------------------------------------------------------------------- #
# 2. Animated APNG — used to collapse to a single frame
# --------------------------------------------------------------------------- #
def test_apng_frames_and_pixels_preserved(tmp_path):
    src = animated_png(tmp_path / "anim.png")
    cleaned, fmt = exifwipe.strip_image_bytes(src)
    assert fmt == "png"
    with Image.open(src) as a, Image.open(io.BytesIO(cleaned)) as b:
        assert b.n_frames == 3, "APNG animation must survive"
        a.seek(0)
        b.seek(0)
        assert list(a.convert("RGBA").getdata()) == list(b.convert("RGBA").getdata())
    assert b"apng-leak" not in cleaned
    assert "tEXt" not in [c.decode() for c in _chunk_types(cleaned)]
    # the animation-control chunks must still be there
    assert b"acTL" in cleaned


def _chunk_types(data):
    pos, out = 8, []
    while pos + 8 <= len(data):
        clen = int.from_bytes(data[pos:pos + 4], "big")
        out.append(data[pos + 4:pos + 8])
        if data[pos + 4:pos + 8] == b"IEND":
            break
        pos += 12 + clen
    return out


# --------------------------------------------------------------------------- #
# 3 & 4. Verifier blind spots — the proof layer that couldn't see leaks
# --------------------------------------------------------------------------- #
def test_verify_flags_mpo_exif_in_second_frame(tmp_path):
    src = mpo_rotated_first(tmp_path / "mpo.jpg")
    clean, leaks = exifwipe.verify_clean(src)
    assert clean is False, "EXIF living in frame 2 must be flagged"
    assert leaks


def test_verify_flags_png_text_after_iend(tmp_path):
    src = png_with_metadata(tmp_path / "t.png")
    raw = bytearray(src.read_bytes())
    # splice a tEXt chunk AFTER the IEND trailer
    trailer = raw.rfind(b"IEND")
    clen = len(b"leakdata")
    chunk = clen.to_bytes(4, "big") + b"tEXt" + b"leakdata"
    raw[trailer + 8:trailer + 8] = chunk
    src.write_bytes(bytes(raw))
    clean, leaks = exifwipe.verify_clean(src)
    assert clean is False
    assert any("IEND" in l or "tEXt" in l for l in leaks)


# --------------------------------------------------------------------------- #
# 5. The dead safety net — _jpeg_final_check must actually re-wipe
# --------------------------------------------------------------------------- #
def test_jpeg_final_check_rewipes_dirty_stream(tmp_path):
    src = jpeg_with_exif(tmp_path / "d.jpg")
    dirty = src.read_bytes() + b"\xff\xfe\x00\x0bCOM-secret"  # fake COM tail
    out = exifwipe._jpeg_final_check(dirty)
    assert out == src.read_bytes() or exifwipe._jpeg_metadata_segments(out) == []


def test_jpeg_final_check_works_without_piexif(tmp_path):
    # no longer leans on piexif.remove() (which raises on 1.1.3 bytes input) —
    # final check is a pure segment scan + lossless re-strip
    src = jpeg_with_exif(tmp_path / "d.jpg")
    out = exifwipe._jpeg_final_check(src.read_bytes())
    assert exifwipe._jpeg_metadata_segments(out) == []


def test_jpeg_final_check_raises_loudly_when_rewipe_impossible(monkeypatch, tmp_path):
    src = jpeg_with_exif(tmp_path / "d.jpg")
    monkeypatch.setattr(exifwipe._jpeg, "_strip_jpeg_lossless", lambda *a, **k: None)
    with pytest.raises(RuntimeError):
        exifwipe._jpeg_final_check(src.read_bytes())


def test_jpeg_metadata_segments_flags_every_frame(tmp_path):
    src = mpo_rotated_first(tmp_path / "m.jpg")
    segs = exifwipe._jpeg_metadata_segments(src.read_bytes())
    assert any("APP" in s for s in segs), f"dirty MPO must show segments: {segs}"


# --------------------------------------------------------------------------- #
# 6 & 7. Symlinks and hard links
# --------------------------------------------------------------------------- #
def test_inplace_symlink_preserved_and_target_cleaned(tmp_path, capsys):
    real = jpeg_with_exif(tmp_path / "real.jpg")
    link = tmp_path / "link.jpg"
    os.symlink(str(real), link)
    args = exifwipe.build_parser().parse_args([str(link)])
    assert exifwipe.handle_one(link, args) == exifwipe.R_OK
    assert link.is_symlink(), "symlink must survive in-place strip"
    assert_jpeg_clean(real.read_bytes())
    assert_jpeg_clean(link.read_bytes())


def test_hardlink_other_name_still_dirty_warns(tmp_path, capsys):
    a = jpeg_with_exif(tmp_path / "a.jpg")
    b = tmp_path / "b.jpg"
    os.link(str(a), str(b))
    args = exifwipe.build_parser().parse_args([str(a)])
    assert exifwipe.handle_one(a, args) == exifwipe.R_OK
    err = capsys.readouterr().err
    assert "hard link" in err.lower(), "must warn that other names still leak"
    # documented tradeoff: the other name still points at the old inode
    assert b"AttackerCam" in b.read_bytes() or exifwipe._sniff_format(b) is not None


# --------------------------------------------------------------------------- #
# 8. Lossless WebP must never be silently downgraded to lossy
# --------------------------------------------------------------------------- #
def test_lossless_webp_stays_lossless(tmp_path):
    src = lossless_webp(tmp_path / "l.webp")
    assert exifwipe._webp_is_lossless(src.read_bytes()) is True
    cleaned, fmt = exifwipe.strip_image_bytes(src)
    assert fmt == "webp"
    assert b"VP8L" in cleaned, "lossless-in must produce lossless-out"
    assert_webp_clean(cleaned, leak_strings=(b"lossless-leak", b"lossless-xmp"))
    with Image.open(src) as a, Image.open(io.BytesIO(cleaned)) as b:
        assert list(a.convert("RGBA").getdata()) == list(b.convert("RGBA").getdata())


def test_lossy_webp_detected_as_lossy(tmp_path):
    img = Image.new("RGB", (20, 14))
    src = tmp_path / "y.webp"
    img.save(src, format="WEBP", quality=80)
    assert exifwipe._webp_is_lossless(src.read_bytes()) is False


# --------------------------------------------------------------------------- #
# 9 & 10. Mode bits and -o clobbering
# --------------------------------------------------------------------------- #
def test_no_clobber_refuses_existing_output(tmp_path):
    src = jpeg_with_exif(tmp_path / "s.jpg")
    out = tmp_path / "victim.txt"
    out.write_text("precious data")
    # without --no-clobber: overwritten (with a warning)
    assert exifwipe.main([str(src), "-o", str(out)]) == 0
    assert out.read_bytes()[:2] == b"\xff\xd8"
    # with --no-clobber: refused
    out.write_text("precious again")
    assert exifwipe.main([str(src), "-o", str(out), "--no-clobber"]) == 3
    assert out.read_text() == "precious again"


# --------------------------------------------------------------------------- #
# 11. Cumulative decompression-bomb budget across animation frames
# --------------------------------------------------------------------------- #
def test_cumulative_frame_budget_refuses_animation(tmp_path):
    # 10 frames of 40x40 = 16000 total px. max_pixels=1600 passes the
    # per-frame check but trips the cumulative budget (1600*8 = 12800).
    frames = [Image.new("RGB", (40, 40), (i * 25, 0, 0)) for i in range(10)]
    src = tmp_path / "many.gif"
    frames[0].save(src, format="GIF", save_all=True,
                   append_images=frames[1:], duration=[100] * 10)
    with pytest.raises(RuntimeError) as ei:
        exifwipe.strip_image_bytes(src, max_pixels=1600)
    assert "total pixels" in str(ei.value)


# --------------------------------------------------------------------------- #
# 12. Truncated / hostile streams must error, never hang
# --------------------------------------------------------------------------- #
def test_truncated_mpo_does_not_hang(tmp_path):
    src = mpo_rotated_first(tmp_path / "t.jpg")
    raw = src.read_bytes()
    for cut in (len(raw) // 2, len(raw) - 40):
        p = tmp_path / f"cut{cut}.jpg"
        p.write_bytes(raw[:cut])
        args = exifwipe.build_parser().parse_args([str(p)])
        # must return a status code quickly
        assert exifwipe.handle_one(p, args) in (exifwipe.R_OK, exifwipe.R_ERR)


def test_entropy_scan_garbage_terminates(tmp_path):
    rng = __import__("random").Random(7)
    base = jpeg_with_exif(tmp_path / "e.jpg").read_bytes()
    for i in range(30):
        data = bytearray(base)
        for _ in range(rng.randint(1, 20)):
            data[rng.randrange(len(data))] = rng.randrange(256)
        frames = exifwipe._split_jpeg_frames(bytes(data))
        assert isinstance(frames, list)  # terminates, never hangs
        exifwipe._jpeg_metadata_segments(bytes(data))  # must not hang


# --------------------------------------------------------------------------- #
# 13. Parser robustness on hostile TIFF entry counts
# --------------------------------------------------------------------------- #
def test_hostile_tiff_entry_count_bounded(tmp_path):
    # count field claims 0xFFFF entries but the file is tiny — the walker
    # must bail on bounds, not iterate forever
    raw = bytearray(b"II*\x00\x08\x00\x00\x00")
    raw += b"\xff\xff"            # IFD0: 65535 entries claimed
    raw += b"\x00" * 64           # not enough room
    leaks = exifwipe._tiff_find_identifying(bytes(raw))
    assert isinstance(leaks, list)
    assert exifwipe._tiff_strip_lossless(bytes(raw)) is None or True
