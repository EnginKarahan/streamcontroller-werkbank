import os
import sys

from src.backend.DeckManagement.InputIdentifier import Input
from src.backend.PluginManager.ActionHolder import ActionHolder
from src.backend.PluginManager.ActionInputSupport import ActionInputSupport
from src.backend.PluginManager.PluginBase import PluginBase

sys.path.append(os.path.dirname(__file__))

from .actions.api_key import ApiKey  # noqa: E402
from .actions.claude_session import ClaudeSession  # noqa: E402
from .actions.claude_status import ClaudeOverview, ClaudeSlot  # noqa: E402
from .actions.countdown import Countdown  # noqa: E402
from .actions.dnd import DoNotDisturb  # noqa: E402
from .actions.shortcut import Shortcut  # noqa: E402
from .actions.focus import FocusApp  # noqa: E402
from .actions.hold import HoldCommand  # noqa: E402
from .actions.note import NewNote  # noqa: E402
from .actions.toggle import GuardedToggle  # noqa: E402

KEYS_ONLY = {
    Input.Key: ActionInputSupport.SUPPORTED,
    Input.Dial: ActionInputSupport.UNTESTED,
    Input.Touchscreen: ActionInputSupport.UNSUPPORTED,
}

ACTIONS = [
    (FocusApp, "FocusApp", "Focus or start app"),
    (ClaudeSession, "ClaudeSession", "Claude Code session"),
    (ApiKey, "ApiKey", "API call / status"),
    (NewNote, "NewNote", "New note from template"),
    (HoldCommand, "HoldCommand", "Hold: press / release command"),
    (GuardedToggle, "GuardedToggle", "Guarded start/stop (recording)"),
    (ClaudeOverview, "ClaudeOverview", "Claude: overall status light"),
    (ClaudeSlot, "ClaudeSlot", "Claude: session slot"),
    (Shortcut, "Shortcut", "Shortcut (layout-aware)"),
    (Countdown, "Countdown", "Countdown"),
    (DoNotDisturb, "DoNotDisturb", "Do not disturb (KDE)"),
]


class Werkbank(PluginBase):
    def __init__(self):
        super().__init__()
        for cls, suffix, name in ACTIONS:
            self.add_action_holder(ActionHolder(
                plugin_base=self,
                action_base=cls,
                action_id_suffix=suffix,
                action_name=self.locale_manager.get(f"actions.{suffix}.name", name),
                action_support=KEYS_ONLY,
            ))
        self.register(
            plugin_name=self.locale_manager.get("plugin.name", "Werkbank"),
            github_repo="https://github.com/EnginKarahan/streamcontroller-werkbank",
            plugin_version="0.1.0",
            app_version="1.5.0-beta.15",
        )
