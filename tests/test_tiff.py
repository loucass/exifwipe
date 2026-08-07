"""TIFF stripping: single and multipage, identifying tags gone,
structural layout tags allowed."""

import io

from PIL import Image

import exifwipe
from helpers import multipage_tiff


def test_single_tiff_identifying_tags_stripped(tmp_path):
    img = Image.new("RGB", (40, 30), (10, 200, 30))
    src = tmp_path / "single.tiff"
    img.save(src, format="TIFF", description="leaky description",
             software="leaky software", artist="leaky artist")
    cleaned, fmt = exifwipe.strip_image_bytes(src)
    assert fmt == "tiff"
    for s in (b"leaky description", b"leaky software", b"leaky artist"):
        assert s not in cleaned, f"identifying tag survived: {s}"
    # structural-only: no identifying tags per our own IFD walker
    assert exifwipe._tiff_find_identifying(cleaned) == []
    with Image.open(io.BytesIO(cleaned)) as out:
        assert out.size == (40, 30)


def test_multipage_tiff_preserved(tmp_path):
    src = multipage_tiff(tmp_path / "multi.tiff", pages=3)
    cleaned, fmt = exifwipe.strip_image_bytes(src)
    assert fmt == "tiff"
    with Image.open(io.BytesIO(cleaned)) as out:
        assert out.n_frames == 3, "all pages must survive"
    assert exifwipe._tiff_find_identifying(cleaned) == []


def test_tiff_walker_flags_dirty_file(tmp_path):
    img = Image.new("RGB", (20, 20), (1, 2, 3))
    src = tmp_path / "dirty.tiff"
    img.save(src, format="TIFF", software="leaky", copyright="leaky")
    found = exifwipe._tiff_find_identifying(src.read_bytes())
    assert "Software" in found
    assert "Copyright" in found
