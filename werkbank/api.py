"""HTTP calls for keys: trigger an action, or read a value to show on a key.

Secrets never live in key settings (StreamController stores those in page
JSON that people export and share). A key only names an environment
variable; its value comes from the process environment or from the env file
(default ~/.config/werkbank/.env, which must be mode 600).
"""

from __future__ import annotations

import json
import logging
import os
import re
import stat
import urllib.error
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

ENV_FILE = Path(os.environ.get(
    "WERKBANK_ENV",
    Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "werkbank" / ".env"))


class ApiError(RuntimeError):
    pass


def read_env_file(path: Path = ENV_FILE) -> dict[str, str]:
    if not path.exists():
        return {}
    mode = path.stat().st_mode
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise ApiError(f"{path} is readable by others; run: chmod 600 {path}")
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip().removeprefix("export ").strip()] = value.strip().strip("'\"")
    return values


def secret(name: str) -> str:
    """Value of a secret by variable name; environment wins over the env file."""
    value = os.environ.get(name) or read_env_file().get(name)
    if not value:
        raise ApiError(f"secret {name} is not set (environment or {ENV_FILE})")
    return value


def request(url: str, method: str = "GET", body: dict | str | None = None,
            headers: dict[str, str] | None = None, token_env: str | None = None,
            token_scheme: str = "Bearer", token_header: str = "Authorization",
            timeout: float = 10) -> tuple[int, object]:
    """Perform the call; returns (HTTP status, parsed JSON or text).

    The token goes into `token_header`; only the Authorization header gets
    the scheme prefix (others, like X-Hub-Token, carry the bare token).
    HTTP error statuses are returned, not raised, so a key can show them
    (e.g. 428 = the server wants a confirmation). Network failures raise.
    """
    headers = dict(headers or {})
    data = None
    if body is not None:
        data = (body if isinstance(body, str) else json.dumps(body)).encode()
        headers.setdefault("Content-Type", "application/json")
    if token_env:
        token = secret(token_env)
        headers[token_header] = (f"{token_scheme} {token}".strip()
                                 if token_header.lower() == "authorization" else token)
    headers.setdefault("Accept", "application/json")

    req = urllib.request.Request(url, data=data, method=method.upper(), headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status, raw = resp.status, resp.read()
    except urllib.error.HTTPError as err:
        status, raw = err.code, err.read()
    except (urllib.error.URLError, TimeoutError, OSError) as err:
        raise ApiError(f"{method} {url}: {getattr(err, 'reason', err)}") from err

    text = raw.decode("utf-8", errors="replace")
    try:
        return status, json.loads(text)
    except json.JSONDecodeError:
        return status, text


def pick(data: object, path: str) -> object:
    """Dot path into JSON: "items.0.name". Missing parts give None.

    "*" maps the rest of the path over a list: "tasks.*.status.level".
    """
    parts = [p for p in path.split(".") if p]
    for i, part in enumerate(parts):
        if part == "*":
            if not isinstance(data, list):
                return None
            rest = ".".join(parts[i + 1:])
            return [pick(item, rest) for item in data]
        if isinstance(data, list) and part.lstrip("-").isdigit():
            idx = int(part)
            data = data[idx] if -len(data) <= idx < len(data) else None
        elif isinstance(data, dict):
            data = data.get(part)
        else:
            return None
    return data


def _hm(value: object) -> str:
    """Minutes to H:MM; empty when there is no value (e.g. timer not running)."""
    if value is None:
        return ""
    try:
        minutes = int(float(value))
    except (TypeError, ValueError):
        return "?"
    return f"{minutes // 60}:{minutes % 60:02d}"


SEVERITY = ["ok", "info", "warn", "warning", "error", "critical"]


def _worst(value: object) -> str:
    """Most severe of a list of status words (ok < info < warn < error)."""
    items = [str(v).lower() for v in (value if isinstance(value, list) else [value])
             if v is not None]
    if not items:
        return ""
    return max(items, key=lambda v: SEVERITY.index(v) if v in SEVERITY else len(SEVERITY))


FILTERS = {
    "hm": _hm,
    "worst": _worst,
    "upper": lambda v: str(v).upper(),
}

_FIELD = re.compile(r"\{([^{}|]*)(?:\|(\w+))?\}")


def render(template: str, data: object) -> str:
    """Fill {path} or {path|filter} placeholders from JSON data.

    {} alone is the whole response. Booleans render as "true"/"false",
    so state rules can match them.
    """
    def sub(m: re.Match) -> str:
        value = pick(data, m.group(1)) if m.group(1) else data
        if m.group(2):
            fn = FILTERS.get(m.group(2))
            if fn is None:
                raise ApiError(f"unknown filter |{m.group(2)}")
            return fn(value)
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, list):
            return " ".join("" if v is None else str(v) for v in value)
        return "" if value is None else str(value)
    return _FIELD.sub(sub, template)
