"""One key per Claude Code session: focus its kitty window or reopen it.

`claude --resume <term>` opens a picker instead of resuming directly, and
`claude --continue` picks whatever session in the folder was used last. To
get a stable "this key is that session" we pin a session id per key name in a
small state file and resume it by id.

On first use a key adopts the newest existing session of its folder, so
long-running sessions keep their history. Re-pin with `werkbank claude pin`.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shlex
import subprocess
import uuid
from pathlib import Path

from . import kwin
from .launch import in_login_shell, spawn

logger = logging.getLogger(__name__)

PROJECTS = Path.home() / ".claude" / "projects"
STATE = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) \
    / "werkbank" / "claude-sessions.json"
KITTY_SOCKET = "unix:@mykitty-{pid}"  # kitty.conf: listen_on unix:@mykitty


def project_dir(directory: str | Path) -> Path:
    """Where Claude Code keeps the transcripts of sessions started in `directory`."""
    slug = re.sub(r"[^A-Za-z0-9]", "-", str(Path(directory).expanduser().resolve()))
    return PROJECTS / slug


def session_exists(session_id: str) -> bool:
    return any(PROJECTS.glob(f"*/{session_id}.jsonl"))


def newest_session(directory: str | Path) -> str | None:
    files = sorted(project_dir(directory).glob("*.jsonl"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0].stem if files else None


def _load() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def _save(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1), encoding="utf-8")
    tmp.replace(STATE)


def pin(name: str, session_id: str) -> None:
    state = _load()
    state[name] = session_id
    _save(state)


def resolve(name: str, directory: str | Path) -> tuple[str, bool]:
    """Session id for this key, and whether it already exists on disk."""
    state = _load()
    sid = state.get(name)
    if sid and session_exists(sid):
        return sid, True
    if not sid:
        sid = newest_session(directory)
        if sid:
            logger.info("key %r adopts newest session %s", name, sid)
            pin(name, sid)
            return sid, True
    # Pinned but never written (opened and closed without a prompt), or a
    # folder without any session yet: start fresh under a known id.
    sid = sid or str(uuid.uuid4())
    pin(name, sid)
    return sid, False


def _kitty_pids() -> list[int]:
    out = subprocess.run(["pgrep", "-x", "kitty"], capture_output=True, text=True)
    return [int(p) for p in out.stdout.split()]


def find_window(session_id: str, directory: str | Path) -> tuple[int, int, str] | None:
    """(kitty pid, kitty window id, title) of the window running this session.

    Prefers a window whose claude process carries the session id; falls back
    to a claude running in the same folder (sessions started by hand).
    """
    want_cwd = str(Path(directory).expanduser().resolve())
    fallback = None
    for pid in _kitty_pids():
        try:
            proc = subprocess.run(
                ["kitten", "@", "--to", KITTY_SOCKET.format(pid=pid), "ls"],
                capture_output=True, text=True, timeout=5, check=True)
            os_windows = json.loads(proc.stdout)
        except (subprocess.SubprocessError, json.JSONDecodeError, OSError) as err:
            logger.warning("kitty %s not reachable via remote control: %s", pid, err)
            continue
        for osw in os_windows:
            for tab in osw.get("tabs", []):
                for win in tab.get("windows", []):
                    procs = win.get("foreground_processes") or []
                    claude = [p.get("cmdline") or [] for p in procs
                              if p.get("cmdline") and os.path.basename(p["cmdline"][0]) == "claude"]
                    if not claude:
                        continue
                    hit = (pid, win["id"], win.get("title", ""))
                    if any(session_id in arg for cmd in claude for arg in cmd):
                        return hit
                    if fallback is None and win.get("cwd") == want_cwd:
                        fallback = hit
    return fallback


def claude_windows() -> list[dict]:
    """Every kitty window whose foreground process is claude.

    Returns {pid (of claude), kitty_pid, window_id, title, cwd}. Works without
    hooks, so sessions that have been quiet since the hook was set up show too.
    """
    found = []
    for kpid in _kitty_pids():
        try:
            proc = subprocess.run(
                ["kitten", "@", "--to", KITTY_SOCKET.format(pid=kpid), "ls"],
                capture_output=True, text=True, timeout=5, check=True)
            os_windows = json.loads(proc.stdout)
        except (subprocess.SubprocessError, json.JSONDecodeError, OSError):
            continue
        for osw in os_windows:
            for tab in osw.get("tabs", []):
                for win in tab.get("windows", []):
                    for fp in win.get("foreground_processes") or []:
                        cmd = fp.get("cmdline") or []
                        if cmd and os.path.basename(cmd[0]) == "claude":
                            found.append({"pid": fp.get("pid"), "kitty_pid": kpid,
                                          "window_id": win["id"], "title": win.get("title", ""),
                                          "cwd": win.get("cwd") or fp.get("cwd") or ""})
                            break
    return found


def focus_pid(claude_pid: int) -> bool:
    """Bring the kitty window that runs this claude process to the front."""
    for pid in _kitty_pids():
        try:
            proc = subprocess.run(
                ["kitten", "@", "--to", KITTY_SOCKET.format(pid=pid), "ls"],
                capture_output=True, text=True, timeout=5, check=True)
            os_windows = json.loads(proc.stdout)
        except (subprocess.SubprocessError, json.JSONDecodeError, OSError):
            continue
        for osw in os_windows:
            for tab in osw.get("tabs", []):
                for win in tab.get("windows", []):
                    pids = {p.get("pid") for p in win.get("foreground_processes") or []}
                    if claude_pid in pids:
                        subprocess.run(["kitten", "@", "--to", KITTY_SOCKET.format(pid=pid),
                                        "focus-window", "--match", f"id:{win['id']}"],
                                       capture_output=True, timeout=5)
                        title = win.get("title", "")
                        return bool(kwin.activate(cls="^kitty$", caption=re.escape(title), pid=pid)
                                    or kwin.activate(pid=pid))
    return False


def pinned_names() -> dict[str, str]:
    """Session id → key name, for sessions bound to a key."""
    return {sid: name for name, sid in _load().items()}


def open_session(name: str, directory: str | Path) -> str:
    """Focus the session's window or start it. Returns "focused" or "launched"."""
    directory = Path(directory).expanduser()
    if not directory.is_dir():
        raise FileNotFoundError(f"session folder does not exist: {directory}")
    sid, exists = resolve(name, directory)

    hit = find_window(sid, directory)
    if hit:
        pid, win_id, title = hit
        subprocess.run(["kitten", "@", "--to", KITTY_SOCKET.format(pid=pid),
                        "focus-window", "--match", f"id:{win_id}"],
                       capture_output=True, timeout=5)
        # The OS window now carries this window's title; one kitty process
        # may own several OS windows, so match on both.
        if kwin.activate(cls="^kitty$", caption=re.escape(title), pid=pid) \
                or kwin.activate(pid=pid):
            return "focused"

    claude = ["claude", "--resume" if exists else "--session-id", sid, "--name", name]
    shell, flag, cmd = in_login_shell(claude)
    # Keep a shell open after claude exits, like a normal terminal tab.
    spawn(["kitty", "--directory", str(directory), shell, flag,
           f"{cmd}; exec {shlex.quote(shell)} -l"])
    return "launched"
