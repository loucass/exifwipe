"""_cli - exifwipe internal module (format/strip machinery)."""

from __future__ import annotations



import argparse
import shutil
import sys
from pathlib import Path
from typing import Optional

from _color import c_err, c_ok, c_warn, set_color
from _config import DEFAULT_MAX_PIXELS, IMAGE_FORMATS, RAW_FORMATS, R_ERR, R_OK, __version__
from _driver import _sniff_format, handle_one, iter_inputs
from _inspect import exiftool_hint, inspect_image
from _menu import run_interactive_menu
from _verify import print_formats_matrix, verify_clean

try:
    import piexif
except ImportError:
    piexif = None

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="exifwipe",
        description=("Make ExifTool return blank for an image or PDF.\n"
                     "Strips EXIF / XMP / GPS / MakerNotes / PNG text chunks "
                     "/ WebP XMP / HEIC EXIF / PDF DocInfo+XMP.\n"
                     "Built around the pattern from production metadata-scrubbers: "
                     "pixel rebuild + Pillow exif=b''  + piexif round-trip verify."),
        epilog=(
            "examples:\n"
            "  exifwipe photo.jpg                       # strip in place\n"
            "  exifwipe ./images/ -o ./clean/           # batch to new folder\n"
            "  exifwipe photo.jpg --inspect             # preview what exiftool sees\n"
            "  exifwipe photo.jpg --dry-run -v          # verbose inspect, no writes\n"
            "\n"
            "aliases I keep in my shell:\n"
            "  alias sc=exifwipe ~/Pictures/Screenshots/*.png\n"
            "  alias sm=exifwipe ~/Pictures/Shotwell/*/*.JPG -o ~/clean/\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("input", nargs="?", type=Path, default=None,
                   help="image file, PDF, or directory (omit to open the menu)")
    p.add_argument("-o", "--output", type=Path, default=None,
                   help="output file or dir (default: strip in place)")
    p.add_argument("--keep-icc", action="store_true",
                   help="preserve ICC color profile (default: also stripped)")
    p.add_argument("--dry-run", action="store_true",
                   help="inspect what would be stripped, write nothing")
    p.add_argument("--inspect", action="store_true",
                   help="print metadata exiftool-style and exit (no write)")
    p.add_argument("--verify", action="store_true",
                   help="after stripping, prove no metadata remains "
                        "(exiftool if installed, else per-format parsers); "
                        "exit nonzero if anything leaks")
    p.add_argument("--max-pixels", type=int, default=None,
                   help=f"refuse images larger than N pixels "
                        f"(default {DEFAULT_MAX_PIXELS:,}; 0 = unlimited)")
    p.add_argument("--no-clobber", action="store_true",
                   help="refuse to overwrite an existing -o target")
    p.add_argument("--report", action="store_true",
                   help="print exactly which metadata fields were removed "
                        "per file (also works with --dry-run)")
    p.add_argument("--drop-orientation", action="store_true",
                   help="RAW/TIFF only: also blank the Orientation tag "
                        "(kept by default — display instruction, not identity)")
    p.add_argument("--perturb", nargs="?", const=2, type=int, default=None,
                   metavar="LEVEL",
                   help="slightly change pixels (+-LEVEL, 1-4, default 2) "
                        "so reverse-image search can't match the original — "
                        "deterministic, opt-in, rebuild paths only")
    p.add_argument("--formats", action="store_true",
                   help="print what formats are guaranteed clean "
                      "vs best-effort, then exit")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="also print inspection after stripping")
    p.add_argument("--version", action="version",
                   version=f"%(prog)s {__version__}")
    color_group = p.add_mutually_exclusive_group()
    color_group.add_argument("--color", dest="color", action="store_const",
                             const=True, default=None,
                             help="force ANSI colors even when piped")
    color_group.add_argument("--no-color", dest="color", action="store_const",
                             const=False,
                             help="disable ANSI colors entirely")
    return p


