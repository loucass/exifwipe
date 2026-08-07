# exifwipe

**Make ExifTool return blank on any image you're about to post — losslessly where physics allows, loudly when it doesn't.**

Every photo ships with a passenger: EXIF. GPS coords, camera serial, software versions, DateTimeOriginal, MakerNotes — riding in bytes nobody sees and anybody can read. `exifwipe` strips that and then **proves** it stripped it, because "trust me bro" is not an incident-response strategy.

The philosophy is simple and it's the opposite of the other tools: **when the format lets us keep the pixels byte-identical, we keep them byte-identical.** JPEG markers get rewritten without a re-encode. DNG/CR2/NEF/ARW sensor data never gets "rebuilt" — you can't re-encode a raw sensor dump, and any tool that claims to is lying or destroying your file. We do lossless in-place surgery instead.

## Install

```bash
pip install exifwipe            # or: pipx install .
```

System Pillow is usually better on Linux (it's the one with the C codecs):

```bash
sudo apt install python3-pil
pip install piexif             # recommended: JPEG verify
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
exifwipe --formats                  # mechanism | guarantee per format
exifwipe                            # interactive menu
```

Detection is by **magic bytes**, not extension — a downloaded JPEG with no name is stripped like `photo.jpg`, and an extensionless CR2 is still caught by its header. DNG is caught by its DNGVersion tag even without an extension.

### Exit codes

| code | meaning |
|------|---------|
| 0 | everything processed (unrecognized files are **skipped**, not errors) |
| 2 | usage error: input not found, or `-o` is a single file for >1 input |
| 3 | one or more files failed, or `--verify` found leaks |

## Format matrix — mechanism, not marketing

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
| HEIC / AVIF | re-encode via pillow-heif (optional dep) | clean single-frame only |
| PDF | pikepdf: /Info + /Metadata + /Lang + JS + PageLabels + PieceInfo + StructTreeRoot | **best-effort**: embedded-image EXIF may survive |

Structural things are kept on purpose (JFIF header, dimensions, ICC only when you ask) — viewers refuse to open files without them, and they're not identifying.

## The RAW/DNG deep dive

RAW sensor data cannot be re-encoded — it's not pixels, it's a sensor dump with a million vendor quirks. So `exifwipe` treats the whole TIFF family (DNG, CR2, NEF, ARW, ORF, RW2, PEF, SRW, SR2, plus plain TIFF) with **in-place IFD surgery**:

1. Every **EXIF IFD (0x8769)** and **GPS IFD (0x8825)** target is physically destroyed — the entry block *and* every payload it referenced get zeroed. MakerNotes, DateTimeOriginal, the whole Interop chain, GPS coordinates: gone, not just unreachable. Orphaned bytes are still forensically present; we don't leave forensic presents.
2. Identifying scalar tags (Make, Model, Software, Artist, Copyright, ImageDescription, SerialNumber, UniqueCameraModel, LocalizedCameraModel, DNGPrivateData, OriginalRawFile\*) are blanked in place.
3. **No offset is ever remapped.** Pixel data — and the 40MB of compressed sensor data in a CR2 — stays byte-identical. We verify that in the test suite, byte for byte.

Supported: classic TIFF *and* BigTIFF (the DNG spec explicitly allows BigTIFF; so do we). Detection: DNG by extension or by its DNGVersion tag (0xC612) — extensionless DNGs work; CR2 by its 0x0201 magic — extensionless CR2s work; the rest of the RAW family by their extensions.

And if a RAW file's IFD structure is truncated or hostile, the surgery **refuses** — it will not "clean" a file it can't fully verify, and it will never fall back to rebuilding sensor data it can't decode.

## How it works

Three layers, because "just one" quietly fails sometimes:

1. **Lossless marker rewrite (JPEG).** Every APPn/COM segment is dropped from the marker stream; entropy-coded pixels are copied **verbatim**. Multi-frame streams (MPO) are split per SOI..EOI pair so no frame is lost, trailing garbage after the final EOI is dropped, and a rotated first frame is re-encoded while the rest stays lossless. If the whole photo needs rotation, the rotation is baked into the pixels and the frame is rebuilt.
2. **Lossless surgery (TIFF family)** — see above. No decode, no re-encode, no offset remap.
3. **Fresh-frame rebuild (everything else).** Pixels copied one bounded 256px tile at a time (a 100MP photo never materializes a giant Python list), saved with `exif=b""`, `xmp=b""`, empty `pnginfo`. Animated GIF/APNG/WebP and multipage TIFF keep every frame; lossless WebP in stays lossless WebP out — we don't silently downgrade your byte-exact file to q90 lossy.
4. **Verification.** `--verify` re-opens the output and confirms nothing survived — exiftool when it's installed, otherwise per-format byte parsers. The JPEG verifier checks **every frame** (an MPO whose EXIF only lives in frame 2 used to sail through as "clean"). The PNG verifier scans the **whole file**, including chunks tucked after IEND. A file that still leaks exits 3.

## Benchmark — receipts

`python3 benchmarks/bench.py`, best-of-3, 8.4MP fixtures, solid colors (JPEG/WebP love solid colors — real photos are slower):

| format | in (KB) | out (KB) | ms/op | MB/s |
|--------|--------:|---------:|------:|-----:|
| jpeg (lossless) | 129 | 129 | 58.6 | 2.1 |
| jpeg (rotated, rebuild) | 129 | 48 | 222 | 0.6 |
| png (rebuild) | 37 | 36 | 447 | 0.1 |
| gif (5 frames, lossless) | 4 | 4 | 2.1 | 2.1 |
| webp (rebuild) | 15 | 15 | 1269 | 0.0 |
| tiff (surgery) | 24576 | 24576 | 31.3 | **767** |

Read it right: the lossless paths (JPEG markers, GIF bytes, TIFF surgery) cost almost nothing; the rebuild paths pay the encode tax, and `webp` at method 6 is the tax man. That's the price of a clean file, and it's why the lossless paths exist. Your numbers will differ — that's physics, not a feature.

## The black-hoodie test suite

The suite is **88 tests** and it's not there to make the tool look good — it's there to make it **fail**. Every attack I could think of across the rounds is a test now:

- MPO with a rotated first frame (used to silently delete frame 2) → both frames must survive, rotation baked in
- APNG (used to collapse to one frame) → animation + pixels byte-identical
- EXIF hidden in an MPO's second frame → the verifier must flag it
- a tEXt chunk spliced **after** PNG's IEND → the verifier must flag it
- the JPEG final check (used to be dead code — `piexif.remove(bytes)` raises on 1.1.3 and the exception was swallowed) → now re-wipes with our own stripper and **fails loudly** if it can't
- in-place strip on a **symlink** (used to destroy the link and leave the target dirty) → link survives, target cleaned
- a **hard-linked** photo → warns you that the other name still points at pre-wipe data
- lossless WebP (used to be re-encoded lossy) → VP8L in, VP8L out, pixels identical
- setuid/sticky bits (used to survive the atomic rewrite) → masked off
- `-o victim.txt` → overwrites only with a warning, refuses with `--no-clobber`
- a 10-frame animation over the cumulative pixel budget → refused
- hostile TIFF IFD graphs (cycles, fake entry counts) → terminate, never hang
- mutation-fuzzed JPEG/GIF entropy streams → terminate, never hang
- the whole RAW family: CR2/DNG/BigTIFF fixtures handcrafted byte-by-byte, sensor data asserted byte-identical after the wipe

```bash
pip install pytest
python -m pytest            # 88 tests. They pass because they had to.
```

## Known limits (be honest about these)

- **PDF is best-effort**: embedded-image EXIF and exotic keys may survive. Strip the embedded images separately if provenance matters.
- **Animated AVIF is refused** rather than silently collapsed — re-save the frames yourself and scrub those.
- **HEIC/AVIF** still require `pip install pillow-heif` and are re-encoded, not byte-identical.
- Decompression bombs are refused by default (`--max-pixels N` to raise the 178M-pixel limit, `0` for unlimited), including a cumulative budget across animation frames.

## Why not just exiftool / mat2?

- **exiftool `-all=`**: needs Perl, and it's not installed on most boxes you'll actually run this on.
- **mat2**: great for folders of mixed audio/video/doc, but it's GObject-heavy for a single phone screenshot.

`exifwipe` is a narrow sharp knife for images. Use it on your own files before you publish them — not to launder someone else's. It's a screwdriver, not a suitcase.

## License

MIT — do whatever, it's still a screwdriver.
