"""_sniff - exifwipe internal module: format detection from magic bytes."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from lib._config import RAW_EXTENSIONS, _PNG_SIG, _RAF_MAGIC
from lib._tiff import _tiff_has_tag, _tiff_vendor_from_makernote


def _sniff_bytes(data: bytes) -> Optional[str]:
    """Format from magic bytes only (no extension hints). Used by the
    strip path and the report inventory; the CR2 magic (0x0201 in the
    extended header) is the only RAW family detectable from bytes alone."""
    if data[:2] == b"\xff\xd8":
        return "jpeg"
    if data[:8] == _PNG_SIG:
        return "png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:16] == _RAF_MAGIC:
        return "raf"          # Fuji — NOT a TIFF container
    if data[:4] in (b"II*\x00", b"MM\x00*"):
        # CR2: 16-byte header (IFD0 at 0x10) + CR2 magic 0x0201 at offset 8
        if (data[:8] == b"II*\x00\x10\x00\x00\x00"
                and data[8:10] == b"\x01\x02"):
            return "cr2"
        return "tiff"
    if data[:2] == b"BM":
        return "bmp"
    if data[:4] == b"%PDF":
        return "pdf"
    if data[4:8] == b"ftyp":
        brand = data[8:12]
        # HEIF/AVIF share the ISO BMFF container; disambiguate by brand
        if brand in (b"avif", b"avis"):
            return "avif"
        if brand in (b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1",
                     b"heif", b"heim"):
            return "heif"
    return None


def _sniff_format(path: Path) -> Optional[str]:
    """Detect a file's real format from its magic bytes, not its name.
    Returns a normalized format name ('jpeg', 'png', 'gif', 'tiff',
    'webp', 'bmp', 'heif', 'avif', 'raf', 'pdf') or None if unrecognized.

    TIFF-family files that aren't obviously CR2/DNG-by-extension get a
    deep read: DNG by its DNGVersion tag, then RAW family by MakerNote
    prefix — so an extensionless NEF or a .tiff that's really an ARW is
    handled as the RAW it actually is."""
    try:
        head = path.open("rb").read(16)
    except OSError:
        return None
    fmt = _sniff_bytes(head)
    if fmt != "tiff":
        return fmt
    ext = path.suffix.lower()
    if ext == ".cr2":
        return "cr2"
    if ext == ".dng":
        return "dng"
    if ext in RAW_EXTENSIONS:
        return ext.lstrip(".")
    # anything else TIFF-family (extensionless, .tiff, or a .bin that's
    # really a NEF): the extension is only a hint — the DNGVersion tag
    # and the MakerNote are authoritative
    try:
        more = path.open("rb").read(1 << 20)
    except OSError:
        more = b""
    if not more:
        return "tiff"
    if _tiff_has_tag(more, 0xC612):
        return "dng"
    vend = _tiff_vendor_from_makernote(more)
    return vend if vend else "tiff"
