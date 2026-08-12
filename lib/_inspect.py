"""_inspect - exifwipe internal module (format/strip machinery)."""

from __future__ import annotations



import sys
from pathlib import Path
from typing import Optional
from PIL import Image

from lib._color import c_dim, c_head, c_info, c_mag, c_warn
from lib._config import DEFAULT_MAX_PIXELS

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
            detail = "too large to inspect in detail " \
                     f"({w * h:,}px > {max_pixels:,} limit)"
            print(f"  {c_warn(detail)}")
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

