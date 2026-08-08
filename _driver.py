"""_driver - exifwipe internal module (format/strip machinery)."""

from __future__ import annotations



import argparse
import io
import os
import secrets
import stat
import sys
from pathlib import Path
from typing import Iterable, Optional
from PIL import Image

from _color import c_dim, c_err, c_head, c_info, c_ok, c_warn
from _config import DEFAULT_MAX_PIXELS, IMAGE_FORMATS, RAW_EXTENSIONS, RAW_FORMATS, R_ERR, R_OK, R_SKIP, _PNG_SIG, _RAF_MAGIC, _SYSTEM_DIRS
from _gif import _strip_gif_lossless
from _heif import _strip_heif_lossless
from _inspect import inspect_image
from _jpeg import _jpeg_final_check, _jpeg_orientation_from_bytes, _jpeg_sof_size, _rebuild_jpeg_from_img, _strip_jpeg_lossless, _strip_mpo_rotated_first
from _pdf import strip_pdf_bytes
from _pixels import _apply_orientation, _perturb_image, _perturb_seed, _rebuild_frame, _strip_multiframe
from _png import _png_is_animated, _strip_png_lossless
from _raf import _strip_raf_lossless
from _report import _inventory_metadata, _print_report
from _tiff import _is_tiff_family, _tiff_has_tag, _tiff_strip_lossless, _tiff_vendor_from_makernote
from _webp import _webp_is_lossless

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


def _refuse_system_target(path: Path) -> None:
    """Refuse to write into top-level system directories so a stray -o
    can't drop an image into /etc or /usr. /tmp, /var, /home and
    /run/media (USB mounts) are fine."""
    try:
        parts = path.resolve().parts
    except Exception:
        return
    if len(parts) > 1 and parts[1] in _SYSTEM_DIRS:
        # /run/media/<user>/... is a legitimate removable-mount target
        if parts[1] == "run" and len(parts) > 2 and parts[2] == "media":
            return
        raise RuntimeError(
            f"refusing to write into system directory '/{parts[1]}' ({path}); "
            "use a user-writable location"
        )


def _atomic_write_bytes(path: Path, cleaned: bytes, st) -> None:
    """Write `cleaned` to `path` atomically via a private temp file that
    only we created (O_EXCL — no attacker can pre-plant a symlink at a
    predictable name), fsync it, then rename over the original.

    A symlink is resolved FIRST so the write lands on the target — the
    link itself is preserved (the old behavior replaced the symlink with
    a regular file AND left the target dirty, which was both silent and
    a leak).

    Mode and mtime of the original are preserved on the new inode so a
    0600 private photo stays 0600; setuid/setgid/sticky bits are NOT
    carried over (masked with 0o7777).
    """
    if path.is_symlink():
        path = path.resolve()
    import secrets
    for _ in range(10):
        tmp = path.with_name(f".{path.name}.exifwipe_tmp_{secrets.token_hex(8)}")
        try:
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            continue            # collision — try another random name
        except OSError as e:
            raise OSError(f"cannot create temp file for {path.name}: {e}") from e
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(cleaned)
                f.flush()
                os.fsync(f.fileno())
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        # preserve the permission bits only — setuid/setgid/sticky are
        # dropped (carrying them over would be sloppy and exploitable)
        os.chmod(tmp, stat.S_IMODE(st.st_mode) & 0o777)
        os.utime(tmp, ns=(st.st_atime_ns, st.st_mtime_ns))
        os.replace(tmp, path)
        return
    raise OSError(f"could not reserve a unique temp name for {path.name}")


