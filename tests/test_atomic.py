"""Atomic in-place writes: mode + mtime preserved, no temp files left,
symlink-safe temp naming."""

import os
import stat

import exifwipe
from helpers import jpeg_with_exif


def test_atomic_write_preserves_mode_and_mtime(tmp_path):
    src = jpeg_with_exif(tmp_path / "secret.jpg")
    os.chmod(src, 0o600)
    st = src.stat()
    payload = b"\xff\xd8fake-clean-data"
    exifwipe._atomic_write_bytes(src, payload, st)
    after = src.stat()
    assert src.read_bytes() == payload
    assert stat.S_IMODE(after.st_mode) == 0o600, "mode must survive"
    assert after.st_mtime_ns == st.st_mtime_ns, "mtime must survive"


def test_atomic_write_leaves_no_temp_files(tmp_path):
    src = jpeg_with_exif(tmp_path / "x.jpg")
    st = src.stat()
    exifwipe._atomic_write_bytes(src, b"data", st)
    leftovers = [p for p in tmp_path.iterdir()
                 if ".exifwipe_tmp_" in p.name]
    assert leftovers == [], f"temp files left behind: {leftovers}"


def test_atomic_write_through_symlink_preserves_link_and_cleans_target(tmp_path):
    # round-2 bug: in-place strip destroyed the symlink AND left the target
    # fully dirty. The link must survive and the target gets the new bytes.
    real = tmp_path / "real.jpg"
    real.write_bytes(b"original")
    link = tmp_path / "link.jpg"
    os.symlink(str(real), link)
    st = link.stat()
    exifwipe._atomic_write_bytes(link, b"scrubbed", st)
    assert link.is_symlink(), "symlink must be preserved, not replaced"
    assert real.read_bytes() == b"scrubbed", "target must be cleaned in place"
    assert link.read_bytes() == b"scrubbed", "link must still read through"


def test_atomic_write_masks_special_mode_bits(tmp_path):
    # round-2 finding: chmod(st.st_mode) carried setuid/setgid/sticky over
    src = tmp_path / "suid.jpg"
    src.write_bytes(b"data")
    os.chmod(src, 0o4755)
    st = src.stat()
    exifwipe._atomic_write_bytes(src, b"clean", st)
    assert stat.S_IMODE(src.stat().st_mode) == 0o755, \
        "setuid bit must not survive the rewrite"
