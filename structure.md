# Project structure

exifwipe/
├── exifwipe.py           # thin facade: re-exports the whole API from the
│                         # _*.py modules so `import exifwipe` and the CLI entry
│                         # keep working unchanged (main() lives in _cli.py)
├── _config.py           # formats, vendor MakerNotes, constants, __version__
├── _color.py            # ANSI color / NO_COLOR / tty detection
├── _inspect.py          # metadata inventory (inspect_image, exiftool_hint)
├── _verify.py           # verify_clean: exiftool fallback + per-format scanners
│                         # (optional piexif guard for JPEG round-trip)
├── _tiff.py             # TIFF/RAW surgery engine: IFD walkers, BigTIFF,
│                         # structure check, protected regions, lossless strip
├── _pixels.py           # orientation baking, perturbation, frame rebuild,
│                         # multi-frame strip (DNG/MPO edge)
├── _jpeg.py             # JPEG marker machinery (fast path, frame split),
│                         # final-check safety net, _strip_jpeg_lossless
├── _gif.py              # GIF sub-block scanner + lossless strip
├── _png.py              # PNG chunk strip, APNG awareness
├── _webp.py             # WebP lossless vs lossy detection + strip
├── _heif.py             # HEIC/AVIF ISO-BMFF surgery (iloc extents)
├── _raf.py              # Fuji RAF surgery (borrows TIFF + JPEG pieces)
├── _pdf.py              # PDF strip (pikepdf optional, local import)
├── _report.py           # report metadata inventory (optional piexif)
├── _driver.py           # handle_one, strip_image_bytes dispatcher,
│                         # iter_inputs (pillow-heif optional)
├── _sniff.py            # format detection from magic bytes
├── _write.py            # atomic writes, output paths, system-dir guard
├── _menu.py             # interactive menu + prompt_input
├── _cli.py              # argparse, main(), formats matrix (optional piexif)
├── tests/               # 131 tests, 20 files
│   ├── helpers.py       # fixture builders: build_tiff, cr2/dng/heic/raf,
│   │                     #   jpeg_with_exif, animated_png, mpo_rotated_first...
│   ├── conftest.py      # sys.path wiring (repo root importable from tests)
│   └── test_*.py        # one file per concern (raw, heif, raf, report,
│                         #   perturb, fuzz, fast_jpeg, adversarial, menu...)
├── benchmarks/bench.py  # benchmark harness (--quick for CI, prints receipts)
├── pyproject.toml       # packaging: deps, extras [verify/heif/pdf/dev],
│                         #   console script exifwipe=exifwipe:main
├── README.md            # the docs
└── LICENSE / .gitignore