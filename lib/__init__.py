"""exifwipe internals — one module per format/concern.

Not a public API; everything is re-exported through the root `exifwipe`
facade so `import exifwipe` keeps working. The layout:

    _config  formats, vendor MakerNotes, constants
    _color   ANSI output helpers
    _inspect metadata inventory
    _verify  exiftool referee + per-format leak scanners
    _tiff    TIFF/RAW IFD surgery
    _pixels  orientation / perturbation / frame rebuild
    _jpeg    JPEG marker machinery
    _gif/_png/_webp/_heif/_raf/_pdf  per-format strippers
    _report  report inventory
    _sniff   format detection from magic bytes
    _write   atomic writes, output paths
    _driver  strip dispatcher + handle_one
    _menu    interactive menu
    _cli     argparse + main
"""
