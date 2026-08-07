"""PNG stripping: tEXt/zTXt/iTXt/eXIf/iCCP removed across modes."""

import io

from PIL import Image
from PIL.PngImagePlugin import PngInfo

import exifwipe
from helpers import assert_png_clean, png_chunks, png_with_metadata


def test_png_metadata_stripped(tmp_path):
    src = png_with_metadata(tmp_path / "meta.png")
    cleaned, fmt = exifwipe.strip_image_bytes(src)
    assert fmt == "png"
    assert_png_clean(cleaned)
    # pixels preserved
    with Image.open(src) as a, Image.open(io.BytesIO(cleaned)) as b:
        assert list(a.getdata()) == list(b.getdata())
    # structural chunks still present
    assert "IHDR" in png_chunks(cleaned)
    assert "IEND" in png_chunks(cleaned)


def test_grayscale_png_stripped(tmp_path):
    img = Image.new("L", (20, 10), 128)
    meta = PngInfo()
    meta.add_text("Comment", "leak")
    src = tmp_path / "gray.png"
    img.save(src, pnginfo=meta)
    cleaned, _ = exifwipe.strip_image_bytes(src)
    assert_png_clean(cleaned)
    with Image.open(io.BytesIO(cleaned)) as out:
        assert out.mode == "L"


def test_palette_png_stripped(tmp_path):
    img = Image.new("P", (16, 16), 3)
    meta = PngInfo()
    meta.add_text("Comment", "leak")
    src = tmp_path / "pal.png"
    img.save(src, pnginfo=meta)
    cleaned, _ = exifwipe.strip_image_bytes(src)
    assert_png_clean(cleaned)
    with Image.open(io.BytesIO(cleaned)) as out:
        out.load()  # decodes fine
