#!/usr/bin/env python3
# ============================================================================#
r"""
   ███████╗██╗  ██╗██╗███████╗██╗    ██╗██╗██████╗ ███████╗
   ██╔════╝╚██╗██╔╝██║██╔════╝██║    ██║██║██╔══██╗██╔════╝
   █████╗   ╚███╔╝ ██║█████╗  ██║ █╗ ██║██║██████╔╝█████╗
   ██╔══╝   ██╔██╗ ██║██╔══╝  ██║███╗██║██║██╔═══╝ ██╔══╝
   ███████╗██╔╝ ██╗██║███████╗╚███╔███╔╝██║██║     ███████╗
   ╚══════╝╚═╝  ╚═╝╚═╝╚══════╝ ╚══╝╚══╝ ╚═╝╚═╝     ╚══════╝

   exifwipe  -  make ExifTool return BLANK on any image you're about to post.

      author   :  loucas
      repo     :  https://github.com/loucass/exifwipe
      license  :  MIT

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 THE PROBLEM, IN ONE SCREENSHOT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

   Every photo you post carries a passenger: EXIF. And EXIF never shuts up.

      $ exiftool ~/Pictures/2am_pizza.jpg
      GPS Latitude                  : 37 deg 30' 0.00" N
      GPS Longitude                 : 122 deg 25' 0.00" W
      Make                          : AcmeCam
      Model                         : X-9000
      DateTimeOriginal              : 2024:01:02 03:04:05
      Software                      : AcmeFW v1
      Artist                        : Jane Q Investigator

   That's your house. Your phone. Your timezone. Your name. Riding along
   in a JPEG marker that nobody sees but anybody can read.

   THIS TOOL TURNS THAT INTO A WALL OF NOTHING:

      $ exiftool ~/Pictures/clean/2am_pizza.jpg
      ExifTool Version Number    : 12.00
      File Name                  : 2am_pizza.jpg
      Image Width                : 1280
      Image Height               : 720
      ...and that's it. No GPS. No Make. No Model. No Artist. No you.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 WHAT GETS NUKED (everything exiftool would surface)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

   GONE:
     - EXIF IFD0 / IFD1 / ExifIFD / InteropIFD / GPS sub-IFD
         Make, Model, Software, DateTime, DateTimeOriginal,
         DateTimeDigitized, GPSInfo (tags 1-7), BodySerialNumber,
         CameraOwnerName, LensSerialNumber, UserComment, Artist,
         Copyright, MakerNotes (Apple / Canon / Nikon / Sony / Fuji)
     - JPEG APP1 (Exif), APP13 (Photoshop 8BIM), APP2 (ICC)
     - COM comment segments
     - PNG tEXt / zTXt / iTXt chunks, eXIf chunk, pHYs chunk, iCCP chunk
     - WebP EXIF + XMP containers
     - TIFF / GeoTIFF tag block
     - HEIC / AVIF EXIF (with pillow-heif installed)
     - PDF /DocInfo + XMP metadata stream (with pikepdf installed)

   KEPT (structural, not identifying):
     - JFIF version/density (some viewers refuse to open without it)
     - Pixel dimensions (obviously)
     - Optional ICC profile (--keep-icc); otherwise dropped too

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 OH WAIT, WHY NOT JUST `exiftool -all=` LIKE EVERYONE SAYS?
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

   exiftool -all= IMAGE.jpg    -> standard. still leaves an APP0/JFIF stub,
                                  and some MakerNotes (Canon blocks, Nikon
                                  truncates). It edits the marker; it doesn't
                                  drop the file.

   mat2 IMAGE.jpg              -> heavier: GObject, mutagen, filters by input.
                                  GUI + CLI. Use it when you're scrubbing
                                  folders of mixed audio/video/pdf, not for
                                  a single phone screenshot.

   exifwipe.py  IMAGE.jpg   -> rebuild, not edit. pixel data out, fresh
                      blank frame in. then a piexif round-trip verify
                      catches anything Pillow tries to sneak back.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 HOW IT WORKS (three paths, all boring)
 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    1. JPEG, orientation-neutral     -> rewrite the marker stream. drop
      APPn + COM segments (EXIF, XMP, Photoshop, ICC unless
      --keep-icc); pass the entropy-coded pixels through untouched.
      No re-encode. The pixels are byte-identical to the source.

    2. JPEG that needs rotation     -> bake rotation into pixels, then
      rebuild a fresh frame with zero metadata (quality 95 re-encode).

    3. everything else              -> rebuild every frame from pixels
      (animated GIF / multipage TIFF keep all frames + timing), then
      save with exif=b"", xmp=b"", icc_profile=None, pnginfo=empty.

    Pixel rebuilds are tiled (256px) instead of list(getdata()),
    so a 100MP photo never becomes a giant Python list in RAM.
    For JPEG we still run a piexif round-trip reload after saving
    and re-wipe any IFD that came back -- that catches the
    imgproxy#668 class of bug where ColorSpace or ExifVersion or
    Orientation sneaks back in post-save.

    Pattern borrowed from the same scrubbers you'll find on grep.app:
      MK2112/any_to_any.py            core/utils/metadata_handler.py
      joenorton/comfyui-mcp-server    asset_processor.py
      DocWorkBox/DocCaptioner         ui/layout.py
      s0n4jit/metawiper               app.py

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 INSTALL (linux edition)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

   Debian / Ubuntu     : sudo apt install python3-pil python3-piexif
   Arch                : sudo pacman -S python-pillow
   Fedora              : sudo dnf install python-pillow

   plus the optional bits (only if you hit .heic/.pdf):
     pip3 install --user pillow-heif pikepdf

   Or, into a venv:
     python3 -m venv .venv && source .venv/bin/activate
     pip install pillow piexif pillow-heif pikepdf

   The only hard dep is Pillow. The loader will tell you to pip the
   optional ones if a file type actually needs them.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 USE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

      python3 exifwipe.py photo.jpg                   # strip in place
      python3 exifwipe.py ./images/ -o ./clean/       # batch a folder
      python3 exifwipe.py photo.jpg --inspect        # show what exiftool sees
      python3 exifwipe.py photo.jpg --dry-run -v     # preview, no writes
      python3 exifwipe.py photo.jpg --keep-icc       # keep the ICC profile

   My actual daily use:

      # kill the EXIF on every screenshot before I pasted it anywhere
      python3 exifwipe.py ~/Pictures/Screenshots/

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 LEGAL / NOT-LEGAL
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

   Strip your OWN images before you publish them. Full stop.

   Don't use this to scrub someone else's photo, don't use it to
   launder provenance, don't run it on evidence a casefile needs
   intact. That's not "opsec", that's a crime. Most jurisdictions
   agree with us here.

   License: MIT. Author: loucas (github: loucass).
"""

