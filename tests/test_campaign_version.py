"""Each world records the engine version it was built with; old worlds are offered an update."""
from __future__ import annotations

import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from test_playtest_round6 import SCRIPTS, _Camp  # noqa: E402

sys.path.insert(0, str(SCRIPTS))


class CampaignVersionTests(_Camp):
    def v(self, *a):
        return self.run_py("campaign_version.py", "-c", "eden", *a)

    def engine(self):
        import campaign_version
        return campaign_version.engine_version()

    def test_engine_version_matches_the_repo(self):
        repo_version = (SCRIPTS.parents[2] / "VERSION").read_text(encoding="utf-8").strip()
        self.assertEqual(self.engine(), repo_version)

    def test_stamp_then_current(self):
        self.assertIn("UPDATE AVAILABLE", self.v("check").stdout)            # untracked = older
        self.assertIn(f"v{self.engine()}", self.v("stamp").stdout)
        data = json.loads((self.camp / "dne-version.json").read_text(encoding="utf-8"))
        self.assertEqual(data["created_with"], self.engine())
        self.assertIn("up to date", self.v("check").stdout)
        self.assertIn("Already stamped", self.v("stamp").stdout)

    def test_older_world_declined_then_updated(self):
        (self.camp / "dne-version.json").write_text(json.dumps(
            {"created_with": "1.1.0", "world_version": "1.1.0", "declined": None}), encoding="utf-8")
        out = self.v("check").stdout
        self.assertIn("this world is at v1.1.0", out)
        self.assertIn("New since then:", out)
        self.assertIn("v1.2.0", out)
        self.assertNotIn("v1.1.0:", out)                  # only versions after the world's
        self.v("mark", "--declined")
        self.assertIn("chose not to update", self.v("check").stdout)
        self.v("mark")
        data = json.loads((self.camp / "dne-version.json").read_text(encoding="utf-8"))
        self.assertEqual((data["created_with"], data["world_version"], data["declined"]),
                         ("1.1.0", self.engine(), None))
        self.assertEqual(len(data["history"]), 2)

    def test_newer_world_needs_an_engine_update(self):
        (self.camp / "dne-version.json").write_text(json.dumps({"world_version": "99.0.0"}), encoding="utf-8")
        self.assertIn("/dne update", self.v("check").stdout)

    def test_audit_lists_the_gaps(self):
        (self.camp / "world.md").write_text("# W\n## Factions\n### The Kept\n", encoding="utf-8")
        (self.camp / "characters" / "mae.md").write_text("# Mae\n## Identity\n", encoding="utf-8")
        out = self.v("audit").stdout
        self.assertIn("state.md: add section `## Session Flags`", out)
        self.assertIn("state.md Session Flags: add `- content: standard` (ask the table)", out)
        self.assertIn("world.md: add section `## The Settlement`", out)
        self.assertIn("npcs.md: missing", out)
        self.assertIn("characters/mae.md: add", out)
        self.assertIn("`## Bonds`", out)
        self.assertNotIn("Spell Slots", out)               # optional for non-casters
        self.assertIn("worldkit.json: add `place_tags`", out)
        self.assertIn("add `morale`, `instinct` and `instincts` to monsters", out)
        self.assertIn("faction.py add", out)
        self.assertIn("calendar.py init", out)

    def test_audit_clean_world(self):
        tpl = SCRIPTS.parent / "templates"
        for name in ("state.md", "world.md", "npcs.md", "npcs-full.md", "session-log.md"):
            (self.camp / name).write_text((tpl / name).read_text(encoding="utf-8"), encoding="utf-8")
        (self.camp / "worldkit.json").unlink()
        (self.camp / "factions.json").write_text("{}", encoding="utf-8")
        (self.camp / "calendar.json").write_text("{}", encoding="utf-8")
        (self.camp / "graph.json").write_text("{}", encoding="utf-8")
        todo = [l for l in self.v("audit").stdout.splitlines() if l.startswith("- [ ]")]
        self.assertEqual(todo, ["- [ ] worldkit.json: none (classic SRD fantasy); nothing to add unless "
                                "the table wants a World Kit"])

    def test_chained_sequel_keeps_the_world(self):
        self.v("stamp")
        (self.camp / "world.md").write_text("# W\n", encoding="utf-8")
        r = self.run_py("campaign_chain.py", "--from", "eden", "--to", "eden-2")
        self.assertEqual(r.returncode, 0, r.stderr)
        sequel = self.root / "campaigns" / "eden-2"
        self.assertTrue((sequel / "dne-version.json").exists())
        self.assertTrue((sequel / "worldkit.json").exists())

    def test_snapshot_tracks_the_file(self):
        import turn_snapshot
        self.assertIn("dne-version.json", turn_snapshot.CAMPAIGN_FILES)


class VersionOrderTests(unittest.TestCase):
    def test_pre_releases_sort_as_semver(self):
        import campaign_version
        import update_skill
        order = ["1.8.6", "2.0.0-alpha.1", "2.0.0-alpha.2", "2.0.0-alpha.10", "2.0.0-beta", "2.0.0", "2.0.1"]
        self.assertEqual(sorted(reversed(order), key=campaign_version.vkey), order)
        self.assertTrue(update_skill._is_newer("2.0.0", "2.0.0-alpha.9"))
        self.assertFalse(update_skill._is_newer("2.0.0-alpha.9", "2.0.0"))
        self.assertTrue(update_skill._is_newer("1.8.6", "unknown"))
