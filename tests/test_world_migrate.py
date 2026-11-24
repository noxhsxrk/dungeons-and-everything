"""World plan section 5: an existing save comes onto the engine without being rewritten, can be
watched in shadow first, and can be taken off again or restored, with what would be lost said first."""
from __future__ import annotations

import json
import os
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _engine_case import EngineCase  # noqa: E402


class MigrateTests(EngineCase):
    FLAGS = "- display: none\n- roll_mode: auto\n"          # an old save: the engine was never mentioned

    def setUp(self):
        super().setUp()
        (self.camp / "npcs.md").write_text(
            "# NPCs\n\n| Name | Role | Faction | Location | Attitude | Notes |\n|---|---|---|---|---|---|\n"
            "| Bren | miller | | Millbridge | friendly | |\n| Rina Saelim | inventor | | Market | friendly | |\n"
            "| Rina Voss | toll clerk | Tollmen | The Ford | neutral | |\n", encoding="utf-8")
        (self.camp / "npcs-full.md").write_text(
            "# NPCs\n\n## Bren\n- **Aliases:** เบรน\n- **HP:** 9 | **AC:** 11\n- **Schedule:** At the mill from dawn; the tavern after dark.\n\n"
            "## Rina Saelim\n- **Aliases:** รินะ, Rina\n- **HP:** 12 | **AC:** 12\n\n"
            "## Rina Voss\n- **Aliases:** Rina\n- **HP:** 8 | **AC:** 10\n", encoding="utf-8")
        import world_migrate
        self.m = world_migrate

    def files(self):
        return {str(p.relative_to(self.camp)): p.read_bytes() for p in self.camp.rglob("*") if p.is_file()}

    def test_inspect_changes_nothing_and_says_what_is_unclear(self):
        before = self.files()
        report = self.m.inspect("oldworld")
        self.assertEqual(self.files(), before)                                   # a dry run
        ids = {e["id"]: e["name"] for e in report["entities"]}
        self.assertEqual(ids["npc:rina-saelim"], "Rina Saelim")
        self.assertEqual(ids["npc:rina-voss"], "Rina Voss")                      # two Rinas, two stable ids
        self.assertIn("รินะ", [a for e in report["entities"] if e["id"] == "npc:rina-saelim" for a in e["aliases"]])
        unclear = {u["alias"]: u["could_mean"] for u in report["unclear"]}
        self.assertEqual(sorted(unclear["rina"]), ["npc:rina-saelim", "npc:rina-voss"])   # "Rina" alone could be either
        self.assertEqual(report["waiting_for_the_gm"], [{"npc": "Bren", "schedule": "At the mill from dawn; the tavern after dark."}])
        self.assertEqual(report["schema_version"]["engine"], 1)
        self.assertTrue(any("world.db" in line for line in report["would_change"]))

    def test_enable_backs_up_first_and_converts_nothing(self):
        sheet = (self.camp / "npcs-full.md").read_bytes()
        out = self.m.enable("oldworld")
        self.assertEqual(out["enabled"], "on")
        backup = self.camp / ".world-backups" / out["backup"]["backup"]
        manifest = json.loads((backup / "manifest.json").read_text(encoding="utf-8"))
        self.assertIn("state.md", manifest["files"])
        self.assertIn("companions/Bren.md", manifest["files"])
        self.assertNotIn("world_engine", (backup / "state.md").read_text(encoding="utf-8"))   # taken before the change
        self.assertEqual((self.camp / "npcs-full.md").read_bytes(), sheet)       # the prose schedule is still prose
        self.assertEqual(self.wdb.enabled("oldworld"), True)
        self.assertEqual(self.thing("entity", "npc:rina-voss")["name"], "Rina Voss")
        played = self.do("[Mira]: we wait an hour", {"action": "wait", "hours": 1})   # and it plays through the normal way in
        self.assertEqual(played["elapsed_minutes"], 60)

    def test_shadow_watches_without_touching_the_campaign(self):
        self.m.enable("oldworld", shadow=True)
        self.assertFalse(self.wdb.enabled("oldworld"))
        self.assertFalse((self.camp / "world.db").exists())
        import gm_guide
        note = "\n".join(gm_guide.turn_notes("oldworld", count=False, text="[Mira]: I ask Bren about the toll"))
        self.assertIn("(world engine, shadow) It would have told you:", note)
        logged = json.loads((self.camp / ".world-shadow.jsonl").read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(logged["context"]["mentioned"][0]["name"], "Bren")
        before = self.files()
        calendar = (self.camp / "calendar.json").read_bytes()
        ran = self.m.shadow_run("oldworld", [{"action": "rest", "type": "long"}])
        self.assertEqual(ran["would_have"]["elapsed_minutes"], 480)              # what the engine would have done
        self.assertIn("calendar.json", ran["files_it_would_change"])
        self.assertTrue(ran["real_campaign_untouched"])
        self.assertEqual((self.camp / "calendar.json").read_bytes(), calendar)   # the GM's own rest is the only one
        self.assertEqual(self.files(), before)

    def test_compare_shows_where_the_gm_and_the_engine_differ(self):
        self.m.enable("oldworld", shadow=True)
        self.assertIn("no shadow run", self.m.compare("oldworld")["error"])
        ran = self.m.shadow_run("oldworld", [{"action": "rest", "type": "long"}])
        self.assertIn("compare", ran["next"])
        cal = json.loads((self.camp / "calendar.json").read_text(encoding="utf-8"))
        cal["hour"] = (int(cal.get("hour", 0)) + 4) % 24                       # the GM rests only four hours
        (self.camp / "calendar.json").write_text(json.dumps(cal, indent=2), encoding="utf-8")
        (self.camp / "notes.md").write_text("the GM's own note\n", encoding="utf-8")
        got = self.m.compare("oldworld")
        self.assertFalse(got["same"])
        self.assertIn("calendar.json", got["differ"])
        self.assertTrue(any(line.startswith("-") or line.startswith("+") for line in got["differ"]["calendar.json"]))
        self.assertIn("notes.md", got["gm_only"])
        self.assertNotIn("state.md", got["gm_only"] + list(got["engine_only"]))

    def test_disable_leaves_nothing_half_done_and_a_page_to_run_from(self):
        self.m.enable("oldworld")
        self.flags(self.FLAGS.replace("roll_mode: auto", "roll_mode: players") + "- world_engine: on\n")
        self.do("a market and a roll in the air",
                {"action": "market", "at": "Market", "stock": {"flour": 3}, "base": {"flour": 5}, "target": {"flour": 20}, "cash": 50},
                {"action": "schedule", "in_minutes": 600, "text": "The rider reaches the mill.", "event_id": "rider"},
                {"actor": "Mira", "action": "roll", "spec": "1d20+5", "dc": 13})
        out = self.m.disable("oldworld")
        self.assertEqual(out["parked_turn"]["was_waiting_on"][0][:10], "Mira: roll")
        self.assertFalse(self.wdb.enabled("oldworld"))
        page = (self.camp / "world-export.md").read_text(encoding="utf-8")
        self.assertIn("The rider reaches the mill.", page)
        self.assertIn("## Markets", page)
        self.assertTrue((self.camp / "world.db").exists())                       # history kept for reopening
        self.m.enable("oldworld")
        self.assertEqual(self.turn.status("oldworld")["status"], "idle")        # nothing was left open
        self.assertEqual(self.thing("market", "market")["stock"]["flour"], 3)   # and it goes on from where it was

    def test_restore_says_what_would_be_lost_before_doing_it(self):
        made = self.m.enable("oldworld")["backup"]["backup"]
        self.do("[Mira]: three days go by", {"action": "wait", "days": 3})
        self.turn.finish("oldworld", "Days pass.")
        ask = self.m.restore("oldworld")
        self.assertEqual(ask["would_restore"], made)
        self.assertEqual(ask["would_lose"], {"turns": 1, "in_world_minutes": 3 * 1440})
        self.assertIn("1 engine turn(s) and 3 in-world day(s)", ask["say"])
        self.assertTrue(self.wdb.enabled("oldworld"))                            # nothing happened yet
        done = self.m.restore("oldworld", yes=True)
        self.assertFalse(self.wdb.enabled("oldworld"))                           # back to the save as it was
        self.assertEqual(self.read_json("calendar.json")["day"], 15)
        self.assertEqual(len(self.m.backups("oldworld")), 2)                     # the state before the restore is kept too
        self.assertIn(done["safety_backup"], [b["taken"] for b in self.m.backups("oldworld")])


if __name__ == "__main__":
    unittest.main()
