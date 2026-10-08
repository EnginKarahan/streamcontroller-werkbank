"""Create a Markdown note from a template and open it in an editor.

Templates are plain Markdown files with YAML front matter, as used by Zettlr
or Obsidian. They need no special placeholders: if the front matter has the
keys id, date or title, their values are replaced, and so is the first
level-one heading (title and heading only when a title is given). Explicit placeholders work too, in the template body and
in the file-name pattern:

    {id}       timestamp id, %Y%m%d%H%M%S (Zettlr's default)
    {date}     2026-10-08
    {date_de}  08.10.2026
    {time}     14:05
    {title}    the note title
"""

from __future__ import annotations

import logging
import re
import shlex
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from .launch import spawn

logger = logging.getLogger(__name__)

_UNSAFE = re.compile(r'[/\\:*?"<>|\x00-\x1f]')


def fields(title: str, now: datetime) -> dict[str, str]:
    return {
        "id": now.strftime("%Y%m%d%H%M%S"),
        "date": now.strftime("%Y-%m-%d"),
        "date_de": now.strftime("%d.%m.%Y"),
        "time": now.strftime("%H:%M"),
        "title": title,
    }


def _fill(text: str, values: dict[str, str]) -> str:
    for key, value in values.items():
        text = text.replace("{" + key + "}", value)
    return text


def _yaml_str(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def render(template: str, values: dict[str, str]) -> str:
    """Apply placeholders, then set front-matter keys and the first H1."""
    text = _fill(template, values)
    lines = text.splitlines(keepends=True)

    body_start = 0
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                body_start = i + 1
                break
        overrides = {"id": values["id"], "date": values["date"]}
        if values["title"]:
            overrides["title"] = _yaml_str(values["title"])
        keys = "|".join(overrides)
        for i in range(1, max(body_start - 1, 1)):
            m = re.match(rf"^({keys}):", lines[i])  # top level keys only
            if m:
                eol = "\n" if lines[i].endswith("\n") else ""
                lines[i] = f"{m.group(1)}: {overrides[m.group(1)]}{eol}"

    for i in range(body_start, len(lines)):
        if values["title"] and lines[i].startswith("# "):
            eol = "\n" if lines[i].endswith("\n") else ""
            lines[i] = f"# {values['title']}{eol}"
            break
    return "".join(lines)


def safe_filename(name: str) -> str:
    name = _UNSAFE.sub("-", name).strip(" .")
    return name or "note"


def ask_title(prompt: str, default: str = "") -> str | None:
    """Ask for a title with kdialog or zenity. None if cancelled."""
    if shutil.which("kdialog"):
        argv = ["kdialog", "--title", "Werkbank", "--inputbox", prompt, default]
    elif shutil.which("zenity"):
        argv = ["zenity", "--entry", "--title", "Werkbank", "--text", prompt,
                "--entry-text", default]
    else:
        logger.error("neither kdialog nor zenity found, cannot ask for a title")
        return None
    out = subprocess.run(argv, capture_output=True, text=True)
    title = out.stdout.strip()
    return title if out.returncode == 0 and title else None


def create(template: Path, directory: Path, name_pattern: str = "{title}.md",
           title: str = "", now: datetime | None = None) -> tuple[Path, bool]:
    """Create the note (or find the existing one). Returns (path, created).

    An existing file is never overwritten: a daily-journal key simply opens
    today's file a second time.
    """
    now = now or datetime.now()
    values = fields(title, now)
    path = Path(directory).expanduser() / safe_filename(_fill(name_pattern, values))
    if path.exists():
        return path, False
    text = render(Path(template).expanduser().read_text(encoding="utf-8"), values)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as fh:  # "x": never clobber a race winner
        fh.write(text)
    logger.info("created %s", path)
    return path, True


def open_in(editor: str, path: Path) -> None:
    """Open with the editor command; {path} is replaced, else appended."""
    if "{path}" in editor:
        argv = [part.replace("{path}", str(path)) for part in shlex.split(editor)]
    else:
        argv = [*shlex.split(editor), str(path)]
    spawn(argv)
