# exifwipe

Make ExifTool return blank on any image you're about to post.

Photos carry hidden data. GPS coordinates, camera model, software versions, and the date are stored inside the file itself, invisible in the viewer but readable by anyone. `exifwipe` removes that data, then checks its own work to make sure nothing survived.

The rule is simple: **for lossless formats, the pixels are never touched.** JPEG markers get rewritten in place, GIF bytes are rewritten, and RAW/HEIC/AVIF files get metadata tables surgically removed — the pixels stay **byte-identical**, and the tool proves it. The only time pixels are re-encoded is when physics demands it (a JPEG that needs rotating, PNG/WebP rebuilds, and other lossy paths) — and the docs say so, per format, below.

## Install

Not on PyPI yet. Clone and install:

```bash
git clone https://github.com/loucass/exifwipe
cd exifwipe
pip install .
```

then run it:

```bash
python3 exifwipe.py photo.jpg
```

Optional extras:

```bash
pip install .[verify]   # + piexif — JPEG round-trip verification
pip install .[heif,pdf] # + pillow-heif, pikepdf — HEIC/AVIF/PDF
pip install .[dev]      # + pytest — to run the test suite
```

RAW files need no extra libraries — the surgery is pure Python.

## Usage

```bash
exifwipe photo.jpg                  # strip in place
exifwipe IMG_0001.CR2               # RAW: lossless, sensor data untouched
exifwipe ./images/ -o ./clean/      # batch a folder to a new one
exifwipe photo.jpg --inspect        # show what exiftool would see
exifwipe photo.jpg --verify         # prove nothing leaked (exit 3 if it did)
exifwipe photo.jpg --report         # print exactly which fields were removed
exifwipe photo.jpg --dry-run -v     # show what would happen, write nothing
exifwipe photo.jpg --no-clobber     # refuse to overwrite an existing target
exifwipe IMG_0001.DNG --drop-orientation   # RAW: also remove the Orientation tag
exifwipe photo.jpg --perturb 2      # tilt pixels +/-2: kills naive image search
exifwipe --formats                  # what each format is guaranteed
exifwipe                            # interactive menu
```

Format detection uses magic bytes, not file extensions. A JPEG with no name is still recognized, and an extensionless CR2 pops out of its header.

### Exit codes

| code | meaning |
|------|---------|
| 0 | everything processed (unrecognized files are skipped, not errors) |
| 2 | usage error: input missing, or `-o` is a single file for multiple inputs |
| 3 | a file failed, or `--verify` found leaks |

## What gets stripped

Every photo carries more than what you see: the camera's make, model, and
serial; GPS coordinates; the exact time it was taken; the software that wrote
it; and so-called MakerNotes, a private blob of vendor diagnostics. `exifwipe`
removes all of this, including every copy the camera stashed in the file.

| Format | Mechanism | Guarantee |
|--------|-----------|-----------|
| JPEG (no rotation needed) | lossless marker rewrite | clean; pixels byte-identical |
| JPEG (needs rotation) | re-encode pixels | clean; pixels re-encoded |
| MPO / multi-frame JPEG | each frame handled separately, first frame re-encoded if rotated | clean; every frame kept |
| PNG | fresh frame rebuild, empty metadata | clean |
| APNG | lossless chunk strip | clean; animation + pixels unchanged |
| GIF | lossless in-place rewrite | clean; frames/palette/loop exact |
| WebP | lossless-in → lossless-out (byte-identical); lossy-in → clean re-encode | clean; animation kept |
| TIFF / DNG / CR2 / NEF / ARW / ORF / RW2 / PEF / SRW | lossless IFD surgery | clean; sensor data byte-identical, never rebuilt |
| BMP | pixel rebuild | clean |
| HEIC / AVIF | lossless ISO-BMFF surgery | clean; pixels byte-identical |
| PDF | pikepdf: /Info, /Metadata, /Lang, /JS, PageLabels, PieceInfo, StructTreeRoot | best-effort: embedded-image EXIF may survive |
| RAF (Fuji) | lossless: header strings + preview EXIF + FujiIFD | clean; refuses if it can't parse |

