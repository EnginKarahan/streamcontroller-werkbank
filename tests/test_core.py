"""Tests for the parts of the core that need no desktop (run: python3 -m unittest)."""

import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from werkbank import api, claude, dnd, icons, keys, notes

NOW = datetime(2026, 10, 8, 14, 5, 9)

TEMPLATE = """---
title: "Zetteltitel"
date: 2026-02-18
id: 20260218120327
type: "zettel"
nested:
  title: keep me
---

# Zetteltitel

## Zusammenfassung
# not the first heading
"""


class PickRender(unittest.TestCase):
    data = {"active": True, "elapsed_minutes": 134, "items": [{"name": "a"}, {"name": "b"}]}

    def test_pick(self):
        self.assertEqual(api.pick(self.data, "items.1.name"), "b")
        self.assertEqual(api.pick(self.data, "items.-1.name"), "b")
        self.assertIsNone(api.pick(self.data, "items.5.name"))
        self.assertIsNone(api.pick(self.data, "missing.deep"))

    def test_render(self):
        self.assertEqual(api.render("{elapsed_minutes|hm} h", self.data), "2:14 h")
        self.assertEqual(api.render("{active}", self.data), "true")
        self.assertEqual(api.render("{missing}", self.data), "")
        self.assertEqual(api.render("{}", 5), "5")

    def test_wildcard_and_worst(self):
        data = {"tasks": [{"s": {"level": "ok"}}, {"s": {"level": "warn"}}, {"s": None}]}
        self.assertEqual(api.pick(data, "tasks.*.s.level"), ["ok", "warn", None])
        self.assertEqual(api.render("{tasks.*.s.level|worst}", data), "warn")
        self.assertEqual(api.render("{tasks.*.s.level}", data), "ok warn ")

    def test_unknown_filter(self):
        with self.assertRaises(api.ApiError):
            api.render("{active|nope}", self.data)


