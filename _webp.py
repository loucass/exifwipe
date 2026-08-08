"""_webp - exifwipe internal module (format/strip machinery)."""

from __future__ import annotations



def _webp_is_lossless(data: bytes) -> bool:
    """True when a WebP's image data is a VP8L (lossless) chunk rather
    than a VP8 (lossy) chunk. VP8X containers carry the VP8L/VP8 chunk
    as a top-level sibling, so one flat chunk scan suffices."""
    if data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return False
    pos, n = 12, len(data)
    while pos + 8 <= n:
        tag = data[pos:pos + 4]
        size = int.from_bytes(data[pos + 4:pos + 8], "little")
        if size > n:
            break
        if tag == b"VP8L":
            return True
        if tag == b"VP8 ":
            return False
        pos += 8 + size + (size & 1)
    return False

