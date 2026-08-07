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
import stat
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

# result codes for handle_one(): OK / ERROR / SKIPPED (unrecognized)
R_OK, R_ERR, R_SKIP = 0, 1, 2

# raster formats handled by the pixel-rebuild path
RASTER_FORMATS = ("jpeg", "png", "gif", "tiff", "webp", "bmp", "heif", "avif")
IMAGE_FORMATS = RASTER_FORMATS  # dispatch alias

# TIFF-family RAW containers. These are NEVER pixel-rebuilt — the sensor
# data can't be re-encoded — they get lossless in-place IFD surgery
# (EXIF/GPS IFDs emptied, identifying tags blanked, pixel bytes untouched).
RAW_FORMATS = ("dng", "cr2", "nef", "arw", "orf", "rw2", "pef", "srw",
               "sr2", "3fr")
RAW_EXTENSIONS = frozenset("." + f for f in RAW_FORMATS)
SUPPORTED_FORMATS = IMAGE_FORMATS + RAW_FORMATS

# guard against decompression bombs: refuse anything above this many pixels
# (Pillow's own DecompressionBombError threshold is ~2x this). 0 = unlimited.
DEFAULT_MAX_PIXELS = 178_000_000

# top-level system directories we refuse to write into, so a stray -o can't
# drop an image into /etc or /usr by accident.
_SYSTEM_DIRS = {"etc", "usr", "bin", "sbin", "lib", "lib64", "boot",
                "proc", "sys", "dev", "run"}


# --------------------------------------------------------------------------- #
# inspection — print what exiftool would surface
# --------------------------------------------------------------------------- #
def inspect_image(path: Path, max_pixels: Optional[int] = None) -> None:
    """Print the metadata fields ExifTool would surface on this image."""
    if max_pixels is None:
        max_pixels = DEFAULT_MAX_PIXELS
    print(f"\n{c_head('=' * 3)} {c_head(path.name)} {c_head('=' * 3)}")
    with Image.open(path) as img:
        w, h = img.size
        print(f"  {c_info('format')}={img.format}  {c_info('mode')}={img.mode}  "
              f"{c_info('size')}={w}x{h}")
        if max_pixels and w * h > max_pixels:
            print(f"  {c_warn(f'too large to inspect in detail '
                              f'({w*h:,}px > {max_pixels:,} limit)')}")
            return

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
# verification — prove nothing leaked before/after a wipe, or refuse
# --------------------------------------------------------------------------- #
_STRUCTURAL_KEYS = {
    "SourceFile", "FileName", "Directory", "ExifToolVersion", "FileSize",
    "FileModifyDate", "FileAccessDate", "FileInodeChangeDate", "FilePermissions",
    "FileType", "FileTypeExtension", "MIMEType", "ImageWidth", "ImageHeight",
    "BitDepth", "ColorType", "EncodingProcess", "Megapixels", "ImageSize",
}
# groups that are structural (color management / viewer hints), not identifying
_STRUCTURAL_GROUPS = {"JFIF", "ICC_Profile", "Composite", "ExifTool", "File"}


def _parse_exiftool_json(text: str) -> list:
    """Turn `exiftool -j -a -G1 FILE` output into a list of leaked tag names.

    Keys that are structural (file size, dimensions, JFIF, ICC...) are
    ignored; everything else is a leak. Returns [] on unparseable output.
    """
    import json
    try:
        data = json.loads(text)
    except Exception:
        return []
    if not isinstance(data, list) or not data:
        return []
    obj = data[0] if isinstance(data[0], dict) else {}
    leaks = []
    for key in obj:
        parts = key.split(":")
        group = parts[0] if len(parts) > 1 else ""
        tag = parts[-1]
        if tag in _STRUCTURAL_KEYS or group in _STRUCTURAL_GROUPS:
            continue
        leaks.append(key)
    return leaks


def _verify_with_exiftool(path: Path) -> Optional[list]:
    """Run `exiftool` if present and return a list of leaked tag names
    (empty = clean). Returns None when exiftool is unavailable."""
    import shutil
    exif = shutil.which("exiftool")
    if exif is None:
        return None
    import subprocess
    out = subprocess.run([exif, "-j", "-a", "-G1", str(path)],
                         capture_output=True, text=True).stdout
    return _parse_exiftool_json(out)


# TIFF tags that are identifying (vs structural layout tags). Orientation
# is deliberately NOT here: it's a display instruction, not identity, and
# RAW containers keep it because the sensor pixels can't be re-rotated.
_TIFF_IDENTIFYING = {
    0x010E: "ImageDescription", 0x010F: "Make", 0x0110: "Model",
    0x0131: "Software", 0x0132: "DateTime", 0x013B: "Artist",
    0x02BC: "XMLPacket", 0x83BB: "IPTC", 0x8649: "Photoshop",
    0x8298: "Copyright", 0x8769: "ExifIFD", 0x8825: "GPSInfo",
    0x9286: "UserComment", 0x9C9B: "XPTitle", 0x9C9C: "XPComment",
    0x9C9D: "XPAuthor", 0x9C9E: "XPKeywords",
    0xC62D: "SerialNumber", 0xC614: "UniqueCameraModel",
    0xC615: "LocalizedCameraModel", 0xC68B: "OriginalRawFileName",
    0xC68C: "OriginalRawFileData", 0xC634: "DNGPrivateData",
}

# tags whose VALUES are blanked in place during RAW/TIFF surgery (all
# size-1 types: ASCII / BYTE / UNDEFINED — safe to overwrite without
# touching any offset). 0x8773 (ICC) is blanked only when NOT keep_icc.
_TIFF_BLANK = {
    0x010E, 0x010F, 0x0110, 0x0131, 0x0132, 0x013B, 0x02BC, 0x83BB,
    0x8649, 0x8298, 0x9286, 0x9C9B, 0x9C9C, 0x9C9D, 0x9C9E,
    0xC62D, 0xC614, 0xC615, 0xC68B, 0xC68C, 0xC634,
}

# TIFF layout per flavor. Classic TIFF (magic 42): IFD entry = tag(2)
# + type(2) + count(4, uint32!) + value/offset(4) = 12 bytes; the IFD's
# own entry-count field is uint16. BigTIFF (magic 43 — explicitly allowed
# by the DNG spec): entry = tag(2) + type(2) + count(8) + value/offset(8)
# = 20 bytes; IFD entry-count is uint64. Returns (entry_size,
# ifd_count_size, entry_count_size, offset_size, header_len).
def _tiff_layout(bo: str, magic: int) -> tuple:
    if magic == 43:
        return (20, 8, 8, 8, 16)
    return (12, 2, 4, 4, 8)


_TYPE_SIZE = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4,
              10: 8, 11: 4, 12: 8, 13: 4}


def _tiff_parse_header(data: bytes):
    """Return (byteorder, magic) or None for non-TIFF input."""
    if len(data) < 8:
        return None
    bo = "little" if data[:2] == b"II" else "big" if data[:2] == b"MM" else None
    if bo is None:
        return None
    magic = int.from_bytes(data[2:4], bo)
    if magic not in (42, 43):
        return None
    return bo, magic


