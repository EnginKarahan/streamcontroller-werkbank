"""Talk to KWin (Plasma 6, Wayland) through short-lived scripts.

Under Wayland only the compositor knows which windows exist and may activate
one. KWin scripts cannot return values and their print() goes to a logging
category that is off by default, so each script reports back via callDBus to
a receiver this module owns for the duration of one call.

Deliberately not used: kglobalaccel. Registering global shortcuts over D-Bus
crashes KWin on Plasma 6.7.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

logger = logging.getLogger(__name__)

SCRIPTS = Path(__file__).with_name("kwin_scripts")
SINK_IFACE = "io.github.EnginKarahan.Werkbank.Sink"
SINK_PATH = "/Sink"
SINK_XML = f"""
<node>
  <interface name='{SINK_IFACE}'>
    <method name='Push'>
      <arg type='s' name='payload' direction='in'/>
    </method>
  </interface>
</node>
"""


class KWinError(RuntimeError):
    """KWin was unreachable or did not answer in time."""


def _call(conn, path: str, iface: str, method: str, args=None):
    return conn.call_sync(
        "org.kde.KWin", path, iface, method, args, None,
        Gio.DBusCallFlags.NONE, 5000, None,
    )


def _unload(conn, plugin: str) -> None:
    try:
        _call(conn, "/Scripting", "org.kde.kwin.Scripting", "unloadScript",
              GLib.Variant("(s)", (plugin,)))
    except GLib.Error:
        pass  # not loaded, nothing to do


def run_script(name: str, params: dict | None = None, timeout: int = 5):
    """Run kwin_scripts/<name>.js once and return what it pushed (parsed JSON).

    The script gets its parameters as a JSON literal in place of the token
    __PARAMS__ and the receiver's bus name in place of __SINK__.
    """
    template = SCRIPTS / f"{name}.js"
    if not template.exists():
        raise KWinError(f"KWin script missing: {template}")

    # Unique per process, so two keys pressed at once do not collide.
    tag = f"p{os.getpid()}"
    sink_name = f"{SINK_IFACE}.{tag}"
    plugin = f"werkbank-{name}-{tag}"
    source = (template.read_text(encoding="utf-8")
              .replace("__PARAMS__", json.dumps(params or {}))
              .replace("__SINK__", sink_name))
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "werkbank"
    runtime.mkdir(mode=0o700, exist_ok=True)
    script_file = runtime / f"{plugin}.js"
    script_file.write_text(source, encoding="utf-8")

    conn = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    loop = GLib.MainLoop()
    box: dict[str, object] = {}

    def on_call(_conn, _sender, _path, _iface, method, params_, invocation):
        if method != "Push":
            invocation.return_error_literal(
                Gio.dbus_error_quark(), Gio.DBusError.UNKNOWN_METHOD, method)
            return
        box["payload"] = params_.unpack()[0]
        invocation.return_value(None)
        loop.quit()

    def on_acquired(_conn, _name):
        node = Gio.DBusNodeInfo.new_for_xml(SINK_XML)
        box["registration"] = conn.register_object(
            SINK_PATH, node.interfaces[0], on_call, None, None)
        GLib.idle_add(trigger)

    def on_lost(_conn, _name):
        box["error"] = f"could not own D-Bus name {sink_name}"
        loop.quit()

    def trigger():
        try:
            _unload(conn, plugin)
            script_id = _call(
                conn, "/Scripting", "org.kde.kwin.Scripting", "loadScript",
                GLib.Variant("(ss)", (str(script_file), plugin)),
            ).unpack()[0]
            _call(conn, f"/Scripting/Script{script_id}", "org.kde.kwin.Script", "run")
        except GLib.Error as err:
            box["error"] = f"KWin script failed: {err.message}"
            loop.quit()
        return False

    owner = Gio.bus_own_name_on_connection(
        conn, sink_name, Gio.BusNameOwnerFlags.DO_NOT_QUEUE, on_acquired, on_lost)
    timer = GLib.timeout_add_seconds(timeout, lambda: (loop.quit(), False)[1])
    try:
        loop.run()
    finally:
        if "payload" in box or "error" in box:
            GLib.source_remove(timer)
        if "registration" in box:
            conn.unregister_object(int(box.pop("registration")))
        Gio.bus_unown_name(owner)
        _unload(conn, plugin)
        script_file.unlink(missing_ok=True)

    if "error" in box:
        raise KWinError(str(box["error"]))
    if "payload" not in box:
        raise KWinError(f"KWin did not answer within {timeout}s")
    return json.loads(str(box["payload"]))


def list_windows() -> list[dict]:
    """Normal windows: resourceClass, resourceName, caption, pid, active."""
    return run_script("list")


def activate(cls: str | None = None, caption: str | None = None,
             pid: int | None = None) -> dict | None:
    """Activate the first window matching all given criteria.

    cls and caption are JavaScript regular expressions (case-insensitive);
    cls is tested against resourceClass and resourceName. Returns the
    activated window, or None if nothing matched.
    """
    if not (cls or caption or pid):
        raise ValueError("activate() needs at least one criterion")
    result = run_script("activate", {"cls": cls, "caption": caption, "pid": pid})
    return result or None


def switch_desktop(number: int) -> dict | None:
    """Switch to virtual desktop `number` (1-based). None if it does not exist."""
    return run_script("desktop", {"number": number}) or None
