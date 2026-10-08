"""Find an app's icon on this machine and render it as a PNG for a key.

Nothing is bundled: the icon comes from the app's .desktop file and the
user's icon theme, so every user sees their own apps' icons and the plugin
ships no third-party logos.

The PNG goes to ~/.cache/werkbank/icons, a path the sandboxed StreamController
can read (it has access to $HOME, not to /usr or /var/lib/flatpak).
"""

from __future__ import annotations

import configparser
import logging
import os
import re
from pathlib import Path

logger = logging.getLogger(__name__)

CACHE = Path.home() / ".cache" / "werkbank" / "icons"
SIZE = 256
# hicolor: 48x48/apps/x.png, Breeze: actions/32/x.svg
_SIZE_DIR = re.compile(r"/(\d+)(?:x\d+)?(?:@\dx?)?/")


def data_dirs() -> list[Path]:
    dirs = [Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))]
    dirs += [Path(d) for d in os.environ.get("XDG_DATA_DIRS", "").split(":") if d]
    dirs += [Path.home() / ".local/share/flatpak/exports/share",
             Path("/var/lib/flatpak/exports/share"),
             Path("/usr/local/share"), Path("/usr/share")]
    seen, out = set(), []
    for d in dirs:
        if d not in seen:
            seen.add(d)
            out.append(d)
    return out


def _entry(path: Path) -> dict[str, str]:
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    try:
        parser.read(path, encoding="utf-8")
        return dict(parser["Desktop Entry"]) if parser.has_section("Desktop Entry") else {}
    except configparser.Error as err:
        logger.warning("cannot read %s: %s", path, err)
        return {}


def desktop_icon(app_id: str) -> str | None:
    """Icon= of <app_id>.desktop, or of the entry whose Exec runs `app_id`.

    The second form lets a key guess the icon from a plain start command
    ("dolphin", "~/bin/resolve-wrapper.sh").
    """
    files = [d / "applications" for d in data_dirs()]
    for apps in files:
        path = apps / f"{app_id}.desktop"
        if path.is_file():
            return _entry(path).get("icon")
    program = Path(app_id).name
    for apps in files:
        if not apps.is_dir():
            continue
        for path in sorted(apps.glob("*.desktop")):
            entry = _entry(path)
            exe = entry.get("exec", "").split()
            if exe and Path(exe[0].strip('"')).name == program and entry.get("icon"):
                return entry["icon"]
    return None


def current_theme() -> str:
    """Icon theme of the Plasma session, following KDE's config cascade.

    The value often lives only in kdedefaults/kdeglobals (set by the global
    theme), not in ~/.config/kdeglobals.
    """
    config = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    for path in (config / "kdeglobals", config / "kdedefaults" / "kdeglobals",
                 Path("/etc/xdg/kdeglobals")):
        parser = configparser.ConfigParser(interpolation=None, strict=False)
        try:
            parser.read(path, encoding="utf-8")
        except configparser.Error:
            continue
        theme = parser.get("Icons", "Theme", fallback=None)
        if theme:
            return theme
    return "hicolor"


def _icon_roots() -> list[Path]:
    return [Path.home() / ".icons"] + [d / "icons" for d in data_dirs()]


def theme_chain(theme: str) -> list[str]:
    """The theme and everything it inherits from, ending with hicolor."""
    chain, todo = [], [theme]
    while todo:
        name = todo.pop(0)
        if name in chain:
            continue
        chain.append(name)
        for root in _icon_roots():
            index = root / name / "index.theme"
            if index.is_file():
                parser = configparser.ConfigParser(interpolation=None, strict=False)
                try:
                    parser.read(index, encoding="utf-8")
                    todo += [t.strip() for t in parser.get("Icon Theme", "Inherits",
                                                           fallback="").split(",") if t.strip()]
                except configparser.Error:
                    pass
                break
    if "hicolor" not in chain:
        chain.append("hicolor")
    return chain


def _rank(path: Path) -> int:
    """Higher is better: SVG over bitmap, then the largest size."""
    m = _SIZE_DIR.search(str(path))
    size = int(m.group(1)) if m else (512 if "scalable" in path.parts else 0)
    return size + (100_000 if path.suffix == ".svg" else 0)


def lookup(name: str, theme: str | None = None) -> Path | None:
    """Best file for an icon name in the theme chain, then /usr/share/pixmaps."""
    for t in theme_chain(theme or current_theme()):
        hits = []
        for root in _icon_roots():
            base = root / t
            if base.is_dir():
                # Fixed depth instead of rglob: themes link whole directories
                # (Breeze: 22@2x -> 22), and rglob does not follow those.
                hits += [p for ext in ("svg", "png")
                         for pattern in (f"*/*/{name}.{ext}", f"*/{name}.{ext}")
                         for p in base.glob(pattern)]
        if hits:
            return max(hits, key=_rank)
    for d in data_dirs():
        for ext in ("svg", "png"):
            p = d / "pixmaps" / f"{name}.{ext}"
            if p.is_file():
                return p
    return None


def find(spec: str) -> Path | None:
    """Icon file for an app id, an icon name or a path."""
    candidate = Path(spec).expanduser()
    if candidate.is_absolute():
        return candidate if candidate.is_file() else None
    icon = desktop_icon(spec) or spec
    if Path(icon).is_absolute():
        return Path(icon) if Path(icon).is_file() else None
    return lookup(icon)


def cached_path(spec: str, size: int = SIZE) -> Path:
    """Where render() puts the PNG; the plugin checks it to skip a host call.

    For a file path the modification time is part of the name, so an edited
    icon file shows up instead of the cached old one.
    """
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", spec)
    path = Path(spec).expanduser()
    if path.is_absolute() and path.is_file():
        safe += f"-{int(path.stat().st_mtime)}"
    return CACHE / f"{safe}-{size}.png"


def render(spec: str, size: int = SIZE) -> Path | None:
    """PNG of the icon in the cache (created once). None if not found."""
    out = cached_path(spec, size)
    if out.is_file():
        return out
    src = find(spec)
    if src is None:
        return None

    import gi
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf, GLib

    try:
        pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(src), size, size, True)
    except GLib.Error as err:
        logger.error("cannot load icon %s: %s", src, err.message)
        return None
    CACHE.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(f".{os.getpid()}.tmp")  # keys may render the same icon at once
    pixbuf.savev(str(tmp), "png", [], [])
    tmp.replace(out)
    return out
