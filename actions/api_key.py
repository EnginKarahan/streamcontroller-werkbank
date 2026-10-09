import re
import threading

from loguru import logger as log

from src.backend.DeckManagement.InputIdentifier import Input

from .base import GREEN, GREY, NONE, RED, Field, WerkbankAction


class ApiKey(WerkbankAction):
    """Call an HTTP API on press; optionally poll a status and show it.

    Tokens are referenced by variable name only (see README), never stored
    in the key settings.
    """

    FIELDS = [
        Field("url", "Action URL (on press)"),
        Field("url_active", "Action URL while highlighted (optional)",
              subtitle="makes the key a toggle, e.g. clock in / clock out"),
        Field("method", "Method", default="POST"),
        Field("body", "JSON body (optional)"),
        Field("token_env", "Token variable", subtitle="name of the variable in ~/.config/werkbank/.env"),
        Field("token_header", "Token header", default="Authorization"),
        Field("scheme", "Authorization scheme", default="Bearer"),
        Field("hold", "Only on long press", kind="switch", default=False,
              subtitle="for actions that change things"),
        Field("status_url", "Status URL (optional)"),
        Field("show", "Status text", subtitle='e.g. {elapsed_minutes|hm} — {} is the whole reply'),
        Field("match", "Highlight when text matches (regex)"),
        Field("interval", "Refresh every (s)", kind="spin", default=30, rng=(0, 3600, 5)),
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._ticks = 0
        self._matched = False
        self._polling = threading.Lock()

    def on_ready(self):
        super().on_ready()
        self._ticks = 0
        self.poll()

    def on_settings_changed(self):
        super().on_settings_changed()
        self.poll()

    def on_tick(self):
        super().on_tick()
        interval = int(self.setting("interval") or 0)
        if not interval or not self.setting("status_url"):
            return
        self._ticks += 1
        if self._ticks >= interval:
            self._ticks = 0
            self.poll()

    def event_callback(self, event, data=None):
        long_only = bool(self.setting("hold"))
        if (event == Input.Key.Events.HOLD_START and long_only) or \
                (event == Input.Key.Events.SHORT_UP and not long_only):
            if self.setting("url"):
                self.in_background(self.press)

    def _args(self, url: str, method: str, body: str = "") -> list[str]:
        args = ["api", url, "-X", method]
        if body:
            args += ["--json", body]
        if self.setting("token_env"):
            args += ["--token-env", self.setting("token_env"),
                     "--token-header", self.setting("token_header") or "Authorization",
                     "--scheme", self.setting("scheme") or "Bearer"]
        return args

    def press(self):
        url = (self._matched and self.setting("url_active")) or self.setting("url")
        self.report(self.core(*self._args(url, self.setting("method") or "POST",
                                          self.setting("body"))))
        self.poll()

    def poll(self):
        if not self.setting("status_url") or not self._polling.acquire(blocking=False):
            return

        def run():
            try:
                args = self._args(self.setting("status_url"), "GET")
                if self.setting("show"):
                    args += ["--show", self.setting("show")]
                result = self.core(*args)
                if not result.get("ok"):
                    self._matched = False
                    self.ui(self.show_status, str(result.get("status") or "!"), RED)
                    return
                text = result.get("text") or ""
                log.debug(f"Werkbank: status {self.setting('status_url')} -> {text!r}")
                self.ui(self.show_status, text)
                pattern = self.setting("match")
                self._matched = bool(pattern and re.search(pattern, text))
                self.ui(self.show_status, None, (GREEN if self._matched else GREY) if pattern else NONE)
            finally:
                self._polling.release()
        threading.Thread(target=run, daemon=True, name="werkbank-poll").start()