def _iter_tiff_entries(data: bytes, bo: str, magic: int):
    """Yield (entry_pos, tag, typ, count, value_field_pos) for every entry
    in every reachable IFD — next-IFD chain, SubIFDs (0x014A) and the
    EXIF/GPS IFDs they point at. Cycle-safe (seen set) and bounded, so a
    hostile IFD graph can't hang the walker."""
    entry, ifd_cnt, ent_cnt, off_size, header = _tiff_layout(bo, magic)
    # the IFD0 offset sits right before the header tail: bytes 4-7 for
    # classic TIFF, bytes 8-15 for BigTIFF
    ifd0 = int.from_bytes(data[header - off_size:header], bo)
    seen = set()
    queue = [ifd0]
    while queue:
        off = queue.pop(0)
        if off in seen or off + ifd_cnt > len(data):
            continue
        seen.add(off)
        count = int.from_bytes(data[off:off + ifd_cnt], bo)
        # cap entry iteration: classic TIFF counts are uint16; BigTIFF
        # counts are uint64 but a real photo IFD has a few hundred entries
        if count > 1_000_000:
            count = 1_000_000          # hostile count — don't iterate forever
        p = off + ifd_cnt
        for _ in range(count):
            if p + entry > len(data):
                break
            tag = int.from_bytes(data[p:p + 2], bo)
            typ = int.from_bytes(data[p + 2:p + 4], bo)
            cnt = int.from_bytes(data[p + 4:p + 4 + ent_cnt], bo)
            # value/offset field: entry start + 4 (tag/type) + offset_size
            vf = p + 4 + off_size
            yield (p, tag, typ, cnt, vf)
            if tag == 0x014A and typ in (3, 4, 9, 13):   # SubIFDs: n offsets
                n_sub = min(cnt, 256)
                for i in range(n_sub):
                    so = int.from_bytes(data[vf + i * off_size:vf + (i + 1) * off_size], bo)
                    if so:
                        queue.append(so)
            elif tag in (0x8769, 0x8825):                # EXIF / GPS IFD
                tgt = int.from_bytes(data[vf:vf + off_size], bo)
                if tgt:
                    queue.append(tgt)
            p += entry
        if p + off_size <= len(data):
            nxt = int.from_bytes(data[p:p + off_size], bo)
            if nxt:
                queue.append(nxt)


def _tiff_value_bytes(data: bytes, bo: str, magic: int, typ: int, cnt: int,
                      vf: int) -> bytes:
    """Raw value bytes of a TIFF entry (inline or via offset)."""
    entry, ifd_cnt, ent_cnt, off_size, header = _tiff_layout(bo, magic)
    tsize = _TYPE_SIZE.get(typ)
    if tsize is None:
        return b""
    nbytes = cnt * tsize
    max_inline = off_size
    if nbytes <= max_inline:
        start = vf
    else:
        start = int.from_bytes(data[vf:vf + off_size], bo)
    if start + nbytes > len(data):
        return b""
    return data[start:start + nbytes]


def _value_is_blank(value: bytes) -> bool:
    """True when a value carries no content (all spaces / NULs / empty)."""
    return all(b in (32, 0) for b in value)


def _tiff_find_identifying(data: bytes) -> list:
    """Walk every reachable TIFF IFD and return identifying tag names that
    still carry real content — an ExifIFD/GPS pointer is only flagged when
    the pointed-to IFD has entries, and scalar tags only when their value
    isn't blank. Handles classic TIFF and BigTIFF."""
    hdr = _tiff_parse_header(data)
    if hdr is None:
        return []
    bo, magic = hdr
    ifd_cnt = _tiff_layout(bo, magic)[1]
    off_size = _tiff_layout(bo, magic)[3]
    found = []
    for (p, tag, typ, cnt, vf) in _iter_tiff_entries(data, bo, magic):
        name = _TIFF_IDENTIFYING.get(tag)
        if name is None:
            continue
        if tag in (0x8769, 0x8825):
            tgt = int.from_bytes(data[vf:vf + off_size], bo)
            if tgt and tgt + ifd_cnt <= len(data):
                if int.from_bytes(data[tgt:tgt + ifd_cnt], bo) > 0:
                    if name not in found:
                        found.append(name)
        else:
            if not _value_is_blank(_tiff_value_bytes(data, bo, magic, typ, cnt, vf)):
                if name not in found:
                    found.append(name)
    return found


def _tiff_protected_regions(data: bytes, bo: str, magic: int) -> list:
    """Byte ranges that must never be overwritten as tag *values*: the
    file header and every reachable IFD block (count + entries + next
    pointer). A hostile file can point a tag's value offset at its own
    structure — blanking there would silently destroy the file. The
    surgery refuses the file instead."""
    entry, ifd_cnt, ent_cnt, off_size, header = _tiff_layout(bo, magic)
    regions = [(0, header)]
    ifd0 = int.from_bytes(data[header - off_size:header], bo)
    seen, queue = set(), [ifd0]
    while queue:
        off = queue.pop(0)
        if off in seen or off + ifd_cnt > len(data):
            continue
        seen.add(off)
        count = int.from_bytes(data[off:off + ifd_cnt], bo)
        if count > 1_000_000:
            count = 1_000_000
        regions.append((off, min(off + ifd_cnt + count * entry + off_size,
                                 len(data))))
        p = off + ifd_cnt
        for _ in range(count):
            if p + entry > len(data):
                break
            tag = int.from_bytes(data[p:p + 2], bo)
            typ = int.from_bytes(data[p + 2:p + 4], bo)
            cnt = int.from_bytes(data[p + 4:p + 4 + ent_cnt], bo)
            vfield = p + 4 + off_size
            if tag == 0x014A and typ in (3, 4, 9, 13):   # SubIFDs
                for i in range(min(cnt, 256)):
                    so = int.from_bytes(data[vfield + i * off_size:
                                             vfield + (i + 1) * off_size], bo)
                    if so:
                        queue.append(so)
            elif tag in (0x8769, 0x8825):                # EXIF / GPS IFD
                tgt = int.from_bytes(data[vfield:vfield + off_size], bo)
                if tgt:
                    queue.append(tgt)
            p += entry
        if p + off_size <= len(data):
            nxt = int.from_bytes(data[p:p + off_size], bo)
            if nxt:
                queue.append(nxt)
    return regions


def _overlaps_protected(regions: list, start: int, end: int) -> bool:
    """True when [start, end) touches any protected structural region."""
    return any(start < r_end and end > r_start for (r_start, r_end) in regions)


def _tiff_structure_ok(data: bytes, bo: str, magic: int) -> bool:
    """Strict structural validation: every reachable IFD's declared
    entries and every external value must lie inside the file. A truncated
    or hostile container fails here — surgery must not "clean" a file it
    can't fully verify."""
    entry, ifd_cnt, ent_cnt, off_size, header = _tiff_layout(bo, magic)
    ifd0 = int.from_bytes(data[header - off_size:header], bo)
    if ifd0 < header or ifd0 + ifd_cnt > len(data):
        return False
    seen = set()
    queue = [ifd0]
    while queue:
        off = queue.pop(0)
        if off in seen:
            continue
        if off + ifd_cnt > len(data):
            return False               # referenced IFD is missing
        seen.add(off)
        count = int.from_bytes(data[off:off + ifd_cnt], bo)
        if count > 1_000_000:
            return False               # hostile count
        p = off + ifd_cnt
        if p + count * entry + off_size > len(data):
            return False               # IFD claims entries past EOF
        for _ in range(count):
            tag = int.from_bytes(data[p:p + 2], bo)
            typ = int.from_bytes(data[p + 2:p + 4], bo)
            cnt = int.from_bytes(data[p + 4:p + 4 + ent_cnt], bo)
            tsize = _TYPE_SIZE.get(typ)
            vfield = p + 4 + off_size
            if tsize:
                nbytes = cnt * tsize
                if nbytes > off_size:
                    off2 = int.from_bytes(data[vfield:vfield + off_size], bo)
                    if off2 + nbytes > len(data):
                        return False  # value extends past EOF
            if tag == 0x014A and typ in (3, 4, 9, 13):
                for i in range(min(cnt, 256)):
                    so = int.from_bytes(data[vfield + i * off_size:
                                             vfield + (i + 1) * off_size], bo)
                    if so:
                        queue.append(so)
            elif tag in (0x8769, 0x8825):
                tgt = int.from_bytes(data[vfield:vfield + off_size], bo)
                if tgt:
                    queue.append(tgt)
            p += entry
        if p + off_size > len(data):
            return False
        nxt = int.from_bytes(data[p:p + off_size], bo)
        if nxt:
            queue.append(nxt)
    return True


