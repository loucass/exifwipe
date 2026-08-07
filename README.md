# exifwipe

Make ExifTool return blank on any image (or PDF) you're about to publish.

I wrote this because between "screenshot it" and "upload it" there's
one perfectly sized gap where your phone model, GPS, or even your
name starts living in a file forever. `exiftool -all=` exists and works,
but it leaves the APP0/JFIF stub behind and can be picky about MakerNotes.
`exifwipe` rebuilds the image from raw pixels instead, so the metadata
isn't just deleted — it's never there.

## Install

Requires Python 3.9+. Pillow is mandatory; the rest are optional and
degrade gracefully if absent.

```bash
pip install exifwipe            # or: pipx install .
```

System-managed Pillow is usually better on Linux (gets you the C
image codecs):

```bash
# Debian / Ubuntu
sudo apt install python3-pil
pip install piexif              # for the JPEG round-trip verify

# Arch
sudo pacman -S python-pillow
pip install piexif

# Fedora
sudo dnf install python-pillow
pip install piexif
```

## Use

```bash
exifwipe photo.jpg                  # strip in place
exifwipe ./images/ -o ./clean/      # batch a folder to a new one
exifwipe photo.jpg --inspect        # show what exiftool would see
exifwipe photo.jpg --dry-run        # inspect without writing
exifwipe photo.jpg --keep-icc       # keep the ICC profile (rarely matters)
```

Alias it if you're lazy like me:

```bash
alias screenclean="exifwipe ~/Pictures/Screenshots/*.png"
```

## What it removes

| Format  | What goes away |
|---------|----------------|
| JPEG    | EXIF IFD0/IFD1/ExifIFD/GPS/Interop, MakerNotes, Photoshop 8BIM, COM markers, APP1/APP2 |
| PNG     | tEXt / zTXt / iTXt, eXIf, pHYs, iCCP |
| WebP    | EXIF + XMP containers |
| TIFF    | full tag block |
| HEIC/AVIF | EXIF (with pillow-heif) |
| PDF     | /DocInfo + XMP stream (with pikepdf) |

A tiny bit is kept on purpose (JFIF version/density, pixel dimensions)
because some viewers refuse to open JPEGs without that header. It's
structural, not identifying.

## How the strip works

Three layers, because "just one" quietly fails sometimes:

1. **Pixel rebuild** — `list(getdata()) -> Image.new() -> putdata()`.
   Breaks the borrow of the source frame's metadata reference. Same
   trick production scrubbers use (e.g.
   `comfyui-mcp-server/asset_processor.py`, and the pattern in
   `MK2112/any_to_any.py`'s metadata handler).
2. **Explicit empty writes** — `exif=b""` (JPEG/PNG/WebP), `xmp=b""`
   (WebP), empty `pnginfo` (PNG). This is the pattern Pillow's own
   security-guide blesses.
3. **piexif round-trip verify** — after Pillow saves, we re-load with
   `piexif.load()` and re-wipe any IFD that claws its way back. This
   is the bug-class that imgproxy#668 documented.

## Why not just exiftool / mat2?

- **exiftool `-all=`**: standard, but leaves the APP0/JFIF marker and
  truncates some Canon MakerNotes instead of removing them. Benchmarked
  after handling those cases.
- **mat2** — good, heavier (GObject, mutagen), CLI+GUI, also scrubs
  audio/video/doc. Use it when your problem is "entire folder of mixed
  content." Single-use image cleanup lives shorter here.

## License

MIT — do whatever, it's a screwdriver, not a suitcase.