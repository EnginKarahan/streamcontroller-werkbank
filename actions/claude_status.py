"""Claude Code status keys: an overall light and one key per running session.

All keys share one status snapshot, refreshed on the host at most every
few seconds, so a page full of session keys costs one host call, not one
per key. Updates are applied in on_tick, like every other Werkbank key.
"""

import subprocess
import threading
import time

from loguru import logger as log

from .base import GREEN, GREY, NONE, RED, Field, WerkbankAction, host

YELLOW = [214, 160, 20, 255]
COLORS = {"permission": RED, "waiting": YELLOW, "working": GREEN, "open": GREY}
WORDS = {"permission": "Freigabe", "waiting": "wartet", "working": "arbeitet", "open": "offen"}


class _Snapshot:
    """One shared `werkbank-cli claude status`, refreshed in the background."""

    def __init__(self):
        self.data = {"overall": None, "sessions": []}
        self.fetched = 0.0
        self._lock = threading.Lock()

    def get(self, action: WerkbankAction, max_age: float = 3.0) -> dict:
        if time.time() - self.fetched > max_age and self._lock.acquire(blocking=False):
            def run():
                try:
                    result = action.core("claude", "status", timeout=10)
                    if result.get("ok"):
                        self.data = result
                finally:
                    self.fetched = time.time()
                    self._lock.release()
            threading.Thread(target=run, daemon=True, name="werkbank-claude").start()
        return self.data


SNAPSHOT = _Snapshot()


class _ClaudeKey(WerkbankAction):
    DEFAULT_ICON = "kitty"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._shown = None

    def on_tick(self):
        super().on_tick()
        view = self.view(SNAPSHOT.get(self))
        if view != self._shown:
            self._shown = view
            text, color = view
            self.set_center_label(text, font_size=13)
            self.set_background_color(color)

    def view(self, data: dict) -> tuple[str, list]:
        raise NotImplementedError


class ClaudeOverview(_ClaudeKey):
    """The overall light (meant as a sticky key); press opens the overview page."""

    FIELDS = [Field("page", "Overview page", default="Claude")]
    DEFAULT_ICON = "com.anthropic.Claude"

    def view(self, data):
        sessions = data.get("sessions") or []
        state = data.get("overall")
        if not sessions:
            return "", NONE
        urgent = sum(1 for s in sessions if s["state"] == state)
        if state in ("working", "open"):
            return f"{len(sessions)}", COLORS.get(state, GREY)
        return f"{urgent}× {WORDS.get(state, '')}", COLORS.get(state, GREY)

    def on_key_down(self):
        page = self.setting("page") or "Claude"
        serial = self.deck_controller.serial_number()
        subprocess.Popen(host([
            "gdbus", "call", "--session", "--dest", "com.core447.StreamController",
            "--object-path", f"/com/core447/StreamController/controllers/{serial}",
            "--method", "com.core447.StreamController.Controller.SetActivePage", page]),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


class ClaudeSlot(_ClaudeKey):
    """The n-th running session (sorted by name): name, state color; press focuses it."""

    FIELDS = [Field("slot", "Slot number", kind="spin", default=1, rng=(1, 32, 1))]
    DEFAULT_ICON = ""

    def _session(self, data):
        idx = int(self.setting("slot") or 1) - 1
        sessions = data.get("sessions") or []
        return sessions[idx] if 0 <= idx < len(sessions) else None

    def view(self, data):
        s = self._session(data)
        if s is None:
            return "", NONE
        return f"{s['name'][:12]}\n{WORDS.get(s['state'], '')}", COLORS.get(s["state"], GREY)

    def on_key_down(self):
        s = self._session(SNAPSHOT.data)
        if s and s.get("pid"):
            self.in_background(lambda: self.report(self.core("claude", "focus", str(s["pid"]))))
        else:
            log.info("Werkbank: no Claude session on this key")
