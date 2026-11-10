"""Konsole over D-Bus: which tab runs a process, and bringing a tab to the front.

Every Konsole process registers as `org.kde.konsole-<pid>` with /Windows/<n>
(the tabs of one window) and /Sessions/<n> (one terminal). Konsole refuses
sendText/runCommand over D-Bus by default, but the calls used here are allowed.
"""

from __future__ import annotations

import logging

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

logger = logging.getLogger(__name__)

DISPLAYED_TITLE = 1  # Session.title(role): 0 = name, 1 = title shown in the tab


class Konsole:
    def __init__(self, pid: int):
        self.pid = pid
        self.service = f"org.kde.konsole-{pid}"

    def _call(self, path: str, iface: str, method: str, args: GLib.Variant | None = None):
        conn = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        result = conn.call_sync(self.service, path, iface, method, args, None,
                                Gio.DBusCallFlags.NONE, 3000, None).unpack()
        return result[0] if result else None

    def _children(self, path: str) -> list[int]:
        xml = self._call(path, "org.freedesktop.DBus.Introspectable", "Introspect")
        return sorted(int(n.path) for n in Gio.DBusNodeInfo.new_for_xml(xml).nodes
                      if n.path.isdigit())

    def title(self, session: int) -> str:
        return self._call(f"/Sessions/{session}", "org.kde.konsole.Session", "title",
                          GLib.Variant("(i)", (DISPLAYED_TITLE,)))

    def session_of(self, ancestors: list[int]) -> tuple[int, str] | None:
        """(session, title) of the tab whose shell is one of these processes."""
        try:
            for session in self._children("/Sessions"):
                shell = self._call(f"/Sessions/{session}", "org.kde.konsole.Session", "processId")
                if shell in ancestors:
                    return session, self.title(session)
        except GLib.Error as err:
            logger.warning("Konsole %s not reachable over D-Bus: %s", self.pid, err.message)
        return None

    def show_session(self, session: int) -> str | None:
        """Make this tab the current one in its window; returns the window title."""
        try:
            for window in self._children("/Windows"):
                sessions = self._call(f"/Windows/{window}", "org.kde.konsole.Window", "sessionList")
                if str(session) in sessions:
                    self._call(f"/Windows/{window}", "org.kde.konsole.Window", "setCurrentSession",
                               GLib.Variant("(i)", (session,)))
                    return self.title(session)
        except GLib.Error as err:
            logger.warning("Konsole %s: could not switch tab: %s", self.pid, err.message)
        return None
