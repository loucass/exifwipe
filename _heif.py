"""_heif - exifwipe internal module (format/strip machinery)."""

from __future__ import annotations



from _config import _HEIF_META_TYPES

def _heif_box_children(data: bytes, start: int, end: int):
    """Yield (box_pos, size, type, payload_pos) for boxes in [start, end),
    honoring 64-bit (size=1) and to-EOF (size=0) boxes. Yields nothing on
    malformed input — a hostile file can't make this loop forever."""
    pos = start
    while pos + 8 <= end:
        size = int.from_bytes(data[pos:pos + 4], "big")
        typ = data[pos + 4:pos + 8]
        hdr = 8
        if size == 1:
            if pos + 16 > end:
                return
            size = int.from_bytes(data[pos + 8:pos + 16], "big")
            hdr = 16
        elif size == 0:
            size = end - pos
        if size < hdr or pos + size > end:
            return
        yield (pos, size, typ, pos + hdr)
        pos += size


def _heif_iloc_items(b: bytes):
    """Decode an iloc fullbox payload -> [(item_id, construction_method,
    base_offset, [(extent_offset, extent_length)])]. Bounded on hostile
    counts; returns what parsed."""
    if len(b) < 6:
        return []
    ver = b[0]
    off_size = (b[4] >> 4) & 0xF
    len_size = b[4] & 0xF
    base_size = (b[5] >> 4) & 0xF
    idx_size = b[5] & 0xF
    i = 6
    if ver < 2:
        if i + 2 > len(b):
            return []
        count = int.from_bytes(b[i:i + 2], "big")
        i += 2
    else:
        if i + 4 > len(b):
            return []
        count = int.from_bytes(b[i:i + 4], "big")
        i += 4
    items = []
    for _ in range(min(count, 4096)):
        if ver < 2:
            if i + 2 > len(b):
                return items
            item_id = int.from_bytes(b[i:i + 2], "big")
            i += 2
        else:
            if i + 4 > len(b):
                return items
            item_id = int.from_bytes(b[i:i + 4], "big")
            i += 4
        if ver in (1, 2):
            if i + 2 > len(b):
                return items
            cm = int.from_bytes(b[i:i + 2], "big") & 0xF
            i += 2
        else:
            cm = 0
        if i + 2 > len(b):
            return items
        i += 2                      # data_reference_index
        base = int.from_bytes(b[i:i + base_size], "big") if base_size else 0
        i += base_size
        if i + 2 > len(b):
            return items
        ecnt = int.from_bytes(b[i:i + 2], "big")
        i += 2
        extents = []
        for _ in range(min(ecnt, 256)):
            if idx_size and ver in (1, 2):
                i += idx_size
            eo = int.from_bytes(b[i:i + off_size], "big") if off_size else 0
            i += off_size
            el = int.from_bytes(b[i:i + len_size], "big") if len_size else 0
            i += len_size
            extents.append((eo, el))
        items.append((item_id, cm, base, extents))
    return items


def _heif_item_types(b: bytes) -> dict:
    """Map item_ID -> item_type from the iinf box's infe children."""
    if len(b) < 5:
        return {}
    ver = b[0]
    i = 4
    if ver < 2:
        if i + 2 > len(b):
            return {}
        i += 2                      # item count
    else:
        if i + 4 > len(b):
            return {}
        i += 4
    types = {}
    end = len(b)
    while i + 8 <= end:
        size = int.from_bytes(b[i:i + 4], "big")
        typ = b[i + 4:i + 8]
        if size < 8 or i + size > end:
            break
        if typ == b"infe":
            p = i + 8
            if p >= end:
                break
            ver2 = b[p]
            p += 4                  # fullbox header (version + flags)
            item_id, consumed = _heif_infe_item_id(b, p, ver2, end)
            if consumed == 0:
                break
            p += consumed
            p += 2                  # item_protection_index
            if p + 4 > end:
                break
            types[item_id] = b[p:p + 4]
        i += size
    return types


