"""Send shortcuts and text to the focused window with dotool, layout-correct.

dotool treats plain key names as *physical* keys in US positions, so on a
German keyboard "ctrl+z" would arrive as Ctrl+Y and "minus" as ß. Names
prefixed with "x:" are resolved through the active XKB layout instead.
This module writes shortcuts the way they are meant ("ctrl+z") and adds the
prefix for letters and punctuation; special keys (enter, f5, pageup, raw
"k:13") are layout independent and stay as they are.

Needs dotool (https://git.sr.ht/~geb/dotool) and write access to /dev/uinput
(usually: member of the "input" group).
"""

from __future__ import annotations

import configparser
import os
import shutil
import subprocess
from pathlib import Path

LAYOUT_CHARS = set("abcdefghijklmnopqrstuvwxyz") | {
    "minus", "plus", "equal", "slash", "backslash", "comma", "period", "numbersign",
    "grave", "less", "greater", "bracketleft", "bracketright", "semicolon", "apostrophe"}


class KeysError(RuntimeError):
    pass


def translate(keys: str) -> str:
    """'ctrl+z f5' -> 'ctrl+x:z f5' (space separates chords)."""
    chords = []
    for chord in keys.split():
        *mods, key = chord.split("+")
        if key in LAYOUT_CHARS:
            key = "x:" + key
        chords.append("+".join([*mods, key]))
    return " ".join(chords)


def current_layout() -> str | None:
    """First layout of the Plasma session (kxkbrc), unless DOTOOL_XKB_LAYOUT is set."""
    if os.environ.get("DOTOOL_XKB_LAYOUT"):
        return os.environ["DOTOOL_XKB_LAYOUT"]
    rc = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "kxkbrc"
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    try:
        parser.read(rc, encoding="utf-8")
        layouts = parser.get("Layout", "LayoutList", fallback="")
    except configparser.Error:
        return None
    first = layouts.split(",")[0].strip()
    return first or None


def _dotool(script: str) -> None:
    exe = shutil.which("dotool")
    if exe is None:
        raise KeysError("dotool is not installed")
    env = dict(os.environ)
    layout = current_layout()
    if layout:
        env["DOTOOL_XKB_LAYOUT"] = layout
    proc = subprocess.run([exe], input=script, text=True, env=env,
                          capture_output=True, timeout=10)
    if proc.returncode != 0:
        raise KeysError(proc.stderr.strip() or f"dotool exited with {proc.returncode}")


def send(keys: str) -> str:
    """Press the shortcut(s); returns what was sent to dotool."""
    translated = translate(keys)
    _dotool(f"key {translated}\n")
    return translated


def type_text(text: str, enter: bool = False) -> None:
    """Type text in the active layout (dotool 'type' is layout aware already)."""
    script = "".join(f"type {line}\n" for line in text.split("\n"))
    _dotool(script + ("key enter\n" if enter else ""))
