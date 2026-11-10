import threading

from src.backend.DeckManagement.InputIdentifier import Input

from .base import GREEN, NONE, Field, WerkbankAction


class DoNotDisturb(WerkbankAction):
    """KDE Plasma "Do not disturb" for N minutes; Plasma ends it by itself.

    Short press starts (or extends), long press ends it. The key shows the
    minutes left, also when the mode was switched on in the applet.
    """

    FIELDS = [Field("minutes", "Minutes", kind="spin", default=50, rng=(1, 720, 5))]
    DEFAULT_ICON = "notifications-disabled"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._ticks = 0
        self._polling = threading.Lock()

    def on_ready(self):
        super().on_ready()
        self.poll()

    def event_callback(self, event, data=None):
        if event == Input.Key.Events.SHORT_UP:
            self.in_background(self._run, "start", str(int(self.setting("minutes") or 50)))
        elif event == Input.Key.Events.HOLD_START:
            self.in_background(self._run, "stop")

    def _run(self, *args):
        self._show(self.core("dnd", *args))

    def on_tick(self):
        super().on_tick()
        self._ticks += 1
        if self._ticks >= 20:
            self._ticks = 0
            self.poll()

    def poll(self):
        if not self._polling.acquire(blocking=False):
            return

        def run():
            try:
                self._show(self.core("dnd", "status"))
            finally:
                self._polling.release()
        threading.Thread(target=run, daemon=True, name="werkbank-dnd").start()

    def _show(self, result: dict):
        if not result.get("ok"):
            self.report(result)
            return
        if result.get("active"):
            self.ui(self.show_status, f"{result['minutes']} min", GREEN)
        else:
            self.ui(self.show_status, "", NONE)
