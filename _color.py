"""_color - exifwipe internal module (format/strip machinery)."""

from __future__ import annotations



import os
import sys
from typing import Optional
try:
    import readline  # arrow keys / history (linux) - best-effort
except ImportError:
    readline = None

def _can_color() -> bool:
    """Respect NO_COLOR, and don't colorize when output is piped."""
    if os.environ.get("NO_COLOR"):
        return False
    try:
        return bool(sys.stdout.isatty())
    except Exception:
        return False


_COLOR = _can_color()


def set_color(on: Optional[bool]) -> None:
    """Turn colorization on/off (None -> auto-detect on a tty)."""
    global _COLOR
    if on is None:
        _COLOR = _can_color()
    else:
        _COLOR = bool(on)


def _c(text, code, bold=True):
    if not _COLOR:
        return str(text)
    return f"\033[{'1;' if bold else ''}{code}m{text}\033[0m"


def c_ok(t):    return _c(t, "32")                     # green


def c_err(t):   return _c(t, "31")                     # red


def c_warn(t):  return _c(t, "33")                     # yellow


def c_info(t):  return _c(t, "36", bold=False)         # cyan, non-bold


def c_head(t):  return _c(t, "36")                     # cyan, bold


def c_dim(t):   return _c(t, "90", bold=False)         # gray


def c_mag(t):   return _c(t, "35")                     # magenta


def c_blue(t):  return _c(t, "34")                     # blue

