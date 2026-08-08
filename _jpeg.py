"""_jpeg - exifwipe internal module (format/strip machinery)."""

from __future__ import annotations



import io
from typing import Optional
from PIL import Image

from _pixels import _apply_orientation, _perturb_image, _rebuild_frame

def _jpeg_orientation_from_bytes(data: bytes) -> Optional[int]:
    """EXIF Orientation (0x0112, IFD0) read straight off the APP1 segment
    — no pixel decode, no Pillow open. Returns 1 when there's no
    rotation (or no EXIF at all), None only when the stream isn't a
    JPEG. This is what lets the common JPEG case skip decode entirely."""
    if data[:2] != b"\xff\xd8":
        return None
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
        if marker in (0xDA, 0xD9):
            break
        if i + 2 > n:
            break
        seg_len = int.from_bytes(data[i:i + 2], "big")
        if seg_len < 2 or i + seg_len > n:
            break
        payload = data[i + 2:i + seg_len]
        if marker == 0xE1 and payload.startswith(b"Exif\x00\x00"):
            tiff = payload[6:]
            bo = ("little" if tiff[:2] == b"II"
                  else "big" if tiff[:2] == b"MM" else None)
            if bo and len(tiff) >= 10 and int.from_bytes(tiff[2:4], bo) == 42:
                ifd0 = int.from_bytes(tiff[4:8], bo)
                if ifd0 + 2 <= len(tiff):
                    cnt = int.from_bytes(tiff[ifd0:ifd0 + 2], bo)
                    p = ifd0 + 2
                    for _ in range(min(cnt, 512)):
                        if p + 12 > len(tiff):
                            break
                        tag = int.from_bytes(tiff[p:p + 2], bo)
                        typ = int.from_bytes(tiff[p + 2:p + 4], bo)
                        if tag == 0x0112 and typ == 3:
                            return int.from_bytes(tiff[p + 8:p + 10], bo) or 1
                        p += 12
            break
        i += seg_len
    return 1


def _jpeg_sof_size(data: bytes):
    """(width, height) from the first SOF marker, without decoding pixels
    (the bomb guard wants dimensions, not a full decode)."""
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
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            if i + 7 > n:
                return None
            h = int.from_bytes(data[i + 3:i + 5], "big")
            w = int.from_bytes(data[i + 5:i + 7], "big")
            return (w, h)
        if i + 2 > n:
            break
        seg_len = int.from_bytes(data[i:i + 2], "big")
        if seg_len < 2:
            break
        i += seg_len
    return None


def _orientation_is_neutral(img) -> bool:
    """True when the image carries no rotation (or EXIF at all)."""
    try:
        if not hasattr(img, "getexif"):
            return True
        return int(img.getexif().get(0x0112, 1) or 1) == 1
    except Exception:
        # can't read EXIF -> assume no orientation to honor
        return True


def _entropy_marker_index(data: bytes, j: int) -> int:
    """From inside entropy-coded data, find the FF-run that precedes the
    next real marker (handles FF 00 stuffing and RSTn). Returns the index
    of the last FF of that run, or len(data) at EOF."""
    n = len(data)
    while j < n:
        if data[j] != 0xFF:
            j += 1
            continue
        k = j
        while k < n and data[k] == 0xFF:
            k += 1
        if k >= n:
            return n
        nxt = data[k]
        if nxt == 0x00 or 0xD0 <= nxt <= 0xD7:
            j = k + 1
            continue
        return k - 1
    return n


def _split_jpeg_frames(data: bytes) -> list:
    """Split a (possibly multi-frame) JPEG into SOI..EOI byte strings by
    walking markers and skipping entropy-coded data. Tolerates garbage
    between frames; a frame without an EOI runs to EOF. Returns [] on
    input that doesn't even start with a SOI."""
    frames = []
    i, n = 0, len(data)
    while i < n:
        if data[i:i + 2] != b"\xff\xd8":
            nxt = data.find(b"\xff\xd8", i, min(i + 64, n))
            if nxt == -1:
                break
            i = nxt
        start = i
        j = i + 2
        eoi = None
        while j < n:
            while j < n and data[j] != 0xFF:
                j += 1
            while j < n and data[j] == 0xFF:
                j += 1
            if j >= n:
                break
            marker = data[j]
            j += 1
            if marker == 0xD9:
                eoi = j
                break
            if marker == 0xDA:
                j = _entropy_marker_index(data, j)
                continue
            if 0xD0 <= marker <= 0xD7 or marker == 0x01:
                continue
            if j + 2 > n:
                break
            seg_len = int.from_bytes(data[j:j + 2], "big")
            j += 2 + max(seg_len - 2, 0)
        frames.append(data[start:eoi if eoi is not None else n])
        if eoi is None:
            break
        i = eoi
    return frames