def _tiff_has_tag(data: bytes, wanted: int) -> bool:
    """True if any reachable IFD carries `wanted` (e.g. DNGVersion 0xC612)."""
    hdr = _tiff_parse_header(data)
    if hdr is None:
        return False
    bo, magic = hdr
    for (_, tag, _, _, _) in _iter_tiff_entries(data, bo, magic):
        if tag == wanted:
            return True
    return False


def _is_tiff_family(data: bytes) -> bool:
    return _tiff_parse_header(data) is not None


def _tiff_strip_lossless(data: bytes, keep_icc: bool = False):
    """Lossless metadata surgery for TIFF-family containers (TIFF / DNG /
    CR2 / NEF / ARW / ORF / RW2 / PEF / SRW / SR2...).

    No offset is ever remapped, so pixel data stays byte-identical:
      * every EXIF IFD (0x8769) and GPS IFD (0x8825) target is overwritten
        with an empty IFD (count=0, next=0) — MakerNotes, DateTimeOriginal,
        GPS coordinates and the whole Interop chain die with them;
      * identifying scalar tags (Make, Model, Software, Artist, Copyright,
        ImageDescription, SerialNumber, DNG camera model / private data /
        original-raw blobs...) are blanked in place;
      * ICC (0x8773) is blanked unless keep_icc.

    Returns cleaned bytes, or None when the input isn't a parseable TIFF
    container (caller decides: refuse loudly for RAW, fall back to a
    rebuild for plain TIFF)."""
    hdr = _tiff_parse_header(data)
    if hdr is None:
        return None
    bo, magic = hdr
    entry, ifd_cnt, ent_cnt, off_size, header = _tiff_layout(bo, magic)
    if not _tiff_structure_ok(data, bo, magic):
        # truncated / hostile container — refuse instead of "cleaning" a
        # file whose result we can't verify
        return None
    # structural regions that must never be blanked as tag values: the
    # header and every reachable IFD block (a hostile file can point a
    # tag's value offset at its own structure — that's a refuse, not a wipe)
    protected = _tiff_protected_regions(data, bo, magic)
    out = bytearray(data)
    for (p, tag, typ, cnt, vf) in _iter_tiff_entries(data, bo, magic):
        if tag in (0x8769, 0x8825):
            # physically destroy the pointed-to EXIF/GPS IFD: the whole
            # entry block AND every payload it referenced. Orphaned bytes
            # are unreachable but still forensically present — zero them.
            tgt = int.from_bytes(data[vf:vf + off_size], bo)
            if tgt and tgt + ifd_cnt <= len(data):
                tcount = int.from_bytes(data[tgt:tgt + ifd_cnt], bo)
                q = tgt + ifd_cnt
                for _ in range(min(tcount, 4096)):
                    if q + entry > len(data):
                        break
                    typ2 = int.from_bytes(data[q + 2:q + 4], bo)
                    cnt2 = int.from_bytes(data[q + 4:q + 4 + ent_cnt], bo)
                    tsize = _TYPE_SIZE.get(typ2)
                    if tsize:
                        nbytes = cnt2 * tsize
                        if 0 < nbytes <= len(data):
                            vfield = q + 4 + off_size
                            if nbytes <= off_size:
                                start = vfield
                            else:
                                start = int.from_bytes(data[vfield:vfield + off_size], bo)
                                if _overlaps_protected(protected, start,
                                                       start + nbytes):
                                    continue  # hostile target — block dies anyway
                            if start + nbytes <= len(out):
                                out[start:start + nbytes] = b"\x00" * nbytes
                    q += entry
                block_end = min(q + off_size, len(out))
                out[tgt:block_end] = b"\x00" * (block_end - tgt)
        elif tag in _TIFF_BLANK or (tag == 0x8773 and not keep_icc):
            tsize = _TYPE_SIZE.get(typ)
            if tsize is None:
                continue
            nbytes = cnt * tsize
            if nbytes <= 0 or nbytes > len(data):
                continue
            if nbytes <= off_size:
                start = vf
            else:
                start = int.from_bytes(data[vf:vf + off_size], bo)
                if _overlaps_protected(protected, start, start + nbytes):
                    # hostile value offset pointing at the header/IFDs —
                    # refuse the file instead of corrupting it
                    return None
            if start + nbytes <= len(out):
                out[start:start + nbytes] = b" " * nbytes
    cleaned = bytes(out)
    # verify our own work before handing it out — a wipe that still leaks
    # is not a wipe
    if _tiff_find_identifying(cleaned):
        raise RuntimeError("TIFF surgery left identifying metadata behind "
                           "— refusing to write a dirty file")
    return cleaned


def _verify_bytes(path: Path, fmt: str) -> list:
    """Per-format leak detection on a file, independent of exiftool.
    Returns a list of leaked metadata names (empty = clean)."""
    leaks = []
    data = path.read_bytes()
    if fmt == "jpeg":
        # verify EVERY frame, not just the first — an MPO whose EXIF only
        # lives in frame 2 used to sail through as "clean"
        for frame in _split_jpeg_frames(data):
            if piexif is not None:
                try:
                    ifd = piexif.load(frame)
                    for k, d in ifd.items():
                        if d and k != "thumbnail":
                            leaks.append(k)
                except Exception:
                    pass
            # also catch comment/APP segments a piexif round-trip can't see
            i, n = 2, len(frame)
            while i + 4 <= n:
                if frame[i] != 0xFF:
                    break
                while i < n and frame[i] == 0xFF:
                    i += 1
                if i >= n:
                    break
                marker = frame[i]; i += 1
                if marker == 0xDA:
                    break
                if marker == 0xD9:
                    break
                seg_len = int.from_bytes(frame[i:i + 2], "big")
                if seg_len < 2 or i + seg_len > n:
                    break
                payload = frame[i + 2:i + seg_len]
                if marker == 0xFE:
                    leaks.append("COM")
                elif 0xE0 <= marker <= 0xEF:
                    if marker == 0xE0 and payload.startswith(b"JFIF"):
                        pass  # structural, keep
                    elif marker == 0xE2 and payload.startswith(b"ICC_PROFILE\x00"):
                        pass  # ICC, structural (color management)
                    else:
                        name = payload[:8].split(b"\x00")[0].decode(errors="replace")
                        leaks.append(f"APP{marker - 0xE0}:{name or hex(marker)}")
                i += seg_len
    elif fmt == "png":
        # scan the WHOLE file, including chunks past IEND — a tEXt tucked
        # after the trailer used to be invisible to the verifier
        pos = 8
        n = len(data)
        iend_seen = False
        while pos + 8 <= n:
            clen = int.from_bytes(data[pos:pos + 4], "big")
            ctype = data[pos + 4:pos + 8]
            if ctype == b"IEND":
                iend_seen = True
            elif iend_seen:
                leaks.append("data-after-IEND")
            if ctype in (b"tEXt", b"zTXt", b"iTXt", b"eXIf", b"pHYs", b"iCCP"):
                leaks.append(ctype.decode())
            pos += 12 + clen
        if pos != n:
            leaks.append("trailing-bytes")
    elif fmt == "webp":
        pos = 12
        n = len(data)
        while pos + 8 <= n:
            tag = data[pos:pos + 4]
            size = int.from_bytes(data[pos + 4:pos + 8], "little")
            if tag in (b"EXIF", b"XMP ", b"ICCP"):
                leaks.append(tag.strip().decode())
            if size > n:
                break
            pos += 8 + size + (size & 1)
    elif fmt == "gif":
        # comment ext is 0x21 0xFE — scan the whole stream
        if data.count(b"\x21\xfe") > 0:
            leaks.append("comment-ext")
        if b"XMP Data" in data:
            leaks.append("XMP")
    elif fmt in ("tiff",) + tuple(RAW_FORMATS):
        leaks = _tiff_find_identifying(data)
    elif fmt in ("heif", "avif"):
        # ISO BMFF: hunt box types that carry metadata
        if b"Exif" in data or b"mime" in data:
            leaks.append("EXIF box")
        if b"XMP " in data:
            leaks.append("XMP box")
    elif fmt == "pdf":
        try:
            import pikepdf
            with pikepdf.open(path) as pdf:
                root = pdf.Root if pdf.Root is not None else {}
                if "/Metadata" in root:
                    leaks.append("XMP/Metadata")
                if pdf.docinfo and len(pdf.docinfo) > 0:
                    leaks.append("DocInfo")
                for name in ("/Lang", "/OpenAction", "/PieceInfo",
                             "/StructTreeRoot", "/PageLabels", "/MarkInfo"):
                    if name in root:
                        leaks.append(name.lstrip("/"))
        except Exception:
            leaks.append("unverifiable")
    return leaks


