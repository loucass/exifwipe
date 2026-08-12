"""_raf - exifwipe internal module (format/strip machinery)."""

from __future__ import annotations



from lib._config import _RAF_MAGIC
from lib._jpeg import _jpeg_metadata_segments, _strip_jpeg_lossless
from lib._tiff import _tiff_find_identifying, _tiff_parse_header, _tiff_strip_lossless

def _strip_raf_lossless(data: bytes, keep_icc: bool = False):
    """Lossless wipe of a Fuji RAF container: blank the serial + camera
    model + firmware in the header, lossless-strip the embedded JPEG
    preview's EXIF (write back padded, update the length field), and run
    TIFF surgery on the FujiIFD block when it's a parseable TIFF. Returns
    None when the container can't be verified clean (caller refuses)."""
    if data[:16] != _RAF_MAGIC or len(data) < 0x94:
        return None
    out = bytearray(data)
    # header identity: serial + model + firmware (version digits kept)
    out[0x14:0x40] = b"\x00" * (0x40 - 0x14)
    jpos = int.from_bytes(data[0x54:0x58], "big")
    jlen = int.from_bytes(data[0x58:0x5c], "big")
    foff = int.from_bytes(data[0x64:0x68], "big")
    flen = int.from_bytes(data[0x68:0x6c], "big")
    # embedded JPEG preview — this is where camera EXIF lives
    if jpos and jlen and jpos + jlen <= len(data):
        jpeg = bytes(data[jpos:jpos + jlen])
        if jpeg[:2] != b"\xff\xd8":
            return None         # preview exists but isn't a JPEG — refuse
        stripped = _strip_jpeg_lossless(jpeg, keep_icc)
        if stripped is None:
            return None
        if stripped != jpeg:
            if len(stripped) > jlen:
                return None     # can't grow in place — refuse
            out[jpos:jpos + len(stripped)] = stripped
            if len(stripped) < jlen:
                out[jpos + len(stripped):jpos + jlen] = b"\x00" * (jlen - len(stripped))
            out[0x58:0x5c] = len(stripped).to_bytes(4, "big")
    # FujiIFD TIFF block (only some models; self-contained TIFF whose
    # internal offsets are relative to the block start)
    if foff and flen and foff + flen <= len(data):
        region = bytes(out[foff:foff + flen])
        if region[:2] in (b"II", b"MM") and _tiff_parse_header(region):
            surg = _tiff_strip_lossless(region, keep_icc)
            if surg is None:
                return None     # TIFF-looking block we can't verify — refuse
            out[foff:foff + flen] = surg
    cleaned = bytes(out)
    # self-verify before handing it out — a wipe that still leaks is not
    # a wipe
    jpos2 = int.from_bytes(cleaned[0x54:0x58], "big")
    jlen2 = int.from_bytes(cleaned[0x58:0x5c], "big")
    if jpos2 and jlen2 and jpos2 + jlen2 <= len(cleaned):
        if _jpeg_metadata_segments(bytes(cleaned[jpos2:jpos2 + jlen2]), keep_icc):
            raise RuntimeError("RAF embedded JPEG still carries metadata "
                               "— refusing to write a dirty file")
    foff2 = int.from_bytes(cleaned[0x64:0x68], "big")
    flen2 = int.from_bytes(cleaned[0x68:0x6c], "big")
    if foff2 and flen2 and foff2 + flen2 <= len(cleaned):
        reg2 = bytes(cleaned[foff2:foff2 + flen2])
        if reg2[:2] in (b"II", b"MM") and _tiff_parse_header(reg2):
            if _tiff_find_identifying(reg2):
                raise RuntimeError("RAF FujiIFD still carries identifying "
                                   "metadata — refusing to write a dirty file")
    return cleaned

