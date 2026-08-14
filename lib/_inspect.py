"""_inspect - exifwipe internal module (format/strip machinery).

The `--inspect` brain. Unlike the strip engine (which only needs to know
what it destroys), inspect exists to surface EVERYTHING a file carries:
every reachable IFD, every tag with its decoded value, every APP segment
and chunk — plus a small anomaly scanner that flags the things an OSINT
reviewer would raise an eyebrow at (GPS, MakerNotes, vendor data that
survived a previous wipe attempt, overlong blobs...).

Output is paginated on a TTY (Enter = next page, q = quit) and printed
in full when piped or with --full.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from lib._color import (c_danger, c_dim, c_head, c_err, c_info, c_mag,
                       c_ok, c_orange, c_warn)
from lib._config import DEFAULT_MAX_PIXELS, RAW_FORMATS
from lib._heif import _heif_metadata_extents
from lib._jpeg import _jpeg_metadata_segments
from lib._sniff import _sniff_format
from lib._tiff import (_TIFF_IDENTIFYING, _TYPE_SIZE, _tiff_find_identifying,
                       _tiff_layout, _tiff_parse_header, _tiff_value_bytes,
                       _value_is_blank)

try:
    import piexif
except ImportError:
    piexif = None

_IFD_LABELS = {
    0x8769: "ExifIFD",
    0x8825: "GPS",
    0xA005: "Interop",
    0x014A: "SubIFD",
    0x927C: "MakerNote",
}

# common tag names beyond the identifying set, used when piexif is absent
_COMMON_TAGS = {
    0x0100: "ImageWidth", 0x0101: "ImageLength", 0x0102: "BitsPerSample",
    0x0103: "Compression", 0x0106: "PhotometricInterpretation",
    0x010A: "FillOrder", 0x010E: "ImageDescription", 0x010F: "Make",
    0x0110: "Model", 0x0111: "StripOffsets", 0x0112: "Orientation",
    0x0115: "SamplesPerPixel", 0x0116: "RowsPerStrip",
    0x0117: "StripByteCounts", 0x011A: "XResolution", 0x011B: "YResolution",
    0x0128: "ResolutionUnit", 0x0131: "Software", 0x0132: "DateTime",
    0x013B: "Artist", 0x013E: "WhitePoint", 0x013F: "PrimaryChromaticities",
    0x0211: "YCbCrCoefficients", 0x0213: "YCbCrPositioning",
    0x0214: "ReferenceBlackWhite", 0x8298: "Copyright",
    0x829A: "ExposureTime", 0x829D: "FNumber", 0x8769: "ExifIFDPointer",
    0x8822: "ExposureProgram", 0x8825: "GPSInfo",
    0x8827: "ISOSpeedRatings", 0x9000: "ExifVersion",
    0x9003: "DateTimeOriginal", 0x9004: "DateTimeDigitized",
    0x9010: "OffsetTime", 0x9101: "ComponentsConfiguration",
    0x9102: "CompressedBitsPerPixel", 0x9201: "ShutterSpeedValue",
    0x9202: "ApertureValue", 0x9203: "BrightnessValue",
    0x9204: "ExposureBiasValue", 0x9205: "MaxApertureValue",
    0x9206: "SubjectDistance", 0x9207: "MeteringMode", 0x9208: "LightSource",
    0x9209: "Flash", 0x920A: "FocalLength", 0x9214: "SubjectArea",
    0x927C: "MakerNote", 0x9286: "UserComment", 0x9290: "SubSecTime",
    0x9291: "SubSecTimeOriginal", 0x9292: "SubSecTimeDigitized",
    0xA000: "FlashpixVersion", 0xA001: "ColorSpace",
    0xA002: "PixelXDimension", 0xA003: "PixelYDimension",
    0xA004: "RelatedSoundFile", 0xA005: "InteroperabilityIFDPointer",
    0xA20B: "FlashEnergy", 0xA20E: "FocalPlaneXResolution",
    0xA20F: "FocalPlaneYResolution", 0xA210: "FocalPlaneResolutionUnit",
    0xA215: "ExposureIndex", 0xA217: "SensingMethod", 0xA300: "FileSource",
    0xA301: "SceneType", 0xA302: "CFAPattern",
    0xA401: "CustomRendered", 0xA402: "ExposureMode",
    0xA403: "WhiteBalance", 0xA404: "DigitalZoomRatio",
    0xA405: "FocalLengthIn35mmFilm", 0xA406: "SceneCaptureType",
    0xA407: "GainControl", 0xA408: "Contrast", 0xA409: "Saturation",
    0xA40A: "Sharpness", 0xA40B: "DeviceSettingDescription",
    0xA40C: "SubjectDistanceRange", 0xA420: "ImageUniqueID",
    0xA430: "CameraOwnerName", 0xA431: "BodySerialNumber",
    0xA432: "LensSpecification", 0xA433: "LensMake", 0xA434: "LensModel",
    0xA435: "LensSerialNumber",
    0xC4A5: "PrintIM", 0xC612: "DNGVersion", 0xC614: "UniqueCameraModel",
    0xC615: "LocalizedCameraModel", 0xC62D: "SerialNumber",
    0xC634: "DNGPrivateData", 0xC68B: "OriginalRawFileName",
    0xC68C: "OriginalRawFileData",
}

_GPS_TAGS = {
    0x0000: "GPSVersionID", 0x0001: "GPSLatitudeRef",
    0x0002: "GPSLatitude", 0x0003: "GPSLongitudeRef",
    0x0004: "GPSLongitude", 0x0005: "GPSAltitudeRef",
    0x0006: "GPSAltitude", 0x0007: "GPSTimeStamp",
    0x0008: "GPSSatellites", 0x0009: "GPSStatus",
    0x000A: "GPSMeasureMode", 0x000B: "GPSDOP",
    0x000C: "GPSSpeedRef", 0x000D: "GPSSpeed",
    0x000E: "GPSTrackRef", 0x000F: "GPSTrack",
    0x0010: "GPSImgDirectionRef", 0x0011: "GPSImgDirection",
    0x0012: "GPSMapDatum", 0x0013: "GPSDestLatitudeRef",
    0x0014: "GPSDestLatitude", 0x0015: "GPSDestLongitudeRef",
    0x0016: "GPSDestLongitude", 0x0017: "GPSDestBearingRef",
    0x0018: "GPSDestBearing", 0x0019: "GPSDestDistanceRef",
    0x001A: "GPSDestDistance", 0x001B: "GPSProcessingMethod",
    0x001C: "GPSAreaInformation", 0x001D: "GPSDateStamp",
    0x001E: "GPSDifferential", 0x001F: "GPSHPositioningError",
}

_TYPE_NAMES = {1: "BYTE", 2: "ASCII", 3: "SHORT", 4: "LONG", 5: "RATIONAL",
               6: "SBYTE", 7: "UNDEFINED", 8: "SSHORT", 9: "SLONG",
               10: "SRATIONAL", 11: "FLOAT", 12: "DOUBLE", 13: "IFD"}

_ANOMALY_BLOB = 1 << 14      # >= 16 KB of opaque data
_ANOMALY_STRING = 1 << 12    # >= 4 KB in a text field


class _Pager:
    """Print lines, pausing on a TTY so a long dump doesn't fly by.

    Page size 40; Enter advances, q quits. Non-TTY output (pipes, test
    runs) prints everything with no prompt.
    """

    def __init__(self, full: bool = False):
        self.full = full or not sys.stdout.isatty()
        self.count = 0

    def emit(self, line: str = "") -> bool:
        """Print one line; returns False when the user quit the pager."""
        print(line)
        self.count += 1
        if self.full or self.count < 40:
            return True
        try:
            ans = input(c_dim("  — press Enter for more, q to quit — "))
        except (EOFError, KeyboardInterrupt):
            return False
        self.count = 0
        return ans.strip().lower() not in ("q", "quit")


def _unfamiliar(msg: str) -> str:
    """The anomaly badge: red [unfamiliar] tag + orange explanation."""
    return c_err("[unfamiliar]") + " " + c_orange(msg)


def _lcol(text: str, color, width: int) -> str:
    """Pad plain text to width, THEN colorize.

    Coloring first would let the invisible ANSI escape codes count
    toward the width, which collapses column alignment on a TTY.
    """
    return color(text.ljust(width))


def _size_str(n: int) -> str:
    """Human size: 512 B, 1.2 KB, 45.0 KB, 3.1 MB..."""
    if n < 1024:
        return f"{n} B"
    for unit in ("KB", "MB", "GB"):
        if n < 1024 * 1024 or unit == "GB":
            return f"{n / 1024:.1f} {unit}"
        n //= 1024
    return f"{n / 1024:.1f} GB"


def _decode_ascii(raw: bytes) -> str:
    """Strip NULs/trailing whitespace; keep printable text."""
    try:
        s = raw.decode("utf-8", errors="replace")
    except Exception:
        s = repr(raw)
    return s.rstrip("\x00 \t\r\n")


def _format_value(raw: bytes, typ: int, tag: int, ifd: str) -> str:
    """Render a tag's value in the most useful form: strings decoded,
    numbers as numbers, rationals as fractions, GPS as coordinates,
    everything else as a sized hex preview."""
    tsize = _TYPE_SIZE.get(typ, 1)
    cnt = len(raw) // tsize if tsize else 0
    if typ == 2:                                   # ASCII
        return f'"{_decode_ascii(raw)}"'
    if typ in (3, 4, 8, 9, 13):                    # SHORT/LONG families
        vals = [int.from_bytes(raw[i:i + tsize],
                               "big" if tsize in (1, 2) else "little")
                for i in range(0, len(raw), tsize)]
        vals = vals[:cnt]
        if len(vals) == 1:
            return str(vals[0])
        return "[" + ", ".join(str(v) for v in vals[:8]) + \
            ("..." if len(vals) > 8 else "") + "]"
    if typ in (5, 10):                             # RATIONAL / SRATIONAL
        vals = []
        for i in range(0, len(raw), 8):
            num = int.from_bytes(raw[i:i + 4], "little")
            den = int.from_bytes(raw[i + 4:i + 8], "little")
            vals.append((num, den))
        if ifd == "GPS" and tag in (0x0002, 0x0004, 0x0014, 0x0016):
            # coordinates are 3 rationals: degrees, minutes, seconds
            if len(vals) == 3 and all(d for _, d in vals):
                deg, mn, sec = vals
                d = deg[0] + mn[0] / 60 + sec[0] / 3600 / (sec[1] or 1) \
                    if sec[1] else deg[0]
                ref = ""
                return f"{d:.6f}°"
        parts = []
        for num, den in vals:
            parts.append(f"{num}/{den}" if den else f"{num}/0")
        if len(parts) == 1:
            num, den = vals[0]
            return f"{num}/{den} = {num / den:.6g}" if den else f"{num}/0"
        return "[" + ", ".join(parts[:8]) + "]"
    if typ in (1, 6, 7):                           # BYTE / SBYTE / UNDEFINED
        if not raw:
            return "<empty>"
        if all(b in (32, 9, 10, 13) or 32 <= b < 127 or b >= 0xA0
               for b in raw[:128]) and raw:
            return f'"{_decode_ascii(raw)}" ({len(raw)} B)'
        hx = " ".join(f"{b:02x}" for b in raw[:16])
        return f"<{len(raw)} B> {hx}" + (" ..." if len(raw) > 16 else "")
    if typ in (11, 12):                            # FLOAT / DOUBLE
        import struct
        fmtc = "f" if typ == 11 else "d"
        sz = 4 if typ == 11 else 8
        vals = []
        for i in range(0, len(raw) - sz + 1, sz):
            try:
                vals.append(struct.unpack("<" + fmtc, raw[i:i + sz])[0])
            except Exception:
                pass
        if len(vals) == 1:
            return f"{vals[0]:g}"
        return "[" + ", ".join(f"{v:g}" for v in vals[:8]) + "]"
    return f"<{len(raw)} B>"


def _tag_name(tag: int, ifd: str) -> str:
    if ifd == "GPS":
        return _GPS_TAGS.get(tag, f"tag 0x{tag:04X}")
    return _COMMON_TAGS.get(tag, _TIFF_IDENTIFYING.get(tag,
                                                       f"tag 0x{tag:04X}"))


def _anomalies(raw: bytes, typ: int, tag: int, ifd: str,
               name: str) -> list:
    """Small suspicion scanner: things a reviewer should look twice at."""
    out = []
    if tag == 0x927C:
        out.append("MakerNote: vendor data, fingerprints the camera")
    if ifd == "GPS" and tag in (0x0002, 0x0004, 0x0014, 0x0016):
        out.append("GPS coordinate")
    if typ == 2 and len(raw) >= _ANOMALY_STRING:
        out.append(f"overlong text ({len(raw)} B)")
    if typ in (1, 7) and len(raw) >= _ANOMALY_BLOB:
        out.append(f"large opaque blob ({len(raw)} B)")
    if typ in (1, 2, 7) and raw and _value_is_blank(raw):
        out.append("blanked but present: possible previous wipe attempt")
    return out


def _walk_tiff(pager, data: bytes, fmt: str) -> None:
    """Recursively walk every reachable IFD and print every entry.

    Uses the same IFD graph the strip engine walks (next-IFD chain,
    SubIFDs, EXIF/GPS pointers) but keeps the IFD *names* so the output
    shows the hierarchy: IFD0 -> ExifIFD -> MakerNote, GPS, thumbnails...
    """
    hdr = _tiff_parse_header(data)
    if hdr is None:
        pager.emit(c_warn("    not a parseable TIFF container"))
        return
    bo, magic = hdr
    entry, ifd_cnt, ent_cnt, off_size, header = _tiff_layout(bo, magic)
    ifd0 = int.from_bytes(data[header - off_size:header], bo)
    seen = set()
    queue = [(ifd0, "IFD0", 0)]
    totals = {"entries": 0, "anomalies": 0}

    while queue:
        off, label, depth = queue.pop(0)
        if off in seen or off + ifd_cnt > len(data):
            continue
        seen.add(off)
        count = int.from_bytes(data[off:off + ifd_cnt], bo)
        if count > 1_000_000:
            count = 1_000_000
        p = off + ifd_cnt
        indent = "  " * depth
        ifd_entries = 0
        pager.emit(f"  {c_head(label + ':')}")
        for _ in range(count):
            if p + entry > len(data):
                break
            tag = int.from_bytes(data[p:p + 2], bo)
            typ = int.from_bytes(data[p + 2:p + 4], bo)
            cnt = int.from_bytes(data[p + 4:p + 4 + ent_cnt], bo)
            vf = p + 4 + off_size
            raw = _tiff_value_bytes(data, bo, magic, typ, cnt, vf)
            ifd_entries += 1
            totals["entries"] += 1
            name = _tag_name(tag, label)
            flags = _anomalies(raw, typ, tag, label, name)
            line = (f"{indent}  {_lcol(name, c_info, 24)} "
                    f"{c_dim('0x%04X' % tag)} "
                    f"{_lcol(_TYPE_NAMES.get(typ, '?') + ':' + str(cnt),
                             c_dim, 16)}"
                    f" = {c_warn(_format_value(raw, typ, tag, label))}")
            if flags:
                line += "  " + c_danger("[danger] ") + "; ".join(flags)
                totals["anomalies"] += 1
            if not pager.emit(line):
                return
            if tag == 0x014A and typ in (3, 4, 9, 13):   # SubIFDs
                n_sub = min(cnt, 256)
                for i in range(n_sub):
                    so = int.from_bytes(data[vf + i * off_size:
                                             vf + (i + 1) * off_size], bo)
                    if so:
                        queue.append((so, f"{label}.SubIFD[{i}]", depth + 1))
            elif tag in (0x8769, 0x8825, 0xA005):
                tgt = int.from_bytes(data[vf:vf + off_size], bo)
                if tgt:
                    queue.append((tgt, _IFD_LABELS.get(tag, "IFD"), depth + 1))
            p += entry
        if p + off_size <= len(data):
            nxt = int.from_bytes(data[p:p + off_size], bo)
            if nxt:
                queue.append((nxt, f"IFD{len(seen)}", depth))
    pager.emit(c_dim(f"    {totals['entries']} entries, "
                     f"{totals['anomalies']} [danger]"))
    if fmt in RAW_FORMATS:
        pager.emit(c_dim("    RAW container — sensor data is never "
                         "re-encoded; surgery is in-place"))


def _inspect_jpeg(pager, data: bytes) -> None:
    """JPEG: APP-segment sweep + piexif recursive IFD dump (optional)."""
    names = _jpeg_metadata_segments(data)
    if names:
        pager.emit(f"  {c_head('APP segments:')}")
        for nm in names:
            pager.emit(f"    - {c_warn(nm)}")
    else:
        pager.emit(f"  {c_head('APP segments:')} {c_ok('none')}")
    if piexif is not None:
        try:
            ifd = piexif.load(data)
            for section in ("0th", "Exif", "GPS", "Interop", "1st"):
                d = ifd.get(section)
                if not d:
                    continue
                label = {"0th": "IFD0", "1st": "thumbnail"}.get(
                    section, section)
                pager.emit(f"  {c_head(label + ':')}")
                for tag, val in d.items():
                    tagname = piexif.TAGS.get(section, {}).get(
                        tag, {}).get("name", f"tag 0x{tag:04X}")
                    disp = val
                    if isinstance(val, bytes):
                        disp = _format_value(val, 7, tag, label)
                    elif isinstance(val, (tuple, list)):
                        if (section == "GPS" and tag in (0x0002, 0x0004)
                                and len(val) == 3):
                            frac = []
                            for num, den in val:
                                frac.append(num / den if den else 0)
                            deg = frac[0] + frac[1] / 60 + frac[2] / 3600
                            ref = ""
                            if (tag == 0x0002
                                    and d.get(0x0001, b"N") == b"S"):
                                ref = " S"
                            if (tag == 0x0004
                                    and d.get(0x0003, b"E") == b"W"):
                                ref = " W"
                            disp = f"{deg:.6f}°{ref}"
                        else:
                            disp = str(val)
                    raw = val if isinstance(val, bytes) else b""
                    flags = _anomalies(raw, 7, tag, label, tagname)
                    line = (f"    {_lcol(str(tagname), c_info, 24)} "
                            f"{c_dim('0x%04X' % tag)} = {c_warn(str(disp))}")
                    if flags:
                        line += "  " + c_danger("[danger] ") + "; ".join(flags)
                    pager.emit(line)
        except Exception as e:
            pager.emit(c_dim(f"    (piexif could not parse: {e})"))
    else:
        pager.emit(c_dim("    (piexif not installed — IFD contents "
                         "not decoded)"))
    if b"JFIF" in data[:32]:
        pager.emit(c_dim("    JFIF marker present (structural)"))
    for nm in ("APP13:Photoshop", "ICC_PROFILE"):
        if nm == "ICC_PROFILE" and b"ICC_PROFILE\x00" in data:
            pager.emit("  " + _unfamiliar("ICC profile present — color management, "
                                           "not metadata"))


def _inspect_png(pager, data: bytes) -> None:
    pos, n = 8, len(data)
    iend = False
    while pos + 8 <= n:
        clen = int.from_bytes(data[pos:pos + 4], "big")
        ctype = data[pos + 4:pos + 8]
        if pos + 12 + clen > n:
            pager.emit(c_warn(f"    truncated chunk {ctype!r} at {pos}"))
            break
        payload = data[pos + 8:pos + 8 + clen]
        flag = ""
        if ctype in (b"tEXt", b"iTXt", b"zTXt"):
            kw = _decode_ascii(payload[:80].split(b"\x00")[0])
            flag = " " + _unfamiliar(f"text chunk keyword={kw!r}")
        elif ctype in (b"eXIf", b"iCCP", b"pHYs", b"acTL", b"fcTL"):
            flag = c_warn(f" ({ctype.decode()} metadata/structure)")
        elif ctype == b"IEND":
            iend = True
        elif iend:
            flag = " " + _unfamiliar("data after IEND")
        pager.emit(f"    {_lcol(ctype.decode('ascii', 'replace'), c_info, 8)} "
                   f"{_lcol(_size_str(clen), c_dim, 10)} @ {pos}{flag}")
        pos += 12 + clen
    if pos != n:
        pager.emit("    " + _unfamiliar(f"{n - pos} trailing bytes after last chunk"))


def _inspect_webp(pager, data: bytes) -> None:
    pos, n = 12, len(data)
    while pos + 8 <= n:
        tag = data[pos:pos + 4]
        size = int.from_bytes(data[pos + 4:pos + 8], "little")
        if size > n:
            break
        flag = ""
        if tag in (b"EXIF", b"XMP ", b"ICCP"):
            flag = " " + _unfamiliar("metadata chunk")
        pager.emit(f"    {_lcol(tag.decode('ascii', 'replace'), c_info, 6)} "
                   f"{_lcol(_size_str(size), c_dim, 10)} @ {pos}{flag}")
        pos += 8 + size + (size & 1)
    if b"VP8X" in data[:20]:
        pager.emit(c_dim("    VP8X extended header (animation/canvas "
                         "info)"))
    if data[12:16] == b"VP8L":
        pager.emit(c_dim("    VP8L — lossless WebP (strip stays "
                         "lossless)"))


def _inspect_gif(pager, data: bytes) -> None:
    ncom = data.count(b"\x21\xfe")
    if ncom:
        pager.emit("  " + _unfamiliar(f"{ncom} comment extension(s)"))
    else:
        pager.emit("  comment extensions: none")
    if b"XMP Data" in data:
        pager.emit("  " + _unfamiliar("XMP application extension present"))
    else:
        pager.emit("  XMP: none")


def _inspect_heif(pager, data: bytes) -> None:
    ext = _heif_metadata_extents(data)
    if ext is None:
        pager.emit(c_warn("    container unparseable (iloc missing?)"))
        return
    pager.emit(f"  ISO-BMFF metadata item extents: {len(ext)}")
    for s, e in ext:
        filled = any(data[s:e])
        mark = " " + _unfamiliar("still populated") if filled else c_ok("blank")
        pager.emit(f"    {s}..{e} ({_size_str(e - s)}) {mark}")
    if b"<x:xmpmeta" in data:
        pager.emit("  " + _unfamiliar("XMP payload present"))


def _inspect_raf(pager, data: bytes) -> None:
    zone = data[0x14:0x40] if len(data) >= 0x40 else b""
    if any(b not in (0, 32) for b in zone):
        pager.emit("  " + _unfamiliar("header zone (serial/model/firmware) "
                                       "NOT blank"))
    else:
        pager.emit("  header zone (serial/model/firmware): blank")
    jpos = int.from_bytes(data[0x54:0x58], "big") if len(data) >= 0x5c else 0
    jlen = int.from_bytes(data[0x58:0x5c], "big") if len(data) >= 0x5c else 0
    if jpos and jlen and jpos + jlen <= len(data):
        pager.emit(f"  embedded JPEG preview: {jpos}..{jpos + jlen} "
                   f"({_size_str(jlen)})")
        for nm in _jpeg_metadata_segments(data[jpos:jpos + jlen]):
            pager.emit("    " + _unfamiliar(f"preview carries: {nm}"))
    foff = int.from_bytes(data[0x64:0x68], "big") if len(data) >= 0x6c else 0
    flen = int.from_bytes(data[0x68:0x6c], "big") if len(data) >= 0x6c else 0
    if foff and flen and foff + flen <= len(data):
        region = data[foff:foff + flen]
        pager.emit(f"  FujiIFD block: {foff}..{foff + flen}")
        for nm in _tiff_find_identifying(region):
            pager.emit("    " + _unfamiliar(f"FujiIFD carries: {nm}"))


def _inspect_pdf(pager, data: bytes) -> None:
    try:
        import pikepdf
    except ImportError:
        pager.emit(c_warn("  pikepdf not installed — install with "
                          "`pip install .[pdf]`"))
        return
    from pathlib import Path as _P
    import tempfile
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(data)
            name = f.name
        try:
            with pikepdf.open(name) as pdf:
                root = pdf.Root if pdf.Root is not None else {}
                if pdf.docinfo:
                    pager.emit(f"  {c_head('DocInfo:')}")
                    for k, v in pdf.docinfo.items():
                        pager.emit(f"    {c_info(str(k))} = "
                                   f"{c_warn(str(v))}")
                else:
                    pager.emit("  DocInfo: none")
                pager.emit(f"  {c_head('Root keys:')}")
                for k in root:
                    if k in ("/Type", "/Pages", "/Size", "/Info",
                             "/ID", "/Metadata", "/Lang", "/OpenAction",
                             "/PieceInfo", "/StructTreeRoot", "/PageLabels",
                             "/MarkInfo", "/Perms"):
                        pager.emit(f"    {c_info(str(k))}")
        finally:
            _P(name).unlink(missing_ok=True)
    except Exception as e:
        pager.emit(c_warn(f"  could not parse PDF: {e}"))


def inspect_image(path: Path, max_pixels: Optional[int] = None,
                  full: bool = False) -> None:
    """Print a recursive metadata dump of one file.

    Uses the same byte-level machinery as the strip engine, so what you
    see here is exactly what a wipe would destroy — IFD by IFD, chunk by
    chunk, with decoded values and a small anomaly scanner on top.
    """
    if max_pixels is None:
        max_pixels = DEFAULT_MAX_PIXELS
    pager = _Pager(full)
    if not pager.emit(f"\n{c_head('=' * 3)} {c_head(path.name)} "
                      f"{c_head('=' * 3)}"):
        return
    try:
        data = path.read_bytes()
    except OSError as e:
        pager.emit(c_err(f"  [ERR] {e}"))
        return
    fmt = _sniff_format(path)
    pager.emit(f"  {c_info('format')}={fmt or 'unknown'}")
    pager.emit(f"  {c_info('size')}={c_dim(_size_str(len(data)))}")
    if fmt is None:
        pager.emit(c_warn("    unrecognized file — nothing to show"))
        return
    from PIL import Image
    import io
    try:
        with Image.open(io.BytesIO(data)) as img:
            w, h = img.size
            pager.emit(f"  {c_info('pixels')}={w}x{h} "
                       f"({w * h:,} px)")
    except Exception:
        pass
    if max_pixels and fmt in ("jpeg", "png", "gif", "webp", "bmp",
                              "heif", "avif"):
        from PIL import Image
        import io
        try:
            with Image.open(io.BytesIO(data)) as img:
                w, h = img.size
                if w * h > max_pixels:
                    pager.emit(c_warn(
                        f"  pixel dump skipped ({w * h:,}px > "
                        f"{max_pixels:,} limit) — use --max-pixels"))
        except Exception:
            pass

    if fmt in ("tiff", "cr2", "dng", "nef", "arw", "orf", "rw2", "pef",
               "srw"):
        _walk_tiff(pager, data, fmt)
    elif fmt == "jpeg":
        _inspect_jpeg(pager, data)
    elif fmt == "png":
        _inspect_png(pager, data)
    elif fmt == "webp":
        _inspect_webp(pager, data)
    elif fmt == "gif":
        _inspect_gif(pager, data)
    elif fmt in ("heif", "avif"):
        _inspect_heif(pager, data)
    elif fmt == "raf":
        _inspect_raf(pager, data)
    elif fmt == "pdf":
        _inspect_pdf(pager, data)
    elif fmt == "bmp":
        pager.emit("  BMP: no metadata carriers (pixel rebuild)")
    else:
        pager.emit(c_dim("    no structured metadata dump for this "
                         "format yet"))

    info = None
    try:
        from PIL import Image
        import io
        with Image.open(io.BytesIO(data)) as img:
            info = img.info or {}
    except Exception:
        info = {}
    if info:
        pager.emit(f"  {c_head('img.info:')}")
        for k, v in info.items():
            disp = _img_info_value(k, v)
            sz = _img_info_size(v)
            key = repr(str(k))
            if sz is not None:
                line = (f"    {_lcol(key, c_mag, 20)} "
                        f"{_lcol('(' + _size_str(sz) + ')', c_dim, 9)} = "
                        f"{c_warn(disp)}")
            else:
                line = f"    {_lcol(key, c_mag, 20)} = {c_warn(disp)}"
            pager.emit(line)


def _img_info_size(v) -> Optional[int]:
    """Byte size of an img.info value, or None when not meaningful."""
    if isinstance(v, (bytes, bytearray)):
        return len(v)
    if isinstance(v, str):
        return len(v.encode("utf-8", errors="replace"))
    return None


def _img_info_value(k, v):
    """Turn Pillow's img.info entries into something a human can read."""
    if k == "jfif" and isinstance(v, int):
        # 0x0101 = version 1.01 (major byte, minor byte)
        return f"JFIF v{v >> 8}.{v & 0xFF:02d}"
    if k == "jfif_version" and isinstance(v, tuple):
        return ".".join(str(x) for x in v)
    if k == "jfif_unit":
        return {0: "none (aspect only)", 1: "dots per inch",
                2: "dots per cm"}.get(v, str(v))
    if k in ("jfif_density", "dpi") and isinstance(v, tuple):
        return f"{v[0]:g}x{v[1]:g}"
    if k == "progressive":
        return "yes" if v else "no"
    if isinstance(v, (bytes, bytearray)):
        if k in ("exif", "xmp", "icc_profile"):
            return {"exif": "raw EXIF payload (decoded above)",
                    "xmp": "XMP XML payload",
                    "icc_profile": "ICC color profile"}[k]
        return "binary blob"
    if isinstance(v, str):
        return repr(v[:80]) + ("..." if len(v) > 80 else "")
    return repr(v)


def exiftool_hint() -> str:
    return (
        "exiftool -a -G -s IMAGE.jpg       # see everything ExifTool sees\n"
        "exiftool -all= IMAGE.jpg           # the CLI equivalent of --in-place\n"
    )