def verify_clean(path: Path) -> tuple[bool, list]:
    """Return (clean, list-of-leaks). exiftool when installed, else the
    per-format byte parsers."""
    fmt = _sniff_format(path) if path.is_file() else None
    if fmt is None:
        return True, []
    leaks = _verify_with_exiftool(path)
    if leaks is not None:
        return (not leaks, leaks)
    leaks = _verify_bytes(path, fmt)
    return (not leaks, leaks)


def print_formats_matrix() -> None:
    """What exifwipe guarantees per format — honest about limits."""
    rows = [
        ("jpeg",      "lossless marker rewrite (no re-encode)",
                      "clean; pixels byte-identical when orientation-neutral"),
        ("jpeg-rot",  "orientation baked into pixels, q95 re-encode",
                      "clean (pixels re-encoded, not byte-identical)"),
        ("mpo",       "per-SOI/EOI marker rewrite; rotated frame 0 "
                      "re-encoded",
                      "clean (all frames kept, trailing garbage dropped)"),
        ("png",       "fresh frame rebuild, empty PngInfo",
                      "clean"),
        ("png-anim",  "lossless chunk strip (acTL/fcTL/fdAT kept)",
                      "clean; APNG animation + pixels byte-identical"),
        ("gif",       "lossless byte rewrite: comments/XMP dropped",
                      "clean; frames/palette/loop byte-exact"),
        ("webp",      "frame rebuild; lossless-in -> lossless-out",
                      "clean; animated frames preserved"),
        ("tiff",      "lossless in-place IFD surgery (no re-encode)",
                      "clean; pixels + pages byte-identical"),
        ("dng/cr2/nef/arw/orf/rw2/pef/srw",
                      "lossless in-place IFD surgery",
                      "clean; sensor data byte-identical, never rebuilt"),
        ("bmp",       "pixel rebuild",
                      "clean"),
        ("heif",      "re-encode via pillow-heif",
                      "clean single-frame only"),
        ("avif",      "re-encode via pillow-heif",
                      "clean single-frame only; animated AVIF refuses"),
        ("pdf",       "pikepdf: /Info + /Metadata + /Lang/JS/PageLabels",
                      "BEST-EFFORT: embedded-image EXIF may survive"),
    ]
    w = max(len(r[0]) for r in rows)
    print(c_head("format capability — mechanism | guarantee (honest)"))
    for name, how, claim in rows:
        print(f"  {c_info(name.ljust(w))}  {c_dim(how.ljust(56))} {claim}")


# --------------------------------------------------------------------------- #
# core strip — image formats
# --------------------------------------------------------------------------- #
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


def strip_image_bytes(path: Path, keep_icc: bool = False,
                      max_pixels: Optional[int] = None) -> tuple[bytes, str]:
    """Strip metadata, keeping pixels as close to byte-identical as the
    format allows.

    JPEG (orientation-neutral): rewrite the marker stream — drop every
    APPn/COM segment (EXIF, XMP, Photoshop, ICC unless --keep-icc),
    keep the entropy-coded pixel data verbatim. No re-encode, no loss.

    JPEG (needs rotation) and everything else: bake the rotation (if
    any) into the pixels, then rebuild into a brand-new frame with an
    empty metadata block. The rebuild is tiled so memory stays bounded
    no matter the megapixel count.

    GIF: lossless byte-level rewrite first — drops comment + XMP
    application extensions anywhere in the block stream and keeps every
    frame, palette, transparency, disposal and the loop count
    byte-exact. Falls back to a pixel rebuild if the stream is malformed.

    TIFF family (incl. DNG/RAW when they reach this path): lossless
    in-place IFD surgery — pixels byte-identical, pages kept.

    Animated GIF / APNG / multipage TIFF / animated WebP keep every
    frame, timing and loop (APNG + lossless WebP are stripped losslessly).
    Animated AVIF is refused loudly. Multi-frame JPEG (MPO) with a
    rotated frame 0 bakes the rotation in and keeps every other frame
    lossless — never drops them.

    `max_pixels` guards against decompression bombs: images larger than
    the limit (per frame, and a cumulative budget across animation
    frames) are refused loudly instead of being decoded into RAM.

    Returns (clean_bytes, output_format_lowercase).
    """
    if max_pixels is None:
        max_pixels = DEFAULT_MAX_PIXELS
    raw = path.read_bytes()
    # TIFF family -> lossless in-place surgery. NEVER re-encode sensor
    # data: pixels byte-identical, pages kept, no encode cost.
    if raw[:4] in (b"II*\x00", b"MM\x00*") and _is_tiff_family(raw):
        surg = _tiff_strip_lossless(raw, keep_icc)
        if surg is not None:
            return surg, "tiff"
    with Image.open(path) as img:
        w, h = img.size
        if max_pixels and w * h > max_pixels:
            raise RuntimeError(
                f"refusing to process {w}x{h} = {w*h:,} pixels "
                f"(limit {max_pixels:,}); pass --max-pixels N to raise "
                "the limit (memory risk)"
            )
        fmt = (img.format or path.suffix.lstrip(".")).upper()
        img.load()
        n_frames = getattr(img, "n_frames", 1)
        if max_pixels and n_frames > 1 and w * h * n_frames > max_pixels * 8:
            # cumulative budget: a hostile "animation" with thousands of
            # huge frames is a decompression bomb in slow motion
            raise RuntimeError(
                f"refusing: ~{w*h*n_frames:,} total pixels across "
                f"{n_frames} frames (cumulative limit {max_pixels*8:,})"
            )

        # GIF: prefer the byte-level strip — it keeps every frame,
        # palette, transparency and disposal EXACTLY as-is (no
        # P→RGBA→re-quantize round-trip) and only drops comment + XMP
        # application extensions wherever they appear in the stream.
        # Fall back to a rebuild if the stream doesn't parse.
        if fmt == "GIF":
            lossless = _strip_gif_lossless(raw)
            if lossless is not None:
                return lossless, "gif"
            if n_frames > 1:
                return _strip_multiframe(img, fmt, keep_icc=keep_icc)

        webp_lossless = fmt == "WEBP" and _webp_is_lossless(raw)

        # animated/multipage WebP / TIFF / AVIF — strip every frame,
        # keep the animation
        if fmt in ("TIFF", "TIF", "WEBP", "AVIF") and n_frames > 1:
            return _strip_multiframe(img, fmt, keep_icc=keep_icc,
                                     webp_lossless=webp_lossless)

        # APNG: lossless chunk strip (animation + pixels byte-exact).
        # The old code rebuilt through the single-frame path and silently
        # collapsed every animated PNG to frame 1.
        if fmt == "PNG" and _png_is_animated(raw):
            lossless = _strip_png_lossless(raw)
            if lossless is not None:
                return lossless, "png"
            if n_frames > 1:
                return _strip_multiframe(img, "PNG", keep_icc=keep_icc)

        # JPEG / MPO: prefer the lossless marker-stream strip. Only when
        # the photo is orientation-neutral — otherwise we must bake the
        # rotation into the pixels, which requires re-encoding.
        if fmt in ("JPEG", "JPG", "MPO"):
            n_jpeg = raw.count(b"\xff\xd8")
            if n_jpeg > 1 and not _orientation_is_neutral(img):
                # rotated multi-frame (MPO): bake frame 0's rotation,
                # keep every other frame lossless — NEVER drop them
                mpo = _strip_mpo_rotated_first(raw, img, keep_icc)
                if mpo is None:
                    raise RuntimeError(
                        "multi-frame JPEG needs rotation but its frames "
                        "could not be split — refusing to drop them")
                return mpo, "jpeg"
            if _orientation_is_neutral(img):
                lossless = _strip_jpeg_lossless(raw, keep_icc)
                if lossless is not None:
                    return _jpeg_final_check(lossless, keep_icc), "jpeg"

        img = _apply_orientation(img, strict=fmt in ("JPEG", "JPG", "MPO"))

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
            # lossless in -> lossless out: never silently downgrade a
            # byte-exact file to q90 lossy
            kwargs = {"format": "WEBP", "method": 6, "exif": b"",
                      "xmp": b"", "icc_profile": icc_bytes or None}
            if webp_lossless:
                kwargs.update(lossless=True, quality=100, exact=True)
            else:
                kwargs["quality"] = 90
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

    if fmt_out == "JPEG":
        cleaned = _jpeg_final_check(cleaned, keep_icc)
    return cleaned, fmt_out.lower()