def _jpeg_metadata_segments(data: bytes, keep_icc: bool = False) -> list:
    """Names of every non-structural APPn/COM segment in every frame
    (JFIF APP0 and ICC APP2 — when keep_icc — are structural)."""
    found = []
    for frame in _split_jpeg_frames(data):
        i, n = 2, len(frame)
        while i + 4 <= n:
            if frame[i] != 0xFF:
                break
            while i < n and frame[i] == 0xFF:
                i += 1
            if i >= n:
                break
            marker = frame[i]
            i += 1
            if marker == 0xDA or marker == 0xD9:
                break
            if i + 2 > n:
                break
            seg_len = int.from_bytes(frame[i:i + 2], "big")
            if seg_len < 2 or i + seg_len > n:
                break
            payload = frame[i + 2:i + seg_len]
            if marker == 0xFE:
                found.append("COM")
            elif 0xE0 <= marker <= 0xEF:
                if marker == 0xE0 and payload.startswith(b"JFIF"):
                    pass
                elif marker == 0xE2 and keep_icc and payload.startswith(b"ICC_PROFILE\x00"):
                    pass
                else:
                    name = payload[:8].split(b"\x00")[0].decode(errors="replace")
                    found.append(f"APP{marker - 0xE0}:{name or hex(marker)}")
            i += seg_len
    return found


def _jpeg_final_check(cleaned: bytes, keep_icc: bool = False) -> bytes:
    """Round-trip verify, JPEG only. If any metadata segment survived the
    wipe (a re-encode can sneak segments back in), re-run the lossless
    stripper — and if THAT still leaves something, fail loudly instead of
    handing back a dirty file.

    (The old implementation leaned on piexif.remove(), which with
    piexif 1.1.3 raises ValueError on bytes input — the exception was
    swallowed, and the re-wipe never ran. The safety net was dead code.)"""
    leftovers = _jpeg_metadata_segments(cleaned, keep_icc)
    if not leftovers:
        return cleaned
    rewiped = _strip_jpeg_lossless(cleaned, keep_icc)
    if rewiped is not None and not _jpeg_metadata_segments(rewiped, keep_icc):
        return rewiped
    raise RuntimeError(
        "JPEG final check failed: metadata segments survived rewrite: "
        + ", ".join(leftovers)
    )


def _rebuild_jpeg_from_img(img, keep_icc: bool = False, perturb=None,
                           seed: int = 0) -> bytes:
    """Bake orientation into pixels, rebuild a clean q95 JPEG frame."""
    img = _apply_orientation(img, strict=True)
    mode = img.mode
    if mode not in ("RGB", "RGBA", "L"):
        mode = "RGBA" if ("A" in mode or mode == "P") else "RGB"
        img = img.convert(mode)
    clean = _rebuild_frame(img, mode)
    if perturb:
        clean = _perturb_image(clean, seed, perturb)
    icc = b""
    if keep_icc:
        try:
            icc = img.info.get("icc_profile", b"") or b""
        except Exception:
            icc = b""
    buf = io.BytesIO()
    clean.save(buf, format="JPEG", quality=95, optimize=True, exif=b"",
               progressive=False, icc_profile=icc or None)
    return _jpeg_final_check(buf.getvalue(), keep_icc)


def _strip_mpo_rotated_first(raw: bytes, img, keep_icc: bool = False,
                             perturb=None, seed: int = 0):
    """Multi-frame JPEG whose FIRST frame carries a rotation: re-encode
    frame 0 with the rotation baked in, then lossless-strip the remaining
    frames so no frame is ever silently dropped. Returns None when the
    stream can't be split (caller must refuse loudly, not guess)."""
    frames = _split_jpeg_frames(raw)
    if len(frames) < 2:
        return None
    f0 = frames[0]
    rest = raw[len(f0):]
    try:
        img.seek(0)
        clean0 = _rebuild_jpeg_from_img(img, keep_icc, perturb, seed)
    except Exception as e:
        raise RuntimeError(
            f"multi-frame JPEG needs rotation and frame 0 could not be "
            f"re-encoded ({e}) — refusing to drop the other frames") from e
    if rest:
        rest_clean = _strip_jpeg_lossless(rest, keep_icc)
        if rest_clean is None:
            raise RuntimeError(
                "multi-frame JPEG: trailing frames could not be parsed "
                "losslessly — refusing to drop them")
        return clean0 + rest_clean
    return clean0


