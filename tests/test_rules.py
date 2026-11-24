"""Living World plan PR 3: each campaign declares its own kinds of work, and they run on the one scheduler.
Two worlds with different rules: a forge that needs coal hauled in over a road that can close, and a ferry that
cannot finish a crossing while the river is up. Materials are reserved, used once, given back on a cancel;
a change one task makes moves another, with the cause on record; a month at once equals a month of days."""
from __future__ import annotations

import pathlib
import shutil
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _engine_case import EngineCase  # noqa: E402

FORGE = [
    {"action": "store", "id": "forge", "items": {"ore": 4, "coal": 0}},
    {"action": "agent", "name": "Bren", "skills": {"smith": 2}},
    {"action": "agent", "name": "Tam", "skills": {"haul": 1}},
    {"action": "rule", "id": "smelt", "label": "smelt iron", "actor": {"skill": "smith", "min": 1},
     "cost": {"forge": {"ore": 2, "coal": 1}}, "minutes": 480, "gives": {"forge": {"iron": 1}}},
    {"action": "rule", "id": "haul-coal", "label": "haul coal from the pits", "actor": {"skill": "haul"},
     "minutes": 1440, "gives": {"forge": {"coal": 3}},
     "cancel_if": [{"thing": ["route", "ford|millbridge"], "path": "access", "equals": "closed"}]},
]


