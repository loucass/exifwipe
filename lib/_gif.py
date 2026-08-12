"""_gif - exifwipe internal module (format/strip machinery)."""

from __future__ import annotations



def _strip_gif_lossless(data: bytes):
    """Rewrite a GIF stream, dropping comment blocks (0x21 0xFE) and
    XMP application extensions (0x21 0xFF carrying 'XMP Data') anywhere
    in the block stream — before, between and after image frames. Every
    frame descriptor, palette, transparency, disposal and loop count is
    copied byte-identical. Bytes after the trailer are dropped. Returns
    None if the stream doesn't parse (caller falls back to a rebuild).

    GIF blocks that can carry metadata:
      0x21 0xFE ...   comment extension              — dropped
      0x21 0xFF ...   application extension          — dropped if it
                        carries XMP; NETSCAPE loop kept
      0x21 0xF9 ...   graphic control (disposal + transparency) — kept
      0x2C ...        image descriptor + pixel data  — kept verbatim
      0x3B ...        trailer                        — end of file
    """
    if data[:6] not in (b"GIF87a", b"GIF89a"):
        return None
    n = len(data)
    out = bytearray(data[:6])
    i = 6
    if i + 7 > n:
        return None
    lsdesc = data[i:i + 7]
    out += lsdesc
    i += 7
    if lsdesc[4] & 0x80:                    # global color table
        gct_size = 3 * (2 ** ((lsdesc[4] & 0x07) + 1))
        if i + gct_size > n:
            return None
        out += data[i:i + gct_size]
        i += gct_size

    while i < n:
        b = data[i]
        if b == 0x3B:                       # trailer — official end
            out += b"\x3b"
            return bytes(out)
        if b == 0x2C:                       # image descriptor
            if i + 10 > n:
                return None
            packed = data[i + 9]
            out += data[i:i + 10]
            i += 10
            if packed & 0x80:               # local color table
                lct_size = 3 * (2 ** ((packed & 0x07) + 1))
                if i + lct_size > n:
                    return None
                out += data[i:i + lct_size]
                i += lct_size
            if i >= n:
                return None
            out += data[i:i + 1]            # LZW minimum code size
            i += 1
            i = _copy_gif_subblocks(data, i, out)   # pixel data, verbatim
            if i is None:
                return None
            continue
        if b == 0x21:                       # extension
            if i + 2 > n:
                return None
            label = data[i + 1]
            start = i
            end = _skip_gif_subblocks(data, i + 2)
            if end is None:
                return None
            if label == 0xFE:
                i = end                     # comment — dropped
                continue
            block = data[start:end]
            if label == 0xFF and b"XMP Data" in block:
                i = end                     # XMP application ext — dropped
                continue
            out += block                    # GCE / NETSCAPE / others — kept
            i = end
            continue
        return None                         # unknown top-level byte
    return bytes(out)


def _skip_gif_subblocks(data: bytes, idx: int):
    """Return index just past a GIF sub-block chain; None if malformed."""
    n = len(data)
    while True:
        if idx >= n:
            return None
        size = data[idx]
        if size == 0:
            return idx + 1
        if idx + 1 + size > n:
            return None
        idx += 1 + size


def _copy_gif_subblocks(data: bytes, idx: int, out: bytearray):
    """Copy a GIF sub-block chain (pixel data) verbatim into `out`.
    Returns the index just past the chain; None if malformed."""
    n = len(data)
    while True:
        if idx >= n:
            return None
        size = data[idx]
        if idx + 1 + size > n:
            return None
        out += data[idx:idx + 1 + size]
        idx += 1 + size
        if size == 0:
            return idx

