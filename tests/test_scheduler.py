"""World plan PR 4: in-world time and the consequence queue. Crossing 70 days at once or a day at a
time gives the same world, a batch limit loses no event, and loading again on the same day moves
no faction."""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
SCRIPTS = ROOT / "skills" / "dne" / "scripts"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(SCRIPTS))
import _old_campaign  # noqa: E402

WORLD = ("events", "things")          # the world itself, without the turns that moved it


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)
        self.rt = self.root / "rt"
        self.rt.mkdir()
        self.camp = _old_campaign.make(self.root)
        state = self.camp / "state.md"
        state.write_text(state.read_text(encoding="utf-8").split("## Session Flags")[0]
                         + "## Session Flags\n- display: none\n- roll_mode: auto\n- world_engine: on\n", encoding="utf-8")
        (self.camp / "tracker.json").write_text(json.dumps({"mira": {
            "name": "Mira", "conditions": [], "concentration": "Bless", "exhaustion": 0,
            "effects": [{"name": "Bless", "duration_type": "minutes", "remaining_minutes": 600.0, "concentration": True},
                        {"name": "Ward", "duration_type": "hours", "remaining_minutes": 30000.0}]}}), encoding="utf-8")
        self._saved = {k: os.environ.get(k) for k in ("DNE_CAMPAIGN_ROOT", "DNE_RUNTIME_DIR", "DNE_OUTBOX_LOG")}
        os.environ.update(DNE_CAMPAIGN_ROOT=str(self.root), DNE_RUNTIME_DIR=str(self.rt), DNE_OUTBOX_LOG=str(self.root / "out.jsonl"))
        import scheduler
        import turn
        import world_db
        self.s, self.turn, self.wdb = scheduler, turn, world_db
        with world_db.writer("oldworld") as db:
            db.execute("UPDATE meta SET value='fixed-seed' WHERE key='seed'")     # the same world on every run

    def tearDown(self):
        for k, v in self._saved.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        self._tmp.cleanup()

    def queue(self):
        """Things set in motion across the next ten weeks, some at the same minute, one waiting on another."""
        with self.wdb.writer("oldworld") as db:
            now = self.s.World("oldworld", db).minute
            for day, name, prio in ((1, "rider-leaves", 0), (3, "bridge-toll-starts", 5), (3, "flour-runs-low", 0),
                                    (20, "caravan-arrives", 0), (45, "festival", 0), (69, "tax-collectors", 0)):
                self.s.schedule(db, name, now + day * 1440, {"type": "note", "text": name}, priority=prio, cause_id="setup")
            self.s.schedule(db, "open-bridge", now + 10 * 1440, {"type": "set", "thing": ["bridge", "millbridge"],
                                                                 "data": {"status": "open"}})
            self.s.schedule(db, "market-reopens", None, {"type": "note", "text": "market reopens"},
                            trigger={"when": {"thing": ["bridge", "millbridge"], "path": "status", "equals": "open"}})
            self.s.schedule(db, "ambush", now + 30 * 1440, {"type": "note", "text": "ambush at the bridge"},
                            preconditions=[{"thing": ["bridge", "millbridge"], "path": "status", "equals": "closed"}])

    def world_hash(self):
        return self.wdb.state_hash("oldworld", WORLD)

    def fork(self):
        """A copy of the campaign as it is now: the same save, played a second way."""
        other = self.root / "campaigns" / "fork"
        shutil.copytree(self.camp, other)
        return other

    def statuses(self, campaign="oldworld"):
        with self.wdb.reader(campaign) as db:
            return {r["event_id"]: r["status"] for r in db.execute("SELECT event_id, status FROM events")}

    def test_seventy_days_at_once_or_a_day_at_a_time_is_the_same_world(self):
        self.queue()
        self.fork()
        self.s.run("oldworld", minutes=70 * 1440)
        for _ in range(70):
            self.s.run("fork", minutes=1440)
        self.assertEqual(self.wdb.state_hash("oldworld", WORLD), self.wdb.state_hash("fork", WORLD))
        factions = json.loads((self.camp / "factions.json").read_text(encoding="utf-8"))
        self.assertEqual(factions["turn"], 10)                           # ten weeks, none capped away
        self.assertEqual(self.statuses()["faction-week-10"], "applied")
        self.assertEqual(self.statuses()["faction-week-11"], "pending")  # the remainder of the week is kept
        tracker = json.loads((self.camp / "tracker.json").read_text(encoding="utf-8"))
        self.assertEqual([e["name"] for e in tracker["mira"]["effects"]], [])    # both timed effects ran out on the way
        self.assertIsNone(tracker["mira"]["concentration"])

    def test_a_small_batch_loses_nothing(self):
        self.queue()
        self.fork()
        self.s.run("oldworld", minutes=70 * 1440)
        calls, out = 0, {"remaining": 1}
        import scheduler
        target = None
        while out["remaining"]:
            with self.wdb.writer("fork") as db:
                world = scheduler.World("fork", db)
                target = target or world.minute + 70 * 1440
                out = scheduler.advance(world, target, batch=3)
                self.wdb.stage_writes(db, f"b{calls}", world.writes())
            self.wdb.apply_staged("fork")
            calls += 1
        self.assertGreater(calls, 3)                                     # it really was cut into batches
        self.assertEqual(self.wdb.state_hash("oldworld", WORLD), self.wdb.state_hash("fork", WORLD))

    def test_order_at_the_same_minute_triggers_and_cancelled_events_are_on_record(self):
        self.queue()
        out = self.s.run("oldworld", minutes=31 * 1440)
        texts = [v.get("text") for v in out["visible_events"]]
        self.assertLess(texts.index("bridge-toll-starts"), texts.index("flour-runs-low"))   # higher priority first
        self.assertLess(texts.index("flour-runs-low"), texts.index("market reopens"))       # fired by the bridge opening
        self.assertNotIn("ambush at the bridge", texts)
        with self.wdb.reader("oldworld") as db:
            ambush = db.execute("SELECT status, note FROM events WHERE event_id='ambush'").fetchone()
        self.assertEqual(ambush["status"], "cancelled")
        self.assertIn("precondition no longer true", ambush["note"])    # why it never happened can be looked up

    def test_loading_again_on_the_same_day_moves_no_faction(self):
        self.s.run("oldworld", minutes=8 * 1440)                         # one faction week has passed
        before = json.loads((self.camp / "factions.json").read_text(encoding="utf-8"))
        for _ in range(3):                                               # /dne load, three times that day
            r = subprocess.run([sys.executable, str(SCRIPTS / "faction.py"), "-c", "oldworld", "turn"],
                               capture_output=True, encoding="utf-8", env=dict(os.environ), timeout=60)
            self.assertIn("World engine is on", r.stdout)
        self.assertEqual(json.loads((self.camp / "factions.json").read_text(encoding="utf-8")), before)
        self.assertEqual(before["turn"], 1)

    def test_correcting_the_date_runs_nothing_and_keeps_every_distance(self):
        self.queue()
        with self.wdb.reader("oldworld") as db:
            due = db.execute("SELECT due_minute FROM events WHERE event_id='rider-leaves'").fetchone()["due_minute"]
        out = self.s.run("oldworld", fix=5 * 1440)                       # the calendar was five days behind
        self.assertEqual(out["corrected_by"], 5 * 1440)
        self.assertEqual(set(self.statuses().values()), {"pending"})    # nothing happened: it was not time passing
        with self.wdb.reader("oldworld") as db:
            self.assertEqual(db.execute("SELECT due_minute FROM events WHERE event_id='rider-leaves'").fetchone()["due_minute"],
                             due + 5 * 1440)

    def test_the_wait_and_schedule_actions_go_through_a_turn(self):
        self.turn.begin("oldworld", "[Mira]: I bribe the clerk and we wait until evening")
        self.turn.resolve("oldworld", [{"action": "schedule", "in_minutes": 120, "text": "The clerk's cousin talks.",
                                        "cause": "bribed the clerk", "event_id": "cousin-talks", "audience": "dm"}])
        before = json.loads((self.camp / "calendar.json").read_text(encoding="utf-8"))["hour"]
        out = self.turn.resolve("oldworld", [{"action": "wait", "hours": 6}])
        self.assertEqual(out["elapsed_minutes"], 360)
        self.assertEqual(json.loads((self.camp / "calendar.json").read_text(encoding="utf-8"))["hour"], before + 6)
        event = [v for v in out["visible_events"] if v.get("event_id") == "cousin-talks"][0]
        self.assertEqual((event["text"], event["cause_id"]), ("The clerk's cousin talks.", "bribed the clerk"))

    def test_an_event_waiting_on_a_place_fires_when_the_party_enters(self):
        with self.wdb.writer("oldworld") as db:
            self.s.schedule(db, "old-friend", None, {"type": "note", "text": "an old friend waves"}, trigger={"enter": "Millbridge"})
            world = self.s.World("oldworld", db)
            self.assertEqual(self.s.fire(world, "enter", "Riverton"), [])
            seen = self.s.fire(world, "enter", "millbridge")
        self.assertEqual(seen[0]["text"], "an old friend waves")
        self.assertEqual(self.statuses()["old-friend"], "applied")


if __name__ == "__main__":
    unittest.main()
