---
name: Bug report
about: Something isn't being stripped, or a file got corrupted
title: "[bug] "
labels: bug
assignees: ""
---

**What were you stripping?**

- File format: (JPEG / PNG / GIF / WebP / TIFF / RAW: which vendor / HEIC / AVIF / PDF / RAF)
- How the file was made: (camera model, phone, app, downloaded, edited in X)
- File size if small enough to attach (strip real GPS data first)

**Exact command you ran**

```bash
exifwipe ... [flags] file
```

**What did you expect, and what happened?**

(e.g. "exiftool still shows GPS after the wipe" / "the file got corrupted and won't open")

**Did --report / --verify say anything?**

Paste the output of `exifwipe file --report --verify` here. If it failed, paste the error.

**Environment**

- OS / distro:
- Python version (`python3 --version`):
- Pillow version (`python3 -c "import PIL; print(PIL.__version__)"`):
- exifwipe version (`exifwipe --version`):

