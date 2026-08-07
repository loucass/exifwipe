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
def jpeg_with_exif(path, orient=1, progressive=False, icc=False, quality=90):
    """A 96x64 JPEG with Make/Model/Copyright/UserComment/GPS EXIF."""
    img = Image.new("RGB", (96, 64), (200, 30, 30))
    exif = piexif.dump({
        "0th": {0x010F: b"AttackerCam", 0x0112: orient, 0x0131: b"AcmeFW",
                0x8298: b"LeakCopyright"},
        "Exif": {0x9003: b"2024:01:02 03:04:05", 0x9286: b"LeakUserComment"},
        "GPS": {1: b"N", 2: ((37, 1), (30, 1), (0, 1))},
    })
    kw = {"format": "JPEG", "exif": exif, "quality": quality}
    if icc:
        kw["icc_profile"] = b"fake-icc-profile-data-" * 4
    if progressive:
        kw["progressive"] = True
    img.save(path, **kw)
    return Path(path)


def png_with_metadata(path):
    """PNG with tEXt, iTXt, eXIf and iCCP chunks."""
    img = Image.new("RGBA", (40, 30), (10, 200, 30, 255))
    meta = PngInfo()
    meta.add_text("Comment", "leaky comment")
    meta.add_text("Software", "leaky software")
    meta.add_itxt("International", "leaky iTXt", "xml:lang")
    exif = piexif.dump({"0th": {0x010F: b"LeakCam"}})
    img.save(path, pnginfo=meta, exif=exif, icc_profile=b"leak-icc")
    return Path(path)


def animated_gif(path, frames=3, comment_payload=b"hi there",
                 xmp=True, loop=0):
    """Animated GIF; comment + XMP app-ext are spliced in right before the
    trailer (the position that used to leak), keeping the stream valid."""
    imgs = [Image.new("RGB", (12, 12), (i * 60 % 255, 30, 40))
            for i in range(frames)]
    buf = io.BytesIO()
    imgs[0].save(buf, format="GIF", save_all=True, append_images=imgs[1:],
                 duration=[80 + i * 10 for i in range(frames)], loop=loop)
    data = bytearray(buf.getvalue())
    trailer = find_gif_trailer(data)
    assert trailer is not None, "could not locate GIF trailer"
    payload = bytearray()
    if comment_payload is not None:
        payload += b"\x21\xfe" + _subblocks(comment_payload)
    if xmp:
        payload += b"\x21\xff" + _subblocks(b"XMP DataXMP") + _subblocks(b"<x:xmpmeta>leak</x:xmpmeta>")
    data[trailer:trailer] = payload
    Path(path).write_bytes(bytes(data))
    return Path(path)


def animated_webp(path, frames=3, with_exif=True, with_xmp=True):
    imgs = [Image.new("RGBA", (24, 18), (255, i * 60, 0, 255)) for i in range(frames)]
    kw = {"save_all": True, "append_images": imgs[1:],
          "duration": [100, 110, 120], "loop": 0}
    if with_exif:
        kw["exif"] = piexif.dump({"0th": {0x010F: b"LeakCam"}})
    if with_xmp:
        kw["xmp"] = b"<x:xmpmeta>leak-xmp</x:xmpmeta>"
    imgs[0].save(path, format="WEBP", **kw)
    return Path(path)


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


def mpo_jpeg(path, second_exif=True):
    """Two JPEGs concatenated (fake MPO); 2nd carries EXIF."""
    a = io.BytesIO()
    b = io.BytesIO()
    Image.new("RGB", (32, 24), (200, 0, 0)).save(a, format="JPEG")
    exif2 = piexif.dump({"0th": {0x0112: 1}, "Exif": {0x9286: b"LeakMe2"}})
    Image.new("RGB", (32, 24), (0, 200, 0)).save(b, format="JPEG", exif=exif2)
    Path(path).write_bytes(a.getvalue() + b.getvalue())
    return Path(path)


# --------------------------------------------------------------------------- #
# forensic scanners (independent of exifwipe)
# --------------------------------------------------------------------------- #
def _subblocks(payload: bytes) -> bytes:
    chunks = []
    for i in range(0, len(payload), 200):
        chunk = payload[i:i + 200]
        chunks.append(bytes([len(chunk)]) + chunk)
    chunks.append(b"\x00")
    return b"".join(chunks)


def find_gif_trailer(data: bytes):
    """Return the index of the GIF trailer byte (0x3B) by walking the
    block stream — the first 0x3B inside LZW data is NOT the trailer."""
    n = len(data)
    i = 6
    if i + 7 > n:
        return None
    lsdesc = data[i:i + 7]
    i += 7
    if lsdesc[4] & 0x80:
        i += 3 * (2 ** ((lsdesc[4] & 0x07) + 1))
    while i < n:
        b = data[i]
        if b == 0x3B:
            return i
        if b == 0x2C:
            packed = data[i + 9]
            i += 10
            if packed & 0x80:
                i += 3 * (2 ** ((packed & 0x07) + 1))
            i += 1  # LZW min code size
            while i < n:
                size = data[i]
                i += 1 + size
                if size == 0:
                    break
            continue
        if b == 0x21:
            i += 2
            while i < n:
                size = data[i]
                i += 1 + size
                if size == 0:
                    break
            continue
        return None
    return None


