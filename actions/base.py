"""Shared plumbing for all Werkbank actions.

The real work happens in the `werkbank` core, called through werkbank-cli on
the host. StreamController usually runs as a Flatpak, where KWin, kitty and
the user's programs are out of reach; flatpak-spawn --host bridges that.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading

from loguru import logger as log

from src.backend.PluginManager.ActionBase import ActionBase

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

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


class Field:
    """One setting with its config row. kind: entry | switch | spin."""

    def __init__(self, key, title, kind="entry", default="", subtitle=None, rng=(0, 3600, 1)):
        self.key, self.title, self.kind = key, title, kind
        self.default, self.subtitle, self.rng = default, subtitle, rng


class WerkbankAction(ActionBase):
    FIELDS: list[Field] = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.has_configuration = True
        self._busy = threading.Lock()

    # -- settings ---------------------------------------------------------
    def setting(self, key):
        default = next((f.default for f in self.FIELDS if f.key == key), "")
        return self.get_settings().get(key, default)

    def t(self, key: str, fallback: str) -> str:
        return self.plugin_base.locale_manager.get(key, fallback)

    def get_config_rows(self):
        rows = []
        for f in self.FIELDS:
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
        pass

    # -- running things on the host ----------------------------------------
    def core(self, *args: str, timeout: float = 30) -> dict:
        """Run werkbank-cli on the host and return its JSON answer."""
        cli = os.path.join(self.plugin_base.PATH, "werkbank-cli")
        try:
            proc = subprocess.run(host(["python3", cli, *args]), capture_output=True,
                                  text=True, timeout=timeout)
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
        argv = host(["sh", "-lc", command])
        if not wait:
            subprocess.Popen(argv, start_new_session=True, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return None
        try:
            return subprocess.run(argv, capture_output=True, timeout=timeout).returncode
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
                self.show_error(duration=2)
            finally:
                self._busy.release()
        threading.Thread(target=run, daemon=True, name="werkbank").start()

    def report(self, result: dict) -> None:
        if not result.get("ok"):
            log.error(f"Werkbank: {type(self).__name__}: {result.get('error') or result}")
            self.show_error(duration=2)