def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv)
    set_color(args.color)

    if args.perturb is not None and not (1 <= args.perturb <= 4):
        print(f"  [ERR] --perturb level must be 1-4, got {args.perturb}",
              file=sys.stderr)
        return 2

    # --formats / --version don't need an input at all
    if args.formats:
        print_formats_matrix()
        return 0

    # no input → interactive menu
    if args.input is None:
        return run_interactive_menu()

    if not args.input.exists():
        print(f"  [ERR] not found: {args.input}", file=sys.stderr)
        return 2

    targets = list(iter_inputs(args.input))

    # --inspect is a read-only mode
    if args.inspect:
        n_err = 0
        for p in targets:
            try:
                fmt = _sniff_format(p) if p.is_file() else None
                if fmt in IMAGE_FORMATS:
                    inspect_image(p, max_pixels=args.max_pixels)
                elif fmt in RAW_FORMATS:
                    st = p.stat()
                    print(f"\n=== {p.name} ===")
                    print(f"  RAW {fmt.upper()}: {st.st_size:,} bytes, "
                          "TIFF-family container — `exiftool -a -G1 FILE` "
                          "sees what surgery would remove")
                elif fmt == "raf":
                    st = p.stat()
                    print(f"\n=== {p.name} ===")
                    print(f"  Fuji RAF: {st.st_size:,} bytes — header "
                          "model/serial + embedded JPEG EXIF + FujiIFD "
                          "block (surgery would remove all of it)")
                elif fmt == "pdf":
                    print(f"\n=== {p.name} ===")
                    print("  (PDF — use pikepdf or `exiftool -all=` to inspect)")
            except Exception as e:
                print(f"  {c_err('[ERR]')} {c_warn(p.name)}: {e}", file=sys.stderr)
                n_err += 1
        print("\n-- exiftool reference --\n" + exiftool_hint())
        return 0 if n_err == 0 else 3

    # guard: batch input to a single-file `-o` silently overwrites itself.
    # If --output looks like a FILE (has a suffix, isn't a dir) but we're
    # about to process more than one source, refuse loudly instead.
    output_is_file = (args.output is not None and args.output.suffix
                      and not args.output.is_dir())
    if output_is_file and len(targets) > 1:
        print(
            f"  {c_err('[ERR]')} -o looks like a single file but "
            f"{len(targets)} inputs are queued. Point -o at a directory instead.",
            file=sys.stderr,
        )
        return 2

    # -o pointing at a (new) dir: resolve per-file outputs and make sure
    # duplicate basenames don't silently clobber each other.
    out_dir = None
    if args.output is not None and (args.output.is_dir()
                                    or (not args.output.suffix and not args.output.exists())):
        out_dir = args.output

    n_ok = n_err = n_skip = 0
    leaks = []
    used_out = {}
    for p in targets:
        per = args
        if out_dir is not None:
            stem, suff = p.stem, p.suffix
            cand, i = p.name, 2
            while cand in used_out:
                cand = f"{stem} ({i}){suff}"
                i += 1
            used_out[cand] = True
            per = argparse.Namespace(**vars(args))
            per.output = out_dir / cand

        res = handle_one(p, per)
        if res == R_OK:
            n_ok += 1
        elif res == R_ERR:
            n_err += 1
            continue
        else:
            n_skip += 1
            continue

        # verify only files that were actually written (dry-run leaves the
        # original untouched, so verifying it would be a guaranteed FAIL)
        if args.verify and not args.dry_run:
            check = per.output if per.output is not None else p
            try:
                clean, found = verify_clean(check)
            except Exception as e:
                clean, found = False, [f"verify-error: {e}"]
            if not clean or found:
                leaks.extend(found or ["unknown"])
                print(f"  {c_err('[LEAK]')} {c_warn(p.name)}: "
                      f"{', '.join(found)}", file=sys.stderr)
                n_err += 1

    msg = f"\ndone. {n_ok} processed"
    if n_skip:
        msg += f", {n_skip} skipped"
    if n_err:
        msg += f", {n_err} errors"
    print(msg + ".")
    if args.verify:
        if leaks:
            print(f"  {c_err('VERIFY FAILED:')} metadata still present in "
                  f"{c_err(str(len(leaks)))} file(s). Do not publish these.",
                  file=sys.stderr)
        else:
            print(f"  {c_ok('VERIFY OK:')} no metadata on any clean file.")
    if piexif is None and args.verify and shutil.which("exiftool") is None:
        print("tip: install piexif for JPEG round-trip verify:  pip3 install piexif",
              file=sys.stderr)
    return 0 if (n_err == 0 and (not args.verify or not leaks)) else 3

