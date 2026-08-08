"""_png - exifwipe internal module (format/strip machinery)."""

from __future__ import annotations



from _config import _PNG_SIG

def _png_is_animated(data: bytes) -> bool:
    """True when the PNG stream carries an acTL (animation control) chunk."""
    if data[:8] != _PNG_SIG:
        return False
    pos, n = 8, len(data)
    while pos + 8 <= n:
        clen = int.from_bytes(data[pos:pos + 4], "big")
        if pos + 12 + clen > n:
            break
        ctype = data[pos + 4:pos + 8]
        if ctype == b"acTL":
            return True
        if ctype == b"IDAT":
            break          # acTL must precede the image data
        pos += 12 + clen
    return False


def _strip_png_lossless(data: bytes):
    """Drop PNG metadata chunks (tEXt/zTXt/iTXt/eXIf/iCCP/pHYs) and
    anything after IEND, keeping every other chunk — including the acTL /
    fcTL / fdAT animation blocks and IDAT pixel data — byte-identical.
    Returns None when the chunk stream is malformed."""
    if data[:8] != _PNG_SIG:
        return None
    DROP = {b"tEXt", b"zTXt", b"iTXt", b"eXIf", b"iCCP", b"pHYs"}
    out = bytearray(data[:8])
    pos, n = 8, len(data)
    iend = False
    while pos + 8 <= n:
        clen = int.from_bytes(data[pos:pos + 4], "big")
        if clen > n or pos + 12 + clen > n:
            return None
        ctype = data[pos + 4:pos + 8]
        if ctype == b"IEND":
            out += data[pos:pos + 12 + clen]
            iend = True
            break
        if ctype not in DROP:
            out += data[pos:pos + 12 + clen]
        pos += 12 + clen
    if not iend:
        return None
    return bytes(out)