The tool keeps structural bytes on purpose (the JFIF header, dimensions, and
ICC profile only when asked) — files need those to display, and they're not
secret.

In the table, "byte-identical" is only ever claimed for lossless paths.
Anything else means the pixels were rebuilt clean — not byte-identical, but
metadata-free.

## How it works

Four layers, because any single one quietly fails sometimes:

1. **Lossless rewrite (JPEG).** Drops every APPn/COM marker, copies the
   compressed pixels verbatim. No decode, no encode — a 50MP photo strips in
   milliseconds. Multi-frame files are split per frame so nothing is lost;
   if the first frame needs rotating it gets re-encoded, the rest stay exact.
2. **Lossless surgery (RAW, HEIC/AVIF, RAF).** RAW: each metadata table is
   zeroed in place, and only identifying tags are blanked; offsets are never
   touched, so the sensor data stays byte-identical. HEIC/AVIF: the item size
   table is used to zero EXIF/XMP. RAF: header strings + preview EXIF +
   FujiIFD scrubbed.
3. **Fresh rebuild (everything else).** Pixels copied one tile at a time,
   saved with empty metadata. A 100 MP photo *never* becomes a giant in-memory
   list.
4. **Verify.** `--verify` re-opens the output and scans for anything that
   survived — exiftool if available, otherwise its own per-format parser.
   The verifier checks *every* JPEG frame and the *whole* PNG, not just the
   obvious parts.

RAW sensor data can't be re-encoded — it's a sensor dump with vendor quirks,
not a photo you can just re-save. So `exifwipe` edits the tables in place.
If a RAW file's structure is corrupted or hostile, the tool **refuses** —
it won't "clean" a file it can't fully verify, and it never half-touches
data it can't check.

## Things you need to know

- **PDF is best-effort**: EXIF inside embedded images may survive. Strip those separately if it matters.
- **Animated AVIF** is refused rather than silently squashed.
- **HEIC/AVIF** opening (not stripping) needs `pip install .[heif]`; the surgery itself is pure bytes.
- **RAF (Fuji)** is lossless for the carriers we know — Fuji changes layouts between models. If it can't parse, it refuses, it doesn't half-wipe.
- **Decompression bombs** are refused by default (**`--max-pixels N`** to raise the 178M-pixel cap).
- **NEF/ARW/ORF/RW2/PEF** are told apart from plain TIFF by vendor MakerNotes prefixes — a generic extensionless TIFF stays a TIFF.
- **`--perturb`** breaks exact/feature image-matching. It's not unlinkability and it's not cryptography.

## The test suite

The suite exists to catch the attacks that used to break the tool — and lock
them in so they never come back. 131 tests cover MPO re-rotation, EXIF hidden in
a second frame, APNG collapse, fuzzed RAW surgery, symlink in-place strips,
setuid bits surviving rebuilds, and more.

```bash
pip install .[dev]
python -m pytest
```

## Benchmark — receipts

`python3 benchmarks/bench.py`, best-of-3, ~8-MP fixtures:

| format | in (KB) | out (KB) | ms/op | MB/s |
|--------|--------:|---------:|------:|-----:|
| jpeg (lossless) | 129 | 129 | 36.5 | 3.4 |
| jpeg (rotated, rebuild) | 129 | 48 | 238 | 0.5 |
| png (rebuild) | 37 | 36 | 479 | 0.1 |
| gif (5 frames, lossless) | 4 | 4 | 1.7 | 2.5 |
| webp (rebuild) | 15 | 15 | 1467 | 0.0 |
| tiff (surgery) | 24576 | 24576 | 38.9 | 617 |

Lossless paths cost almost nothing. The rebuild paths pay the encoder — WebP's
re-encode is the price of a clean file. Your numbers will differ.

## Why not exiftool / mat2?

- **exiftool `-all=`**: needs Perl, and it's not installed on most machines you'll actually run this on.
- **mat2**: great for mixed folders of video/audio, but heavy for a single phone screenshot.

`exifwipe` is a small sharp knife for images. Clean **your own** files before
you post them — it's not a tool for washing other people's.

## License

MIT — do whatever, it's a screwdriver.