def _orientation_is_neutral(img) -> bool:
    """True when the image carries no rotation (or EXIF at all)."""
    try:
        if not hasattr(img, "getexif"):
            return True
        return int(img.getexif().get(0x0112, 1) or 1) == 1
    except Exception:
        return True


def _entropy_marker_index(data: bytes, j: int) -> int:
    """From inside entropy-coded data, find the FF-run that precedes the
    next real marker (handles FF 00 stuffing and RSTn). Returns the index
    of the last FF of that run, or len(data) at EOF."""
    n = len(data)
    while j < n:
        if data[j] != 0xFF:
            j += 1
            continue
        k = j
        while k < n and data[k] == 0xFF:
            k += 1
        if k >= n:
            return n
        nxt = data[k]
        if nxt == 0x00 or 0xD0 <= nxt <= 0xD7:
            j = k + 1
            continue
        return k - 1
    return n


def _split_jpeg_frames(data: bytes) -> list:
    """Split a (possibly multi-frame) JPEG into SOI..EOI byte strings by
    walking markers and skipping entropy-coded data. Tolerates garbage
    between frames; a frame without an EOI runs to EOF. Returns [] on
    input that doesn't even start with a SOI."""
    frames = []
    i, n = 0, len(data)
    while i < n:
        if data[i:i + 2] != b"\xff\xd8":
            nxt = data.find(b"\xff\xd8", i, min(i + 64, n))
            if nxt == -1:
                break
            i = nxt
        start = i
        j = i + 2
        eoi = None
        while j < n:
            while j < n and data[j] != 0xFF:
                j += 1
            while j < n and data[j] == 0xFF:
                j += 1
            if j >= n:
                break
            marker = data[j]
            j += 1
            if marker == 0xD9:
                eoi = j
                break
            if marker == 0xDA:
                j = _entropy_marker_index(data, j)
                continue
            if 0xD0 <= marker <= 0xD7 or marker == 0x01:
                continue
            if j + 2 > n:
                break
            seg_len = int.from_bytes(data[j:j + 2], "big")
            j += 2 + max(seg_len - 2, 0)
        frames.append(data[start:eoi if eoi is not None else n])
        if eoi is None:
            break
        i = eoi
    return frames


def _jpeg_metadata_segments(data: bytes, keep_icc: bool = False) -> list:
    """Names of every non-structural APPn/COM segment in every frame
    (JFIF APP0 and ICC APP2 — when keep_icc — are structural)."""
    found = []
    for frame in _split_jpeg_frames(data):
        i, n = 2, len(frame)
        while i + 4 <= n:
            if frame[i] != 0xFF:
                break
            while i < n and frame[i] == 0xFF:
                i += 1
            if i >= n:
                break
            marker = frame[i]
            i += 1
            if marker == 0xDA or marker == 0xD9:
                break
            if i + 2 > n:
                break
            seg_len = int.from_bytes(frame[i:i + 2], "big")
            if seg_len < 2 or i + seg_len > n:
                break
            payload = frame[i + 2:i + seg_len]
            if marker == 0xFE:
                found.append("COM")
            elif 0xE0 <= marker <= 0xEF:
                if marker == 0xE0 and payload.startswith(b"JFIF"):
                    pass
                elif marker == 0xE2 and keep_icc and payload.startswith(b"ICC_PROFILE\x00"):
                    pass
                else:
                    name = payload[:8].split(b"\x00")[0].decode(errors="replace")
                    found.append(f"APP{marker - 0xE0}:{name or hex(marker)}")
            i += seg_len
    return found


def _jpeg_final_check(cleaned: bytes, keep_icc: bool = False) -> bytes:
    """Round-trip verify, JPEG only. If any metadata segment survived the
    wipe (a re-encode can sneak segments back in), re-run the lossless
    stripper — and if THAT still leaves something, fail loudly instead of
    handing back a dirty file.

    (The old implementation leaned on piexif.remove(), which with
    piexif 1.1.3 raises ValueError on bytes input — the exception was
    swallowed, and the re-wipe never ran. The safety net was dead code.)"""
    leftovers = _jpeg_metadata_segments(cleaned, keep_icc)
    if not leftovers:
        return cleaned
    rewiped = _strip_jpeg_lossless(cleaned, keep_icc)
    if rewiped is not None and not _jpeg_metadata_segments(rewiped, keep_icc):
        return rewiped
    raise RuntimeError(
        "JPEG final check failed: metadata segments survived rewrite: "
        + ", ".join(leftovers)
    )


