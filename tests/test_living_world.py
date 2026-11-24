"""Living World plan PR 5: the whole loop through the normal way in, with no model anywhere.
`/dne new` (a seed) → a turn that changes the world → a month passes → a fresh agent opens the save and reads it back.
Two different worlds run for 30 days; one save runs free and with the players stepping in, and the difference
traces back to what they did; a run stopped midway resumes to the same world; an undo takes a month back."""
from __future__ import annotations

import copy
import json
import os
import pathlib
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "skills" / "dne" / "scripts"
sys.path.insert(0, str(SCRIPTS))

MAP = {"party_location": "millbridge",
       "places": {"millbridge": {"name": "Millbridge"}, "ford": {"name": "The Ford"}, "market": {"name": "Market"}},
       "edges": [{"a": "millbridge", "b": "ford", "road": True, "miles": 12},
                 {"a": "ford", "b": "market", "road": True, "miles": 12}]}
CAL = {"date": "1 Thaw 412", "time": "morning", "months": ["Thaw", "Bloom", "Ash", "Frost"], "month_length": 30}

FORGE_TOWN = {
    "seed_version": 1, "campaign": "forge", "flags": {"display": "none", "roll_mode": "auto", "world_engine": "on"},
    "calendar": CAL, "map": MAP,
    "npcs": [{"name": "Bren", "role": "smith", "cr": "1/2"}, {"name": "Tam", "role": "carter", "cr": "1/4"}],
    "factions": [{"name": "Tollmen", "force": 3, "wealth": 4, "influence": 2, "rivals": ["Millers"]},
                 {"name": "Millers", "force": 2, "wealth": 3, "influence": 3}],
    "setup": [
        {"action": "store", "id": "forge", "items": {"ore": 10, "coal": 0}},
        {"action": "rule", "id": "smelt", "label": "smelt iron", "actor": {"skill": "smith"},
         "cost": {"forge": {"ore": 2, "coal": 1}}, "minutes": 480, "gives": {"forge": {"iron": 1}}},
        {"action": "rule", "id": "haul-coal", "label": "haul coal", "actor": {"skill": "haul"}, "minutes": 1440,
         "gives": {"forge": {"coal": 2}},
         "cancel_if": [{"thing": ["route", "ford|millbridge"], "path": "access", "equals": "closed"}]},
        {"action": "agent", "name": "Bren", "skills": {"smith": 2}, "duties": [{"rule": "smelt", "priority": 5}]},
        {"action": "agent", "name": "Tam", "skills": {"haul": 1}, "duties": [{"rule": "haul-coal", "priority": 5}]},
        {"action": "market", "at": "Market", "stock": {"flour": 6}, "base": {"flour": 5}, "target": {"flour": 20},
         "cash": 400, "eats": {"flour": 1}},
        {"action": "caravan", "id": "flour", "from": "Millbridge", "to": "Market", "goods": {"flour": 20},
         "departs_in_minutes": 4320},
        {"action": "schedule", "in_minutes": 7200, "event_id": "fair", "text": "The spring fair opens at the ford.",
         "unless": [{"thing": ["route", "ford|millbridge"], "path": "access", "equals": "closed"}]},
    ]}

HOLLOW = {"seed_version": 1, "campaign": "hollow", "flags": {"display": "none", "world_engine": "on"},
          "calendar": CAL, "map": MAP, "setup": [{"action": "settlement", "at": "The Ford", "template": "hollow-9"}]}

CLOSE = [{"action": "route", "between": ["Millbridge", "The Ford"], "access": "closed", "reason": "the Tollmen hold it"}]


class LivingWorldTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)
        self.env = {**os.environ, "DNE_CAMPAIGN_ROOT": str(self.root), "DNE_RUNTIME_DIR": str(self.root / "rt"),
                    "DNE_DISPLAY_HOST": "127.0.0.1:9", "DNE_OUTBOX_LOG": str(self.root / "out.jsonl"),
                    "PYTHONIOENCODING": "utf-8"}
        self.env.pop("DNE_CRASH_AT", None)

    def tearDown(self):
        self._tmp.cleanup()

    # every call is a new process: a new agent opening the save
    def run_py(self, script, *args, stdin=None, crash=None, ok=True):
        env = {**self.env, **({"DNE_CRASH_AT": crash} if crash else {})}
        r = subprocess.run([sys.executable, str(SCRIPTS / script), *args], input=stdin, capture_output=True,
                           encoding="utf-8", env=env, timeout=120)
        if crash:
            self.assertEqual(r.returncode, 77, r.stdout + r.stderr)
            return None
        if ok:
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return json.loads(r.stdout) if r.stdout.strip().startswith("{") else r.stdout

    def new(self, seed):
        out = self.run_py("campaign_init.py", "--seed", "-", stdin=json.dumps(seed))
        self.assertTrue(out["ok"], out)

    def turn(self, campaign, text, intents, narration="So it goes.", crash=None):
        self.run_py("turn.py", "-c", campaign, "begin", "--text", text)
        res = self.run_py("turn.py", "-c", campaign, "resolve", "--intents", "-", stdin=json.dumps(intents), crash=crash)
        if crash:
            return None
        self.run_py("turn.py", "-c", campaign, "finish", "--narration", narration)
        return res

    def db(self, campaign):
        db = sqlite3.connect(str(self.root / "campaigns" / campaign / "world.db"))
        db.row_factory = sqlite3.Row
        return db

    def things(self, campaign, kind):
        db = self.db(campaign)
        try:
            return {r["id"]: json.loads(r["data"]) for r in db.execute("SELECT id, data FROM things WHERE kind=?", (kind,))}
        finally:
            db.close()

    def world_hash(self, campaign):
        os.environ["DNE_CAMPAIGN_ROOT"], os.environ["DNE_RUNTIME_DIR"] = self.env["DNE_CAMPAIGN_ROOT"], self.env["DNE_RUNTIME_DIR"]
        import world_db
        return world_db.state_hash(campaign, ("events", "things"))

    def overdue(self, campaign):
        cal = json.loads((self.root / "campaigns" / campaign / "calendar.json").read_text(encoding="utf-8"))
        import importlib.util
        spec = importlib.util.spec_from_file_location("dne_calendar", SCRIPTS / "calendar.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        import scheduler
        now = scheduler._minutes_of(cal)
        db = self.db(campaign)
        try:
            return db.execute("SELECT COUNT(*) FROM events WHERE status='pending' AND due_minute <= ?", (now,)).fetchone()[0]
        finally:
            db.close()

    def test_from_new_to_a_month_later_read_back_by_a_new_agent(self):
        self.new(FORGE_TOWN)
        self.turn("forge", "[Mira]: we pay the Tollmen to keep the road open",
                  [{"action": "route", "between": ["Millbridge", "The Ford"], "access": "toll", "owner": "Tollmen", "toll": "1 sp"}])
        month = self.turn("forge", "a month passes", [{"action": "wait", "days": 30}])
        self.assertEqual(month["elapsed_minutes"], 30 * 1440)
        self.assertEqual(self.overdue("forge"), 0)                        # nothing due was left behind
        forge = self.things("forge", "store")["forge"]["items"]
        hauls = [t for t in self.things("forge", "task").values() if t["rule"] == "haul-coal" and t["status"] == "done"]
        self.assertEqual(forge["iron"], 5)                                # ten ore, two a time
        self.assertEqual(forge["ore"] + 2 * forge["iron"], 10)          # nothing used twice
        self.assertEqual(forge["coal"], 2 * len(hauls) - forge["iron"])
        self.assertEqual(self.things("forge", "caravan")["flour"]["status"], "arrived")
        # A new agent opens the save and can tell the story from it.
        status = self.run_py("turn.py", "-c", "forge", "status")
        self.assertEqual(status["status"], "idle")
        state = (self.root / "campaigns" / "forge" / "state.md").read_text(encoding="utf-8")
        block = state[state.index("<!-- unrolled:world -->"):state.index("<!-- /unrolled:world -->")]
        self.assertIn("In-world time:", block)
        self.assertIn("ford|millbridge toll", block)
        self.assertIn("Last engine turn:", block)
        log = self.run_py("turn.py", "-c", "forge", "log")
        self.assertIn("a month passes", json.dumps(log, ensure_ascii=False))

    def test_two_different_worlds_each_run_a_month_without_a_model(self):
        self.new(FORGE_TOWN)
        self.new(HOLLOW)
        for c in ("forge", "hollow"):
            self.turn(c, "a month passes", [{"action": "wait", "days": 30}])
            self.assertEqual(self.overdue(c), 0)
        self.assertGreater(self.things("forge", "store")["forge"]["items"]["iron"], 0)
        hollow = self.things("hollow", "settlement")["ford"]
        self.assertEqual(hollow["day"], 30)
        self.assertIn("Deepwell", hollow.get("pacts", {}))
        self.assertTrue(self.things("hollow", "chronicle"))

    def test_from_one_save_the_players_stepping_in_changes_what_follows_and_why(self):
        self.new(FORGE_TOWN)
        shutil.copytree(self.root / "campaigns" / "forge", self.root / "campaigns" / "meddled")
        self.turn("forge", "ten days", [{"action": "wait", "days": 10}])
        self.turn("meddled", "[Mira]: we bribe the Tollmen to shut the road", CLOSE)
        self.turn("meddled", "ten days", [{"action": "wait", "days": 10}])
        free_ev = self.db("forge").execute("SELECT status, note FROM events WHERE event_id='fair'").fetchone()
        meddled_ev = self.db("meddled").execute("SELECT status, note FROM events WHERE event_id='fair'").fetchone()
        self.assertEqual(free_ev["status"], "applied")
        self.assertEqual(meddled_ev["status"], "cancelled")                # the world cancels what lost its condition
        self.assertIn("precondition no longer true", meddled_ev["note"])
        cancelled = [t for t in self.things("meddled", "task").values() if t["status"] == "cancelled"]
        self.assertTrue(cancelled and "route/ford|millbridge.access equals closed" in cancelled[0]["why"])
        free_iron = self.things("forge", "store")["forge"]["items"].get("iron", 0)
        meddled_iron = self.things("meddled", "store")["forge"]["items"].get("iron", 0)
        self.assertGreater(free_iron, meddled_iron)                        # no coal over a shut road, no iron

    def test_a_month_stopped_midway_resumes_to_the_same_world(self):
        self.new(FORGE_TOWN)
        shutil.copytree(self.root / "campaigns" / "forge", self.root / "campaigns" / "clean")
        self.turn("clean", "a month", [{"action": "wait", "days": 30}])
        self.turn("forge", "a month", [{"action": "wait", "days": 30}], crash="mid_file_replace")
        self.run_py("turn.py", "-c", "forge", "resume")                   # a new agent picks it up
        self.run_py("turn.py", "-c", "forge", "finish", "--narration", "A month.")
        self.assertEqual(self.world_hash("forge"), self.world_hash("clean"))
        self.assertEqual(self.overdue("forge"), 0)

    def test_undo_takes_the_month_back(self):
        self.new(FORGE_TOWN)
        self.turn("forge", "a day", [{"action": "wait", "days": 1}])
        before = self.world_hash("forge")
        self.turn("forge", "a month", [{"action": "wait", "days": 30}])
        self.assertNotEqual(self.world_hash("forge"), before)
        self.run_py("turn_snapshot.py", "-c", "forge", "undo", "--no-display")
        self.assertEqual(self.world_hash("forge"), before)


if __name__ == "__main__":
    unittest.main()
