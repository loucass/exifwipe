#!/usr/bin/env python3
"""Benchmark exifwipe — throughput per format, honest numbers.

Generates its own fixtures (never touches your files), times a real
strip for each format, and prints ms/op + MB/s. Run:

    python3 benchmarks/bench.py            # full run (8MP fixtures)
    python3 benchmarks/bench.py --quick    # tiny fixtures, 1 iteration
    python3 benchmarks/bench.py --json     # machine-readable results

The numbers in the README were produced by `python3 benchmarks/bench.py`
on a stock dev box. Yours will differ. That's physics.
"""

import argparse
import io
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import exifwipe  # noqa: E402
from PIL import Image  # noqa: E402
from PIL.PngImagePlugin import PngInfo  # noqa: E402
import piexif  # noqa: E402

JPEG_EXIF = piexif.dump({
    "0th": {0x010F: b"BenchCam", 0x0112: 1, 0x0131: b"BenchFW"},
    "Exif": {0x9003: b"2024:01:02 03:04:05", 0x9286: b"BenchComment"},
    "GPS": {2: ((37, 1), (30, 1), (0, 1))},
})


def _jpeg(path, size, orient=1, quality=90):
    Image.new("RGB", size, (200, 30, 30)).save(
        path, format="JPEG", quality=quality,
        exif=piexif.dump({"0th": {0x010F: b"BenchCam", 0x0112: orient,
                                  0x0131: b"BenchFW"},
                          "Exif": {0x9003: b"2024:01:02 03:04:05"}}))
    return path


def _png(path, size):
    meta = PngInfo()
    meta.add_text("Comment", "leaky comment")
    Image.new("RGBA", size, (10, 200, 30, 255)).save(
        path, format="PNG", pnginfo=meta, exif=JPEG_EXIF)
    return path


def _gif(path, frames=5, size=(512, 512)):
    imgs = [Image.new("RGB", size, (i * 50 % 255, 30, 40))
            for i in range(frames)]
    imgs[0].save(path, format="GIF", save_all=True, append_images=imgs[1:],
                 duration=[100] * frames, loop=0)
    return path


def _webp(path, size):
    Image.new("RGBA", size, (10, 200, 30, 255)).save(
        path, format="WEBP", quality=90, exif=JPEG_EXIF,
        xmp=b"<x:xmpmeta>bench</x:xmpmeta>")
    return path


def _tiff(path, size):
    Image.new("RGB", size, (5, 60, 200)).save(
        path, format="TIFF", description="leaky description",
        software="leaky software")
    return path


def _build_fixtures(tmp: Path, quick: bool) -> dict:
    n = 8 if not quick else 1
    size = (80, 60) if quick else (4096, 2048)   # ~8.4 MP
    gif_size = (80, 60) if quick else (512, 512)
    return {
        "jpeg (lossless)": _jpeg(tmp / "a.jpg", size),
        "jpeg (rotated)": _jpeg(tmp / "b.jpg", size, orient=6),
        "png": _png(tmp / "c.png", size),
        "gif (5 frames)": _gif(tmp / "d.gif", size=gif_size),
        "webp": _webp(tmp / "e.webp", size),
        "tiff (surgery)": _tiff(tmp / "f.tiff", size),
    }


def bench(path: Path, iterations: int) -> dict:
    """Time strip_image_bytes on one fixture, return stats."""
    best = float("inf")
    sizes = []
    for i in range(iterations):
        data = path.read_bytes()
        t0 = time.perf_counter()
        cleaned, fmt = exifwipe.strip_image_bytes(path)
        dt = (time.perf_counter() - t0) * 1000
        best = min(best, dt)
        sizes.append((len(data), len(cleaned)))
    in_bytes = sum(s[0] for s in sizes) / len(sizes)
    out_bytes = sum(s[1] for s in sizes) / len(sizes)
    return {
        "ms_best": best,
        "ms_avg": None,
        "in_kb": in_bytes / 1024,
        "out_kb": out_bytes / 1024,
        "mbps": (in_bytes / 1024 / 1024) / (best / 1000),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--quick", action="store_true",
                    help="tiny fixtures, 1 iteration (CI smoke)")
    ap.add_argument("--iterations", type=int, default=3)
    ap.add_argument("--json", action="store_true", help="emit JSON")
    args = ap.parse_args()

    with tempfile.TemporaryDirectory(prefix="exifwipe_bench_") as td:
        fixtures = _build_fixtures(Path(td), args.quick)
        results = {}
        for name, path in fixtures.items():
            results[name] = bench(path, args.iterations if not args.quick else 1)

    if args.json:
        import json
        print(json.dumps(results, indent=2))
        return 0

    w = max(len(n) for n in results)
    print("format".ljust(w), " in(KB)  out(KB)   ms/op   MB/s")
    print("-" * (w + 40))
    for name, r in results.items():
        print(f"{name.ljust(w)} {r['in_kb']:>7.0f}  {r['out_kb']:>7.0f}  "
              f"{r['ms_best']:>7.1f}  {r['mbps']:>6.1f}")
    print("\nbest-of-N ms/op; MB/s is input bytes over that time.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
