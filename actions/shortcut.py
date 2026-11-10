from .base import Field, WerkbankAction


class Shortcut(WerkbankAction):
    """Send a keyboard shortcut (or type text) to the focused window.

    Written the way it is meant, e.g. "ctrl+z": letters and punctuation are
    sent through the active keyboard layout, so it works on German, French
    or Turkish keyboards too. Needs dotool on the host.
    """

    FIELDS = [
        Field("keys", "Shortcut", subtitle='e.g. ctrl+z, ctrl+shift+t, f11, "ctrl+k f" for a sequence'),
        Field("text", "…or text to type (optional)"),
        Field("enter", "Press Enter after the text", kind="switch", default=False),
    ]
    DEFAULT_ICON = "input-keyboard"

    def on_key_down(self):
        if self.setting("text"):
            args = ["keys", "--type", self.setting("text")] + (["--enter"] if self.setting("enter") else [])
        elif self.setting("keys"):
            args = ["keys", self.setting("keys")]
        else:
            self.show_error(duration=2)
            return
        self.in_background(lambda: self.report(self.core(*args)))
