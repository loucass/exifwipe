# exifwipe

**Make ExifTool return blank on any image you're about to post — losslessly where physics allows, loudly when it doesn't.**

Every photo you post carries a passenger: EXIF. GPS coordinates, camera serial, software versions, DateTimeOriginal, MakerNotes — riding in bytes nobody sees and anybody can read. `exifwipe` strips all of it and then **proves** it stripped it, because "trust me bro" is not an incident-response strategy.

The philosophy is simple and it's the opposite of most tools: **when the format lets us keep the pixels byte-identical, we keep them byte-identical.** JPEG markers get rewritten without a re-encode. DNG/CR2/NEF/ARW sensor data never gets "rebuilt" — you can't re-encode a raw sensor dump, and any tool that claims to is lying or destroying your file. We do lossless in-place surgery instead.

## Install

Not on PyPI yet — clone the repo:

```bash
git clone https://github.com/loucass/exifwipe
cd exifwipe
pip install .                 # installs the `exifwipe` command
```

Or run it straight from the clone, no install:

```bash
python3 exifwipe.py photo.jpg
```

Optional extras (same clone, just pick your flags):

```bash
pip install .[verify]         # + piexif     (JPEG round-trip verification)
pip install .[heif,pdf]       # + pillow-heif, pikepdf (HEIC/AVIF/PDF)
pip install .[dev]            # + pytest     (to run the test suite)
```

