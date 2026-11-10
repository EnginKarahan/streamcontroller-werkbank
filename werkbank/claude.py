"""One key per Claude Code session: focus its terminal window or reopen it.

`claude --resume <term>` opens a picker instead of resuming directly, and
`claude --continue` picks whatever session in the folder was used last. To
get a stable "this key is that session" we pin a session id per key name in a
small state file and resume it by id.

On first use a key adopts the newest existing session of its folder, so
long-running sessions keep their history. Re-pin with `werkbank claude pin`.

Sessions are found from the claude processes themselves: each one is traced up
its parent chain to the terminal it runs in. Konsole is asked over D-Bus which
tab (session) holds it; kitty, still supported, over its remote control
socket. New sessions open in Konsole.
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
from .konsole import Konsole
from .launch import in_login_shell, spawn

logger = logging.getLogger(__name__)

PROJECTS = Path.home() / ".claude" / "projects"
STATE = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) \
    / "werkbank" / "claude-sessions.json"
KITTY_SOCKET = "unix:@mykitty-{pid}"  # kitty.conf: listen_on unix:@mykitty
SESSIONS = Path.home() / ".claude" / "sessions"  # <pid>.json, written by Claude Code
TERMINALS = {"konsole", "kitty"}
# A terminal started from inside a Claude session would hand its markers on;
# a claude started there then counts as a child session and keeps no transcript.
INHERITED_PREFIXES = ("CLAUDE", "CODEX_COMPANION_", "AI_AGENT")


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


def _parent(pid: int) -> int | None:
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return None
    return int(stat.rsplit(")", 1)[1].split()[1])


def _comm(pid: int) -> str:
    try:
        return Path(f"/proc/{pid}/comm").read_text().strip()
    except OSError:
        return ""


def _ancestors(pid: int) -> list[int]:
    chain, cur = [], _parent(pid)
    while cur and cur > 1:
        chain.append(cur)
        cur = _parent(cur)
    return chain


def _claude_pids() -> list[int]:
    out = subprocess.run(["pgrep", "-x", "claude"], capture_output=True, text=True)
    return [int(p) for p in out.stdout.split()]


def _registry(claude_pid: int) -> dict:
    try:
        return json.loads((SESSIONS / f"{claude_pid}.json").read_text())
    except (OSError, ValueError):
        return {}


def _user_name(claude_pid: int) -> str:
    """Session name if you gave it yourself; derived ones ("karahan-45") say
    less than the topic title Claude puts in the terminal title."""
    reg = _registry(claude_pid)
    return reg.get("name", "") if reg.get("nameSource") == "user" else ""


def _session_id(claude_pid: int) -> str:
    """Session id of a running claude: its registry file, else its command line."""
    if _registry(claude_pid).get("sessionId"):
        return _registry(claude_pid)["sessionId"]
    try:
        args = Path(f"/proc/{claude_pid}/cmdline").read_bytes().split(b"\0")
    except OSError:
        return ""
    for flag, value in zip(args, args[1:]):
        if flag in (b"--resume", b"-r", b"--session-id"):
            return value.decode()
    return ""


def _kitty_window(kitty_pid: int, claude_pid: int) -> tuple[int, str] | None:
    """(window id, title) of the kitty window whose foreground is this claude."""
    try:
        proc = subprocess.run(
            ["kitten", "@", "--to", KITTY_SOCKET.format(pid=kitty_pid), "ls"],
            capture_output=True, text=True, timeout=5, check=True)
        os_windows = json.loads(proc.stdout)
    except (subprocess.SubprocessError, json.JSONDecodeError, OSError) as err:
        logger.warning("kitty %s not reachable via remote control: %s", kitty_pid, err)
        return None
    for osw in os_windows:
        for tab in osw.get("tabs", []):
            for win in tab.get("windows", []):
                if claude_pid in {p.get("pid") for p in win.get("foreground_processes") or []}:
                    return win["id"], win.get("title", "")
    return None


def claude_windows() -> list[dict]:
    """Every claude process running in a terminal window.

    Returns {pid (of claude), session_id, name, terminal, term_pid, window_id,
    title, cwd}; window_id is the Konsole session or kitty window, name the
    session name you gave it in Claude Code ("" if none). Works without
    hooks, so sessions that have been quiet since the hook was set up show too.
    """
    found = []
    for pid in _claude_pids():
        chain = _ancestors(pid)
        term_pid = next((p for p in chain if _comm(p) in TERMINALS), None)
        if term_pid is None:
            continue  # not in a terminal (e.g. started by a script)
        terminal = _comm(term_pid)
        if terminal == "konsole":
            hit = Konsole(term_pid).session_of(chain)
        else:
            hit = _kitty_window(term_pid, pid)
        if hit is None:
            continue
        try:
            cwd = str(Path(f"/proc/{pid}/cwd").resolve(strict=True))
        except OSError:
            cwd = ""
        found.append({"pid": pid, "session_id": _session_id(pid),
                      "name": _user_name(pid), "terminal": terminal,
                      "term_pid": term_pid, "window_id": hit[0], "title": hit[1], "cwd": cwd})
    return found


def find_window(session_id: str, directory: str | Path) -> dict | None:
    """The terminal window running this session (see claude_windows()).

    Prefers the claude process with this session id; falls back to a claude
    running in the same folder (sessions started by hand).
    """
    want_cwd = str(Path(directory).expanduser().resolve())
    fallback = None
    for win in claude_windows():
        if win["session_id"] == session_id:
            return win
        if fallback is None and win["cwd"] == want_cwd:
            fallback = win
    return fallback


def _focus(win: dict) -> bool:
    """Bring this terminal tab/window to the front."""
    if win["terminal"] == "konsole":
        title = Konsole(win["term_pid"]).show_session(win["window_id"]) or win["title"]
        return bool(kwin.activate(caption="^" + re.escape(title), pid=win["term_pid"])
                    or kwin.activate(pid=win["term_pid"]))
    subprocess.run(["kitten", "@", "--to", KITTY_SOCKET.format(pid=win["term_pid"]),
                    "focus-window", "--match", f"id:{win['window_id']}"],
                   capture_output=True, timeout=5)
    # The OS window now carries this window's title; one kitty process
    # may own several OS windows, so match on both.
    return bool(kwin.activate(cls="^kitty$", caption=re.escape(win["title"]), pid=win["term_pid"])
                or kwin.activate(pid=win["term_pid"]))


def focus_pid(claude_pid: int) -> bool:
    """Bring the terminal window that runs this claude process to the front."""
    win = next((w for w in claude_windows() if w["pid"] == claude_pid), None)
    return _focus(win) if win else False


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
    if hit and _focus(hit):
        return "focused"

    claude = ["claude", "--resume" if exists else "--session-id", sid, "--name", name]
    shell, flag, cmd = in_login_shell(claude)
    # Keep a shell open after claude exits, like a normal terminal tab.
    env = {k: v for k, v in os.environ.items() if not k.startswith(INHERITED_PREFIXES)}
    spawn(["konsole", "--workdir", str(directory), "-e", shell, flag,
           f"{cmd}; exec {shlex.quote(shell)} -l"], env=env)
    return "launched"
