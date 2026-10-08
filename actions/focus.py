import shlex

from .base import Field, WerkbankAction


def guess_icon(launch: str) -> str:
    """App id from "flatpak run <id> …", else the program name."""
    try:
        argv = shlex.split(launch)
    except ValueError:
        return ""
    if len(argv) >= 3 and argv[0].endswith("flatpak") and argv[1] == "run":
        return next((a for a in argv[2:] if not a.startswith("-")), "")
    return argv[0].rsplit("/", 1)[-1] if argv else ""


class FocusApp(WerkbankAction):
    """Bring an app's window to the front, start it if it is not running."""

    FIELDS = [
        Field("cls", "Window class (regex)", subtitle="e.g. ^org.telegram.desktop$ — see: werkbank-cli windows"),
        Field("caption", "Window title (regex, optional)"),
        Field("launch", "Start command if not running", subtitle="e.g. flatpak run org.telegram.desktop"),
    ]

    def default_icon(self):
        return guess_icon(self.setting("launch") or "")

    def on_key_down(self):
        self.in_background(self.run)

    def run(self):
        args = ["focus"]
        for key, flag in (("cls", "--class"), ("caption", "--caption"), ("launch", "--launch")):
            if self.setting(key):
                args += [flag, self.setting(key)]
        result = self.core(*args)
        if result.get("result") != "not-found":  # nothing to start is not an error
            self.report(result)