from __future__ import annotations

import argparse
import io
import os
import sys
from pathlib import Path
from typing import Iterable, Optional

# --------------------------------------------------------------------------- #
# cyber chrome — ANSI color + interactive menu
# --------------------------------------------------------------------------- #
try:
    import readline  # arrow keys / history in prompts (linux) — best-effort
except ImportError:
    readline = None


def _can_color() -> bool:
    """Respect NO_COLOR, and don't colorize when output is piped."""
    if os.environ.get("NO_COLOR"):
        return False
    try:
        return bool(sys.stdout.isatty())
    except Exception:
        return False


# _COLOR is decided at import, then overridden by --color/--no-color
# in main() via set_color().
_COLOR = _can_color()


def set_color(on: Optional[bool]) -> None:
    """Turn colorization on/off (None -> auto-detect on a tty)."""
    global _COLOR
    if on is None:
        _COLOR = _can_color()
    else:
        _COLOR = bool(on)


def _c(text, code, bold=True):
    if not _COLOR:
        return str(text)
    return f"\033[{'1;' if bold else ''}{code}m{text}\033[0m"


def c_ok(t):    return _c(t, "32")                     # green
def c_err(t):   return _c(t, "31")                     # red
def c_warn(t):  return _c(t, "33")                     # yellow
def c_info(t):  return _c(t, "36", bold=False)         # cyan, non-bold
def c_head(t):  return _c(t, "36")                     # cyan, bold
def c_dim(t):   return _c(t, "90", bold=False)         # gray
def c_mag(t):   return _c(t, "35")                     # magenta
def c_blue(t):  return _c(t, "34")                     # blue

# --------------------------------------------------------------------------- #
# optional imports — degrade gracefully if absent
# --------------------------------------------------------------------------- #
try:
    from PIL import Image, features
except ImportError:
    print(
        "exifwipe needs Pillow. on Debian/Ubuntu:  sudo apt install python3-pil\n"
        "or pip3 install pillow",
        file=sys.stderr,
    )
    raise

try:
    import piexif  # extra-safe JPEG round-trip verify
except ImportError:
    piexif = None

