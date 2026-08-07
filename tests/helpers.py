"""Test helpers for the exifwipe suite — fixture builders + forensic scanners.

Everything here deliberately inspects the raw bytes (and independent
libraries like piexif), never exifwipe's own verify functions, so the
tests stay honest: they assert what actually leaked, not what exifwipe
*thinks* leaked.
"""

import io
from pathlib import Path

import piexif
from PIL import Image
from PIL.PngImagePlugin import PngInfo

from exifwipe import _strip_gif_lossless  # noqa: F401  (used by some tests)


# --------------------------------------------------------------------------- #
# fixture builders
# --------------------------------------------------------------------------- #
def multipage_tiff(path, pages=3, tags=True):
    imgs = [Image.new("L", (20, 10 + i), i * 40) for i in range(pages)]
    buf = io.BytesIO()
    kw = {"save_all": True, "append_images": imgs[1:]}
    if tags:
        kw["description"] = "leaky description"
        kw["software"] = "leaky software"
    imgs[0].save(buf, format="TIFF", **kw)
    Path(path).write_bytes(buf.getvalue())
    return Path(path)


# --------------------------------------------------------------------------- #
# TIFF-family fixture builder — handcrafts structurally valid TIFF / DNG /
# CR2 / BigTIFF containers so the RAW surgery is tested against bytes we
# fully control (Pillow validates the layout by opening the result).
# --------------------------------------------------------------------------- #
def _enc(typ, value, bo: str):
    """Encode a tag value -> (count, payload_bytes, [(pos, ref_name)]).
    Refs are ('ref', name) markers patched with real offsets later."""
    end = bo
    refs = []

    def _pack_int(v):
        if isinstance(v, tuple) and len(v) == 2 and v[0] == "ref":
            refs.append((len(payload), v[1]))
            return b"\x00" * 4
        return v.to_bytes(4, end)

    payload = bytearray()
    if typ == 2:                                  # ASCII
        if isinstance(value, bytes):
            payload = bytearray(value)
        else:
            payload = bytearray((str(value) + "\x00").encode("latin-1"))
        if not payload.endswith(b"\x00"):
            payload += b"\x00"
        return len(payload), bytes(payload), []
    if typ == 3:                                  # SHORT
        for v in (value if isinstance(value, list) else [value]):
            payload += int(v).to_bytes(2, end)
    elif typ == 4:                                # LONG
        for v in (value if isinstance(value, list) else [value]):
            payload += _pack_int(v)
    elif typ == 5:                                # RATIONAL (list of (n,d))
        for n, d in value:
            payload += int(n).to_bytes(4, end) + int(d).to_bytes(4, end)
    elif typ in (1, 7):                           # BYTE / UNDEFINED
        payload = bytearray(value if isinstance(value, bytes) else bytes(value))
    else:
        raise ValueError(f"builder: unsupported type {typ}")
    # count is the NUMBER OF ELEMENTS, not the byte length — a LONG ref
    # marker is count=1 (4 bytes), which keeps it inline in the entry
    elem = _TYPE_ELEM.get(typ, 1)
    return len(payload) // elem, bytes(payload), refs


