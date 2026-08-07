"""--perturb: deterministic low-amplitude pixel noise that breaks naive
reverse-image-search matching against the original. Opt-in, changes
pixels slightly (that's the point), never breaks cleanliness."""

import io

import exifwipe
from helpers import assert_jpeg_clean, jpeg_with_exif, png_with_metadata
from PIL import Image


def _rgb(data):
    with Image.open(io.BytesIO(data)) as im:
        return im.convert("RGB").tobytes()


def test_perturb_changes_pixels_and_stays_clean(tmp_path):
    src = jpeg_with_exif(tmp_path / "p.jpg")
    clean, fmt = exifwipe.strip_image_bytes(src, perturb=2)
    assert fmt == "jpeg"
    assert_jpeg_clean(clean, leak_strings=("Leak", "AttackerCam"))
    assert _rgb(clean) != _rgb(src.read_bytes()), "pixels must differ"


def test_perturb_deterministic_per_file(tmp_path):
    a = jpeg_with_exif(tmp_path / "a.jpg")
    b = jpeg_with_exif(tmp_path / "b.jpg")
    c = jpeg_with_exif(tmp_path / "c.jpg")
    ca, _ = exifwipe.strip_image_bytes(a, perturb=3)
    ca2, _ = exifwipe.strip_image_bytes(a, perturb=3)
    cb, _ = exifwipe.strip_image_bytes(b, perturb=3)
    cc, _ = exifwipe.strip_image_bytes(c, perturb=3)
    assert ca == ca2, "same input must give the same perturbed output"
    assert ca != cb, "different input must give different noise"
    assert cb != cc


def test_perturb_magnitude_bounded(tmp_path):
    # PNG rebuild is lossless, so the only pixel delta is the noise
    src = png_with_metadata(tmp_path / "m.png")
    clean, _ = exifwipe.strip_image_bytes(src, perturb=1)
    a, b = _rgb(src.read_bytes()), _rgb(clean)
    assert len(a) == len(b)
    max_delta = max(abs(x - y) for x, y in zip(a, b))
    assert max_delta <= 1, f"level 1 must move pixels by <=1, saw {max_delta}"


def test_neutral_jpeg_without_perturb_stays_lossless(tmp_path):
    src = jpeg_with_exif(tmp_path / "n.jpg", orient=1)
    clean, fmt = exifwipe.strip_image_bytes(src)
    assert fmt == "jpeg"
    # the fast path is lossless: decoded pixels identical to the original
    assert _rgb(clean) == _rgb(src.read_bytes())


def test_perturb_forces_rebuild_path(tmp_path):
    # with --perturb even an orientation-neutral JPEG must re-encode
    # (the noise has to land somewhere), so output bytes differ
    src = jpeg_with_exif(tmp_path / "f.jpg", orient=1)
    plain, _ = exifwipe.strip_image_bytes(src)
    noisy, _ = exifwipe.strip_image_bytes(src, perturb=2)
    assert plain != noisy
    assert _rgb(noisy) != _rgb(src.read_bytes())


def test_perturb_invalid_level_rejected():
    assert exifwipe.main(["x.jpg", "--perturb", "9"]) == 2
