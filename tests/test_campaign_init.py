"""Living World plan PR 1: one checked seed makes a campaign that is ready to play and to run on its own.
A bad seed says where to fix it and creates nothing; an existing campaign is never touched; a failed build
can be run again."""
from __future__ import annotations

import copy
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "skills" / "dne" / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(HERE))
from _unicode import needs_unicode_fs  # noqa: E402

SEED = {
    "seed_version": 1, "campaign": "hollow", "ruleset": "2014",
    "flags": {"display": "none", "roll_mode": "players", "world_engine": "on"},
    "calendar": {"date": "1 Thaw 412", "time": "morning", "months": ["Thaw", "Bloom", "Ash"], "month_length": 30},
    "map": {"party_location": "millbridge",
            "places": {"millbridge": {"name": "Millbridge"}, "ford": {"name": "The Ford"}, "market": {"name": "Market"}},
            "edges": [{"a": "millbridge", "b": "ford", "road": True, "miles": 12},
                      {"a": "ford", "b": "market", "road": True, "miles": 12}]},
    "npcs": [{"name": "Jonas", "role": "mechanic", "cr": "1/2", "aliases": ["Jo"]},
             {"name": "Bren", "role": "wheelwright", "cr": "1/4"}],
    "factions": [{"name": "Tollmen", "force": 3, "wealth": 4, "influence": 2, "goal": "Tax the bridge", "rivals": ["Millers"]},
                 {"name": "Millers", "force": 2, "wealth": 3, "influence": 3}],
    "setup": [{"action": "settlement", "at": "The Ford", "template": "hollow-9"},
              {"action": "route", "between": ["Millbridge", "The Ford"], "access": "toll", "owner": "Tollmen", "toll": "2 sp"},
              {"action": "market", "at": "Market", "stock": {"flour": 5}, "base": {"flour": 5}, "target": {"flour": 20},
               "cash": 300, "eats": {"flour": 1}},
              {"action": "appointment", "npc": "Bren", "from": "Millbridge", "place": "Market", "in_minutes": 2000},
              {"action": "schedule", "in_minutes": 2880, "text": "The rider reaches the ford.", "event_id": "rider"}],
}


class CampaignInitTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)
        self._saved = {k: os.environ.get(k) for k in ("DNE_CAMPAIGN_ROOT", "DNE_RUNTIME_DIR", "DNE_DISPLAY_HOST", "DNE_OUTBOX_LOG")}
        os.environ.update(DNE_CAMPAIGN_ROOT=str(self.root), DNE_RUNTIME_DIR=str(self.root / "rt"),
                          DNE_DISPLAY_HOST="127.0.0.1:9", DNE_OUTBOX_LOG=str(self.root / "out.jsonl"))
        import campaign_init
        self.ci = campaign_init

    def tearDown(self):
        for k, v in self._saved.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        self._tmp.cleanup()

    def turn(self, *args, stdin=None):
        r = subprocess.run([sys.executable, str(SCRIPTS / "turn.py"), "-c", "hollow", *args], input=stdin,
                           capture_output=True, text=True, encoding="utf-8", env=os.environ.copy())
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout) if r.stdout.strip().startswith("{") else r.stdout

    def test_a_seed_makes_a_world_that_runs_on_its_own(self):
        out = self.ci.build(copy.deepcopy(SEED))
        self.assertTrue(out["ok"], out)
        camp = self.root / "campaigns" / "hollow"
        for f in ("state.md", "world.md", "npcs.md", "npcs-full.md", "session-log.md", "calendar.json",
                  "world-map.json", "factions.json", "world.db", "dne-version.json"):
            self.assertTrue((camp / f).is_file(), f)
        self.assertEqual([p.name for p in self.root.iterdir() if p.name.startswith(".dne-init")], [])   # no staging left
        self.assertFalse((camp / ".snapshots").exists())
        state = (camp / "state.md").read_text(encoding="utf-8")
        self.assertIn("- world_engine: on", state)
        self.assertIn("# Campaign: hollow", state)
        self.assertIn("## Jonas", (camp / "npcs-full.md").read_text(encoding="utf-8"))
        self.assertEqual(json.loads((camp / "factions.json").read_text(encoding="utf-8"))["factions"]["Tollmen"]["rivals"], ["Millers"])
        # A new agent picks the save up and the world goes on: a month passes with nobody calling a model.
        self.turn("begin", "--text", "a month passes")
        res = self.turn("resolve", "--intents", "-", stdin=json.dumps([{"action": "wait", "days": 30},
                                                                       {"action": "community", "at": "The Ford"}]))
        self.assertEqual(res["elapsed_minutes"], 30 * 1440)
        kinds = {v["type"] for v in res["visible_events"]}
        self.assertTrue({"community", "consequence", "npc_arrived"} <= kinds, kinds)
        self.assertEqual(res["results"][-1]["data"]["day"], 30)

    def test_a_bad_seed_says_where_and_creates_nothing(self):
        bad = copy.deepcopy(SEED)
        bad["setup"][1]["between"] = ["Millbridge", "Atlantis"]
        bad["npcs"][1]["cr"] = "lots"
        bad["setup"].append({"action": "fly"})
        bad["factions"][0]["rivals"] = ["Nobody"]
        bad["map"]["edges"].append({"a": "ford", "b": "moon"})
        out = self.ci.build(bad)
        self.assertFalse(out["ok"])
        where = {e["path"] for e in out["errors"]}
        self.assertTrue({"setup[1].between[1]", "npcs[1].cr", "setup[5].action", "factions[0].rivals[0]",
                         "map.edges[2].b"} <= where, where)
        self.assertFalse((self.root / "campaigns" / "hollow").exists())

    def test_the_engine_needs_a_calendar_and_setup_needs_the_engine(self):
        seed = copy.deepcopy(SEED)
        del seed["calendar"]
        self.assertIn("calendar", {e["path"] for e in self.ci.check(seed)})
        seed = copy.deepcopy(SEED)
        seed["flags"]["world_engine"] = "off"
        self.assertIn("setup", {e["path"] for e in self.ci.check(seed)})

    def test_a_classic_campaign_without_the_engine_still_builds(self):
        seed = {"seed_version": 1, "campaign": "plain", "flags": {"display": "none"}}
        out = self.ci.build(seed)
        self.assertTrue(out["ok"], out)
        self.assertFalse((self.root / "campaigns" / "plain" / "world.db").exists())

    def test_an_existing_campaign_is_left_alone(self):
        camp = self.root / "campaigns" / "hollow"
        camp.mkdir(parents=True)
        (camp / "state.md").write_text("mine", encoding="utf-8")
        out = self.ci.build(copy.deepcopy(SEED))
        self.assertFalse(out["ok"])
        self.assertEqual(out["errors"][0]["path"], "campaign")
        self.assertEqual((camp / "state.md").read_text(encoding="utf-8"), "mine")

    def test_a_build_that_fails_part_way_leaves_nothing_and_runs_again(self):
        seed = copy.deepcopy(SEED)
        seed["setup"][0]["template"] = "no-such-place"          # passes the checks, fails when it runs
        out = self.ci.build(seed)
        self.assertFalse(out["ok"])
        self.assertEqual(out["errors"][0]["path"], "setup[0]")
        self.assertIn("no template", out["errors"][0]["error"])
        self.assertFalse((self.root / "campaigns" / "hollow").exists())
        self.assertEqual([p.name for p in self.root.iterdir() if p.name.startswith(".dne-init")], [])
        self.assertTrue(self.ci.build(copy.deepcopy(SEED))["ok"])


    def test_with_the_display_defaults_nothing_of_the_build_reaches_a_screen(self):
        seed = copy.deepcopy(SEED)
        seed["flags"].update(display="ngrok", autorun="true")
        self.assertTrue(self.ci.build(seed)["ok"])
        import sqlite3
        db = sqlite3.connect(str(self.root / "campaigns" / "hollow" / "world.db"))
        try:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM turns WHERE status != 'finished'").fetchone()[0], 0)
        finally:
            db.close()

    def test_commas_and_unknown_flags(self):
        seed = copy.deepcopy(SEED)
        seed["npcs"][0]["aliases"] = ["Jo, the mechanic"]
        seed["flags"]["wordl_engine"] = "on"
        self.assertIn("npcs[0].aliases[0]", {e["path"] for e in self.ci.check(seed)})
        self.assertIn("flags.wordl_engine", {w["path"] for w in self.ci.warnings(seed)})

    @needs_unicode_fs
    def test_a_thai_world(self):
        seed = copy.deepcopy(SEED)
        seed["campaign"] = "krung"
        seed["calendar"] = {"date": "1 เมษายน 2567", "months": ["มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน"], "month_length": 30}
        seed["map"]["places"]["ford"]["name"] = "ท่าน้ำ"
        seed["npcs"] = [{"name": "ช่างโจ", "role": "ช่างซ่อม", "cr": "1/2", "aliases": ["โจ"]}]
        seed["factions"] = [{"name": "กลุ่มเรือจ้าง", "force": 2, "wealth": 3, "influence": 2}]
        seed["setup"] = [{"action": "settlement", "at": "ท่าน้ำ", "template": "hollow-9"}]
        out = self.ci.build(seed)
        self.assertTrue(out["ok"], out)
        camp = self.root / "campaigns" / "krung"
        self.assertIn("## ช่างโจ", (camp / "npcs-full.md").read_text(encoding="utf-8"))
        self.assertIn("กลุ่มเรือจ้าง", (camp / "factions.json").read_text(encoding="utf-8"))
        self.assertIn("เมษายน", (camp / "calendar.json").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
