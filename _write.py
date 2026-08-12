"""_write - exifwipe internal module: output paths, atomic writes, safety."""

from __future__ import annotations

import os
import secrets
import stat
import sys
from pathlib import Path
from typing import Optional

from _color import c_dim, c_head, c_ok, c_warn
from _config import _SYSTEM_DIRS


def _refuse_system_target(path: Path) -> None:
    """Refuse to write into top-level system directories so a stray -o
    can't drop an image into /etc or /usr. /tmp, /var, /home and
    /run/media (USB mounts) are fine."""
    try:
        parts = path.resolve().parts
    except Exception:
        return
    if len(parts) > 1 and parts[1] in _SYSTEM_DIRS:
        # /run/media/<user>/... is a legitimate removable-mount target
        if parts[1] == "run" and len(parts) > 2 and parts[2] == "media":
            return
        raise RuntimeError(
            f"refusing to write into system directory '/{parts[1]}' ({path}); "
            "use a user-writable location"
        )


def _atomic_write_bytes(path: Path, cleaned: bytes, st) -> None:
    """Write `cleaned` to `path` atomically via a private temp file that
    only we created (O_EXCL — no attacker can pre-plant a symlink at a
    predictable name), fsync it, then rename over the original.

    A symlink is resolved FIRST so the write lands on the target — the
    link itself is preserved (the old behavior replaced the symlink with
    a regular file AND left the target dirty, which was both silent and
    a leak).

    Mode and mtime of the original are preserved on the new inode so a
    0600 private photo stays 0600; setuid/setgid/sticky bits are NOT
    carried over (masked with 0o7777).
    """
    if path.is_symlink():
        path = path.resolve()
    for _ in range(10):
        tmp = path.with_name(f".{path.name}.exifwipe_tmp_{secrets.token_hex(8)}")
        try:
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            continue            # collision — try another random name
        except OSError as e:
            raise OSError(f"cannot create temp file for {path.name}: {e}") from e
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(cleaned)
                f.flush()
                os.fsync(f.fileno())
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        # preserve the permission bits only — setuid/setgid/sticky are
        # dropped (carrying them over would be sloppy and exploitable)
        os.chmod(tmp, stat.S_IMODE(st.st_mode) & 0o777)
        os.utime(tmp, ns=(st.st_atime_ns, st.st_mtime_ns))
        os.replace(tmp, path)
        return
    raise OSError(f"could not reserve a unique temp name for {path.name}")


def write_output(src: Path, out: Optional[Path], cleaned: bytes,
                 no_clobber: bool = False) -> None:
    """Either overwrite src in place, or write to `out` (file or dir)."""
    if out is None:
        _refuse_system_target(src)
        target = src
        if src.is_symlink():
            resolved = src.resolve()
            if not resolved.is_file():
                raise OSError(f"{src} is a dangling symlink — nothing to strip")
            target = resolved
            print(f"  {c_warn('[LINK]')} {c_head(str(src))} -> "
                  f"{c_head(str(target))} {c_dim('(stripping target in place)')}")
        st = target.stat()
        if st.st_nlink > 1:
            print(f"  {c_warn('[WARN]')} {c_head(str(target))} has "
                  f"{st.st_nlink} hard links — the other names still point "
                  "at the pre-wipe data", file=sys.stderr)
        _atomic_write_bytes(target, cleaned, st)
        print(f"  {c_ok('[STRIPPED]')} {c_head(str(src))}")
    else:
        # if user passed a folder or a path-without-suffix, drop src inside
        if out.is_dir() or (not out.suffix and not out.exists()):
            out = out / src.name
        _refuse_system_target(out)
        if no_clobber and out.exists():
            raise FileExistsError(f"{out} already exists (--no-clobber)")
        if out.exists() and out.resolve() != src.resolve():
            print(f"  {c_warn('[clobber]')} overwriting existing "
                  f"{c_head(str(out))}", file=sys.stderr)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(cleaned)
        print(f"  {c_ok('[STRIPPED]')} {c_head(str(src))}  {c_dim('->')}  "
              f"{c_head(str(out))}")
