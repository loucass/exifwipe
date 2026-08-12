"""_driver - exifwipe internal module (format/strip machinery)."""

from __future__ import annotations



import argparse
import io
import sys
from pathlib import Path
from typing import Iterable, Optional
from PIL import Image

from lib._color import c_dim, c_err, c_head, c_info, c_ok, c_warn
from lib._config import DEFAULT_MAX_PIXELS, IMAGE_FORMATS, RAW_FORMATS, R_ERR, R_OK, R_SKIP
from lib._gif import _strip_gif_lossless
from lib._heif import _strip_heif_lossless
from lib._inspect import inspect_image
from lib._jpeg import _jpeg_final_check, _jpeg_orientation_from_bytes, _jpeg_sof_size, _rebuild_jpeg_from_img, _strip_jpeg_lossless, _strip_mpo_rotated_first
from lib._pdf import strip_pdf_bytes
from lib._pixels import _apply_orientation, _perturb_image, _perturb_seed, _rebuild_frame, _strip_multiframe
from lib._png import _png_is_animated, _strip_png_lossless
from lib._raf import _strip_raf_lossless
from lib._report import _inventory_metadata, _print_report
from lib._sniff import _sniff_bytes, _sniff_format
from lib._tiff import _is_tiff_family, _tiff_strip_lossless
from lib._webp import _webp_is_lossless
from lib._write import _atomic_write_bytes, write_output

try:
    import pillow_heif
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            from PIL import features
            heif_supported = features.check("heif")
        except Exception:
            heif_supported = False
    if not heif_supported:
        register = getattr(pillow_heif, "register_heif_opener", None)
        if register:
            register()
        register_avif = getattr(pillow_heif, "register_avif_opener", None)
        if register_avif:
            register_avif()
except ImportError:
    pillow_heif = None
from PIL.PngImagePlugin import PngInfo