try:
    import pillow_heif
    import warnings
    with warnings.catch_warnings():
        # Pillow's features.check() raises a UserWarning when the 'heif'
        # feature isn't compiled in (it means "not built, not a problem").
        warnings.simplefilter("ignore")
        try:
            heif_supported = features.check("heif") if features is not None else False
        except Exception:
            heif_supported = False
    if not heif_supported:
        register = getattr(pillow_heif, "register_heif_opener", None)
        if register:
            register()
        register_avif = getattr(pillow_heif, "register_avif_opener", None)
        if register_avif:
            register_avif()
except ImportError:
    pillow_heif = None


__version__ = "1.0.0"
__author__ = "loucas"
__github__ = "loucass"
__license__ = "MIT"


# --------------------------------------------------------------------------- #
# config
# --------------------------------------------------------------------------- #
IMAGE_EXTS = {".jpg", ".jpeg", ".jfif", ".png", ".webp", ".tif", ".tiff",
              ".bmp", ".gif", ".heic", ".heif", ".avif"}
DOC_EXTS = {".pdf"}  # pikepdf dep — see strip_pdf_metadata()


# --------------------------------------------------------------------------- #
# inspection — print what exiftool would surface
# --------------------------------------------------------------------------- #
def inspect_image(path: Path) -> None:
    """Print the metadata fields ExifTool would surface on this image."""
    print(f"\n{c_head('=' * 3)} {c_head(path.name)} {c_head('=' * 3)}")
    with Image.open(path) as img:
        print(f"  {c_info('format')}={img.format}  {c_info('mode')}={img.mode}  "
              f"{c_info('size')}={img.size[0]}x{img.size[1]}")

        exif = img.getexif() if hasattr(img, "getexif") else None
        if not exif:
            print("  EXIF IFD0: <none>")
        else:
            from PIL.ExifTags import TAGS
            print(f"  {c_head('EXIF IFD0:')}")
            for tag_id, value in exif.items():
                name = TAGS.get(tag_id, tag_id)
                print(f"    {c_info(str(name)):28s} {c_dim(f'({tag_id:5d})')} = {c_warn(repr(value))}")

        info = img.info or {}
        if not info:
            print("  img.info: <none>")
        else:
            print(f"  {c_head('img.info keys:')} {c_dim(str(list(info.keys())))}")
            for k, v in info.items():
                if isinstance(v, (bytes, bytearray)):
                    v = f"<{len(v)} bytes>"
                print(f"    '{c_mag(k)}' = {c_warn(repr(v))}")


def exiftool_hint() -> str:
    return (
        "exiftool -a -G -s IMAGE.jpg       # see everything ExifTool sees\n"
        "exiftool -all= IMAGE.jpg           # the CLI equivalent of --in-place\n"
    )


# --------------------------------------------------------------------------- #
# core strip — image formats
# --------------------------------------------------------------------------- #
def _apply_orientation(img):
    """Honor EXIF orientation so we don't undo a rotation the
    photographer intended. Older Pillow used exif_transpose (still
    works); current Pillow exposes exif_transpose via ImageOps."""
    try:
        from PIL import ImageOps
        return ImageOps.exif_transpose(img)
    except Exception:
        return img