class Secrets(unittest.TestCase):
    def test_env_file_must_be_private(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = Path(tmp) / ".env"
            env.write_text("export WB_TEST_TOKEN='abc'\n# comment\n")
            env.chmod(0o644)
            with self.assertRaises(api.ApiError):
                api.read_env_file(env)
            env.chmod(0o600)
            self.assertEqual(api.read_env_file(env), {"WB_TEST_TOKEN": "abc"})

    def test_environment_wins(self):
        with mock.patch.dict(os.environ, {"WB_TEST_TOKEN": "from-env"}):
            self.assertEqual(api.secret("WB_TEST_TOKEN"), "from-env")

    def test_missing_secret_fails_fast(self):
        with mock.patch.object(api, "read_env_file", return_value={}), \
                mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(api.ApiError):
                api.secret("WB_NOT_THERE")


class Notes(unittest.TestCase):
    def test_render_overrides_front_matter_and_first_h1(self):
        out = notes.render(TEMPLATE, notes.fields('Ein "Titel"', NOW))
        self.assertIn('title: "Ein \\"Titel\\""\n', out)
        self.assertIn("date: 2026-10-08\n", out)
        self.assertIn("id: 20261008140509\n", out)
        self.assertIn("  title: keep me\n", out)        # nested key untouched
        self.assertIn('# Ein "Titel"\n', out)
        self.assertIn("# not the first heading\n", out)

    def test_placeholders(self):
        out = notes.render("# {date_de} - Tageslog\n{time}\n", notes.fields("", NOW))
        self.assertEqual(out, "# 08.10.2026 - Tageslog\n14:05\n")  # no title: H1 kept

    def test_create_never_overwrites(self):
        with tempfile.TemporaryDirectory() as tmp:
            tpl = Path(tmp) / "t.md"
            tpl.write_text(TEMPLATE)
            path, created = notes.create(tpl, Path(tmp) / "out", "{date} - Tageslog.md",
                                         title="08.10.2026 - Tageslog", now=NOW)
            self.assertTrue(created)
            self.assertEqual(path.name, "2026-10-08 - Tageslog.md")
            path.write_text("edited")
            again, created = notes.create(tpl, Path(tmp) / "out", "{date} - Tageslog.md",
                                          title="x", now=NOW)
            self.assertFalse(created)
            self.assertEqual(again.read_text(), "edited")

    def test_safe_filename(self):
        self.assertEqual(notes.safe_filename("a/b: c?"), "a-b- c-")
        self.assertEqual(notes.safe_filename(" . "), "note")


class ClaudeSessions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.projects = root / "projects"
        self.workdir = root / "work_dir 2.1"
        self.workdir.mkdir()
        self.patches = [mock.patch.object(claude, "PROJECTS", self.projects),
                        mock.patch.object(claude, "STATE", root / "state.json")]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_slug(self):
        self.assertTrue(claude.project_dir(self.workdir).name.endswith("-work-dir-2-1"))

    def test_adopts_newest_then_stays_pinned(self):
        pdir = claude.project_dir(self.workdir)
        pdir.mkdir(parents=True)
        old, new = pdir / "old.jsonl", pdir / "new.jsonl"
        old.write_text("{}")
        new.write_text("{}")
        os.utime(old, (1, 1))
        self.assertEqual(claude.resolve("web", self.workdir), ("new", True))
        os.utime(new, (1, 1))
        os.utime(old, None)  # old is newer now, the key must not wander
        self.assertEqual(claude.resolve("web", self.workdir), ("new", True))

    def test_fresh_folder_gets_stable_new_id(self):
        sid, exists = claude.resolve("neu", self.workdir)
        self.assertFalse(exists)
        self.assertEqual(claude.resolve("neu", self.workdir), (sid, False))
        self.assertEqual(json.loads((Path(self.tmp.name) / "state.json").read_text()),
                         {"neu": sid})


class Icons(unittest.TestCase):
    def test_desktop_file_then_theme_prefers_svg(self):
        with tempfile.TemporaryDirectory() as tmp:
            share = Path(tmp)
            (share / "applications").mkdir()
            (share / "applications/org.example.App.desktop").write_text(
                "[Desktop Entry]\nName=App\nIcon=example-app\nExec=app %U\n")
            for rel in ("hicolor/48x48/apps/example-app.png",
                        "hicolor/256x256/apps/example-app.png",
                        "hicolor/scalable/apps/example-app.svg"):
                f = share / "icons" / rel
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text("x")
            with mock.patch.object(icons, "data_dirs", return_value=[share]), \
                    mock.patch.object(icons, "current_theme", return_value="hicolor"), \
                    mock.patch.object(icons, "_icon_roots", return_value=[share / "icons"]):
                self.assertEqual(icons.desktop_icon("org.example.App"), "example-app")
                self.assertEqual(icons.find("org.example.App").name, "example-app.svg")
                self.assertIsNone(icons.find("org.example.Missing"))

    def test_cache_name_follows_file_changes(self):
        with tempfile.NamedTemporaryFile(suffix=".png") as f:
            before = icons.cached_path(f.name)
            os.utime(f.name, (1, 1))
            self.assertNotEqual(before, icons.cached_path(f.name))
        self.assertEqual(icons.cached_path("org.example.App").name, "org.example.App-256.png")

    def test_guess_from_launch_command(self):
        # actions/ needs StreamController to import; the helper above the
        # class does not, so run just that part of the file.
        src = (Path(__file__).resolve().parent.parent / "actions/focus.py").read_text()
        ns = {}
        exec(src.split("class FocusApp")[0].replace("from .base import Field, WerkbankAction", ""), ns)
        guess = ns["guess_icon"]
        self.assertEqual(guess("flatpak run org.telegram.desktop"), "org.telegram.desktop")
        self.assertEqual(guess("flatpak run --branch=stable us.zoom.Zoom"), "us.zoom.Zoom")
        self.assertEqual(guess("/usr/bin/zettlr --foo"), "zettlr")
        self.assertEqual(guess(""), "")


class Keys(unittest.TestCase):
    def test_translate_letters_and_punctuation_only(self):
        self.assertEqual(keys.translate("ctrl+z"), "ctrl+x:z")
        self.assertEqual(keys.translate("ctrl+alt+minus"), "ctrl+alt+x:minus")
        self.assertEqual(keys.translate("ctrl+k f"), "ctrl+x:k x:f")
        self.assertEqual(keys.translate("shift+pageup f11 ctrl+shift+k:13"),
                         "shift+pageup f11 ctrl+shift+k:13")

    def test_layout_from_kxkbrc(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "kxkbrc").write_text("[Layout]\nLayoutList=de,tr\nUse=true\n")
            with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": tmp}, clear=False):
                os.environ.pop("DOTOOL_XKB_LAYOUT", None)
                self.assertEqual(keys.current_layout(), "de")


class Dnd(unittest.TestCase):
    def test_kconfig_date_roundtrip(self):
        epoch = datetime(2026, 10, 9, 15, 22, 5).timestamp()
        self.assertEqual(dnd.format_until(epoch), "2026,10,9,15,22,5")
        self.assertAlmostEqual(dnd.parse("2026,10,9,15,22,5.812"), epoch + 0.812, places=3)
        self.assertEqual(dnd.parse(""), 0.0)

    def test_start_never_shortens(self):
        later = __import__("time").time() + 3600
        with mock.patch.object(dnd, "until", return_value=later), \
                mock.patch.object(dnd.subprocess, "run") as run:
            dnd.start(10)
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
