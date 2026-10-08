"""Tests for the parts of the core that need no desktop (run: python3 -m unittest)."""

import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from werkbank import api, claude, notes

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


if __name__ == "__main__":
    unittest.main()