def strip_image_bytes(path: Path, keep_icc: bool = False) -> tuple[bytes, str]:
    """Strip metadata, keeping pixels as close to byte-identical as the
    format allows.

    JPEG (orientation-neutral): rewrite the marker stream — drop every
    APPn/COM segment (EXIF, XMP, Photoshop, ICC unless --keep-icc),
    keep the entropy-coded pixel data verbatim. No re-encode, no loss.

    JPEG (needs rotation) and everything else: bake the rotation (if
    any) into the pixels, then rebuild into a brand-new frame with an
    empty metadata block. The rebuild is tiled so memory stays bounded
    no matter the megapixel count.

    Animated GIF / multipage TIFF keep every frame, timing and loop.

    Returns (clean_bytes, output_format_lowercase).
    """
    with Image.open(path) as img:
        img.load()
        fmt = (img.format or path.suffix.lstrip(".")).upper()

        # animated GIF / multipage TIFF / animated WebP / AVIF —
        # strip every frame, keep the animation
        if fmt in ("GIF", "TIFF", "TIF", "WEBP", "AVIF") \
                and getattr(img, "n_frames", 1) > 1:
            return _strip_multiframe(img, fmt, keep_icc=keep_icc)

        # JPEG: prefer the lossless marker-stream strip. Only when the
        # photo is orientation-neutral — otherwise we must bake the
        # rotation into the pixels, which requires re-encoding.
        if fmt in ("JPEG", "JPG", "MPO"):
            if _orientation_is_neutral(img):
                lossless = _strip_jpeg_lossless(path.read_bytes(), keep_icc)
                if lossless is not None:
                    return _jpeg_final_check(lossless), "jpeg"

        img = _apply_orientation(img)

        mode = img.mode
        if mode not in ("RGB", "RGBA", "L"):
            mode = "RGBA" if ("A" in mode or mode == "P") else "RGB"
            img = img.convert(mode)

        clean = _rebuild_frame(img, mode)

        icc_bytes = b""
        if keep_icc:
            try:
                icc_bytes = img.info.get("icc_profile", b"") or b""
            except Exception:
                icc_bytes = b""

        buf = io.BytesIO()

        if fmt in ("JPEG", "JPG", "MPO"):
            # https://pillow.readthedocs.io/en/stable/handbook/security.html
            # recommends exactly this: exif=b"", icc_profile=None,
            # pnginfo=None. We also pass progressive=False so there's
            # no app-segment noise from the encoder.
            kwargs = {"format": "JPEG", "quality": 95, "optimize": True,
                      "exif": b"", "progressive": False}
            kwargs["icc_profile"] = icc_bytes or None
            clean.save(buf, **kwargs)
            fmt_out = "JPEG"

        elif fmt == "PNG":
            from PIL.PngImagePlugin import PngInfo
            # empty PngInfo -> no tEXt/zTXt/iTXt chunks
            kwargs = {"format": "PNG", "pnginfo": PngInfo(), "optimize": True,
                      "icc_profile": icc_bytes or None, "exif": b""}
            clean.save(buf, **kwargs)
            fmt_out = "PNG"

        elif fmt == "WEBP":
            kwargs = {"format": "WEBP", "quality": 90, "method": 6,
                      "exif": b"", "xmp": b"", "icc_profile": icc_bytes or None}
            clean.save(buf, **kwargs)
            fmt_out = "WEBP"

        elif fmt in ("TIFF", "TIF"):
            clean.save(buf, format="TIFF")
            fmt_out = "TIFF"

        elif fmt == "GIF":
            clean.save(buf, format="GIF")
            fmt_out = "GIF"

        elif fmt in ("HEIF", "HEIC", "AVIF"):
            if pillow_heif is None:
                raise RuntimeError(
                    "HEIC/AVIF needs pillow-heif. install:\n"
                    "  pip3 install pillow-heif"
                )
            clean.save(buf, format="HEIF" if fmt in ("HEIF", "HEIC") else "AVIF",
                       quality=90)
            fmt_out = fmt

        else:
            clean.save(buf, format=fmt)
            fmt_out = fmt

        cleaned = buf.getvalue()

    return _jpeg_final_check(cleaned), fmt_out.lower()


def _orientation_is_neutral(img) -> bool:
    """True when the image carries no rotation (or EXIF at all)."""
    try:
        if not hasattr(img, "getexif"):
            return True
        return int(img.getexif().get(0x0112, 1) or 1) == 1
    except Exception:
        return True


def _jpeg_final_check(cleaned: bytes) -> bytes:
    """piexif round-trip verify ( JPEG only ) — the catch in imgproxy#668:
    if any IFD came back non-empty after saving, re-wipe it."""
    if piexif is not None:
        try:
            after = piexif.load(cleaned)
            if any(after.get(k) for k in ("0th", "1st", "Exif", "GPS", "Interop")):
                cleaned = piexif.remove(cleaned) or cleaned
        except Exception:
            # piexif refuses to parse -> there's no EXIF container at all
            # which is what we wanted all along
            pass
    return cleaned