def write_output(src: Path, out: Optional[Path], cleaned: bytes,
                 no_clobber: bool = False) -> None:
    """Either overwrite src in place, or write to `out` (file or dir)."""
    if out is None:
        _refuse_system_target(src)
        target = src
        if src.is_symlink():
            resolved = src.resolve()
            if not resolved.is_file():
                raise OSError(f"{src} is a dangling symlink — nothing to strip")
            target = resolved
            print(f"  {c_warn('[LINK]')} {c_head(str(src))} -> "
                  f"{c_head(str(target))} {c_dim('(stripping target in place)')}")
        st = target.stat()
        if st.st_nlink > 1:
            print(f"  {c_warn('[WARN]')} {c_head(str(target))} has "
                  f"{st.st_nlink} hard links — the other names still point "
                  "at the pre-wipe data", file=sys.stderr)
        _atomic_write_bytes(target, cleaned, st)
        print(f"  {c_ok('[STRIPPED]')} {c_head(str(src))}")
    else:
        # if user passed a folder or a path-without-suffix, drop src inside
        if out.is_dir() or (not out.suffix and not out.exists()):
            out = out / src.name
        _refuse_system_target(out)
        if no_clobber and out.exists():
            raise FileExistsError(f"{out} already exists (--no-clobber)")
        if out.exists() and out.resolve() != src.resolve():
            print(f"  {c_warn('[clobber]')} overwriting existing "
                  f"{c_head(str(out))}", file=sys.stderr)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(cleaned)
        print(f"  {c_ok('[STRIPPED]')} {c_head(str(src))}  {c_dim('->')}  "
              f"{c_head(str(out))}")


def _sniff_bytes(data: bytes) -> Optional[str]:
    """Format from magic bytes only (no extension hints). Used by the
    strip path and the report inventory; the CR2 magic (0x0201 in the
    extended header) is the only RAW family detectable from bytes alone."""
    if data[:2] == b"\xff\xd8":
        return "jpeg"
    if data[:8] == _PNG_SIG:
        return "png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:16] == _RAF_MAGIC:
        return "raf"          # Fuji — NOT a TIFF container
    if data[:4] in (b"II*\x00", b"MM\x00*"):
        # CR2: 16-byte header (IFD0 at 0x10) + CR2 magic 0x0201 at offset 8
        if (data[:8] == b"II*\x00\x10\x00\x00\x00"
                and data[8:10] == b"\x01\x02"):
            return "cr2"
        return "tiff"
    if data[:2] == b"BM":
        return "bmp"
    if data[:4] == b"%PDF":
        return "pdf"
    if data[4:8] == b"ftyp":
        brand = data[8:12]
        # HEIF/AVIF share the ISO BMFF container; disambiguate by brand
        if brand in (b"avif", b"avis"):
            return "avif"
        if brand in (b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1",
                     b"heif", b"heim"):
            return "heif"
    return None


def _sniff_format(path: Path) -> Optional[str]:
    """Detect a file's real format from its magic bytes, not its name.
    Returns a normalized format name ('jpeg', 'png', 'gif', 'tiff',
    'webp', 'bmp', 'heif', 'avif', 'raf', 'pdf') or None if unrecognized.

    TIFF-family files that aren't obviously CR2/DNG-by-extension get a
    deep read: DNG by its DNGVersion tag, then RAW family by MakerNote
    prefix — so an extensionless NEF or a .tiff that's really an ARW is
    handled as the RAW it actually is."""
    try:
        head = path.open("rb").read(16)
    except OSError:
        return None
    fmt = _sniff_bytes(head)
    if fmt != "tiff":
        return fmt
    ext = path.suffix.lower()
    if ext == ".cr2":
        return "cr2"
    if ext == ".dng":
        return "dng"
    if ext in RAW_EXTENSIONS:
        return ext.lstrip(".")
    # anything else TIFF-family (extensionless, .tiff, or a .bin that's
    # really a NEF): the extension is only a hint — the DNGVersion tag
    # and the MakerNote are authoritative
    try:
        more = path.open("rb").read(1 << 20)
    except OSError:
        more = b""
    if not more:
        return "tiff"
    if _tiff_has_tag(more, 0xC612):
        return "dng"
    vend = _tiff_vendor_from_makernote(more)
    return vend if vend else "tiff"


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

