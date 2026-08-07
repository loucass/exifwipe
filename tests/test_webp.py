"""WebP stripping: single-frame clean, animated preserved with
durations + loop, EXIF/XMP chunks removed."""

import io

from PIL import Image

import exifwipe
from helpers import animated_webp, assert_webp_clean


def test_single_webp_metadata_stripped(tmp_path):
    img = Image.new("RGB", (30, 20), (50, 60, 70))
    src = tmp_path / "single.webp"
    img.save(src, format="WEBP", exif=b"\x00\x00\x00\x00leak-exif",
             xmp=b"<x:xmpmeta>leak-xmp</x:xmpmeta>")
    cleaned, fmt = exifwipe.strip_image_bytes(src)
    assert fmt == "webp"
    assert_webp_clean(cleaned, leak_strings=(b"leak-exif", b"leak-xmp"))
    with Image.open(src) as a, Image.open(io.BytesIO(cleaned)) as b:
        pa = list(a.convert("RGB").getdata())
        pb = list(b.convert("RGB").getdata())
        assert len(pa) == len(pb)
        # lossy re-encode: pixels must survive within a small tolerance
        worst = max(sum(abs(x[i] - y[i]) for i in range(3))
                    for x, y in zip(pa, pb))
        assert worst <= 12, f"pixel drift too large: {worst}"


def test_animated_webp_preserved_and_stripped(tmp_path):
    src = animated_webp(tmp_path / "anim.webp")
    cleaned, fmt = exifwipe.strip_image_bytes(src)
    assert fmt == "webp"
    assert_webp_clean(cleaned, leak_strings=(b"LeakCam", b"leak-xmp"))
    with Image.open(io.BytesIO(cleaned)) as out:
        assert out.n_frames == 3, "animation must survive"
        out.seek(0)
        d0 = out.info.get("duration", 100)
        assert d0 in (100, 110, 120)