def _strip_jpeg_lossless(data: bytes, keep_icc: bool = False):
    """Rewrite a JPEG marker stream, dropping every APPn / COM segment
    (EXIF, XMP, Photoshop, ICC unless keep_icc). Entropy-coded pixel
    data is copied verbatim — no re-encode, no quality loss.

    Handles multi-frame images (MPO et al.) by parsing each SOI..EOI
    pair, and drops any trailing garbage after the final EOI (bytes
    appended past the end of the image, e.g. by file-carving tools).

    Returns None if the stream doesn't parse as a normal JPEG (caller
    then falls back to the pixel-rebuild path)."""
    if data[:2] != b"\xff\xd8":
        return None
    n = len(data)
    out = bytearray()
    i = 0
    saw_frame = False

    def scan_entropy(j: int) -> int:
        """Copy entropy-coded bytes verbatim until the next real
        marker. Returns the index of that marker (which the outer
        loop then processes). Handles FF 00 stuffing and RSTn."""
        nonlocal out
        while j < n:
            if data[j] != 0xFF:
                j += 1
                continue
            k = j
            while k < n and data[k] == 0xFF:
                k += 1
            if k >= n:                      # run of FF to EOF — truncated
                out += data[j:k]
                return n
            nxt = data[k]
            if nxt == 0x00 or 0xD0 <= nxt <= 0xD7:
                # stuffed FF 00, or RSTn restart marker — part of the
                # entropy stream, keep byte-exact
                out += data[j:k + 1]
                j = k + 1
                continue
            # first real marker after entropy
            out += data[j:k]
            return k - 1
        return n

    while i < n:
        if data[i] != 0xFF:
            # trailing garbage after the last EOI — drop it
            break
        while i < n and data[i] == 0xFF:
            i += 1
        if i >= n:
            break
        marker = data[i]
        i += 1
        if marker == 0xD8:          # SOI — start of a frame
            out += b"\xff\xd8"
            saw_frame = True
            continue
        if marker == 0xD9:          # EOI
            out += b"\xff\xd9"
            continue
        if 0xD0 <= marker <= 0xD7 or marker == 0x01:
            continue                # RSTn / TEM, only valid inside entropy
        if i + 2 > n:
            continue                # truncated segment header
        seg_len = int.from_bytes(data[i:i + 2], "big")
        if seg_len < 2 or i + seg_len > n:
            continue
        payload = data[i + 2:i + seg_len]
        if marker == 0xDA:          # SOS — entropy-coded data follows
            out += b"\xff\xda" + data[i:i + seg_len]
            i = scan_entropy(i + seg_len)
            continue
        keep = True
        if 0xE0 <= marker <= 0xEF:  # APP0..APP15
            keep = (
                (marker == 0xE0 and payload.startswith(b"JFIF"))      # JFIF density block
                or (marker == 0xE2 and keep_icc
                    and payload.startswith(b"ICC_PROFILE\x00"))        # ICC, opt-in only
            )
        elif marker == 0xFE:        # COM comment
            keep = False
        if keep:
            out += b"\xff" + bytes([marker]) + data[i:i + seg_len]
        i += seg_len
    if not saw_frame:
        return None
    return bytes(out)


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


