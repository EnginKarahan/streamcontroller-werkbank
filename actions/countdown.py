import time

from src.backend.DeckManagement.InputIdentifier import Input

from .base import GREEN, NONE, RED, Field, WerkbankAction

YELLOW = [214, 160, 20, 255]


class Countdown(WerkbankAction):
    """A countdown on the key: talk timer, focus block, tea.

    Short press starts or pauses, long press resets. Green while running,
    yellow in the last minutes, red and counting up once time is over.
    """

    FIELDS = [
        Field("minutes", "Minutes", kind="spin", default=20, rng=(1, 600, 1)),
        Field("warn", "Warn in the last … minutes", kind="spin", default=2, rng=(0, 120, 1)),
        Field("notify", "Desktop notification at zero", kind="switch", default=False),
    ]
    DEFAULT_ICON = "chronometer"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._end = None        # epoch when time is up, while running
        self._left = None       # seconds left, while paused
        self._notified = False

    def _total(self) -> float:
        return float(self.setting("minutes") or 20) * 60

    def event_callback(self, event, data=None):
        if event == Input.Key.Events.SHORT_UP:
            if self._end is not None:                 # pause
                self._left = self._end - time.time()
                self._end = None
            else:                                     # start / resume
                self._end = time.time() + (self._left if self._left is not None else self._total())
                self._left = None
        elif event == Input.Key.Events.HOLD_START:    # reset
            self._end, self._left, self._notified = None, None, False
            self.show_status("", NONE)

    def on_tick(self):
        super().on_tick()
        if self._end is None and self._left is None:
            return
        left = self._end - time.time() if self._end is not None else self._left
        if left >= 0:
            text = f"{int(left) // 60:02d}:{int(left) % 60:02d}"
            color = YELLOW if left <= float(self.setting("warn") or 0) * 60 else GREEN
        else:
            over = -left
            text = f"+{int(over) // 60}:{int(over) % 60:02d}"
            color = RED
            if self.setting("notify") and not self._notified and self._end is not None:
                self._notified = True
                self.shell("notify-send -a Werkbank 'Time is up'")
        if self._end is None:
            text = "⏸ " + text
        self.show_status(text, color, size=16)
