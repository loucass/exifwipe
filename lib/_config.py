"""_config - exifwipe internal module (format/strip machinery)."""

from __future__ import annotations



from pathlib import Path
from typing import Iterable, Optional

__version__ = "1.1.0"


__author__ = "loucas"


__github__ = "loucass"


__license__ = "MIT"


IMAGE_EXTS = {".jpg", ".jpeg", ".jfif", ".png", ".webp", ".tif", ".tiff",
              ".bmp", ".gif", ".heic", ".heif", ".avif"}


DOC_EXTS = {".pdf"}  # pikepdf dep — see strip_pdf_metadata()


R_OK, R_ERR, R_SKIP = 0, 1, 2


RASTER_FORMATS = ("jpeg", "png", "gif", "tiff", "webp", "bmp", "heif", "avif")


IMAGE_FORMATS = RASTER_FORMATS  # dispatch alias


RAW_FORMATS = ("dng", "cr2", "nef", "arw", "orf", "rw2", "pef", "srw",
               "sr2", "3fr")


RAW_EXTENSIONS = frozenset("." + f for f in RAW_FORMATS)


SUPPORTED_FORMATS = IMAGE_FORMATS + RAW_FORMATS


DEFAULT_MAX_PIXELS = 178_000_000


_SYSTEM_DIRS = {"etc", "usr", "bin", "sbin", "lib", "lib64", "boot",
                "proc", "sys", "dev", "run"}


_RAF_MAGIC = b"FUJIFILMCCD-RAW "


_MAKERNOTE_VENDORS = (
    (b"Nikon", "nef"), (b"SONY", "arw"), (b"OLYMP", "orf"),
    (b"Panasonic", "rw2"), (b"PENTAX", "pef"), (b"SAMSUNG", "srw"),
    (b"Canon", "cr2"), (b"HASSELBLAD", "3fr"),
)


_PNG_SIG = b"\x89PNG\r\n\x1a\n"


_HEIF_META_TYPES = frozenset((b"Exif", b"mime", b"xmp "))


_MENU_ART = r"""
   ███████╗██╗  ██╗██╗███████╗██╗    ██╗██╗██████╗ ███████╗
   ██╔════╝╚██╗██╔╝██║██╔════╝██║    ██║██║██╔══██╗██╔════╝
   █████╗   ╚███╔╝ ██║█████╗  ██║ █╗ ██║██║██████╔╝█████╗
   ██╔══╝   ██╔██╗ ██║██╔══╝  ██║███╗██║██║██╔═══╝ ██╔══╝
   ███████╗██╔╝ ██╗██║██║     ╚███╔███╔╝██║██║     ███████╗
   ╚══════╝╚═╝  ╚═╝╚═╝╚═╝      ╚══╝╚══╝ ╚═╝╚═╝     ╚══════╝"""