def strip_image_bytes(path: Path, keep_icc: bool = False,
                      max_pixels: Optional[int] = None,
                      report: Optional[list] = None,
                      drop_orientation: bool = False,
                      perturb: Optional[int] = None) -> tuple[bytes, str]:
    """Strip metadata, keeping pixels as close to byte-identical as the
    format allows.

    JPEG (orientation-neutral): rewrite the marker stream — drop every
    APPn/COM segment (EXIF, XMP, Photoshop, ICC unless --keep-icc),
    keep the entropy-coded pixel data verbatim. No re-encode, no loss —
    and no pixel decode at all: orientation + dimensions come straight
    off the marker stream, so the common case never touches pixels.
    Multi-frame streams (MPO) and trailing garbage after EOI are handled.

    JPEG (needs rotation) and everything else: bake the rotation (if
    any) into the pixels, then rebuild into a brand-new frame with an
    empty metadata block. The rebuild is tiled so memory stays bounded
    no matter the megapixel count.

    GIF: lossless byte-level rewrite first — drops comment + XMP
    application extensions anywhere in the block stream and keeps every
    frame, palette, transparency, disposal and the loop count
    byte-exact. Falls back to a pixel rebuild if the stream is malformed.

    TIFF family (incl. DNG/RAW when they reach this path): lossless
    in-place IFD surgery — pixels byte-identical, pages kept.

    Animated GIF / APNG / multipage TIFF / animated WebP keep every
    frame, timing and loop (APNG + lossless WebP are stripped losslessly).
    Animated AVIF is refused loudly.

    `max_pixels` guards against decompression bombs: images larger than
    the limit (per frame, and a cumulative budget across animation
    frames) are refused loudly instead of being decoded into RAM.
    `drop_orientation` additionally blanks the RAW/TIFF Orientation tag
    (kept by default: display-only, sensor pixels can't be re-rotated).
    `perturb` (1-4) applies deterministic low-amplitude noise to rebuilt
    pixels so reverse-image search can't match the original — opt-in,
    and it does change pixels slightly. `report` (optional list)
    collects the names of every metadata field this wipe removed.

    Returns (clean_bytes, output_format_lowercase).
    """
    if max_pixels is None:
        max_pixels = DEFAULT_MAX_PIXELS
    raw = path.read_bytes()
    sf = _sniff_bytes(raw)
    if report is not None:
        report.extend(_inventory_metadata(raw, sf, keep_icc, drop_orientation))
    # TIFF family -> lossless in-place surgery. NEVER re-encode sensor
    # data: every axis favors the surgery (pixels byte-identical, pages
    # kept, no encode cost).
    if raw[:4] in (b"II*\x00", b"MM\x00*") and _is_tiff_family(raw):
        surg = _tiff_strip_lossless(raw, keep_icc, drop_orientation)
        if surg is not None:
            return surg, "tiff"
        # unparseable TIFF: fall through to Pillow's rebuild as a last resort

    # JPEG family -> fast path: orientation and dimensions straight from
    # the marker stream. Orientation-neutral JPEGs are stripped without
    # a single pixel being decoded — the old code decoded the whole
    # photo just to check a tag it could read from the APP1 bytes.
    if raw[:2] == b"\xff\xd8":
        orient = _jpeg_orientation_from_bytes(raw)
        n_frames = raw.count(b"\xff\xd8")
        seed = _perturb_seed(path, raw) if perturb else 0
        # bomb guard without decoding: dimensions come off the SOF marker
        dims = _jpeg_sof_size(raw)
        if max_pixels and dims and dims[0] * dims[1] > max_pixels:
            raise RuntimeError(
                f"refusing to process {dims[0]}x{dims[1]} = "
                f"{dims[0]*dims[1]:,} pixels (limit {max_pixels:,}); "
                "pass --max-pixels N to raise the limit (memory risk)")
        if orient != 1 and n_frames > 1:
            # rotated multi-frame (MPO): bake frame 0's rotation, keep
            # every other frame lossless — NEVER drop them
            with Image.open(path) as img:
                if max_pixels and (img.size[0] * img.size[1] * n_frames
                                   > max_pixels * 8):
                    raise RuntimeError(
                        f"refusing: ~{img.size[0]*img.size[1]*n_frames:,} "
                        f"total pixels across {n_frames} frames "
                        f"(cumulative limit {max_pixels*8:,})")
                mpo = _strip_mpo_rotated_first(raw, img, keep_icc,
                                               perturb, seed)
                if mpo is None:
                    raise RuntimeError(
                        "multi-frame JPEG needs rotation but its frames "
                        "could not be split — refusing to drop them")
                return mpo, "jpeg"
        if orient == 1 and not perturb:
            lossless = _strip_jpeg_lossless(raw, keep_icc)
            if lossless is not None:
                return _jpeg_final_check(lossless, keep_icc), "jpeg"
        # single-frame rotation to bake (or --perturb): pixel rebuild
        with Image.open(path) as img:
            img.load()
            w, h = img.size
            if max_pixels and w * h > max_pixels:
                raise RuntimeError(
                    f"refusing to process {w}x{h} = {w*h:,} pixels "
                    f"(limit {max_pixels:,}); pass --max-pixels N to raise "
                    "the limit (memory risk)")
            rebuilt = _rebuild_jpeg_from_img(img, keep_icc, perturb, seed)
            return rebuilt, "jpeg"

    with Image.open(path) as img:
        w, h = img.size
        if max_pixels and w * h > max_pixels:
            raise RuntimeError(
                f"refusing to process {w}x{h} = {w*h:,} pixels "
                f"(limit {max_pixels:,}); pass --max-pixels N to raise "
                "the limit (memory risk)"
            )
        fmt = (img.format or path.suffix.lstrip(".")).upper()

        # HEIC/AVIF: prefer lossless ISO-BMFF surgery — EXIF/XMP item
        # extents zeroed, pixel items byte-identical. Only falls back to
        # the pillow-heif re-encode when the container can't be parsed.
        if fmt in ("HEIF", "HEIC", "AVIF") \
                and getattr(img, "n_frames", 1) <= 1:
            surg = _strip_heif_lossless(raw)
            if surg is not None:
                return surg, fmt.lower()

        img.load()
        n_frames = getattr(img, "n_frames", 1)
        if max_pixels and n_frames > 1 and w * h * n_frames > max_pixels * 8:
            # cumulative budget: a hostile "animation" with thousands of
            # huge frames is a decompression bomb in slow motion
            raise RuntimeError(
                f"refusing: ~{w*h*n_frames:,} total pixels across "
                f"{n_frames} frames (cumulative limit {max_pixels*8:,})"
            )
        seed = _perturb_seed(path, raw) if perturb else 0

        # GIF: prefer the byte-level strip — it keeps every frame,
        # palette, transparency and disposal EXACTLY as-is (no
        # P→RGBA→re-quantize round-trip) and only drops comment + XMP
        # application extensions wherever they appear in the stream.
        # Fall back to a rebuild if the stream doesn't parse. (--perturb
        # forces the rebuild — changing pixels is the whole point.)
        if fmt == "GIF":
            if not perturb:
                lossless = _strip_gif_lossless(raw)
                if lossless is not None:
                    return lossless, "gif"
            if n_frames > 1:
                return _strip_multiframe(img, fmt, keep_icc=keep_icc,
                                         perturb=perturb, seed=seed)

        webp_lossless = fmt == "WEBP" and _webp_is_lossless(raw)

        # animated/multipage WebP / TIFF / AVIF — strip every frame,
        # keep the animation
        if fmt in ("TIFF", "TIF", "WEBP", "AVIF") and n_frames > 1:
            return _strip_multiframe(img, fmt, keep_icc=keep_icc,
                                     webp_lossless=webp_lossless,
                                     perturb=perturb, seed=seed)

        # APNG: lossless chunk strip (animation + pixels byte-exact).
        # The old code rebuilt through the single-frame path and silently
        # collapsed every animated PNG to frame 1.
        if fmt == "PNG" and _png_is_animated(raw):
            if not perturb:
                lossless = _strip_png_lossless(raw)
                if lossless is not None:
                    return lossless, "png"
            if n_frames > 1:
                return _strip_multiframe(img, "PNG", keep_icc=keep_icc,
                                         perturb=perturb, seed=seed)

        img = _apply_orientation(img, strict=fmt in ("JPEG", "JPG", "MPO"))

        mode = img.mode
        if mode not in ("RGB", "RGBA", "L"):
            mode = "RGBA" if ("A" in mode or mode == "P") else "RGB"
            img = img.convert(mode)

        clean = _rebuild_frame(img, mode)
        if perturb:
            clean = _perturb_image(clean, seed, perturb)

        icc_bytes = b""
        if keep_icc:
            try:
                icc_bytes = img.info.get("icc_profile", b"") or b""
            except Exception:
                icc_bytes = b""

        buf = io.BytesIO()

        if fmt in ("JPEG", "JPG", "MPO"):
            # https://pillow.readthedocs.io/en/stable/handbook/security.html
            # recommends exactly this: exif=b"", icc_profile=None,
            # pnginfo=None. We also pass progressive=False so there's
            # no app-segment noise from the encoder.
            kwargs = {"format": "JPEG", "quality": 95, "optimize": True,
                      "exif": b"", "progressive": False}
            kwargs["icc_profile"] = icc_bytes or None
            clean.save(buf, **kwargs)
            fmt_out = "JPEG"

        elif fmt == "PNG":
            from PIL.PngImagePlugin import PngInfo
            # empty PngInfo -> no tEXt/zTXt/iTXt chunks
            kwargs = {"format": "PNG", "pnginfo": PngInfo(), "optimize": True,
                      "icc_profile": icc_bytes or None, "exif": b""}
            clean.save(buf, **kwargs)
            fmt_out = "PNG"

        elif fmt == "WEBP":
            # lossless in -> lossless out: never silently downgrade a
            # byte-exact file to q90 lossy
            kwargs = {"format": "WEBP", "method": 6, "exif": b"",
                      "xmp": b"", "icc_profile": icc_bytes or None}
            if webp_lossless:
                kwargs.update(lossless=True, quality=100, exact=True)
            else:
                kwargs["quality"] = 90
            clean.save(buf, **kwargs)
            fmt_out = "WEBP"

        elif fmt in ("TIFF", "TIF"):
            clean.save(buf, format="TIFF")
            fmt_out = "TIFF"

        elif fmt == "GIF":
            clean.save(buf, format="GIF")
            fmt_out = "GIF"

        elif fmt in ("HEIF", "HEIC", "AVIF"):
            if pillow_heif is None:
                raise RuntimeError(
                    "HEIC/AVIF needs pillow-heif. install:\n"
                    "  pip3 install pillow-heif"
                )
            clean.save(buf, format="HEIF" if fmt in ("HEIF", "HEIC") else "AVIF",
                       quality=90)
            fmt_out = fmt

        else:
            clean.save(buf, format=fmt)
            fmt_out = fmt

        cleaned = buf.getvalue()

    if fmt_out == "JPEG":
        cleaned = _jpeg_final_check(cleaned, keep_icc)
    return cleaned, fmt_out.lower()