def build_tiff(entries0, *, exif=None, gps=None, sub=None, ifd1=None,
               pixels=b"\x00\x00\x00" * 64, bo="little", magic=42,
               cr2=False):
    """Build a valid TIFF-family container.

    entriesN: list of (tag, type, value); value may contain ("ref", name)
    markers for exif/gps/sub/ifd1 offsets. pixels: raw RGB rows (Pillow
    opens the result to prove the layout is sound). Returns bytes."""
    big = magic == 43
    entry_size, ifd_cnt, ent_cnt, off_size, header_len = (
        (20, 8, 8, 8, 16) if big else (12, 2, 4, 4, 8))
    end = bo
    inline_max = 8 if big else 4

    blocks = {"ifd0": entries0, "exif": exif or [], "gps": gps or [],
              "sub": sub or [], "ifd1": ifd1 or []}

    # phase 1: encode each IFD's entries -> (typ, count, payload, refs)
    enc = {}
    for name, ents in blocks.items():
        rows = []
        for (tag, typ, value) in ents:
            count, payload, refs = _enc(typ, value, bo)
            inline = count * (1 if typ == 2 else _TYPE_ELEM[typ]) <= inline_max
            rows.append((tag, typ, count, payload, refs, inline))
        enc[name] = rows

    def ifd_block_size(rows):
        size = ifd_cnt + len(rows) * entry_size + off_size
        ext = sum(len(r[3]) for r in rows if not r[5])
        return size, ext

    # phase 2: layout. Order: header, IFD0, IFD1, exif, gps, sub, then a
    # shared external-data region, then pixels.
    cursor = header_len
    if cr2:
        cursor = 16
    ifd0_off = cursor
    cursor += ifd_block_size(enc["ifd0"])[0]
    ifd1_off = cursor if enc["ifd1"] else 0
    if enc["ifd1"]:
        cursor += ifd_block_size(enc["ifd1"])[0]
    exif_off = cursor if enc["exif"] else 0
    if enc["exif"]:
        cursor += ifd_block_size(enc["exif"])[0]
    gps_off = cursor if enc["gps"] else 0
    if enc["gps"]:
        cursor += ifd_block_size(enc["gps"])[0]
    sub_off = cursor if enc["sub"] else 0
    if enc["sub"]:
        cursor += ifd_block_size(enc["sub"])[0]
    data_off = cursor
    # external payloads, each padded to even alignment
    ext_offs = {}
    for name, rows in enc.items():
        for (tag, typ, count, payload, refs, inline) in rows:
            if not inline:
                if cursor % 2:
                    cursor += 1
                ext_offs[(name, tag)] = cursor
                cursor += len(payload)
    pixel_off = cursor

    # phase 3: assemble
    out = bytearray()
    if cr2:
        out += b"II*\x00" + (16).to_bytes(4, end) + (0x0201).to_bytes(4, end)
        out += (ifd1_off or 0).to_bytes(4, end)
    elif big:
        # BigTIFF header is 16 bytes: sig + 43 + reserved HH(8,0) + 8-byte
        # IFD0 offset at bytes 8-15 (matches Pillow's writer exactly)
        out += (b"II" if bo == "little" else b"MM") + (43).to_bytes(2, end)
        out += (8).to_bytes(2, end) + (0).to_bytes(2, end)
        out += (ifd0_off).to_bytes(8, end)
    else:
        out += (b"II" if bo == "little" else b"MM") + (42).to_bytes(2, end)
        out += (ifd0_off).to_bytes(4, end)
    assert len(out) == ifd0_off, "header size mismatch"

    ref_map = {"exif": exif_off, "gps": gps_off, "sub": sub_off,
               "ifd1": ifd1_off}

    def write_ifd(name, next_ifd=0):
        nonlocal out
        rows = enc[name]
        out += len(rows).to_bytes(ifd_cnt, end)
        for (tag, typ, count, payload, refs, inline) in rows:
            out += tag.to_bytes(2, end) + typ.to_bytes(2, end)
            out += count.to_bytes(ent_cnt, end)
            if inline:
                raw = bytearray(payload)
                for pos, ref in refs:
                    raw[pos:pos + 4] = ref_map[ref].to_bytes(4, end)
                out += bytes(raw).ljust(off_size, b"\x00")
            else:
                out += ext_offs[(name, tag)].to_bytes(off_size, end)
        out += next_ifd.to_bytes(off_size, end)

    write_ifd("ifd0", next_ifd=ifd1_off)
    if enc["ifd1"]:
        write_ifd("ifd1")
    if enc["exif"]:
        write_ifd("exif")
    if enc["gps"]:
        write_ifd("gps")
    if enc["sub"]:
        write_ifd("sub")
    # external payloads
    for name, rows in enc.items():
        for (tag, typ, count, payload, refs, inline) in rows:
            if not inline:
                while len(out) % 2:
                    out += b"\x00"
                assert len(out) == ext_offs[(name, tag)], "payload offset mismatch"
                raw = bytearray(payload)
                for pos, ref in refs:
                    raw[pos:pos + 4] = ref_map[ref].to_bytes(4, end)
                out += raw
    assert len(out) == pixel_off
    out += pixels
    return bytes(out)


_TYPE_ELEM = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 7: 1}


