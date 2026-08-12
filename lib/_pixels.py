"""_pixels - exifwipe internal module (format/strip machinery)."""

from __future__ import annotations



import hashlib
import io
import random
from PIL import Image, ImageChops, ImageOps
from typing import Optional

def _apply_orientation(img, strict: bool = False):
    """Honor EXIF orientation so we don't undo a rotation the photographer
    intended. In strict mode (JPEG — where a wrong rotation is the most
    damaging), fail loudly instead of silently saving a mis-rotated photo.
    Other formats degrade to a plain copy when the EXIF is unreadable."""
    try:
        from PIL import ImageOps
        return ImageOps.exif_transpose(img)
    except Exception as e:
        if strict:
            raise RuntimeError(
                f"failed to bake EXIF orientation into pixels: {e}") from e
        return img


def _perturb_seed(path: Path, raw: bytes) -> int:
    """Deterministic per-file seed: same input file -> same perturbed
    output every run (reproducible results, no surprise re-diffs)."""
    try:
        return int.from_bytes(hashlib.blake2b(
            str(path).encode("utf-8", "surrogateescape") + raw[:4096],
            digest_size=8).digest(), "little")
    except Exception:
        return 0xC0FFEE


def _perturb_image(img, seed: int, level: int):
    """Deterministic low-amplitude pixel noise (opt-in anti-reverse-search).

    Changes the color channels of every pixel by +-`level` (clamped),
    driven by a seeded RNG through a small repeated pattern applied
    tile-by-tile, so memory stays bounded on giant photos and the alpha
    band is never touched. This is NOT cryptography: it breaks naive
    exact/feature matching against the original and nothing more."""
    if level <= 0:
        return img
    rng = random.Random(seed)
    bands = img.split()
    keep_alpha = img.mode in ("RGBA", "LA")
    color = bands[:-1] if keep_alpha else bands
    from PIL import ImageChops
    out_bands = []
    for b in color:
        # per-band pattern from the same seeded rng — deterministic
        pat_pos = Image.new("L", (64, 64))
        pat_neg = Image.new("L", (64, 64))
        pp, pn = pat_pos.load(), pat_neg.load()
        for y in range(64):
            for x in range(64):
                d = rng.randint(-level, level)
                pp[x, y] = max(d, 0)
                pn[x, y] = -min(d, 0)
        w, h = b.size
        res = Image.new("L", b.size)
        for y in range(0, h, 512):
            for x in range(0, w, 512):
                box = (x, y, min(x + 512, w), min(y + 512, h))
                tile = b.crop(box)
                p = pat_pos.resize(tile.size, Image.NEAREST)
                n = pat_neg.resize(tile.size, Image.NEAREST)
                res.paste(ImageChops.subtract(ImageChops.add(tile, p), n), box)
        out_bands.append(res)
    if keep_alpha:
        out_bands.append(bands[-1])
    return Image.merge(img.mode, out_bands)


def _rebuild_frame(img, mode: str):
    """Copy pixels into a brand-new image, one bounded tile at a time,
    so a 100MP photo never materializes a giant Python list in RAM."""
    size = img.size
    clean = Image.new(mode, size)
    tile = 256
    w, h = size
    for y in range(0, h, tile):
        for x in range(0, w, tile):
            box = (x, y, min(x + tile, w), min(y + tile, h))
            clean.paste(img.crop(box).copy(), box)
    return clean


def _strip_multiframe(img, fmt: str, keep_icc: bool = False,
                      webp_lossless: bool = False, perturb=None,
                      seed: int = 0) -> tuple[bytes, str]:
    """Rebuild every frame of an animated GIF / APNG / multipage TIFF /
    animated WebP / AVIF from pixels, dropping all per-frame metadata."""
    n = getattr(img, "n_frames", 1)
    frames, durations, disposal = [], [], []
    for i in range(n):
        img.seek(i)
        fr = img.copy()
        mode = fr.mode
        if mode not in ("RGB", "RGBA", "L"):
            mode = "RGBA" if ("A" in mode or mode == "P") else "RGB"
            fr = fr.convert(mode)
        clean = _rebuild_frame(fr, mode)
        if perturb:
            clean = _perturb_image(clean, seed, perturb)
        frames.append(clean)
        durations.append(int(fr.info.get("duration", 100) or 100))
        disposal.append(int(fr.info.get("disposal", 2)))
    buf = io.BytesIO()
    if fmt == "GIF":
        frames[0].save(buf, format="GIF", save_all=True, append_images=frames[1:],
                       duration=durations, disposal=disposal,
                       loop=int(img.info.get("loop", 0) or 0))
        fmt_out = "GIF"
    elif fmt == "PNG":
        frames[0].save(buf, format="PNG", save_all=True,
                       append_images=frames[1:], duration=durations,
                       loop=int(img.info.get("loop", 0) or 0))
        fmt_out = "PNG"
    elif fmt == "TIFF":
        frames[0].save(buf, format="TIFF", save_all=True, append_images=frames[1:])
        fmt_out = "TIFF"
    elif fmt in ("WEBP", "AVIF"):
        # WebP supports a duration list; AVIF sequences exist but
        # pillow-heif doesn't provide an animated save — refuse loudly.
        if fmt == "AVIF":
            raise RuntimeError(
                "animated AVIF cannot be rewritten losslessly — "
                "exifwipe refuses to destroy the animation; re-save "
                "frames yourself and scrub those instead"
            )
        common = {"format": "WEBP", "save_all": True,
                  "append_images": frames[1:], "duration": durations,
                  "loop": int(img.info.get("loop", 0) or 0),
                  "exif": b"", "xmp": b""}
        if webp_lossless:
            common.update(lossless=True, quality=100, exact=True)
        if keep_icc:
            icc = img.info.get("icc_profile")
            if icc:
                common["icc_profile"] = icc
        frames[0].save(buf, **common)
        fmt_out = "WEBP"
    else:
        raise RuntimeError(f"multi-frame save not supported for {fmt}")
    return buf.getvalue(), fmt_out.lower()

