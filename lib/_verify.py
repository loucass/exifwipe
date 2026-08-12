"""_verify - exifwipe internal module (format/strip machinery)."""

from __future__ import annotations



import io
import json
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from lib._color import c_dim, c_head, c_info
from lib._config import RAW_FORMATS
from lib._driver import _sniff_format
from lib._heif import _heif_exif_payload_present, _heif_metadata_extents
from lib._jpeg import _jpeg_metadata_segments, _split_jpeg_frames
from lib._tiff import _tiff_find_identifying, _tiff_parse_header

try:
    import piexif
except ImportError:
    piexif = None

_STRUCTURAL_KEYS = {
    "SourceFile", "FileName", "Directory", "ExifToolVersion", "FileSize",
    "FileModifyDate", "FileAccessDate", "FileInodeChangeDate", "FilePermissions",
    "FileType", "FileTypeExtension", "MIMEType", "ImageWidth", "ImageHeight",
    "BitDepth", "ColorType", "EncodingProcess", "Megapixels", "ImageSize",
}


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
    elif fmt == "raf":
        # header identity zone (serial + model + firmware) must be blank
        zone = data[0x14:0x40] if len(data) >= 0x40 else b""
        if any(b not in (0, 32) for b in zone):
            leaks.append("header-serial/model")
        jpos = int.from_bytes(data[0x54:0x58], "big") if len(data) >= 0x5c else 0
        jlen = int.from_bytes(data[0x58:0x5c], "big") if len(data) >= 0x5c else 0
        if jpos and jlen and jpos + jlen <= len(data):
            for nm in _jpeg_metadata_segments(data[jpos:jpos + jlen]):
                leaks.append(f"preview:{nm}")
        foff = int.from_bytes(data[0x64:0x68], "big") if len(data) >= 0x6c else 0
        flen = int.from_bytes(data[0x68:0x6c], "big") if len(data) >= 0x6c else 0
        if foff and flen and foff + flen <= len(data):
            region = data[foff:foff + flen]
            if region[:2] in (b"II", b"MM") and _tiff_parse_header(region):
                for nm in _tiff_find_identifying(region):
                    leaks.append(f"fujiifd:{nm}")
    elif fmt in ("heif", "avif"):
        # ISO BMFF: check the iloc-mapped EXIF/XMP extents, not the box
        # type strings ("Exif"/"mime" survive the wipe as structure).
        extents = _heif_metadata_extents(data)
        if extents is None:
            if _heif_exif_payload_present(data) or b"<x:xmpmeta" in data:
                leaks.append("EXIF/XMP payload (unmapped container)")
        else:
            for (s, e) in extents:
                if any(data[s:e]):
                    leaks.append("EXIF/XMP extent still populated")
            if not extents and (_heif_exif_payload_present(data)
                                or b"<x:xmpmeta" in data):
                leaks.append("EXIF/XMP payload outside mapped extents")
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
        ("heif/avif", "lossless ISO-BMFF surgery: EXIF/XMP item extents "
                      "zeroed",
                      "clean; pixels byte-identical; re-encode fallback "
                      "only if container unparseable"),
        ("raf",       "lossless: header strings + embedded-JPEG EXIF + "
                      "FujiIFD",
                      "clean for those carriers; refuses on unparseable "
                      "preview/IFD"),
        ("bmp",       "pixel rebuild",
                      "clean"),
        ("raw-orient", "Orientation kept (display-only, sensor can't be "
                      "re-rotated); --drop-orientation blanks it",
                      "opt-in removal"),
        ("--perturb", "seeded +-N pixel noise on rebuild paths",
                      "breaks naive reverse-search; NOT unlinkability"),
        ("pdf",       "pikepdf: /Info + /Metadata + /Lang/JS/PageLabels",
                      "BEST-EFFORT: embedded-image EXIF may survive"),
    ]
    w = max(len(r[0]) for r in rows)
    print(c_head("format capability — mechanism | guarantee (honest)"))
    for name, how, claim in rows:
        print(f"  {c_info(name.ljust(w))}  {c_dim(how.ljust(56))} {claim}")