def _strip_jpeg_lossless(data: bytes, keep_icc: bool = False):
    """Rewrite a JPEG marker stream, dropping every APPn / COM segment
    (EXIF, XMP, Photoshop, ICC unless keep_icc). Entropy-coded pixel
    data is copied verbatim — no re-encode, no quality loss.

    Handles multi-frame images (MPO et al.) by parsing each SOI..EOI
    pair, and drops any trailing garbage after the final EOI (bytes
    appended past the end of the image, e.g. by file-carving tools).

    Returns None if the stream doesn't parse as a normal JPEG (caller
    then falls back to the pixel-rebuild path)."""
    if data[:2] != b"\xff\xd8":
        return None
    n = len(data)
    out = bytearray()
    i = 0
    saw_frame = False

    def scan_entropy(j: int) -> int:
        """Copy entropy-coded bytes verbatim until the next real
        marker. Returns the index of that marker (which the outer
        loop then processes). Handles FF 00 stuffing and RSTn.

        `start` tracks the first unconsumed entropy byte so every byte
        up to a marker's FF-run is copied out — the classic bug here is
        advancing past non-FF bytes without copying them, which emits a
        structurally valid JPEG whose pixels are gone."""
        nonlocal out
        start = j
        while j < n:
            if data[j] != 0xFF:
                j += 1
                continue
            k = j
            while k < n and data[k] == 0xFF:
                k += 1
            if k >= n:                      # run of FF to EOF — truncated
                out += data[start:k]
                return n
            nxt = data[k]
            if nxt == 0x00 or 0xD0 <= nxt <= 0xD7:
                # stuffed FF 00, or RSTn restart marker — part of the
                # entropy stream, keep byte-exact
                out += data[start:k + 1]
                start = j = k + 1
                continue
            # first real marker after entropy — the FF-run is the
            # marker's padding and is emitted by the outer loop, so the
            # entropy copy must stop BEFORE the run (copying it would
            # duplicate the FFs and break byte-exactness)
            out += data[start:j]
            return j
        out += data[start:j]                # entropy runs to EOF — truncated
        return n

    while i < n:
        if data[i] != 0xFF:
            # non-marker byte — either trailing garbage after the final
            # EOI (file-carving residue, drop it) or a stray byte between
            # MPO frames. Peek a bounded distance for a new SOI; if one
            # appears, skip the junk and keep parsing so no frame is lost.
            nxt = data.find(b"\xff\xd8", i, min(i + 64, n))
            if nxt == -1:
                break
            i = nxt
            continue
        while i < n and data[i] == 0xFF:
            i += 1
        if i >= n:
            break
        marker = data[i]
        i += 1
        if marker == 0xD8:          # SOI — start of a frame
            out += b"\xff\xd8"
            saw_frame = True
            continue
        if marker == 0xD9:          # EOI
            out += b"\xff\xd9"
            continue
        if 0xD0 <= marker <= 0xD7 or marker == 0x01:
            continue                # RSTn / TEM, only valid inside entropy
        if i + 2 > n:
            continue                # truncated segment header
        seg_len = int.from_bytes(data[i:i + 2], "big")
        if seg_len < 2 or i + seg_len > n:
            continue
        payload = data[i + 2:i + seg_len]
        if marker == 0xDA:          # SOS — entropy-coded data follows
            out += b"\xff\xda" + data[i:i + seg_len]
            i = scan_entropy(i + seg_len)
            continue
        keep = True
        if 0xE0 <= marker <= 0xEF:  # APP0..APP15
            keep = (
                (marker == 0xE0 and payload.startswith(b"JFIF"))      # JFIF density block
                or (marker == 0xE2 and keep_icc
                    and payload.startswith(b"ICC_PROFILE\x00"))        # ICC, opt-in only
            )
        elif marker == 0xFE:        # COM comment
            keep = False
        if keep:
            out += b"\xff" + bytes([marker]) + data[i:i + seg_len]
        i += seg_len
    if not saw_frame:
        return None
    return bytes(out)

