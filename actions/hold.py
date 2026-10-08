from src.backend.DeckManagement.InputIdentifier import Input

from .base import Field, WerkbankAction


class HoldCommand(WerkbankAction):
    """One command when the key goes down, another when it comes up.

    Push-to-talk and similar. Both run unconditionally, so a release is never
    lost even if the press command is still running.
    """

    FIELDS = [
        Field("down", "Command on press"),
        Field("up", "Command on release"),
    ]

    def event_callback(self, event, data=None):
        if event == Input.Key.Events.DOWN:
            self.shell(self.setting("down"))
        elif event == Input.Key.Events.UP:
            self.shell(self.setting("up"))
