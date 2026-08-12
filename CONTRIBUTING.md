# Contributing

Thanks for wanting to help. This is a small tool, and small is a feature — keep that in mind before adding stuff.

## Setting up

```bash
git clone https://github.com/loucass/exifwipe
cd exifwipe
pip install -e ".[dev]"
```

## Running the tests

```bash
python -m pytest
```

Run them before you commit anything. If your change doesn't keep the suite green, it doesn't land.

## The one rule that matters

**For lossless paths, the pixels are never touched.** JPEG markers, GIF bytes, RAW/HEIC/AVIF surgery — these must stay byte-identical. If your change re-encodes a pixel that was previously untouched, it's a regression, not an improvement.

The suite has tests for exactly this (byte-for-byte comparisons after wipe). If your change can't keep those green, don't send it.

## Filing issues

Use the templates (bug report / feature request). For a bug, include:

- the file format and how it was made (camera, app)
- what you ran (full command with flags)
- the `--report` or `--verify` output
- Python version, OS, Pillow version

No anonymous dumps "it didn't work".

## Security

This tool deletes metadata for a living. If you find a way it leaks data it claims to remove, file a bug report.