def handle_one(path: Path, args: argparse.Namespace) -> int:
    """Process one file. Returns R_OK / R_ERR / R_SKIP.

    Dispatch is by magic bytes (sniffed), not by file extension, so a
    downloaded JPEG with no extension is still stripped. Unrecognized
    files are SKIPPED (never counted as errors)."""
    fmt = _sniff_format(path) if path.is_file() else None
    if fmt is None:
        if args.verbose:
            print(f"  {c_dim('[skip] unrecognized:')} {path.name}")
        return R_SKIP

    no_clobber = bool(getattr(args, "no_clobber", False))
    want_report = bool(getattr(args, "report", False))
    drop_orientation = bool(getattr(args, "drop_orientation", False))
    perturb = getattr(args, "perturb", None)

    if fmt == "raf":
        # Fuji RAF is NOT a TIFF container, but it is writable losslessly:
        # header strings + embedded JPEG preview EXIF + FujiIFD block.
        # Never rebuilt from pixels; loud refusal when it can't be verified.
        report = (_inventory_metadata(path.read_bytes(), "raf",
                                      args.keep_icc)
                  if want_report else None)
        if args.dry_run or args.inspect:
            try:
                st = path.stat()
                print(f"  {c_info('RAF')} {c_head(path.name)}: {st.st_size:,} "
                      "bytes — surgery would blank header model/serial, "
                      "strip the embedded JPEG preview's EXIF and clean "
                      "the FujiIFD block")
                if want_report:
                    _print_report(path, report or [])
            except OSError as e:
                print(f"  {c_err('[ERR]')} {c_warn(path.name)}: {e}",
                      file=sys.stderr)
                return R_ERR
            return R_OK
        try:
            cleaned = _strip_raf_lossless(path.read_bytes(),
                                          keep_icc=args.keep_icc)
            if cleaned is None:
                raise RuntimeError(
                    "not a parseable RAF container (truncated header or "
                    "unparseable embedded preview) — refusing to guess")
            write_output(path, args.output, cleaned, no_clobber=no_clobber)
            if want_report:
                _print_report(path, report or [])
        except Exception as e:
            print(f"  {c_err('[ERR]')} {c_warn(path.name)}: {e}", file=sys.stderr)
            return R_ERR
        return R_OK

    if fmt in RAW_FORMATS:
        # RAW: NEVER pixel-rebuild (the sensor data can't be re-encoded) —
        # lossless in-place IFD surgery only, loud refusal on failure
        report = (_inventory_metadata(path.read_bytes(), fmt, args.keep_icc,
                                      drop_orientation)
                  if want_report else None)
        if args.dry_run or args.inspect:
            try:
                st = path.stat()
                print(f"  {c_info(fmt.upper())} {c_head(path.name)}: "
                      f"{st.st_size:,} bytes, TIFF-family container — "
                      "surgery would blank EXIF/GPS/MakerNotes losslessly")
                if want_report:
                    _print_report(path, report or [])
            except OSError as e:
                print(f"  {c_err('[ERR]')} {c_warn(path.name)}: {e}", file=sys.stderr)
                return R_ERR
            return R_OK
        try:
            cleaned = _tiff_strip_lossless(path.read_bytes(),
                                           keep_icc=args.keep_icc,
                                           drop_orientation=drop_orientation)
            if cleaned is None:
                raise RuntimeError(
                    "not a parseable TIFF container — refusing to rebuild "
                    "RAW sensor data (BigTIFF/encrypted/corrupt?)")
            write_output(path, args.output, cleaned, no_clobber=no_clobber)
            if want_report:
                _print_report(path, report or [])
        except Exception as e:
            print(f"  {c_err('[ERR]')} {c_warn(path.name)}: {e}", file=sys.stderr)
            return R_ERR
        return R_OK

    if fmt in IMAGE_FORMATS:
        report = [] if want_report else None
        if args.dry_run or args.inspect:
            if want_report:
                try:
                    _print_report(path, _inventory_metadata(
                        path.read_bytes(), fmt, args.keep_icc,
                        drop_orientation))
                except OSError:
                    pass
            try:
                inspect_image(path, max_pixels=getattr(args, "max_pixels", None))
            except Exception as e:
                print(f"  {c_err('[ERR]')} {c_warn(path.name)}: {e}", file=sys.stderr)
                return R_ERR
            return R_OK
        try:
            cleaned, fmt_out = strip_image_bytes(
                path, keep_icc=args.keep_icc,
                max_pixels=getattr(args, "max_pixels", None),
                report=report, drop_orientation=drop_orientation,
                perturb=perturb)
            write_output(path, args.output, cleaned, no_clobber=no_clobber)
            if want_report:
                _print_report(path, report or [])
        except Exception as e:
            print(f"  {c_err('[ERR]')} {c_warn(path.name)}: {e}", file=sys.stderr)
            return R_ERR
        if args.verbose:
            try:
                check = args.output if args.output is not None else path
                if check.is_dir() or (not check.suffix and not check.exists()):
                    check = check / path.name
                inspect_image(check, max_pixels=getattr(args, "max_pixels", None))
            except Exception as e:
                print(f"  {c_err('[ERR]')} {c_warn(path.name)}: {e}", file=sys.stderr)
        return R_OK

    if fmt == "pdf":
        if args.dry_run or args.inspect:
            print(f"  {c_dim('(would strip PDF metadata)')} {path.name}")
            return R_OK
        cleaned = strip_pdf_bytes(path)
        if not cleaned:
            return R_ERR
        try:
            write_output(path, args.output, cleaned, no_clobber=no_clobber)
        except Exception as e:
            print(f"  {c_err('[ERR]')} {c_warn(path.name)}: {e}", file=sys.stderr)
            return R_ERR
        return R_OK

    if args.verbose:
        print(f"  {c_dim('[skip] unsupported:')} {path.name}")
    return R_SKIP


def iter_inputs(path: Path) -> Iterable[Path]:
    if path.is_file():
        yield path
    elif path.is_dir():
        yield from (p for p in path.rglob("*") if p.is_file())
    else:
        raise FileNotFoundError(path)

