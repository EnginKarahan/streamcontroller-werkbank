import threading
import time

from src.backend.DeckManagement.InputIdentifier import Input

from .base import GREY, NONE, RED, Field, WerkbankAction


class GuardedToggle(WerkbankAction):
    """Start/stop something long-running, e.g. a recording, with its state on the key.

    The state comes from a status command (exit code 0 = running). Starting
    is a short press; stopping needs a long press, so a stray tap never ends
    a recording. There is deliberately no "discard" path.
    """

    FIELDS = [
        Field("status", "Status command", subtitle="exit code 0 means running"),
        Field("start", "Start command"),
        Field("stop", "Stop command", subtitle="runs on long press only"),
        Field("on_text", "Text while running", default="● REC"),
        Field("off_text", "Text while stopped", default=""),
        Field("interval", "Check every (s)", kind="spin", default=5, rng=(1, 600, 1)),
    ]
    DEFAULT_ICON = "media-record"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._ticks = 0
        self._running = False
        self._checking = threading.Lock()

    def on_ready(self):
        super().on_ready()
        self.check()

    def on_tick(self):
        super().on_tick()
        self._ticks += 1
        if self._ticks >= int(self.setting("interval") or 5):
            self._ticks = 0
            self.check()

    def event_callback(self, event, data=None):
        if event == Input.Key.Events.SHORT_UP and not self._running:
            self.in_background(self._do, "start")
        elif event == Input.Key.Events.HOLD_START and self._running:
            self.in_background(self._do, "stop")

    def _do(self, which):
        # Detached on purpose: a start command may be the recorder itself, and
        # waiting with a timeout would kill it.
        self.shell(self.setting(which))
        time.sleep(2)
        self._ticks = 0
        self.check()

    def check(self):
        if not self.setting("status") or not self._checking.acquire(blocking=False):
            return

        def run():
            try:
                rc = self.shell(self.setting("status"), wait=True, timeout=15)
                self._running = rc == 0
                self.ui(self.set_background_color,
                        RED if self._running else (GREY if rc is None else NONE))
                self.ui(self.set_center_label,
                        self.setting("on_text" if self._running else "off_text"), font_size=14)
            finally:
                self._checking.release()
        threading.Thread(target=run, daemon=True, name="werkbank-status").start()
