"""Bring a window to the front, or start the program if it is not running."""

from __future__ import annotations

import logging
import os
import shlex
import subprocess

from . import kwin

logger = logging.getLogger(__name__)


def spawn(command: list[str] | str, cwd: str | None = None,
          env: dict[str, str] | None = None) -> None:
    """Start a program detached from us, so it survives the caller."""
    argv = shlex.split(command) if isinstance(command, str) else command
    logger.info("starting %s", argv)
    subprocess.Popen(
        argv, cwd=cwd, env=env, start_new_session=True,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def in_login_shell(command: list[str]) -> list[str]:
    """Wrap a command so it runs with the user's login PATH.

    Launchers such as StreamController (or flatpak-spawn --host) often run
    with a minimal environment in which ~/.local/bin is missing.
    """
    shell = os.environ.get("SHELL", "/bin/bash")
    return [shell, "-lc", shlex.join(command)]


def focus_or_launch(command: list[str] | str, cls: str | None = None,
                    caption: str | None = None) -> str:
    """Activate the matching window; start `command` if there is none.

    Returns "focused" or "launched".
    """
    if kwin.activate(cls=cls, caption=caption):
        return "focused"
    spawn(command)
    return "launched"
