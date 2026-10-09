"""Live status of all Claude Code sessions, fed by Claude Code hooks.

Claude Code runs the hook (`werkbank-cli claude hook`) on prompt submit,
after each tool use, on notifications, when a turn ends and when a session
starts or ends. The hook writes one small JSON file per session:

    ~/.local/state/werkbank/claude/<session_id>.json

with the state "working", "waiting" (turn finished, your move) or
"permission" (a tool needs approval), the session's folder and the pid of
its claude process, which ties the session to its kitty window.

The hook must be fast and must never fail the session, so it only uses the
standard library and swallows its own errors.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

STATE_DIR = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) \
    / "werkbank" / "claude"

WORKING, WAITING, PERMISSION, OPEN = "working", "waiting", "permission", "open"
# Most urgent first; used for the overall light. OPEN = running, but no hook
# event yet (e.g. a session that has been quiet since the hook was set up).
URGENCY = {PERMISSION: 0, WAITING: 1, WORKING: 2, OPEN: 3}
_SPINNER = "✳✻✽✶✢·◐◓◑◒⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏ "


def _title_name(title: str) -> str:
    """Claude sets the terminal title to the session's topic, behind a spinner glyph."""
    return title.lstrip(_SPINNER).strip()


def _claude_pid(start: int) -> int | None:
    """Walk up from the hook process to the claude process that runs it."""
    pid = start
    for _ in range(8):
        try:
            stat = Path(f"/proc/{pid}/stat").read_text()
            cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
        except OSError:
            return None
        if cmdline and os.path.basename(cmdline[0].decode(errors="replace")) == "claude":
            return pid
        # stat: "pid (comm) state ppid ..." – comm may contain spaces
        pid = int(stat.rsplit(")", 1)[1].split()[1])
        if pid <= 1:
            return None
    return None


def _state_for(event: dict) -> str | None:
    name = event.get("hook_event_name")
    if name in ("UserPromptSubmit", "PostToolUse", "PreCompact"):
        return WORKING
    if name == "Notification":
        kind = event.get("notification_type") or ""
        text = (event.get("message") or "").lower()
        if kind == "permission_prompt" or "permission" in text:
            return PERMISSION
        return WAITING
    if name in ("Stop", "SessionStart"):
        return WAITING
    return None


def hook(stdin=sys.stdin) -> None:
    """Entry point for Claude Code hooks. Never raises, never prints."""
    try:
        event = json.load(stdin)
        sid = event.get("session_id")
        if not sid:
            return
        path = STATE_DIR / f"{sid}.json"
        if event.get("hook_event_name") == "SessionEnd":
            path.unlink(missing_ok=True)
            return
        state = _state_for(event)
        if state is None:
            return
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        record = {
            "session_id": sid,
            "state": state,
            "cwd": event.get("cwd") or "",
            "message": event.get("message") or "",
            "pid": _claude_pid(os.getppid()),
            "since": time.time(),
        }
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(record), encoding="utf-8")
        tmp.replace(path)
    except Exception:  # a status light must never break a Claude session
        pass


def _alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def sessions(names: dict[str, str] | None = None, windows: list[dict] | None = None) -> list[dict]:
    """All live sessions, sorted by name so every session keeps its key.

    `names` maps session ids to display names (pinned keys). `windows` are the
    claude processes found in kitty (claude.claude_windows()); sessions among
    them without a hook record are added as OPEN. Display name: pinned name,
    else the terminal title, else the folder. Files of dead sessions are removed.
    """
    names = names or {}
    by_pid = {w["pid"]: w for w in windows or [] if w.get("pid")}
    out = []
    for path in STATE_DIR.glob("*.json"):
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not _alive(rec.get("pid")):
            path.unlink(missing_ok=True)
            continue
        win = by_pid.pop(rec.get("pid"), None)
        rec["name"] = (names.get(rec["session_id"]) or (win and _title_name(win["title"]))
                       or Path(rec.get("cwd") or "?").name)
        out.append(rec)
    for pid, win in by_pid.items():
        out.append({"session_id": f"pid-{pid}", "state": OPEN, "cwd": win["cwd"], "message": "",
                    "pid": pid, "since": None,
                    "name": _title_name(win["title"]) or Path(win["cwd"] or "?").name})
    out.sort(key=lambda r: (r["name"].lower(), r["session_id"]))
    return out


def overall(recs: list[dict]) -> str | None:
    """The most urgent state of all sessions, or None if there are none."""
    return min((r["state"] for r in recs), key=lambda s: URGENCY.get(s, 9), default=None)
