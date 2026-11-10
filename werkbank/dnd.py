"""KDE Plasma "Do not disturb" for a number of minutes.

Uses the same setting as the notification applet: [DoNotDisturb] Until in
plasmanotifyrc, written with --notify so plasmashell picks it up at once.
Plasma ends the mode by itself when that time is reached, so no process has
to stay alive, and a crash cannot leave notifications muted.
"""

from __future__ import annotations

import subprocess
import time
from datetime import datetime

GROUP = ["--file", "plasmanotifyrc", "--group", "DoNotDisturb", "--key", "Until"]


class DndError(RuntimeError):
    pass


def parse(value: str) -> float:
    """KConfig date 'Y,M,D,h,m,s[.ms]' -> epoch; empty/invalid -> 0."""
    try:
        y, mo, d, h, mi, s = (float(x) for x in value.split(","))
        return datetime(int(y), int(mo), int(d), int(h), int(mi), int(s)).timestamp() + (s % 1)
    except (ValueError, TypeError):
        return 0.0


def format_until(epoch: float) -> str:
    d = datetime.fromtimestamp(epoch)
    return f"{d.year},{d.month},{d.day},{d.hour},{d.minute},{d.second}"


def until() -> float:
    out = subprocess.run(["kreadconfig6", *GROUP], capture_output=True, text=True, timeout=5)
    return parse(out.stdout.strip())


def remaining_minutes() -> int:
    """Minutes left (rounded up), 0 when not active."""
    left = until() - time.time()
    return int(-(-left // 60)) if left > 0 else 0


def start(minutes: float) -> int:
    """Mute notifications for `minutes`; never shortens a longer active period."""
    target = time.time() + minutes * 60
    if until() < target:
        r = subprocess.run(["kwriteconfig6", *GROUP, "--notify", format_until(target)],
                           capture_output=True, text=True, timeout=5)
        if r.returncode != 0:
            raise DndError(r.stderr.strip() or "kwriteconfig6 failed")
    return remaining_minutes()


def stop() -> None:
    subprocess.run(["kwriteconfig6", *GROUP, "--delete", "--notify"],
                   capture_output=True, text=True, timeout=5)
