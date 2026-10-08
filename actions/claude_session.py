from .base import Field, WerkbankAction


class ClaudeSession(WerkbankAction):
    """One key per Claude Code session: focus its kitty window or reopen it."""

    FIELDS = [
        Field("name", "Session name", subtitle="also the key's identity — keep it stable"),
        Field("directory", "Folder", subtitle="where the session runs, e.g. ~/projects/website"),
    ]

    def on_ready(self):
        if self.setting("name"):
            self.set_bottom_label(self.setting("name"), font_size=11)

    def on_settings_changed(self):
        self.on_ready()

    def on_key_down(self):
        if self.setting("name") and self.setting("directory"):
            self.in_background(self.run)
        else:
            self.show_error(duration=2)

    def run(self):
        self.report(self.core("claude", "open", self.setting("name"), self.setting("directory")))
