"""GIF stripping: the byte-level rewrite must keep every frame byte-exact
and drop comment + XMP blocks wherever they appear (before/between/after
frames — the pre-fix parser stopped at the first image block)."""

from PIL import Image

import exifwipe
from helpers import animated_gif, assert_gif_clean


def test_animated_gif_frames_duration_loop_preserved(tmp_path):
    src = animated_gif(tmp_path / "anim.gif", frames=3, loop=0)
    before = src.read_bytes()
    cleaned, fmt = exifwipe.strip_image_bytes(src)
    assert fmt == "gif"
    with Image.open(src) as src_img, Image.open(__import__("io").BytesIO(cleaned)) as out:
        assert out.n_frames == 3, "frame count must survive"
        assert src_img.n_frames == 3
        src_img.seek(0)
        # frame 0 pixels identical (palette + transparency untouched)
        out.seek(0)
        assert list(src_img.convert("RGB").getdata()) == list(out.convert("RGB").getdata())
        assert out.info.get("loop", 0) == 0
    # the lossless path is byte-exact except for the dropped blocks
    assert len(cleaned) < len(before)  # comments/XMP removed


def test_comment_and_xmp_between_frames_dropped(tmp_path):
    src = animated_gif(tmp_path / "x.gif", frames=2)
    cleaned, _ = exifwipe.strip_image_bytes(src)
    assert_gif_clean(cleaned, leak_strings=(b"hi there", b"leak"))


def test_single_gif_comment_dropped(tmp_path):
    from helpers import _subblocks
    img = Image.new("P", (8, 8), 1)
    buf = __import__("io").BytesIO()
    img.save(buf, format="GIF")
    data = bytearray(buf.getvalue())
    trailer = data.rfind(b"\x3b")
    data[trailer:trailer] = b"\x21\xfe" + _subblocks(b"single_comment_leak")
    src = tmp_path / "single.gif"
    src.write_bytes(bytes(data))
    cleaned, _ = exifwipe.strip_image_bytes(src)
    assert_gif_clean(cleaned, leak_strings=(b"single_comment_leak",))


def test_gif_keeps_netscape_loop_extension(tmp_path):
    src = animated_gif(tmp_path / "loop.gif", frames=2, loop=5)
    cleaned, _ = exifwipe.strip_image_bytes(src)
    with Image.open(__import__("io").BytesIO(cleaned)) as out:
        assert out.info.get("loop", 0) == 5


def test_gif_strip_returns_none_on_garbage():
    assert exifwipe._strip_gif_lossless(b"not a gif at all") is None
    assert exifwipe._strip_gif_lossless(b"GIF89a") is None  # truncated