def _strip_multiframe(img, fmt: str, keep_icc: bool = False) -> tuple[bytes, str]:
    """Rebuild every frame of an animated GIF / multipage TIFF /
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
        frames.append(_rebuild_frame(fr, mode))
        durations.append(int(fr.info.get("duration", 100) or 100))
        disposal.append(int(fr.info.get("disposal", 2)))
    buf = io.BytesIO()
    if fmt == "GIF":
        frames[0].save(buf, format="GIF", save_all=True, append_images=frames[1:],
                       duration=durations, disposal=disposal,
                       loop=int(img.info.get("loop", 0) or 0))
        fmt_out = "GIF"
    elif fmt == "TIFF":
        frames[0].save(buf, format="TIFF", save_all=True, append_images=frames[1:])
        fmt_out = "TIFF"
    elif fmt in ("WEBP", "AVIF"):
        # WebP supports a duration list; AVIF sequences exist but
        # pillow-heif doesn't provide an animated save — refuse loudly.
        if fmt == "AVIF":
            # check whether the installed libwebp/avif plugin can write
            # an animation; if not, fail with a clear error instead of
            # silently collapsing to a single frame.
            raise RuntimeError(
                "animated AVIF cannot be rewritten losslessly — "
                "exifwipe refuses to destroy the animation; re-save "
                "frames yourself and scrub those instead"
            )
        common = {"format": "WEBP", "save_all": True,
                  "append_images": frames[1:], "duration": durations,
                  "loop": int(img.info.get("loop", 0) or 0),
                  "exif": b"", "xmp": b""}
        if keep_icc:
            icc = img.info.get("icc_profile")
            if icc:
                common["icc_profile"] = icc
        frames[0].save(buf, **common)
        fmt_out = "WEBP"
    else:
        raise RuntimeError(f"multi-frame save not supported for {fmt}")
    return buf.getvalue(), fmt_out


# --------------------------------------------------------------------------- #
# PDF — best-effort strip via pikepdf if available
# --------------------------------------------------------------------------- #
def strip_pdf_bytes(path: Path) -> bytes:
    """Strip /DocInfo + XMP from PDF via pikepdf.

    pikepdf is python-only on most distros. If you don't have it,
    fall back to:  qpdf --empty --pages in.pdf -- out.pdf
    (qpdf is in apt / pacman / dnf, usually preinstalled on Kali).
    """
    try:
        import pikepdf
    except ImportError:
        print(
            f"  ! PDF strip needs pikepdf ( pip3 install pikepdf )\n"
            f"  ! OR shell fallback: qpdf --linearize --encrypt '' '' 0 -- "
            f"{path.name} --", file=sys.stderr
        )
        return b""

    try:
        with pikepdf.open(path, allow_overwriting_input=True) as pdf:
            try:
                # pikepdf: assigning None to a Root property removes that key.
                # This nukes the XMP metadata stream entirely.
                if "/Metadata" in pdf.Root:
                    pdf.Root.Metadata = None
            except Exception:
                pass
            try:
                # /Info (DocInfo) holds title/author/creator/date...
                # pikepdf requires the new value to be an INDIRECT object,
                # otherwise assignment silently raises ValueError. Clearing
                # to an empty indirect dictionary removes every /Info key.
                pdf.docinfo = pdf.make_indirect(pikepdf.Dictionary())
            except Exception:
                # if that failed the /Info must still be replaced — delete
                # the trailer key outright as a fallback
                try:
                    del pdf.trailer["/Info"]
                except Exception:
                    pass
            buf = io.BytesIO()
            pdf.save(buf)
            return buf.getvalue()
    except Exception as e:
        # corrupt / encrypted / half-written PDF — be a failure, not a
        # silent "processed" (caller uses return b"" to skip the write)
        print(f"  {c_err('[ERR]')} {c_warn(path.name)}: PDF strip failed: {e}",
              file=sys.stderr)
        return b""


# --------------------------------------------------------------------------- #
# driver
# --------------------------------------------------------------------------- #
def write_output(src: Path, out: Optional[Path], cleaned: bytes) -> None:
    """Either overwrite src in place, or write to `out` (file or dir)."""
    if out is None:
        # atomic-ish: write new inode, then rename over the original.
        # Preserve mode + mtime so a 0600 private photo stays 0600.
        st = src.stat()
        tmp = src.with_suffix(src.suffix + ".exifwipe_tmp")
        tmp.write_bytes(cleaned)
        os.chmod(tmp, st.st_mode)
        os.utime(tmp, ns=(st.st_atime_ns, st.st_mtime_ns))
        os.replace(tmp, src)
        print(f"  {c_ok('[STRIPPED]')} {c_head(str(src))}")
    else:
        # if user passed a folder or a path-without-suffix, drop src inside
        if out.is_dir() or (not out.suffix and not out.exists()):
            out = out / src.name
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(cleaned)
        print(f"  {c_ok('[STRIPPED]')} {c_head(str(src))}  {c_dim('->')}  {c_head(str(out))}")


def _sniff_format(path: Path) -> Optional[str]:
    """Detect a file's real format from its magic bytes, not its name.
    Returns a normalized format name ('jpeg', 'png', 'gif', 'tiff',
    'webp', 'bmp', 'heif', 'avif', 'pdf') or None if unrecognized."""
    try:
        head = path.open("rb").read(16)
    except OSError:
        return None
    if head[:2] == b"\xff\xd8":
        return "jpeg"
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    if head[:4] in (b"II*\x00", b"MM\x00*"):
        return "tiff"
    if head[:2] == b"BM":
        return "bmp"
    if head[:4] == b"%PDF":
        return "pdf"
    if head[4:8] == b"ftyp":
        brand = head[8:12]
        # HEIF/AVIF share the ISO BMFF container; disambiguate by brand
        if brand in (b"avif", b"avis"):
            return "avif"
        if brand in (b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1",
                     b"heif", b"heim"):
            return "heif"
    return None


def handle_one(path: Path, args: argparse.Namespace) -> bool:
    """Return True if the file was processed successfully, False on error.

    The flow per file:
      - dry-run       -> inspect what would happen and return.
      - inspect-only  -> inspect and return.
      - otherwise     -> strip and write.

    Dispatch is by magic bytes (sniffed), not by file extension, so a
    downloaded JPEG with no extension is still stripped. The extension
    only degrades to deciding the output filename."""

    fmt = _sniff_format(path) if path.is_file() else None
    if fmt is None:
        # not a real image/pdf we recognize — skip silently on dry-ness
        if args.verbose:
            print(f"  {c_dim('[skip] unrecognized:')} {path.name}")
        return False

    if fmt in ("jpeg", "png", "gif", "tiff", "webp", "bmp", "heif", "avif"):
        if args.dry_run or args.inspect:
            try:
                inspect_image(path)
            except Exception as e:
                print(f"  {c_err('[ERR]')} {c_warn(path.name)}: {e}", file=sys.stderr)
                return False
            return True
        try:
            cleaned, fmt_out = strip_image_bytes(path, keep_icc=args.keep_icc)
            write_output(path, args.output, cleaned)
        except Exception as e:
            print(f"  {c_err('[ERR]')} {c_warn(path.name)}: {e}", file=sys.stderr)
            return False
        if args.verbose:
            try:
                inspect_image(path if args.output is None else args.output / path.name)
            except Exception as e:
                print(f"  {c_err('[ERR]')} {c_warn(path.name)}: {e}", file=sys.stderr)
        return True

    if fmt == "pdf":
        if args.dry_run or args.inspect:
            print(f"  {c_dim('(would strip PDF metadata)')} {path.name}")
            return True
        cleaned = strip_pdf_bytes(path)
        if not cleaned:
            return False
        try:
            write_output(path, args.output, cleaned)
        except Exception as e:
            print(f"  {c_err('[ERR]')} {c_warn(path.name)}: {e}", file=sys.stderr)
            return False
        return True

    if args.verbose:
        print(f"  {c_dim('[skip] unsupported:')} {path.name}")
    return False


def iter_inputs(path: Path) -> Iterable[Path]:
    if path.is_file():
        yield path
    elif path.is_dir():
        yield from (p for p in path.rglob("*") if p.is_file())
    else:
        raise FileNotFoundError(path)


# --------------------------------------------------------------------------- #
# interactive menu — `exifwipe` with no args
# --------------------------------------------------------------------------- #
_MENU_ART = r"""
   ███████╗██╗  ██╗██╗███████╗██╗    ██╗██╗██████╗ ███████╗
   ██╔════╝╚██╗██╔╝██║██╔════╝██║    ██║██║██╔══██╗██╔════╝
   █████╗   ╚███╔╝ ██║█████╗  ██║ █╗ ██║██║██████╔╝█████╗
   ██╔══╝   ██╔██╗ ██║██╔══╝  ██║███╗██║██║██╔═══╝ ██╔══╝
   ███████╗██╔╝ ██╗██║███████╗╚███╔███╔╝██║██║     ███████╗
   ╚══════╝╚═╝  ╚═╝╚═╝╚══════╝ ╚══╝╚══╝ ╚══════╝ ╚═════╝"""


def print_top_banner() -> None:
    for line in _MENU_ART.splitlines():
        print(c_blue(line))
    print(c_dim("    wipe EXIF from images and PDFs — pick a move, hit Enter"))
    print()


def prompt_input(label: str) -> str:
    try:
        return input(f"  {c_info(label + '')} > ")
    except (EOFError, KeyboardInterrupt):
        print()
        return ""


def _run_menu_action(action: str, path: Path, keep_icc: bool, dry_run: bool) -> None:
    """Run one interactive operation against a path (reuses handle_one)."""
    ns = argparse.Namespace(output=None, keep_icc=keep_icc, dry_run=dry_run,
                            inspect=False, verbose=False)
    if action == "inspect":
        ns.inspect = True

    targets = list(iter_inputs(path))
    if not targets:
        print(c_warn("    nothing processed (no supported files found)"))
        return
    n_ok, n_err = 0, 0
    for p in targets:
        if handle_one(p, ns):
            n_ok += 1
        else:
            n_err += 1
    print(f"\n  {c_ok(str(n_ok))} processed, {c_err(str(n_err))} errors")


def _state(val: bool) -> str:
    return c_ok("on") if val else c_err("off")


def menu_choose(keep_icc: bool, dry_run: bool) -> str:
    print()
    print(c_head("  ▸ what do you want to do?"))
    print(f"    {c_head('[1]')} strip one file")
    print(f"    {c_head('[2]')} strip a whole folder (recursive)")
    print(f"    {c_head('[3]')} inspect a file (see what ExifTool would surface)")
    print(f"    {c_head('[4]')} dry-run a file or folder (no writes)")
    print(f"    {c_head('[5]')} toggle: keep ICC profile    now: {c_mag('[ ' + _state(keep_icc) + ' ]')}")
    print(f"    {c_head('[6]')} toggle: dry-run             now: {c_mag('[ ' + _state(dry_run) + ' ]')}")
    print(f"    {c_head('[q]')} quit")
    return prompt_input("choice")


def run_interactive_menu() -> int:
    print_top_banner()
    keep_icc, dry_run = False, False
    while True:
        choice = menu_choose(keep_icc, dry_run).strip().lower()
        if choice in ("q", "quit", "exit", ""):
            print(c_dim("    later."))
            return 0
        if choice == "5":
            keep_icc = not keep_icc
            continue
        if choice == "6":
            dry_run = not dry_run
            continue
        if choice not in ("1", "2", "3", "4"):
            print(c_warn("    pick 1-6 or q."))
            continue
        raw = prompt_input("Target path").strip()
        if not raw:
            continue
        path = Path(raw).expanduser()
        if not path.exists():
            print(c_err(f"    not found: {path}"))
            continue
        action = {"1": "strip", "2": "strip", "3": "inspect", "4": "dry"}[choice]
        if action == "dry":
            dry_run = True
        _run_menu_action(action, path, keep_icc, dry_run)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="exifwipe",
        description=("Make ExifTool return blank for an image or PDF.\n"
                     "Strips EXIF / XMP / GPS / MakerNotes / PNG text chunks "
                     "/ WebP XMP / HEIC EXIF / PDF DocInfo+XMP.\n"
                     "Built around the pattern from production metadata-scrubbers: "
                     "pixel rebuild + Pillow exif=b''  + piexif round-trip verify."),
        epilog=(
            "examples:\n"
            "  exifwipe photo.jpg                       # strip in place\n"
            "  exifwipe ./images/ -o ./clean/           # batch to new folder\n"
            "  exifwipe photo.jpg --inspect             # preview what exiftool sees\n"
            "  exifwipe photo.jpg --dry-run -v          # verbose inspect, no writes\n"
            "\n"
            "aliases I keep in my shell:\n"
            "  alias sc=exifwipe ~/Pictures/Screenshots/*.png\n"
            "  alias sm=exifwipe ~/Pictures/Shotwell/*/*.JPG -o ~/clean/\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("input", nargs="?", type=Path, default=None,
                   help="image file, PDF, or directory (omit to open the menu)")
    p.add_argument("-o", "--output", type=Path, default=None,
                   help="output file or dir (default: strip in place)")
    p.add_argument("--keep-icc", action="store_true",
                   help="preserve ICC color profile (default: also stripped)")
    p.add_argument("--dry-run", action="store_true",
                   help="inspect what would be stripped, write nothing")
    p.add_argument("--inspect", action="store_true",
                   help="print metadata exiftool-style and exit (no write)")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="also print inspection after stripping")
    color_group = p.add_mutually_exclusive_group()
    color_group.add_argument("--color", dest="color", action="store_const",
                             const=True, default=None,
                             help="force ANSI colors even when piped")
    color_group.add_argument("--no-color", dest="color", action="store_const",
                             const=False,
                             help="disable ANSI colors entirely")
    return p


def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv)
    set_color(args.color)

    # no input → interactive menu
    if args.input is None:
        return run_interactive_menu()

    # --inspect is a read-only mode
    if args.inspect:
        targets = list(iter_inputs(args.input))
        n_err = 0
        for p in targets:
            try:
                fmt = _sniff_format(p) if p.is_file() else None
                if fmt in ("jpeg", "png", "gif", "tiff", "webp", "bmp",
                           "heif", "avif"):
                    inspect_image(p)
                elif fmt == "pdf":
                    print(f"\n=== {p.name} ===")
                    print("  (PDF — use pikepdf or `exiftool -all=` to inspect)")
            except Exception as e:
                print(f"  {c_err('[ERR]')} {c_warn(p.name)}: {e}", file=sys.stderr)
                n_err += 1
        print("\n-- exiftool reference --\n" + exiftool_hint())
        return 0 if n_err == 0 else 3

    if not args.input.exists():
        print(f"  [ERR] not found: {args.input}", file=sys.stderr)
        return 2

    targets = list(iter_inputs(args.input))

    # guard: batch input to a single-file `-o` silently overwrites itself.
    # If --output looks like a FILE (has a suffix, isn't a dir) but we're
    # about to process more than one source, refuse loudly instead.
    output_is_file = (args.output is not None and args.output.suffix
                      and not args.output.is_dir())
    if output_is_file and len(targets) > 1:
        print(
            f"  {c_err('[ERR]')} -o looks like a single file but "
            f"{len(targets)} inputs are queued. Point -o at a directory instead.",
            file=sys.stderr,
        )
        return 2

    n_ok, n_err = 0, 0
    for p in targets:
        if handle_one(p, args):
            n_ok += 1
        else:
            n_err += 1

    print(f"\ndone. {n_ok} processed, {n_err} errors.")
    if piexif is None:
        print("tip: install piexif for JPEG round-trip verify:  pip3 install piexif",
              file=sys.stderr)
    return 0 if n_err == 0 else 3


if __name__ == "__main__":
    raise SystemExit(main())