def cr2_fixture(path, with_leak=True):
    """Minimal Canon CR2 (16-byte header, IFD0 -> IFD1 thumbnail chain)
    with Make/Model + EXIF IFD (MakerNote) + GPS + a raw pixel blob."""
    # StripOffsets is patched by hand after building (the pixel blob's
    # position is only known post-layout)
    data = build_tiff(
        [
            (0x0100, 4, 64), (0x0101, 4, 48), (0x0102, 3, [8, 8, 8]),
            (0x0103, 3, 1), (0x0106, 3, 2),
            (0x010F, 2, "Canon EOS R5" if with_leak else ""),
            (0x0110, 2, "BodySerial1234" if with_leak else ""),
            (0x8769, 4, ("ref", "exif")),
            (0x8825, 4, ("ref", "gps")),
            (0x0111, 4, 0),
            (0x0117, 4, 64 * 48 * 3),
        ],
        exif=[
            (0x9003, 2, "2024:01:02 03:04:05"),
            (0x927C, 7, b"CANONMAKERNOTELEAK"),
        ],
        gps=[(0x0001, 2, "N")],
        ifd1=[(0x010F, 2, "ThumbCam" if with_leak else ""),
              (0x0111, 4, 0), (0x0117, 4, 32)],
        pixels=b"\x01\x02\x03" * (64 * 48),
        cr2=True,
    )
    # patch the real pixel offset into IFD0's StripOffsets entry by
    # finding the tag and overwriting its value field
    bo = "little"
    off = int.from_bytes(data[4:8], bo)
    count = int.from_bytes(data[off:off + 2], bo)
    p = off + 2
    for _ in range(count):
        tag = int.from_bytes(data[p:p + 2], bo)
        if tag == 0x0111:
            vf = p + 8
            # pixel blob starts at len(data) - 64*48*3
            pixel_start = len(data) - 64 * 48 * 3
            data = data[:vf] + pixel_start.to_bytes(4, bo) + data[vf + 4:]
            break
        p += 12
    Path(path).write_bytes(data)
    return Path(path)


def dng_fixture(path, with_leak=True):
    """DNG: TIFF container with DNGVersion, UniqueCameraModel,
    DNGPrivateData, EXIF IFD and a pixel blob."""
    data = build_tiff(
        [
            (0x0100, 4, 16), (0x0101, 4, 12),
            (0x0102, 3, [8, 8, 8]), (0x0103, 3, 1), (0x0106, 3, 2),
            (0x0111, 4, 0), (0x0117, 4, 16 * 12 * 3),
            (0xC612, 3, [1, 4, 0, 0]),          # DNGVersion
            (0xC614, 2, "LeakCamModel" if with_leak else ""),
            (0xC634, 7, b"DNGPRIVATEDATA-LEAK" if with_leak else b""),
            (0x8769, 4, ("ref", "exif")),
        ],
        exif=[(0x9003, 2, "2020:05:06 07:08:09"),
              (0x927C, 7, b"MAKERNOTE-LEAK")],
        pixels=b"\x05\x06\x07" * (16 * 12),
    )
    # fix StripOffsets (placeholder 0) to point at the pixel blob
    bo = "little"
    off = int.from_bytes(data[4:8], bo)
    count = int.from_bytes(data[off:off + 2], bo)
    p = off + 2
    for _ in range(count):
        tag = int.from_bytes(data[p:p + 2], bo)
        if tag == 0x0111:
            pixel_start = len(data) - 16 * 12 * 3
            vf = p + 8
            data = data[:vf] + pixel_start.to_bytes(4, bo) + data[vf + 4:]
            break
        p += 12
    Path(path).write_bytes(data)
    return Path(path)


def tiff_with_ifd_cycle(path):
    """Hostile TIFF: IFD1's next pointer loops back to IFD0. The walker
    must terminate and the surgery must not corrupt the file."""
    data = build_tiff(
        [(0x010F, 2, "LoopCam"), (0x8769, 4, ("ref", "exif"))],
        exif=[(0x9003, 2, "2021:01:01 00:00:00")],
        ifd1=[(0x0131, 2, "LoopSoft")],
        pixels=b"\x0a\x0b\x0c" * 64,
    )
    # point IFD1's next pointer (right after its entries) back at IFD0.
    # Careful with the layout: an IFD block is count(2) + entries + a
    # 4-byte next-pointer — IFD1 starts AFTER IFD0's next-pointer.
    bo = "little"
    ifd0 = int.from_bytes(data[4:8], bo)
    count0 = int.from_bytes(data[ifd0:ifd0 + 2], bo)
    ifd1 = ifd0 + 2 + count0 * 12 + 4      # IFD0's next-pointer field
    ifd1_next = ifd1 + 2 + 1 * 12          # IFD1 has 1 entry
    data = data[:ifd1_next] + ifd0.to_bytes(4, bo) + data[ifd1_next + 4:]
    Path(path).write_bytes(data)
    return Path(path)
