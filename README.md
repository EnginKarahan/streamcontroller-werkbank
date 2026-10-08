# Werkbank – workflow keys for StreamController on KDE Plasma

A [StreamController](https://github.com/StreamController/StreamController) plugin
for people who use their Stream Deck for desk work rather than streaming:
bring apps to the front, jump into a specific Claude Code session, trigger and
watch your own HTTP APIs, create notes from templates, push-to-talk, and
start/stop recordings without ever stopping one by accident.

Built and tested on Fedora 44, KDE Plasma 6 (Wayland), StreamController
1.5.0-beta.16 (Flatpak), Stream Deck XL.

## Actions

| Action | What it does |
|---|---|
| **Focus or start app** | Activates the first window whose class/title matches a regex; runs a start command if none does. Works on Wayland via a short-lived KWin script. |
| **Claude Code session** | One key = one session. Focuses the kitty window that runs it, or opens kitty in the session folder and resumes it by id. On first use the key adopts the newest session of that folder. |
| **API call / status** | HTTP call on press (optionally long press only); polls a status URL and shows a value on the key, e.g. `{elapsed_minutes\|hm}`. Highlights when the text matches a regex; with a second URL the key becomes a toggle (clock in / clock out). |
| **New note from template** | Copies a Markdown template (Zettlr, Obsidian, …), sets `id`, `date`, `title` in the front matter and the first `#` heading, asks for a title if wanted, opens the file. Never overwrites an existing note, so a daily-journal key simply reopens today's file. |
| **Hold: press / release** | One command on key down, another on key up – push-to-talk. |
| **Guarded start/stop** | For recordings: state from a status command (exit code 0 = running), start with a short press, stop **only** with a long press. No discard path. |

Plus, outside the plugin:

- **`kwin/werkbank-autopage`** – a KWin script that tells StreamController
  which window became active (`NotifyForegroundWindow` on its D-Bus API). This
  makes StreamController's per-app page switching work on Plasma Wayland
  without `kdotool` polling: one D-Bus call per window activation, title
  changes are ignored on purpose (terminals retitle constantly).
- **`werkbank-cli`** – the core as a command line tool, usable from any
  launcher: `windows`, `focus`, `desktop N`, `claude open|pin`, `api`, `note`,
  `icon`. Every command prints one JSON object.

## Icons

Every action has an *Icon* setting: an app id (`org.telegram.desktop`), an
icon name from your theme (`media-record`) or a file. Left empty, *Focus or
start app* guesses the app from its start command. Icons are looked up the
way the desktop does it – the app's `.desktop` file, then your icon theme and
its parents (KDE's config cascade included), then `pixmaps` – and rendered to
PNG in `~/.cache/werkbank/icons`, where the sandboxed app can read them. The
plugin ships no third-party logos. An image you pick in StreamController
always wins.

## Install

```sh
# 1. Plugin (Flatpak StreamController)
git clone https://github.com/EnginKarahan/streamcontroller-werkbank \
  ~/.var/app/com.core447.StreamController/data/plugins/io_github_EnginKarahan_Werkbank

# 2. Optional: per-app pages on Plasma Wayland
kpackagetool6 --type=KWin/Script -i kwin/werkbank-autopage
kwriteconfig6 --file kwinrc --group Plugins --key werkbank-autopageEnabled true
qdbus-qt6 org.kde.KWin /KWin reconfigure
```

Then set the window class (e.g. `org.kde.dolphin`) in a page's
*auto change* settings in StreamController. `werkbank-cli windows` lists the
classes of all open windows.

Requirements on the host: Python 3 with PyGObject (preinstalled on Plasma),
KWin 6. For Claude sessions: kitty with remote control
(`allow_remote_control socket-only`, `listen_on unix:@mykitty`). For title
prompts: `kdialog` or `zenity`.

## Secrets

Key settings end up in StreamController's page JSON, which people export and
share. So a key never stores a token – only the **name** of a variable:

```sh
mkdir -p ~/.config/werkbank
printf 'MY_API_TOKEN=...\n' >> ~/.config/werkbank/.env
chmod 600 ~/.config/werkbank/.env   # werkbank refuses group/world-readable files
```

In the key: *Token variable* `MY_API_TOKEN`, *Token header* `Authorization`
(scheme `Bearer`/`Token`) or a custom header such as `X-Api-Token` (sent
without scheme). The process environment wins over the file; set
`WERKBANK_ENV` to use another file.

## How it works

StreamController runs sandboxed, where KWin, kitty and your programs are out
of reach. Every action therefore calls `werkbank-cli` on the host through
`flatpak-spawn --host` (with `--directory=$HOME`, since the sandbox cwd does
not exist on the host). The CLI talks to KWin by loading a small script,
which reports back via `callDBus` to a receiver the CLI owns for that one
call. It never registers global shortcuts (that crashes KWin on Plasma 6.7).

## Development

Notes for anyone hacking on it:

- Pages created over D-Bus (`AddPage`) need `image-control-action`,
  `background-control-action` and `label-control-actions` in each key state,
  or StreamController discards what an action sets at runtime.
- Key updates go through `on_ready` or a queue drained in `on_tick`; updates
  from plugin threads did not reliably reach the key.
- Many parallel `flatpak-spawn` calls make the sandbox's D-Bus proxy refuse
  connections, hence the small pool and retry in `actions/base.py`.


```sh
python3 -m unittest discover -s tests -t .
```

Test without hardware: in StreamController's settings → developer, add a
fake deck (or set `"dev": {"n-fake-decks": 1, "fake-deck-types": ["Stream Deck XL"]}`
in `data/settings/settings.json`), then use
`--emulate-input press|long-press fake-deck-1 <page> x,y`.

## License

GPL-3.0, like StreamController.
