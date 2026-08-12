"""_pdf - exifwipe internal module (format/strip machinery)."""

from __future__ import annotations



import io
import sys
from pathlib import Path
from PIL import Image

from lib._color import c_err, c_warn

def strip_pdf_bytes(path: Path) -> bytes:
    """Strip /DocInfo + XMP from PDF via pikepdf.

    pikepdf is python-only on most distros. If you don't have it,
    fall back to:  qpdf --empty --pages in.pdf -- out.pdf
    (qpdf is in apt / pacman / dnf, usually preinstalled on Kali).
    """
    try:
        import pikepdf
    except ImportError:
        print(
            f"  ! PDF strip needs pikepdf ( pip3 install pikepdf )\n"
            f"  ! OR shell fallback: qpdf --linearize --encrypt '' '' 0 -- "
            f"{path.name} --", file=sys.stderr
        )
        return b""

    try:
        with pikepdf.open(path, allow_overwriting_input=True) as pdf:
            root = pdf.Root
            if root is not None:
                for key in ("/Metadata", "/Lang", "/OpenAction", "/PieceInfo",
                            "/StructTreeRoot", "/PageLabels", "/MarkInfo"):
                    try:
                        if key in root:
                            del root[key]  # pikepdf: del removes the key
                    except Exception:
                        pass
            try:
                # /Info (DocInfo) holds title/author/creator/date...
                # Clearing to an empty indirect dictionary removes every
                # /Info key.
                pdf.docinfo = pdf.make_indirect(pikepdf.Dictionary())
            except Exception:
                try:
                    del pdf.trailer["/Info"]
                except Exception:
                    pass
            buf = io.BytesIO()
            pdf.save(buf)
            return buf.getvalue()
    except Exception as e:
        # corrupt / encrypted / half-written PDF — be a failure, not a
        # silent "processed" (caller uses return b"" to skip the write)
        print(f"  {c_err('[ERR]')} {c_warn(path.name)}: PDF strip failed: {e}",
              file=sys.stderr)
        return b""