def _heif_infe_item_id(b: bytes, p: int, ver2: int, end: int):
    """(item_ID, bytes_consumed) from an infe payload. Spec: version 2 =
    32-bit ID, 0/1 = 16-bit. libheif writes the version-2 header but a
    16-bit ID, so a 32-bit read that comes out implausibly large (>0xFFFF)
    falls back to the 16-bit read."""
    if ver2 < 2:
        if p + 2 > end:
            return 0, 0
        return int.from_bytes(b[p:p + 2], "big"), 2
    if p + 4 <= end:
        wide = int.from_bytes(b[p:p + 4], "big")
        if 0 < wide <= 0xFFFF:
            return wide, 4
    if p + 2 <= end:
        return int.from_bytes(b[p:p + 2], "big"), 2
    return 0, 0


def _heif_exif_payload_present(data: bytes) -> bool:
    """True when a real EXIF item payload exists: the 4-byte offset + the
    b"Exif\0\0" marker + a TIFF header. (The plain "Exif" string in an
    infe item-type box doesn't match — that's structure, not payload.)"""
    idx = 0
    while True:
        idx = data.find(b"Exif\x00\x00", idx)
        if idx == -1:
            return False
        if data[idx + 8:idx + 12] in (b"MM\x00*", b"II*\x00"):
            return True
        idx += 8


def _heif_metadata_extents(data: bytes):
    """Absolute [start, end) byte ranges of EXIF/XMP item payloads, or
    None when the container can't be parsed (unverifiable). Content-sniffs
    extents of unknown item types as a backstop."""
    if data[4:8] != b"ftyp":
        return None
    meta = None
    for (_, ms, bt, bpay) in _heif_box_children(data, 0, len(data)):
        if bt == b"meta":
            meta = (bpay, bpay + ms)
            break
    if meta is None:
        return None
    mstart, mend = meta
    iloc_payload = iinf_payload = None
    # children live after the meta fullbox header (4 bytes), and the walk
    # MUST stop at the meta box end — never past it (mdat pixel bytes
    # could be mistaken for boxes)
    for (cp, cs, ct, cpay) in _heif_box_children(data, mstart + 4, mend):
        if ct == b"iloc" and iloc_payload is None:
            iloc_payload = bytes(data[cpay:cp + cs])
        elif ct == b"iinf" and iinf_payload is None:
            iinf_payload = bytes(data[cpay:cp + cs])
    if iloc_payload is None:
        return None
    items = _heif_iloc_items(iloc_payload)
    types = _heif_item_types(iinf_payload) if iinf_payload else {}
    regions = []
    for (item_id, cm, base, extents) in items:
        t = types.get(item_id, b"")
        known_meta = t in _HEIF_META_TYPES
        for (eo, el) in extents:
            if cm != 0:
                continue        # idat-relative — rare, not handled
            start = base + eo
            if el <= 0 or start < 0 or start + el > len(data):
                continue        # hostile extent — bounds-checked, skipped
            head = data[start:start + min(el, 64)]
            if known_meta or not t:
                # unknown type: sniff. Exif payloads are [4-byte offset]
                # + b"Exif\x00\x00" + TIFF magic; XMP is raw XML.
                exif_like = (b"Exif\x00\x00" in head[:12]
                             and (b"MM\x00*" in head[:16]
                                  or b"II*\x00" in head[:16]))
                xmp_like = b"<x:xmpmeta" in head or head[:3] == b"xmp"
                if known_meta or exif_like or xmp_like:
                    regions.append((start, start + el))
    return regions


def _strip_heif_lossless(data: bytes):
    """Lossless wipe of HEIC/AVIF EXIF + XMP item payloads: zero the iloc
    extents they point at, leave every pixel item byte-identical. Returns
    None when the container can't be parsed safely (caller falls back to
    a re-encode), raw bytes when it parsed and was already clean."""
    regions = _heif_metadata_extents(data)
    if regions is None:
        return None             # unparseable — never claim a clean wipe
    if not regions:
        # nothing mapped; if a payload marker exists that we couldn't
        # map, refuse rather than declare victory on suspicion
        if _heif_exif_payload_present(data) or b"<x:xmpmeta" in data:
            return None
        return bytes(data)      # already clean
    out = bytearray(data)
    for (s, e) in regions:
        out[s:e] = b"\x00" * (e - s)
    return bytes(out)

