"""_tiff - exifwipe internal module (format/strip machinery)."""

from __future__ import annotations



from typing import Optional

from lib._config import _MAKERNOTE_VENDORS

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


_TIFF_BLANK = {
    0x010E, 0x010F, 0x0110, 0x0131, 0x0132, 0x013B, 0x02BC, 0x83BB,
    0x8649, 0x8298, 0x9286, 0x9C9B, 0x9C9C, 0x9C9D, 0x9C9E,
    0xC62D, 0xC614, 0xC615, 0xC68B, 0xC68C, 0xC634,
}


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


def _tiff_inventory(data: bytes, keep_icc: bool = False,
                    drop_orientation: bool = False) -> list:
    """Names of the identifying metadata a TIFF-family wipe will destroy
    (for --report): EXIF/GPS blocks, identifying tags, ICC unless kept,
    Orientation only when it's being dropped."""
    hdr = _tiff_parse_header(data)
    if hdr is None:
        return []
    bo, magic = hdr
    names = []
    for (p, tag, typ, cnt, vf) in _iter_tiff_entries(data, bo, magic):
        if tag == 0x8769:
            names.append("ExifIFD block (destroyed)")
        elif tag == 0x8825:
            names.append("GPSInfo block (destroyed)")
        elif tag == 0x8773 and not keep_icc:
            names.append("ICC profile (0x8773)")
        elif tag == 0x0112 and drop_orientation:
            names.append("Orientation (0x0112)")
        elif tag in _TIFF_IDENTIFYING:
            names.append(f"{_TIFF_IDENTIFYING[tag]} (0x{tag:04X})")
    # dedupe, keep order
    seen, out = set(), []
    for n in names:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def _tiff_protected_regions(data: bytes, bo: str, magic: int) -> list:
    """Byte ranges that must never be overwritten as tag *values*: the
    file header, every reachable IFD block (count + entries + next
    pointer) AND the pixel strip/tile ranges (StripOffsets/ByteCounts).
    A hostile file can point a tag's value offset at its own structure
    or at pixels — blanking there would silently destroy the file or
    its photo. The surgery refuses the file instead."""
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
        strips_off, strips_cnt = [], []
        for _ in range(count):
            if p + entry > len(data):
                break
            tag = int.from_bytes(data[p:p + 2], bo)
            typ = int.from_bytes(data[p + 2:p + 4], bo)
            cnt = int.from_bytes(data[p + 4:p + 4 + ent_cnt], bo)
            vfield = p + 4 + off_size
            tsize = _TYPE_SIZE.get(typ)
            if tsize is None:
                p += entry
                continue
            nbytes = cnt * tsize
            if nbytes <= off_size:      # inline value/array in the entry
                base = vfield
            else:                        # external array behind an offset
                addr = int.from_bytes(data[vfield:vfield + off_size], bo)
                if addr + nbytes > len(data):
                    p += entry
                    continue
                base = addr
            vals = [int.from_bytes(
                data[base + i * tsize:base + (i + 1) * tsize], bo)
                for i in range(min(cnt, 256))]
            if tag == 0x014A:            # SubIFDs — walk them
                for so in vals:
                    if so:
                        queue.append(so)
            elif tag in (0x8769, 0x8825):  # EXIF / GPS targets
                tgt = int.from_bytes(data[vfield:vfield + off_size], bo)
                if tgt:
                    queue.append(tgt)
            elif tag == 0x0111:          # StripOffsets
                strips_off.extend(v for v in vals if v)
            elif tag == 0x0117:          # StripByteCounts
                strips_cnt.extend(v for v in vals if v)
            p += entry
        for so, sc in zip(strips_off, strips_cnt):
            if so + sc <= len(data):
                regions.append((so, so + sc))
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


def _tiff_vendor_from_makernote(data: bytes) -> Optional[str]:
    """Identify a RAW family from its MakerNote prefix (Nikon/Sony/Olympus/
    Panasonic/Pentax/Samsung/Canon/Hasselblad), so extensionless or
    mislabeled TIFF-family files get the right treatment. Returns None
    when there's no recognizable MakerNote."""
    hdr = _tiff_parse_header(data)
    if hdr is None:
        return None
    bo, magic = hdr
    for (_, tag, typ, cnt, vf) in _iter_tiff_entries(data, bo, magic):
        if tag != 0x927C:
            continue
        val = _tiff_value_bytes(data, bo, magic, typ, cnt, vf)
        for prefix, fam in _MAKERNOTE_VENDORS:
            if val.startswith(prefix):
                return fam
    return None


def _is_tiff_family(data: bytes) -> bool:
    return _tiff_parse_header(data) is not None


def _tiff_strip_lossless(data: bytes, keep_icc: bool = False,
                         drop_orientation: bool = False):
    """Lossless metadata surgery for TIFF-family containers (TIFF / DNG /
    CR2 / NEF / ARW / ORF / RW2 / PEF / SRW / SR2...).

    No offset is ever remapped, so pixel data stays byte-identical:
      * every EXIF IFD (0x8769) and GPS IFD (0x8825) target is overwritten
        with an empty IFD (count=0, next=0) — MakerNotes, DateTimeOriginal,
        GPS coordinates and the whole Interop chain die with them;
      * identifying scalar tags (Make, Model, Software, Artist, Copyright,
        ImageDescription, SerialNumber, DNG camera model / private data /
        original-raw blobs...) are blanked in place;
      * Orientation (0x0112) is blanked only with drop_orientation (kept
        by default: it's a display instruction, not identity, and RAW
        pixels can't be re-rotated);
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
        elif tag in _TIFF_BLANK or (tag == 0x8773 and not keep_icc) \
                or (tag == 0x0112 and drop_orientation):
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