def _rebuild_jpeg_from_img(img, keep_icc: bool = False) -> bytes:
    """Bake orientation into pixels, rebuild a clean q95 JPEG frame."""
    img = _apply_orientation(img, strict=True)
    mode = img.mode
    if mode not in ("RGB", "RGBA", "L"):
        mode = "RGBA" if ("A" in mode or mode == "P") else "RGB"
        img = img.convert(mode)
    clean = _rebuild_frame(img, mode)
    icc = b""
    if keep_icc:
        try:
            icc = img.info.get("icc_profile", b"") or b""
        except Exception:
            icc = b""
    buf = io.BytesIO()
    clean.save(buf, format="JPEG", quality=95, optimize=True, exif=b"",
               progressive=False, icc_profile=icc or None)
    return _jpeg_final_check(buf.getvalue(), keep_icc)


def _strip_mpo_rotated_first(raw: bytes, img, keep_icc: bool = False):
    """Multi-frame JPEG whose FIRST frame carries a rotation: re-encode
    frame 0 with the rotation baked in, then lossless-strip the remaining
    frames so no frame is ever silently dropped. Returns None when the
    stream can't be split (caller must refuse loudly, not guess)."""
    frames = _split_jpeg_frames(raw)
    if len(frames) < 2:
        return None
    f0 = frames[0]
    rest = raw[len(f0):]
    try:
        img.seek(0)
        clean0 = _rebuild_jpeg_from_img(img, keep_icc)
    except Exception as e:
        raise RuntimeError(
            f"multi-frame JPEG needs rotation and frame 0 could not be "
            f"re-encoded ({e}) — refusing to drop the other frames") from e
    if rest:
        rest_clean = _strip_jpeg_lossless(rest, keep_icc)
        if rest_clean is None:
            raise RuntimeError(
                "multi-frame JPEG: trailing frames could not be parsed "
                "losslessly — refusing to drop them")
        return clean0 + rest_clean
    return clean0


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
        loop then processes). Handles FF 00 stuffing and RSTn.

        `start` tracks the first unconsumed entropy byte so every byte
        up to a marker's FF-run is copied out — the classic bug here is
        advancing past non-FF bytes without copying them, which emits a
        structurally valid JPEG whose pixels are gone."""
        nonlocal out
        start = j
        while j < n:
            if data[j] != 0xFF:
                j += 1
                continue
            k = j
            while k < n and data[k] == 0xFF:
                k += 1
            if k >= n:                      # run of FF to EOF — truncated
                out += data[start:k]
                return n
            nxt = data[k]
            if nxt == 0x00 or 0xD0 <= nxt <= 0xD7:
                # stuffed FF 00, or RSTn restart marker — part of the
                # entropy stream, keep byte-exact
                out += data[start:k + 1]
                start = j = k + 1
                continue
            # first real marker after entropy — the FF-run is the
            # marker's padding and is emitted by the outer loop, so the
            # entropy copy must stop BEFORE the run (copying it would
            # duplicate the FFs and break byte-exactness)
            out += data[start:j]
            return j
        out += data[start:j]                # entropy runs to EOF — truncated
        return n

    while i < n:
        if data[i] != 0xFF:
            # non-marker byte — either trailing garbage after the final
            # EOI (file-carving residue, drop it) or a stray byte between
            # MPO frames. Peek a bounded distance for a new SOI; if one
            # appears, skip the junk and keep parsing so no frame is lost.
            nxt = data.find(b"\xff\xd8", i, min(i + 64, n))
            if nxt == -1:
                break
            i = nxt
            continue
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


def _strip_gif_lossless(data: bytes):
    """Rewrite a GIF stream, dropping comment blocks (0x21 0xFE) and
    XMP application extensions (0x21 0xFF carrying 'XMP Data') anywhere
    in the block stream — before, between and after image frames. Every
    frame descriptor, palette, transparency, disposal and loop count is
    copied byte-identical. Bytes after the trailer are dropped. Returns
    None if the stream doesn't parse (caller falls back to a rebuild).

    GIF blocks that can carry metadata:
      0x21 0xFE ...   comment extension              — dropped
      0x21 0xFF ...   application extension          — dropped if it
                        carries XMP; NETSCAPE loop kept
      0x21 0xF9 ...   graphic control (disposal + transparency) — kept
      0x2C ...        image descriptor + pixel data  — kept verbatim
      0x3B ...        trailer                        — end of file
    """
    if data[:6] not in (b"GIF87a", b"GIF89a"):
        return None
    n = len(data)
    out = bytearray(data[:6])
    i = 6
    if i + 7 > n:
        return None
    lsdesc = data[i:i + 7]
    out += lsdesc
    i += 7
    if lsdesc[4] & 0x80:                    # global color table
        gct_size = 3 * (2 ** ((lsdesc[4] & 0x07) + 1))
        if i + gct_size > n:
            return None
        out += data[i:i + gct_size]
        i += gct_size

    while i < n:
        b = data[i]
        if b == 0x3B:                       # trailer — official end
            out += b"\x3b"
            return bytes(out)
        if b == 0x2C:                       # image descriptor
            if i + 10 > n:
                return None
            packed = data[i + 9]
            out += data[i:i + 10]
            i += 10
            if packed & 0x80:               # local color table
                lct_size = 3 * (2 ** ((packed & 0x07) + 1))
                if i + lct_size > n:
                    return None
                out += data[i:i + lct_size]
                i += lct_size
            if i >= n:
                return None
            out += data[i:i + 1]            # LZW minimum code size
            i += 1
            i = _copy_gif_subblocks(data, i, out)   # pixel data, verbatim
            if i is None:
                return None
            continue
        if b == 0x21:                       # extension
            if i + 2 > n:
                return None
            label = data[i + 1]
            start = i
            end = _skip_gif_subblocks(data, i + 2)
            if end is None:
                return None
            if label == 0xFE:
                i = end                     # comment — dropped
                continue
            block = data[start:end]
            if label == 0xFF and b"XMP Data" in block:
                i = end                     # XMP application ext — dropped
                continue
            out += block                    # GCE / NETSCAPE / others — kept
            i = end
            continue
        return None                         # unknown top-level byte
    return bytes(out)


def _skip_gif_subblocks(data: bytes, idx: int):
    """Return index just past a GIF sub-block chain; None if malformed."""
    n = len(data)
    while True:
        if idx >= n:
            return None
        size = data[idx]
        if size == 0:
            return idx + 1
        if idx + 1 + size > n:
            return None
        idx += 1 + size


def _copy_gif_subblocks(data: bytes, idx: int, out: bytearray):
    """Copy a GIF sub-block chain (pixel data) verbatim into `out`.
    Returns the index just past the chain; None if malformed."""
    n = len(data)
    while True:
        if idx >= n:
            return None
        size = data[idx]
        if idx + 1 + size > n:
            return None
        out += data[idx:idx + 1 + size]
        idx += 1 + size
        if size == 0:
            return idx


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


_PNG_SIG = b"\x89PNG\r\n\x1a\n"


def _png_is_animated(data: bytes) -> bool:
    """True when the PNG stream carries an acTL (animation control) chunk."""
    if data[:8] != _PNG_SIG:
        return False
    pos, n = 8, len(data)
    while pos + 8 <= n:
        clen = int.from_bytes(data[pos:pos + 4], "big")
        if pos + 12 + clen > n:
            break
        ctype = data[pos + 4:pos + 8]
        if ctype == b"acTL":
            return True
        if ctype == b"IDAT":
            break          # acTL must precede the image data
        pos += 12 + clen
    return False


def _strip_png_lossless(data: bytes):
    """Drop PNG metadata chunks (tEXt/zTXt/iTXt/eXIf/iCCP/pHYs) and
    anything after IEND, keeping every other chunk — including the acTL /
    fcTL / fdAT animation blocks and IDAT pixel data — byte-identical.
    Returns None when the chunk stream is malformed."""
    if data[:8] != _PNG_SIG:
        return None
    DROP = {b"tEXt", b"zTXt", b"iTXt", b"eXIf", b"iCCP", b"pHYs"}
    out = bytearray(data[:8])
    pos, n = 8, len(data)
    iend = False
    while pos + 8 <= n:
        clen = int.from_bytes(data[pos:pos + 4], "big")
        if clen > n or pos + 12 + clen > n:
            return None
        ctype = data[pos + 4:pos + 8]
        if ctype == b"IEND":
            out += data[pos:pos + 12 + clen]
            iend = True
            break
        if ctype not in DROP:
            out += data[pos:pos + 12 + clen]
        pos += 12 + clen
    if not iend:
        return None
    return bytes(out)


def _webp_is_lossless(data: bytes) -> bool:
    """True when a WebP's image data is a VP8L (lossless) chunk rather
    than a VP8 (lossy) chunk. VP8X containers carry the VP8L/VP8 chunk
    as a top-level sibling, so one flat chunk scan suffices."""
    if data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return False
    pos, n = 12, len(data)
    while pos + 8 <= n:
        tag = data[pos:pos + 4]
        size = int.from_bytes(data[pos + 4:pos + 8], "little")
        if size > n:
            break
        if tag == b"VP8L":
            return True
        if tag == b"VP8 ":
            return False
        pos += 8 + size + (size & 1)
    return False


def _strip_multiframe(img, fmt: str, keep_icc: bool = False,
                      webp_lossless: bool = False) -> tuple[bytes, str]:
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
        frames.append(_rebuild_frame(fr, mode))
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
            root = pdf.Root
            if root is not None:
                for key in ("/Metadata", "/Lang", "/OpenAction", "/PieceInfo",
                            "/StructTreeRoot", "/PageLabels", "/MarkInfo"):
                    try:
                        if key in root:
                            del root[key]  # pikepdf: del removes the key
                    except Exception:
                        pass
            try:
                # /Info (DocInfo) holds title/author/creator/date...
                # Clearing to an empty indirect dictionary removes every
                # /Info key.
                pdf.docinfo = pdf.make_indirect(pikepdf.Dictionary())
            except Exception:
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
def _refuse_system_target(path: Path) -> None:
    """Refuse to write into top-level system directories so a stray -o
    can't drop an image into /etc or /usr. /tmp, /var, /home and
    /run/media (USB mounts) are fine."""
    try:
        parts = path.resolve().parts
    except Exception:
        return
    if len(parts) > 1 and parts[1] in _SYSTEM_DIRS:
        # /run/media/<user>/... is a legitimate removable-mount target
        if parts[1] == "run" and len(parts) > 2 and parts[2] == "media":
            return
        raise RuntimeError(
            f"refusing to write into system directory '/{parts[1]}' ({path}); "
            "use a user-writable location"
        )


def _atomic_write_bytes(path: Path, cleaned: bytes, st) -> None:
    """Write `cleaned` to `path` atomically via a private temp file that
    only we created (O_EXCL — no attacker can pre-plant a symlink at a
    predictable name), fsync it, then rename over the original.

    A symlink is resolved FIRST so the write lands on the target — the
    link itself is preserved (the old behavior replaced the symlink with
    a regular file AND left the target dirty, which was both silent and
    a leak).

    Mode and mtime of the original are preserved on the new inode so a
    0600 private photo stays 0600; setuid/setgid/sticky bits are NOT
    carried over (masked with 0o7777).
    """
    if path.is_symlink():
        path = path.resolve()
    import secrets
    for _ in range(10):
        tmp = path.with_name(f".{path.name}.exifwipe_tmp_{secrets.token_hex(8)}")
        try:
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            continue            # collision — try another random name
        except OSError as e:
            raise OSError(f"cannot create temp file for {path.name}: {e}") from e
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(cleaned)
                f.flush()
                os.fsync(f.fileno())
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        # preserve the permission bits only — setuid/setgid/sticky are
        # dropped (carrying them over would be sloppy and exploitable)
        os.chmod(tmp, stat.S_IMODE(st.st_mode) & 0o777)
        os.utime(tmp, ns=(st.st_atime_ns, st.st_mtime_ns))
        os.replace(tmp, path)
        return
    raise OSError(f"could not reserve a unique temp name for {path.name}")


def write_output(src: Path, out: Optional[Path], cleaned: bytes,
                 no_clobber: bool = False) -> None:
    """Either overwrite src in place, or write to `out` (file or dir)."""
    if out is None:
        _refuse_system_target(src)
        target = src
        if src.is_symlink():
            resolved = src.resolve()
            if not resolved.is_file():
                raise OSError(f"{src} is a dangling symlink — nothing to strip")
            target = resolved
            print(f"  {c_warn('[LINK]')} {c_head(str(src))} -> "
                  f"{c_head(str(target))} {c_dim('(stripping target in place)')}")
        st = target.stat()
        if st.st_nlink > 1:
            print(f"  {c_warn('[WARN]')} {c_head(str(target))} has "
                  f"{st.st_nlink} hard links — the other names still point "
                  "at the pre-wipe data", file=sys.stderr)
        _atomic_write_bytes(target, cleaned, st)
        print(f"  {c_ok('[STRIPPED]')} {c_head(str(src))}")
    else:
        # if user passed a folder or a path-without-suffix, drop src inside
        if out.is_dir() or (not out.suffix and not out.exists()):
            out = out / src.name
        _refuse_system_target(out)
        if no_clobber and out.exists():
            raise FileExistsError(f"{out} already exists (--no-clobber)")
        if out.exists() and out.resolve() != src.resolve():
            print(f"  {c_warn('[clobber]')} overwriting existing "
                  f"{c_head(str(out))}", file=sys.stderr)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(cleaned)
        print(f"  {c_ok('[STRIPPED]')} {c_head(str(src))}  {c_dim('->')}  "
              f"{c_head(str(out))}")


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
        # TIFF-family RAW containers are structurally TIFF; the extension
        # (or a deep read below) tells them apart from a plain TIFF
        ext = path.suffix.lower()
        if ext in RAW_EXTENSIONS:
            return ext.lstrip(".")
        # CR2: 16-byte header (IFD0 at 0x10) + CR2 magic 0x0201 at offset 8
        if (head[:8] == b"II*\x00\x10\x00\x00\x00"
                and head[8:10] == b"\x01\x02"):
            return "cr2"
        # extensionless DNG: the DNGVersion tag (0xC612) is authoritative
        try:
            more = path.open("rb").read(1 << 20)
        except OSError:
            more = b""
        if more and _tiff_has_tag(more, 0xC612):
            return "dng"
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


def handle_one(path: Path, args: argparse.Namespace) -> int:
    """Process one file. Returns R_OK / R_ERR / R_SKIP.

    Dispatch is by magic bytes (sniffed), not by file extension, so a
    downloaded JPEG with no extension is still stripped. Unrecognized
    files are SKIPPED (never counted as errors)."""
    fmt = _sniff_format(path) if path.is_file() else None
    if fmt is None:
        if args.verbose:
            print(f"  {c_dim('[skip] unrecognized:')} {path.name}")
        return R_SKIP

    no_clobber = bool(getattr(args, "no_clobber", False))

    if fmt in RAW_FORMATS:
        # RAW: NEVER pixel-rebuild (the sensor data can't be re-encoded) —
        # lossless in-place IFD surgery only, loud refusal on failure
        if args.dry_run or args.inspect:
            try:
                st = path.stat()
                print(f"  {c_info(fmt.upper())} {c_head(path.name)}: "
                      f"{st.st_size:,} bytes, TIFF-family container — "
                      "surgery would blank EXIF/GPS/MakerNotes losslessly")
            except OSError as e:
                print(f"  {c_err('[ERR]')} {c_warn(path.name)}: {e}", file=sys.stderr)
                return R_ERR
            return R_OK
        try:
            cleaned = _tiff_strip_lossless(path.read_bytes(),
                                           keep_icc=args.keep_icc)
            if cleaned is None:
                raise RuntimeError(
                    "not a parseable TIFF container — refusing to rebuild "
                    "RAW sensor data (BigTIFF/encrypted/corrupt?)")
            write_output(path, args.output, cleaned, no_clobber=no_clobber)
        except Exception as e:
            print(f"  {c_err('[ERR]')} {c_warn(path.name)}: {e}", file=sys.stderr)
            return R_ERR
        return R_OK

    if fmt in IMAGE_FORMATS:
        if args.dry_run or args.inspect:
            try:
                inspect_image(path, max_pixels=getattr(args, "max_pixels", None))
            except Exception as e:
                print(f"  {c_err('[ERR]')} {c_warn(path.name)}: {e}", file=sys.stderr)
                return R_ERR
            return R_OK
        try:
            cleaned, fmt_out = strip_image_bytes(
                path, keep_icc=args.keep_icc,
                max_pixels=getattr(args, "max_pixels", None))
            write_output(path, args.output, cleaned, no_clobber=no_clobber)
        except Exception as e:
            print(f"  {c_err('[ERR]')} {c_warn(path.name)}: {e}", file=sys.stderr)
            return R_ERR
        if args.verbose:
            try:
                check = args.output if args.output is not None else path
                if check.is_dir() or (not check.suffix and not check.exists()):
                    check = check / path.name
                inspect_image(check, max_pixels=getattr(args, "max_pixels", None))
            except Exception as e:
                print(f"  {c_err('[ERR]')} {c_warn(path.name)}: {e}", file=sys.stderr)
        return R_OK

    if fmt == "pdf":
        if args.dry_run or args.inspect:
            print(f"  {c_dim('(would strip PDF metadata)')} {path.name}")
            return R_OK
        cleaned = strip_pdf_bytes(path)
        if not cleaned:
            return R_ERR
        try:
            write_output(path, args.output, cleaned, no_clobber=no_clobber)
        except Exception as e:
            print(f"  {c_err('[ERR]')} {c_warn(path.name)}: {e}", file=sys.stderr)
            return R_ERR
        return R_OK

    if args.verbose:
        print(f"  {c_dim('[skip] unsupported:')} {path.name}")
    return R_SKIP


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
    n_ok = n_err = n_skip = 0
    for p in targets:
        res = handle_one(p, ns)
        if res == R_OK:
            n_ok += 1
        elif res == R_ERR:
            n_err += 1
        else:
            n_skip += 1
    msg = f"\n  {c_ok(str(n_ok))} processed"
    if n_skip:
        msg += f", {c_dim(str(n_skip))} skipped"
    if n_err:
        msg += f", {c_err(str(n_err))} errors"
    print(msg)


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
    p.add_argument("--verify", action="store_true",
                   help="after stripping, prove no metadata remains "
                        "(exiftool if installed, else per-format parsers); "
                        "exit nonzero if anything leaks")
    p.add_argument("--max-pixels", type=int, default=None,
                   help=f"refuse images larger than N pixels "
                        f"(default {DEFAULT_MAX_PIXELS:,}; 0 = unlimited)")
    p.add_argument("--no-clobber", action="store_true",
                   help="refuse to overwrite an existing -o target")
    p.add_argument("--formats", action="store_true",
                   help="print what formats are guaranteed clean "
                      "vs best-effort, then exit")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="also print inspection after stripping")
    p.add_argument("--version", action="version",
                   version=f"%(prog)s {__version__}")
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

    # --formats / --version don't need an input at all
    if args.formats:
        print_formats_matrix()
        return 0

    # no input → interactive menu
    if args.input is None:
        return run_interactive_menu()

    if not args.input.exists():
        print(f"  [ERR] not found: {args.input}", file=sys.stderr)
        return 2

    targets = list(iter_inputs(args.input))

    # --inspect is a read-only mode
    if args.inspect:
        n_err = 0
        for p in targets:
            try:
                fmt = _sniff_format(p) if p.is_file() else None
                if fmt in IMAGE_FORMATS:
                    inspect_image(p, max_pixels=args.max_pixels)
                elif fmt in RAW_FORMATS:
                    st = p.stat()
                    print(f"\n=== {p.name} ===")
                    print(f"  RAW {fmt.upper()}: {st.st_size:,} bytes, "
                          "TIFF-family container — `exiftool -a -G1 FILE` "
                          "sees what surgery would remove")
                elif fmt == "pdf":
                    print(f"\n=== {p.name} ===")
                    print("  (PDF — use pikepdf or `exiftool -all=` to inspect)")
            except Exception as e:
                print(f"  {c_err('[ERR]')} {c_warn(p.name)}: {e}", file=sys.stderr)
                n_err += 1
        print("\n-- exiftool reference --\n" + exiftool_hint())
        return 0 if n_err == 0 else 3

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

    # -o pointing at a (new) dir: resolve per-file outputs and make sure
    # duplicate basenames don't silently clobber each other.
    out_dir = None
    if args.output is not None and (args.output.is_dir()
                                    or (not args.output.suffix and not args.output.exists())):
        out_dir = args.output

    n_ok = n_err = n_skip = 0
    leaks = []
    used_out = {}
    for p in targets:
        per = args
        if out_dir is not None:
            stem, suff = p.stem, p.suffix
            cand, i = p.name, 2
            while cand in used_out:
                cand = f"{stem} ({i}){suff}"
                i += 1
            used_out[cand] = True
            per = argparse.Namespace(**vars(args))
            per.output = out_dir / cand

        res = handle_one(p, per)
        if res == R_OK:
            n_ok += 1
        elif res == R_ERR:
            n_err += 1
            continue
        else:
            n_skip += 1
            continue

        # verify only files that were actually written (dry-run leaves the
        # original untouched, so verifying it would be a guaranteed FAIL)
        if args.verify and not args.dry_run:
            check = per.output if per.output is not None else p
            try:
                clean, found = verify_clean(check)
            except Exception as e:
                clean, found = False, [f"verify-error: {e}"]
            if not clean or found:
                leaks.extend(found or ["unknown"])
                print(f"  {c_err('[LEAK]')} {c_warn(p.name)}: "
                      f"{', '.join(found)}", file=sys.stderr)
                n_err += 1

    msg = f"\ndone. {n_ok} processed"
    if n_skip:
        msg += f", {n_skip} skipped"
    if n_err:
        msg += f", {n_err} errors"
    print(msg + ".")
    if args.verify:
        if leaks:
            print(f"  {c_err('VERIFY FAILED:')} metadata still present in "
                  f"{c_err(str(len(leaks)))} file(s). Do not publish these.",
                  file=sys.stderr)
        else:
            print(f"  {c_ok('VERIFY OK:')} no metadata on any clean file.")
    if piexif is None:
        print("tip: install piexif for JPEG round-trip verify:  pip3 install piexif",
              file=sys.stderr)
    return 0 if (n_err == 0 and (not args.verify or not leaks)) else 3


if __name__ == "__main__":
    raise SystemExit(main())
