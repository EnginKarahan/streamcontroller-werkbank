"""Shared plumbing for all Werkbank actions.

The real work happens in the `werkbank` core, called through werkbank-cli on
the host. StreamController usually runs as a Flatpak, where KWin, kitty and
the user's programs are out of reach; flatpak-spawn --host bridges that.
"""

from __future__ import annotations

import collections
import json
import os
import subprocess
import threading
import time

from loguru import logger as log

from src.backend.PluginManager.ActionBase import ActionBase

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from werkbank.icons import cached_path  # noqa: E402

IN_FLATPAK = os.path.exists("/.flatpak-info")
GREEN = [46, 160, 67, 255]
RED = [200, 50, 50, 255]
GREY = [60, 60, 60, 255]
NONE = [0, 0, 0, 0]


def host(argv: list[str]) -> list[str]:
    # Without --directory the host process would inherit the sandbox's cwd
    # (/app/bin/...), which does not exist on the host, and fail to start.
    if IN_FLATPAK:
        return ["flatpak-spawn", "--host", f"--directory={os.path.expanduser('~')}", *argv]
    return argv


# Each flatpak-spawn opens its own D-Bus connection; when a page loads, every
# key resolves its icon and status at once and the sandbox's D-Bus proxy
# starts refusing ("Can't find bus: ... temporarily unavailable"). So: few
# host calls at a time, and a short retry for the refusals that still occur.
HOST_SLOTS = threading.BoundedSemaphore(4)
BUS_BUSY = "Can't find bus"


def run_host(argv: list[str], timeout: float) -> subprocess.CompletedProcess:
    for attempt in range(4):
        with HOST_SLOTS:
            proc = subprocess.run(host(argv), capture_output=True, text=True, timeout=timeout)
        if not (IN_FLATPAK and proc.returncode != 0 and BUS_BUSY in proc.stderr):
            return proc
        time.sleep(0.2 * (attempt + 1))
    return proc


class Field:
    """One setting with its config row. kind: entry | switch | spin."""

    def __init__(self, key, title, kind="entry", default="", subtitle=None, rng=(0, 3600, 1)):
        self.key, self.title, self.kind = key, title, kind
        self.default, self.subtitle, self.rng = default, subtitle, rng


ICON = Field("icon", "Icon (app id, icon name or file)",
             subtitle="from your icon theme, e.g. org.telegram.desktop or media-record")