def jpeg_segments(data: bytes):
    """Return [(marker_byte, name)] for every APPn/COM in a JPEG."""
    out = []
    i, n = 2, len(data)
    while i + 4 <= n:
        if data[i] != 0xFF:
            break
        while i < n and data[i] == 0xFF:
            i += 1
        if i >= n:
            break
        marker = data[i]
        i += 1
        if marker == 0xDA:
            break
        if marker == 0xD9:
            break
        seg_len = int.from_bytes(data[i:i + 2], "big")
        if seg_len < 2 or i + seg_len > n:
            break
        payload = data[i + 2:i + seg_len]
        if marker == 0xFE:
            out.append((0xFE, "COM"))
        elif 0xE0 <= marker <= 0xEF:
            name = payload[:8].split(b"\x00")[0].decode(errors="replace")
            out.append((marker, f"APP{marker - 0xE0}:{name}"))
        i += seg_len
    return out


def png_chunks(data: bytes):
    out = []
    pos = 8
    n = len(data)
    while pos + 8 <= n:
        clen = int.from_bytes(data[pos:pos + 4], "big")
        ctype = data[pos + 4:pos + 8]
        out.append(ctype.decode(errors="replace"))
        if ctype == b"IEND":
            break
        pos += 12 + clen
    return out


def assert_jpeg_clean(data: bytes, leak_strings=("Leak", "AttackerCam", "AcmeFW")):
    assert data[:2] == b"\xff\xd8", "output is not a JPEG"
    # no EXIF via piexif
    ifd = piexif.load(data)
    for k, v in ifd.items():
        if k == "thumbnail":
            continue
        assert not v, f"EXIF IFD {k} not empty after wipe: {v}"
    # no identifying APP segments (JFIF structural APP0 allowed)
    segs = jpeg_segments(data)
    for marker, name in segs:
        if marker == 0xE0 and name.startswith("APP0:JFIF"):
            continue  # structural
        assert False, f"metadata segment survived: {name}"
    for s in leak_strings:
        assert s.encode() not in data, f"leak string {s!r} still in output"


def assert_png_clean(data: bytes, leak_strings=("leak", "LeakCam")):
    chunks = png_chunks(data)
    assert "IEND" in chunks, "not a PNG"
    for c in ("tEXt", "zTXt", "iTXt", "eXIf", "iCCP"):
        assert c not in chunks, f"metadata chunk survived: {c}"
    for s in leak_strings:
        assert s.encode() not in data, f"leak string {s!r} still in output"


def assert_gif_clean(data: bytes, leak_strings=(b"hi there", b"leak")):
    assert data[:6] in (b"GIF87a", b"GIF89a")
    assert b"\x21\xfe" not in data, "comment extension survived"
    for s in leak_strings:
        assert s not in data, f"leak payload {s!r} survived"


def assert_webp_clean(data: bytes, leak_strings=(b"LeakCam", b"leak-xmp")):
    assert data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    pos, n = 12, len(data)
    while pos + 8 <= n:
        tag = data[pos:pos + 4]
        size = int.from_bytes(data[pos + 4:pos + 8], "little")
        assert tag not in (b"EXIF", b"XMP "), f"metadata chunk survived: {tag}"
        if size > n:
            break
        pos += 8 + size + (size & 1)
    for s in leak_strings:
        assert s not in data, f"leak payload {s!r} survived"


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


def animated_png(path, frames=3):
    """APNG with 3 frames and a tEXt metadata chunk."""
    imgs = [Image.new("RGBA", (20, 14), (255, i * 70, 0, 255))
            for i in range(frames)]
    meta = PngInfo()
    meta.add_text("Comment", "apng-leak")
    imgs[0].save(path, format="PNG", save_all=True, append_images=imgs[1:],
                 duration=[90, 100, 110], loop=0, pnginfo=meta)
    return Path(path)


def lossless_webp(path):
    """Lossless WebP with EXIF/XMP chunks."""
    img = Image.new("RGBA", (26, 18), (10, 200, 30, 255))
    img.save(path, format="WEBP", lossless=True, quality=100,
             exif=b"\x00\x00\x00\x00lossless-leak",
             xmp=b"<x:xmpmeta>lossless-xmp</x:xmpmeta>")
    return Path(path)


def mpo_rotated_first(path):
    """Multi-frame JPEG whose FIRST frame carries orientation 6 (the
    round-2 case that silently deleted frame 2)."""
    a = io.BytesIO()
    b = io.BytesIO()
    exif_a = piexif.dump({"0th": {0x010F: b"CamA", 0x0112: 6}})
    Image.new("RGB", (40, 24), (200, 0, 0)).save(a, format="JPEG", exif=exif_a)
    exif_b = piexif.dump({"0th": {0x0112: 1}, "Exif": {0x9286: b"Frame2Leak"}})
    Image.new("RGB", (40, 24), (0, 200, 0)).save(b, format="JPEG", exif=exif_b)
    Path(path).write_bytes(a.getvalue() + b.getvalue())
    return Path(path)


def heic_fixture(path, exif=True, xmp=True, avif=False):
    """HEIC/AVIF with EXIF + XMP items via pillow-heif. Returns None when
    pillow-heif (or its libheif) isn't available so tests can skip."""
    try:
        import pillow_heif
        for _reg in ("register_heif_opener", "register_avif_opener"):
            _fn = getattr(pillow_heif, _reg, None)
            if _fn:
                try:
                    _fn()
                except Exception:
                    pass
    except ImportError:
        return None
    img = Image.new("RGB", (32, 24), (200, 30, 30))
    kw = {}
    if exif:
        kw["exif"] = piexif.dump({"0th": {0x010F: b"HEIFCAMLEAK"},
                                   "Exif": {0x9003: b"2024:01:02 03:04:05"}})
    if xmp:
        kw["xmp"] = b"<x:xmpmeta>heif-xmp-leak</x:xmpmeta>"
    img.save(path, format="AVIF" if avif else "HEIF", **kw)
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