System Pillow is usually better on Linux (it's the one with the C codecs):

```bash
sudo apt install python3-pil
```

RAW/DNG support is pure Python — no libraw, no exiftool, no root. You can wipe a CR2 on a box where exiftool would need Perl and a prayer.

## Use

```bash
exifwipe photo.jpg                  # strip in place
exifwipe IMG_0001.CR2               # RAW: lossless IFD surgery, sensor data untouched
exifwipe ./images/ -o ./clean/      # batch a folder to a new one
exifwipe photo.jpg --inspect        # show what exiftool would surface
exifwipe photo.jpg --dry-run -v     # preview, write nothing (and mean it)
exifwipe photo.jpg --verify         # prove nothing leaked (exit 3 if it did)
exifwipe photo.jpg --no-clobber     # refuse to overwrite an existing -o target
exifwipe photo.jpg --report         # print exactly which fields were removed
exifwipe IMG_0001.DNG --drop-orientation   # RAW: also blank the Orientation tag
exifwipe photo.jpg --perturb 2      # +-2 pixel noise: breaks naive reverse-search
exifwipe --formats                  # mechanism | guarantee per format
exifwipe                            # interactive menu (clears screen between ops)
```

Detection is by **magic bytes**, not extension — a downloaded JPEG with no name is stripped like `photo.jpg`, and an extensionless CR2 is still caught by its header. NEF/ARW/ORF/RW2/PEF are structurally plain TIFFs, but they're told apart from a generic TIFF by their **vendor MakerNote prefixes** — so extensionless NEFs and ARWs work too. `--report` prints exactly which tags/chunks died per file, so you don't have to take anyone's word for it.

### Exit codes

| code | meaning |
|------|---------|
| 0 | everything processed (unrecognized files are **skipped**, not errors) |
| 2 | usage error: input not found, or `-o` is a single file for >1 input |
| 3 | one or more files failed, or `--verify` found leaks |

## Format support — mechanism, not marketing

| Format | Mechanism | Guarantee (honest) |
|--------|-----------|--------------------|
| JPEG (orientation-neutral) | lossless marker rewrite | clean, pixels **byte-identical**, no re-encode |
| JPEG (needs rotation) | rotation baked into pixels, q95 rebuild | clean, pixels re-encoded |
| MPO / multi-frame JPEG | per-SOI/EOI rewrite; rotated frame 0 re-encoded | clean, **all frames kept** |
| PNG | fresh frame rebuild, empty PngInfo | clean |
| APNG | lossless chunk strip (acTL/fcTL/fdAT kept) | clean, animation + pixels byte-identical |
| GIF | lossless byte rewrite | clean, frames/palette/loop byte-exact |
| WebP | rebuild; **lossless-in → lossless-out** | clean, animated frames kept |
| TIFF | lossless in-place IFD surgery | clean, pixels + pages byte-identical |
| DNG / CR2 / NEF / ARW / ORF / RW2 / PEF / SRW | lossless in-place IFD surgery | clean, **sensor data byte-identical, never rebuilt** |
| BMP | pixel rebuild | clean |
| HEIC / AVIF | lossless ISO-BMFF surgery: EXIF/XMP item extents zeroed via iloc | clean, pixels **byte-identical**; clean re-encode fallback only if the container can't be parsed |
| PDF | pikepdf: /Info + /Metadata + /Lang + JS + PageLabels + PieceInfo + StructTreeRoot | **best-effort**: embedded-image EXIF may survive |
| RAF (Fuji) | lossless: header strings + embedded-JPEG EXIF + FujiIFD block surgery | clean for every carrier; refuses on unparseable preview/IFD |

Structural things are kept on purpose (JFIF header, dimensions, ICC only when you ask) — viewers refuse to open files without them, and they're not identifying.

## The RAW/DNG deep dive

RAW sensor data cannot be re-encoded — it's not pixels, it's a sensor dump with a million vendor quirks. So `exifwipe` treats the whole TIFF family (DNG, CR2, NEF, ARW, ORF, RW2, PEF, SRW, SR2, plus plain TIFF) with **in-place IFD surgery**:

1. Every **EXIF IFD (0x8769)** and **GPS IFD (0x8825)** target is physically destroyed — the entry block *and* every payload it referenced get zeroed. MakerNotes, DateTimeOriginal, the whole Interop chain, GPS coordinates: gone, not just unreachable. Orphaned bytes are still forensically present; we don't leave forensic presents.
2. Identifying scalar tags (Make, Model, Software, Artist, Copyright, ImageDescription, SerialNumber, UniqueCameraModel, LocalizedCameraModel, DNGPrivateData, OriginalRawFile\*) are blanked in place.
3. **No offset is ever remapped.** Pixel data — and the 40MB of compressed sensor data in a CR2 — stays byte-identical. We verify that in the test suite, byte for byte.

Supported: classic TIFF *and* BigTIFF (the DNG spec explicitly allows BigTIFF; so do we). Detection: DNG by extension or by its DNGVersion tag (0xC612) — extensionless DNGs work; CR2 by its 0x0201 magic — extensionless CR2s work; NEF/ARW/ORF/RW2/PEF by their vendor MakerNote prefixes — extensionless files work. Fuji **RAF** gets its own lossless surgery — header strings (version, unique ID), the embedded JPEG preview's EXIF, and the FujiIFD TIFF block are all stripped in place, no re-encode. By default RAW files keep their **Orientation** tag (it's a display instruction — you can't re-rotate sensor pixels without a lossy demosaic) — `--drop-orientation` blanks it if you want it gone.

And if a RAW file's IFD structure is truncated or hostile, the surgery **refuses** — it will not "clean" a file it can't fully verify, and it will never fall back to rebuilding sensor data it can't decode.

## How it works

Four layers, because "just one" quietly fails sometimes:

1. **Lossless marker rewrite (JPEG).** Every APPn/COM segment is dropped from the marker stream; entropy-coded pixels are copied **verbatim**. Orientation and dimensions are read from the marker stream (SOF/APP0) — the pixels are **not decoded** when a lossless strip is possible, so a 50MP photo strips in milliseconds. Multi-frame streams (MPO) are split per SOI..EOI pair so no frame is lost, trailing garbage after the final EOI is dropped, and a rotated first frame is re-encoded while the rest stays lossless. If the whole photo needs rotation, the rotation is baked into the pixels and the frame is rebuilt.
2. **Lossless surgery (TIFF family + HEIC/AVIF + RAF)** — see above. TIFF-family IFD surgery at 700+ MB/s; HEIC/AVIF EXIF/XMP item extents zeroed through the iloc table with pixels byte-identical; RAF header strings + preview EXIF + FujiIFD scrubbed. No decode, no re-encode.
3. **Fresh-frame rebuild (everything else).** Pixels copied one bounded 256px tile at a time (a 100MP photo never materializes a giant Python list), saved with `exif=b""`, `xmp=b""`, empty `pnginfo`. Animated GIF/APNG/WebP and multipage TIFF keep every frame; lossless WebP in stays lossless WebP out — we don't silently downgrade your byte-exact file to q90 lossy.
4. **Verification.** `--verify` re-opens the output and confirms nothing survived — exiftool when it's installed, otherwise per-format byte parsers. The JPEG verifier checks **every frame** (an MPO whose EXIF only lives in frame 2 used to sail through as "clean"). The PNG verifier scans the **whole file**, including chunks tucked after IEND. A file that still leaks exits 3.

## Benchmark — receipts

`python3 benchmarks/bench.py`, best-of-3, 8.4MP fixtures, solid colors (JPEG/WebP love solid colors — real photos are slower):

| format | in (KB) | out (KB) | ms/op | MB/s |
|--------|--------:|---------:|------:|-----:|
| jpeg (lossless) | 129 | 129 | 36.5 | 3.4 |
| jpeg (rotated, rebuild) | 129 | 48 | 238 | 0.5 |
| png (rebuild) | 37 | 36 | 479 | 0.1 |
| gif (5 frames, lossless) | 4 | 4 | 1.7 | 2.5 |
| webp (rebuild) | 15 | 15 | 1467 | 0.0 |
| tiff (surgery) | 24576 | 24576 | 38.9 | **617** |

Read it right: the lossless paths (JPEG markers, GIF bytes, TIFF surgery) cost almost nothing; the rebuild paths pay the encode tax, and `webp` at method 6 is the tax man. That's the price of a clean file, and it's why the lossless paths exist. Your numbers will differ — that's physics, not a feature.

## The test suite — 131 tests, and they're not decoration

The suite exists to make the tool **fail**, not to make it look good. Every attack that broke earlier versions is locked in as a test so it can't come back:

- MPO with a rotated first frame (used to silently delete frame 2) → both frames must survive, rotation baked in
- APNG (used to collapse to one frame) → animation + pixels byte-identical
- EXIF hidden in an MPO's second frame → the verifier must flag it
- a tEXt chunk spliced **after** PNG's IEND → the verifier must flag it
- the JPEG final check (used to be dead code — `piexif.remove(bytes)` raises on 1.1.3 and the exception was swallowed) → now re-wipes and **fails loudly** if it can't
- in-place strip on a **symlink** (used to destroy the link and leave the target dirty) → link survives, target cleaned
- a **hard-linked** photo → warns you that the other name still points at pre-wipe data
- lossless WebP (used to be re-encoded lossy) → VP8L in, VP8L out, pixels identical
- setuid/sticky bits (used to survive the atomic rewrite) → masked off
- `-o victim.txt` → overwrites only with a warning, refuses with `--no-clobber`
- a 10-frame animation over the cumulative pixel budget → refused
- hostile TIFF IFD graphs (cycles, fake entry counts) → terminate, never hang
- **mutation-fuzzed TIFF surgery**: byte flips + truncations across a CR2/DNG/TIFF corpus → the surgery must refuse, never corrupt, and any file it *does* clean must come out structurally valid with pixels intact
- a hostile TIFF tag value offset pointing at the IFD **or at pixel strips** → refused (structural bytes AND StripOffsets/StripByteCounts ranges are protected from blanking)
- HEIC: EXIF+XMP extents zeroed through iloc, pixels byte-identical, and the verifier re-reads it
- RAF: header strings + preview EXIF + FujiIFD all wiped, fixture asserted byte-identical on sensor bytes
- `--report` names exactly the removed fields; `--perturb` changes pixels but keeps the image decodable; `--drop-orientation` blanks RAW orientation
- JPEG fast path: a lossless strip on an 8MP JPEG does **no** pixel decode
- the whole RAW family: CR2/DNG/BigTIFF fixtures handcrafted byte-by-byte, sensor data asserted byte-identical after the wipe

```bash
pip install .[dev]
python -m pytest            # 131 tests. They pass because they had to.
```

## Known limits — read these before you trust it

- **PDF is best-effort**: embedded-image EXIF and exotic keys may survive. Strip the embedded images separately if provenance matters.
- **Animated AVIF is refused** rather than silently collapsed — re-save the frames yourself and scrub those.
- **HEIC/AVIF surgery is pure bytes** (no pillow-heif needed), but *opening* a HEIC for inspect/rebuild still requires `pip install .[heif]`. An AVIF container that the surgery can't fully parse falls back to a clean re-encode instead of being left dirty.
- **RAF (Fuji)** is lossless for the carriers we know (header strings, embedded-JPEG EXIF, FujiIFD). Fuji occasionally changes the layout between models — if the preview or IFD doesn't parse, the file is **refused**, not half-wiped.
- Decompression bombs are refused by default (`--max-pixels N` to raise the 178M-pixel limit, `0` for unlimited), including a cumulative budget across animation frames.
- NEF/ARW/ORF/RW2/PEF are told apart from plain TIFF by MakerNote vendor prefixes — an extensionless NEF with a Nikon MakerNote is caught; an extensionless generic TIFF with none stays a TIFF.
- `--perturb` breaks naive reverse-image search (exact/feature matching) — it is **not** unlinkability and it's **not** cryptography.

## Why not just exiftool / mat2?

- **exiftool `-all=`**: needs Perl, and it's not installed on most boxes you'll actually run this on.
- **mat2**: great for folders of mixed audio/video/doc, but it's GObject-heavy for a single phone screenshot.

`exifwipe` is a narrow sharp knife for images. Use it on your own files before you publish them — not to launder someone else's. It's a screwdriver, not a suitcase.

## License

MIT — do whatever, it's still a screwdriver.
