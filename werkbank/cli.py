"""Command line for the Werkbank core.

Every command prints one JSON object on stdout, so the StreamController
plugin (which may run inside a Flatpak and calls this on the host) and other
launchers can use the result. Errors go to stderr and give exit code 1.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

logger = logging.getLogger("werkbank")


def _out(**result) -> None:
    print(json.dumps(result, ensure_ascii=False))


def cmd_windows(_args) -> int:
    from . import kwin
    _out(ok=True, windows=kwin.list_windows())
    return 0


def cmd_focus(args) -> int:
    from . import kwin, launch
    if args.launch:
        _out(ok=True, result=launch.focus_or_launch(args.launch, cls=args.cls,
                                                    caption=args.caption))
        return 0
    hit = kwin.activate(cls=args.cls, caption=args.caption)
    _out(ok=bool(hit), result="focused" if hit else "not-found", window=hit)
    return 0 if hit else 1


def cmd_desktop(args) -> int:
    from . import kwin
    hit = kwin.switch_desktop(args.number)
    _out(ok=bool(hit), desktop=hit)
    return 0 if hit else 1


def cmd_claude(args) -> int:
    from . import claude
    if args.action == "open":
        _out(ok=True, result=claude.open_session(args.name, args.directory))
    elif args.action == "pin":
        claude.pin(args.name, args.session)
        _out(ok=True, result="pinned")
    return 0


def cmd_api(args) -> int:
    from . import api
    body = json.loads(args.json) if args.json else None
    headers = dict(h.split(":", 1) for h in args.header)
    headers = {k.strip(): v.strip() for k, v in headers.items()}
    status, data = api.request(args.url, method=args.method, body=body,
                               headers=headers, token_env=args.token_env,
                               token_scheme=args.scheme, token_header=args.token_header,
                               timeout=args.timeout)
    ok = 200 <= status < 300
    shown = api.render(args.show, data) if args.show else None
    _out(ok=ok, status=status, text=shown, data=None if args.show else data)
    return 0 if ok else 1


def cmd_note(args) -> int:
    from . import notes
    title = args.title
    if title is None and args.ask:
        title = notes.ask_title(args.ask)
        if title is None:
            _out(ok=False, result="cancelled")
            return 1
    path, created = notes.create(Path(args.template), Path(args.directory),
                                 name_pattern=args.name, title=title or "")
    if args.open:
        notes.open_in(args.open, path)
    _out(ok=True, result="created" if created else "exists", path=str(path))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="werkbank", description=__doc__.splitlines()[0])
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("windows", help="list normal windows (KWin)")
    s.set_defaults(func=cmd_windows)

    s = sub.add_parser("focus", help="activate a window, optionally start it if missing")
    s.add_argument("--class", dest="cls", help="regex on window class / app id")
    s.add_argument("--caption", help="regex on window title")
    s.add_argument("--launch", help="command to start when no window matches")
    s.set_defaults(func=cmd_focus)

    s = sub.add_parser("desktop", help="switch to virtual desktop N (1-based)")
    s.add_argument("number", type=int)
    s.set_defaults(func=cmd_desktop)

    s = sub.add_parser("claude", help="one key per Claude Code session in kitty")
    csub = s.add_subparsers(dest="action", required=True)
    c = csub.add_parser("open", help="focus the session window or reopen the session")
    c.add_argument("name")
    c.add_argument("directory")
    c = csub.add_parser("pin", help="bind a key name to a session id")
    c.add_argument("name")
    c.add_argument("session")
    s.set_defaults(func=cmd_claude)

    s = sub.add_parser("api", help="HTTP call, optionally render a value from the JSON reply")
    s.add_argument("url")
    s.add_argument("-X", "--method", default="GET")
    s.add_argument("--json", help="request body (JSON)")
    s.add_argument("-H", "--header", action="append", default=[], help="Name: value")
    s.add_argument("--token-env", help="name of the variable that holds the token")
    s.add_argument("--scheme", default="Bearer", help="Authorization scheme (Bearer, Token, …)")
    s.add_argument("--token-header", default="Authorization",
                   help="header for the token, e.g. X-Hub-Token (gets no scheme)")
    s.add_argument("--show", help='template like "{elapsed_minutes|hm}"')
    s.add_argument("--timeout", type=float, default=10)
    s.set_defaults(func=cmd_api)

    s = sub.add_parser("note", help="create a note from a template and open it")
    s.add_argument("template")
    s.add_argument("directory")
    s.add_argument("--name", default="{title}.md", help="file-name pattern")
    s.add_argument("--title")
    s.add_argument("--ask", metavar="PROMPT", help="ask for the title in a dialog")
    s.add_argument("--open", metavar="EDITOR", help='editor command, e.g. "zettlr"')
    s.set_defaults(func=cmd_note)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="werkbank: %(levelname)s %(message)s", stream=sys.stderr)
    try:
        return args.func(args)
    except Exception as err:  # one clear line for the key, details in the log
        logger.error("%s", err, exc_info=args.verbose)
        _out(ok=False, error=str(err))
        return 1


if __name__ == "__main__":
    sys.exit(main())
