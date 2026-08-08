"""_menu - exifwipe internal module (format/strip machinery)."""

from __future__ import annotations



import argparse
import sys
from pathlib import Path

from _color import c_blue, c_dim, c_err, c_head, c_info, c_mag, c_ok, c_warn
from _config import R_ERR, R_OK, _MENU_ART
from _driver import handle_one, iter_inputs

def print_top_banner() -> None:
    for line in _MENU_ART.splitlines():
        print(c_blue(line))
    print(c_dim("    wipe EXIF from images and PDFs — pick a move, hit Enter"))
    print()


def prompt_input(label: str) -> str:
    try:
        return input(f"  {c_info(label + '')} > ")
    except (EOFError, KeyboardInterrupt):
        print()
        return ""


def _clear_screen() -> None:
    """Clear the terminal before re-rendering the menu (ANSI). No-op
    when output is piped, so redirects and the test suite stay clean."""
    try:
        if sys.stdout.isatty():
            sys.stdout.write("\x1b[2J\x1b[H")
            sys.stdout.flush()
    except Exception:
        pass


def _pause_if_tty() -> None:
    """Hold the screen after an action's output so the user can read it
    before the next clear+re-render wipes it away. No-op when piped."""
    try:
        if sys.stdout.isatty():
            input("    press Enter to continue")
    except (EOFError, KeyboardInterrupt):
        print()


def _run_menu_action(action: str, path: Path, keep_icc: bool, dry_run: bool) -> None:
    """Run one interactive operation against a path (reuses handle_one)."""
    ns = argparse.Namespace(output=None, keep_icc=keep_icc, dry_run=dry_run,
                            inspect=False, verbose=False, max_pixels=None,
                            no_clobber=False)
    if action == "inspect":
        ns.inspect = True

    targets = list(iter_inputs(path))
    if not targets:
        print(c_warn("    nothing processed (no supported files found)"))
        return
    n_ok = n_err = n_skip = 0
    for p in targets:
        res = handle_one(p, ns)
        if res == R_OK:
            n_ok += 1
        elif res == R_ERR:
            n_err += 1
        else:
            n_skip += 1
    msg = f"\n  {c_ok(str(n_ok))} processed"
    if n_skip:
        msg += f", {c_dim(str(n_skip))} skipped"
    if n_err:
        msg += f", {c_err(str(n_err))} errors"
    print(msg)


def _state(val: bool) -> str:
    return c_ok("on") if val else c_err("off")


def menu_choose(keep_icc: bool, dry_run: bool) -> str:
    print()
    print(c_head("  ▸ what do you want to do?"))
    print(f"    {c_head('[1]')} strip one file")
    print(f"    {c_head('[2]')} strip a whole folder (recursive)")
    print(f"    {c_head('[3]')} inspect a file (see what ExifTool would surface)")
    print(f"    {c_head('[4]')} dry-run a file or folder (no writes)")
    print(f"    {c_head('[5]')} toggle: keep ICC profile    now: {c_mag('[ ' + _state(keep_icc) + ' ]')}")
    print(f"    {c_head('[6]')} toggle: dry-run             now: {c_mag('[ ' + _state(dry_run) + ' ]')}")
    print(f"    {c_head('[q]')} quit")
    return prompt_input("choice")


def run_interactive_menu() -> int:
    keep_icc, dry_run = False, False
    while True:
        # clear + re-render every pass: the terminal never piles menus
        # on top of previous output
        _clear_screen()
        print_top_banner()
        choice = menu_choose(keep_icc, dry_run).strip().lower()
        if choice in ("q", "quit", "exit", ""):
            # clear the TUI off the screen, then sign off
            _clear_screen()
            print(c_blue("    0x-goodbye — metadata wiped, pixels clean."))
            print(c_dim("    now go post it before someone else does."))
            return 0
        if choice == "5":
            keep_icc = not keep_icc
            continue
        if choice == "6":
            dry_run = not dry_run
            continue
        if choice not in ("1", "2", "3", "4"):
            print(c_warn("    pick 1-6 or q."))
            _pause_if_tty()
            continue
        raw = prompt_input("Target path").strip()
        if not raw:
            continue
        path = Path(raw).expanduser()
        if not path.exists():
            print(c_err(f"    not found: {path}"))
            _pause_if_tty()
            continue
        action = {"1": "strip", "2": "strip", "3": "inspect", "4": "dry"}[choice]
        # "4" is a one-shot dry-run: it must NOT flip the persistent toggle.
        _run_menu_action(action, path, keep_icc, dry_run or action == "dry")
        _pause_if_tty()