class WerkbankAction(ActionBase):
    FIELDS: list[Field] = []
    DEFAULT_ICON = ""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.has_configuration = True
        self._busy = threading.Lock()
        self._pending = collections.deque()
        self._visual: dict = {}  # last status text/color, re-applied in on_update

    # -- settings ---------------------------------------------------------
    def setting(self, key):
        default = next((f.default for f in self.FIELDS if f.key == key), "")
        return self.get_settings().get(key, default)

    def default_icon(self) -> str:
        return self.DEFAULT_ICON

    def on_ready(self):
        self.show_app_icon(self.setting("icon") or self.default_icon())

    def on_update(self):
        """StreamController clears media and labels when it (re)loads a page and
        then calls on_update; redraw icon, status text and color here."""
        super().on_update()  # calls on_ready (icon)
        if "text" in self._visual:
            self.set_center_label(self._visual["text"], font_size=self._visual.get("size", 14))
        if "color" in self._visual:
            self.set_background_color(self._visual["color"])

    def show_status(self, text: str | None = None, color: list | None = None, size: int = 14) -> None:
        """Set (and remember) the status text and/or color. Call from on_tick or via ui()."""
        if text is not None:
            self._visual.update(text=text, size=size)
            self.set_center_label(text, font_size=size)
        if color is not None:
            self._visual["color"] = color
            self.set_background_color(color)

    def t(self, key: str, fallback: str) -> str:
        return self.plugin_base.locale_manager.get(key, fallback)

    def get_config_rows(self):
        rows = []
        for f in [*self.FIELDS, ICON]:
            title = self.t(f"field.{f.key}", f.title)
            value = self.setting(f.key)
            if f.kind == "switch":
                row = Adw.SwitchRow(title=title)
                row.set_active(bool(value))
                row.connect("notify::active", lambda w, _p, k=f.key: self._store(k, w.get_active()))
            elif f.kind == "spin":
                row = Adw.SpinRow.new_with_range(*f.rng)
                row.set_title(title)
                row.set_value(float(value or 0))
                row.connect("changed", lambda w, k=f.key: self._store(k, w.get_value()))
            else:
                row = Adw.EntryRow(title=title)
                row.set_text(str(value or ""))
                row.connect("notify::text", lambda w, _p, k=f.key: self._store(k, w.get_text()))
            if f.subtitle and hasattr(row, "set_subtitle"):
                row.set_subtitle(self.t(f"field.{f.key}.hint", f.subtitle))
            rows.append(row)
        return rows

    def _store(self, key, value):
        settings = self.get_settings()
        settings[key] = value
        self.set_settings(settings)
        self.on_settings_changed()

    def on_settings_changed(self):
        self.show_app_icon(self.setting("icon") or self.default_icon())

    # -- running things on the host ----------------------------------------
    def core(self, *args: str, timeout: float = 30) -> dict:
        """Run werkbank-cli on the host and return its JSON answer."""
        cli = os.path.join(self.plugin_base.PATH, "werkbank-cli")
        try:
            proc = run_host(["python3", cli, *args], timeout)
        except subprocess.TimeoutExpired:
            log.error(f"Werkbank: werkbank-cli {args[0]} timed out")
            return {"ok": False, "error": "timeout"}
        if proc.stderr.strip():
            log.warning(f"Werkbank: {proc.stderr.strip()}")
        try:
            return json.loads(proc.stdout.strip().splitlines()[-1])
        except (json.JSONDecodeError, IndexError):
            log.error(f"Werkbank: no answer from werkbank-cli {args[0]} (rc {proc.returncode})")
            return {"ok": False, "error": "no answer"}

    def shell(self, command: str, wait: bool = False, timeout: float = 30) -> int | None:
        """Run a shell command on the host in a login shell (user's PATH)."""
        if not command.strip():
            return None
        if not wait:
            subprocess.Popen(host(["sh", "-lc", command]), start_new_session=True, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return None
        try:
            return run_host(["sh", "-lc", command], timeout).returncode
        except subprocess.TimeoutExpired:
            log.error(f"Werkbank: command timed out: {command}")
            return None

    def in_background(self, fn, *args) -> None:
        """Keep the deck responsive; drop presses while one is still running."""
        if not self._busy.acquire(blocking=False):
            return

        def run():
            try:
                fn(*args)
            except Exception as err:
                log.error(f"Werkbank: {type(self).__name__} failed: {err}")
                self.ui(self.show_error, duration=2)
            finally:
                self._busy.release()
        threading.Thread(target=run, daemon=True, name="werkbank").start()

    def show_app_icon(self, spec: str) -> None:
        """Put an app's icon (app id, icon name or path) on the key.

        Resolved on the host, where the icon themes live; an image the user
        picked in StreamController always wins.
        """
        if not spec or self.has_custom_user_asset():
            return
        cached = cached_path(spec)
        if cached.is_file():  # the usual case: no host call, set right away
            self.set_media(media_path=str(cached), size=0.7, valign=-0.3)
            return

        def run():
            result = self.core("icon", spec)
            if result.get("ok"):
                self.ui(self.set_media, media_path=result["path"], size=0.7, valign=-0.3)
            else:
                log.warning(f"Werkbank: no icon found for {spec!r}")
        threading.Thread(target=run, daemon=True, name="werkbank-icon").start()

    def ui(self, fn, *args, **kwargs) -> None:
        """Queue a key update; on_tick applies it on the deck's tick thread.

        Updates made straight from our worker threads or via GLib.idle_add
        did not reliably reach the key; official plugins (e.g. Clocks)
        update from on_tick, so we do the same.
        """
        self._pending.append((fn, args, kwargs))

    def on_tick(self):
        while self._pending:
            fn, args, kwargs = self._pending.popleft()
            try:
                fn(*args, **kwargs)
            except Exception as err:
                log.error(f"Werkbank: key update failed: {err}")

    def report(self, result: dict) -> None:
        if not result.get("ok"):
            log.error(f"Werkbank: {type(self).__name__}: {result.get('error') or result}")
            self.ui(self.show_error, duration=2)
