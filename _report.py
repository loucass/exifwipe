"""_report - exifwipe internal module (format/strip machinery)."""

from __future__ import annotations



from pathlib import Path
from typing import Optional

from _color import c_dim, c_head, c_ok, c_warn
from _config import RAW_FORMATS
from _heif import _heif_metadata_extents
from _jpeg import _jpeg_metadata_segments
from _tiff import _TIFF_IDENTIFYING, _tiff_find_identifying, _tiff_inventory

try:
    import piexif
except ImportError:
    piexif = None

def _inventory_metadata(data: bytes, fmt: Optional[str],
                        keep_icc: bool = False,
                        drop_orientation: bool = False) -> list:
    """Names of the metadata this wipe will remove from `data`, per
    format. Fills --report; mirrors what each stripper actually drops."""
    if fmt is None:
        return []
    items = []
    if fmt in ("jpeg", "mpo"):
        items += _jpeg_metadata_segments(data, keep_icc)
        if piexif is not None:
            try:
                ifd = piexif.load(data)
                for k, d in ifd.items():
                    if d and k != "thumbnail":
                        for tag in d:
                            name = None
                            try:
                                name = piexif.TAGS.get(
                                    k, {}).get(tag, {}).get("name")
                            except Exception:
                                name = None
                            name = name or _TIFF_IDENTIFYING.get(tag)
                            if name:
                                items.append(
                                    f"EXIF:{k} {name} (0x{tag:04X})")
                            else:
                                items.append(f"EXIF:{k} tag 0x{tag:04X}")
            except Exception:
                pass
    elif fmt == "png":
        pos, n = 8, len(data)
        iend = False
        while pos + 8 <= n:
            clen = int.from_bytes(data[pos:pos + 4], "big")
            if pos + 12 + clen > n:
                break
            ctype = data[pos + 4:pos + 8]
            if ctype == b"IEND":
                iend = True
            elif iend:
                items.append("data-after-IEND")
            if ctype in (b"tEXt", b"zTXt", b"iTXt", b"eXIf", b"iCCP",
                         b"pHYs"):
                if not (ctype == b"iCCP" and keep_icc):
                    items.append(ctype.decode())
            pos += 12 + clen
    elif fmt == "webp":
        pos, n = 12, len(data)
        while pos + 8 <= n:
            tag = data[pos:pos + 4]
            size = int.from_bytes(data[pos + 4:pos + 8], "little")
            if tag == b"ICCP" and keep_icc:
                pass
            elif tag in (b"EXIF", b"XMP ", b"ICCP"):
                items.append(tag.strip().decode())
            if size > n:
                break
            pos += 8 + size + (size & 1)
    elif fmt == "gif":
        ncom = data.count(b"\x21\xfe")
        if ncom:
            items.append(f"{ncom} comment extension(s)")
        if b"XMP Data" in data:
            items.append("XMP application extension")
    elif fmt in ("tiff",) + tuple(RAW_FORMATS):
        items = _tiff_inventory(data, keep_icc, drop_orientation)
    elif fmt in ("heif", "avif"):
        ext = _heif_metadata_extents(data)
        if ext:
            items.append(f"{len(ext)} EXIF/XMP item extent(s)")
    elif fmt == "raf":
        if any(b not in (0, 32) for b in data[0x14:0x40]):
            items.append("header serial + camera model")
        if len(data) >= 0x5c:
            jpos = int.from_bytes(data[0x54:0x58], "big")
            jlen = int.from_bytes(data[0x58:0x5c], "big")
            if jpos and jlen and jpos + jlen <= len(data) \
                    and _jpeg_metadata_segments(data[jpos:jpos + jlen]):
                items.append("embedded JPEG preview EXIF")
        if len(data) >= 0x6c:
            foff = int.from_bytes(data[0x64:0x68], "big")
            flen = int.from_bytes(data[0x68:0x6c], "big")
            if foff and flen and foff + flen <= len(data):
                for nm in _tiff_find_identifying(data[foff:foff + flen]):
                    items.append(f"FujiIFD:{nm}")
    # dedupe, keep order
    seen, out = set(), []
    for n in items:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def _print_report(path: Path, items: list) -> None:
    """Print the --report block for one file."""
    if not items:
        print(f"  {c_dim('[report]')} {c_head(str(path))}: "
              f"{c_ok('nothing to remove (already clean)')}")
        return
    print(f"  {c_dim('[report]')} {c_head(str(path))}:")
    for it in items[:200]:
        print(f"    - {c_warn(it)}")
    if len(items) > 200:
        print(f"    ... and {len(items) - 200} more")