class RulesTests(EngineCase):
    def task(self, tid):
        return self.thing("task", tid)

    def items(self, sid="forge"):
        return self.thing("store", sid)["items"]

    def setUp(self):
        super().setUp()
        self.do("the forge", *FORGE)
        self.turn.finish("oldworld", "The forge is cold.")

    def test_a_task_waits_for_what_it_lacks_and_starts_when_another_brings_it(self):
        self.do("[GM]: Bren will smelt; Tam goes for coal",
                {"action": "task", "rule": "smelt", "actor": "Bren", "id": "smelt-1"},
                {"action": "task", "rule": "haul-coal", "actor": "Tam", "id": "haul-1"})
        self.assertEqual(self.task("smelt-1")["status"], "blocked")
        self.assertIn("forge has 0 coal free of 1", self.task("smelt-1")["why"])
        self.do("a day and a half", {"action": "wait", "hours": 36})
        haul, smelt = self.task("haul-1"), self.task("smelt-1")
        self.assertEqual(haul["status"], "done")
        self.assertEqual(smelt["status"], "done")
        started = next(l for l in smelt["log"] if l["status"] == "started")
        self.assertEqual(started["cause"], "task:haul-1")          # what moved it is on record
        self.assertEqual(self.items(), {"ore": 2, "coal": 2, "iron": 1})
        self.assertIsNone(self.thing("agent", "Bren")["busy"])

    def test_materials_are_reserved_and_two_tasks_cannot_spend_them_twice(self):
        self.do("coal", {"action": "store", "id": "forge", "items": {"coal": 1}},
                {"action": "agent", "name": "Ash", "skills": {"smith": 1}})
        self.do("[GM]: both smiths start",
                {"action": "task", "rule": "smelt", "actor": "Bren", "id": "a"},
                {"action": "task", "rule": "smelt", "actor": "Ash", "id": "b"})
        self.assertEqual((self.task("a")["status"], self.task("b")["status"]), ("started", "blocked"))
        self.assertIn("coal", self.task("b")["why"])
        out = self.data(self.do("someone takes the coal", {"action": "store", "id": "forge", "items": {"coal": -1}}))
        self.assertIn("reserved", out["error"])
        self.do("a day", {"action": "wait", "days": 1})
        self.assertEqual(self.items()["iron"], 1)
        self.assertEqual(self.items()["coal"], 0)
        self.assertEqual(self.task("b")["status"], "blocked")

    def test_a_cancel_gives_the_materials_back(self):
        self.do("coal", {"action": "store", "id": "forge", "items": {"coal": 2}})
        self.do("[GM]: Bren starts", {"action": "task", "rule": "smelt", "actor": "Bren", "id": "s"})
        self.do("[GM]: called away", {"action": "task", "cancel": "s", "why": "the alarm bell"})
        self.assertEqual(self.task("s")["status"], "cancelled")
        self.assertEqual(self.thing("store", "forge")["reserved"], {})
        self.assertEqual(self.event("task-end-s")["status"], "cancelled")
        self.assertIsNone(self.thing("agent", "Bren")["busy"])

    def test_the_world_cancels_work_whose_condition_is_gone(self):
        self.do("[GM]: Tam sets out", {"action": "task", "rule": "haul-coal", "actor": "Tam", "id": "h"})
        self.do("the Tollmen shut the road", {"action": "route", "between": ["Millbridge", "The Ford"], "access": "closed"})
        h = self.task("h")
        self.assertEqual(h["status"], "cancelled")
        self.assertIn("route/ford|millbridge.access equals closed", h["why"])
        self.do("a day", {"action": "wait", "days": 1})
        self.assertEqual(self.items()["coal"], 0)                    # no coal from a trip that never happened

    def test_a_different_world_with_different_rules_on_the_same_clock(self):
        self.do("a ferry world",
                {"action": "agent", "name": "Old Nok", "skills": {"boat": 3}},
                {"action": "store", "id": "landing", "items": {"fares": 0}},
                {"action": "rule", "id": "cross", "label": "ferry across", "actor": {"skill": "boat", "min": 2},
                 "requires": [{"thing": ["river", "main"], "path": "level", "at_most": 3}], "minutes": 120,
                 "gives": {"landing": {"fares": 5}}, "sets": [{"thing": ["ferry", "nok"], "data": {"side": "east"}}]})
        self.later(0, "river", "main", {"level": 2})
        self.do("the river is low", {"action": "wait", "minutes": 1})
        self.do("[GM]: Nok casts off", {"action": "task", "rule": "cross", "actor": "Old Nok", "id": "x"})
        self.assertEqual(self.task("x")["status"], "started")
        self.later(60, "river", "main", {"level": 5})                  # the river rises an hour in
        self.do("two hours", {"action": "wait", "hours": 2})
        x = self.task("x")
        self.assertEqual(x["status"], "blocked")                       # time is up, but nobody lands in a flood
        self.assertIn("river/main.level at_most 3", x["why"])
        self.later(30, "river", "main", {"level": 1})
        self.do("an hour", {"action": "wait", "hours": 1})
        self.assertEqual(self.task("x")["status"], "done")
        self.assertEqual(self.thing("ferry", "nok"), {"side": "east"})
        self.assertEqual(self.thing("store", "landing")["items"]["fares"], 5)

    def test_a_month_at_once_equals_a_month_of_days(self):
        self.do("work queued",
                {"action": "task", "rule": "smelt", "actor": "Bren", "id": "s1"},
                {"action": "task", "rule": "haul-coal", "actor": "Tam", "id": "h1"},
                {"action": "store", "id": "forge", "items": {"ore": 10}})
        self.turn.finish("oldworld", "Work.")
        shutil.copytree(self.camp, self.root / "campaigns" / "daily")
        self.do("a month", {"action": "wait", "days": 30})
        for _ in range(30):
            self.do("a day", {"action": "wait", "days": 1}, campaign="daily")
        self.assertEqual(self.wdb.state_hash("oldworld", ("events", "things")),
                         self.wdb.state_hash("daily", ("events", "things")))

    def later(self, minutes, kind, id, data):
        """Queue a change to a record, as an engine effect would make it."""
        with self.wdb.writer("oldworld") as db:
            now = self.wdb.now_minute("oldworld")
            n = db.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"]
            self.s.schedule(db, f"set-{n}", now + minutes, {"type": "set", "thing": [kind, id], "data": data})
