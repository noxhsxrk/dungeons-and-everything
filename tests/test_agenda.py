"""Living World plan PR 4: NPCs and factions work and change plans with no player in the scene. They pick work
from their duties by what they can do and what they know (not what is true), postpone or hand over work when
they learn something or leave, and every choice keeps its reasons."""
from __future__ import annotations

import pathlib
import shutil
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _engine_case import EngineCase  # noqa: E402

WORLD = [
    {"action": "store", "id": "forge", "items": {"ore": 6, "coal": 0}},
    {"action": "store", "id": "yard", "items": {"wood": 0}},
    {"action": "rule", "id": "smelt", "label": "smelt iron", "actor": {"skill": "smith"},
     "cost": {"forge": {"ore": 2, "coal": 1}}, "minutes": 480, "gives": {"forge": {"iron": 1}}, "on_actor_gone": "hand_over"},
    {"action": "rule", "id": "haul-coal", "label": "haul coal from the pits", "actor": {"skill": "haul"},
     "minutes": 1440, "gives": {"forge": {"coal": 2}}, "unless_known": ["road-closed"], "on_learn": "postpone"},
    {"action": "rule", "id": "chop-wood", "label": "chop wood", "actor": {"skill": "haul"}, "minutes": 240,
     "gives": {"yard": {"wood": 1}}},
    {"action": "agent", "name": "Bren", "skills": {"smith": 2}, "duties": [{"rule": "smelt", "priority": 5}]},
    {"action": "agent", "name": "Tam", "skills": {"haul": 1},
     "duties": [{"rule": "haul-coal", "priority": 5}, {"rule": "chop-wood", "priority": 1}]},
]


class AgendaTests(EngineCase):
    def setUp(self):
        super().setUp()
        self.do("the forge and its people", *WORLD)
        self.turn.finish("oldworld", "The forge town wakes.")

    def items(self, sid="forge"):
        return self.thing("store", sid)["items"]

    def tasks(self, who=None):
        with self.wdb.reader("oldworld") as db:
            return {k: v for k, v in self.wdb.all_of(db, "task").items() if who is None or v["actor"] == who}

    def test_with_nobody_watching_the_forge_town_works(self):
        self.do("ten days", {"action": "wait", "days": 10})
        forge = self.items()
        hauls = [t for t in self.tasks("Tam").values() if t["rule"] == "haul-coal" and t["status"] == "done"]
        smelts = [t for t in self.tasks("Bren").values() if t["rule"] == "smelt" and t["status"] == "done"]
        self.assertGreaterEqual(len(hauls), 3)
        self.assertEqual(len(smelts), 3)                                # six ore, two a time: then he stops
        self.assertEqual(forge["iron"], 3)
        self.assertEqual(forge["ore"], 0)
        self.assertEqual(forge["coal"], 2 * len(hauls) - 3)             # nothing used twice, nothing lost
        bren = self.thing("agent", "Bren")
        self.assertIn("short", bren["decisions"][-1]["skipped"][0]["why"])   # out of ore, and he says so
        first = self.thing("agent", "Tam")["decisions"][0]
        self.assertIn("haul-coal", first["because"])

    def test_what_they_believe_not_what_is_true_changes_the_plan(self):
        self.do("Tam sets out", {"action": "wait", "hours": 2})
        haul = next(t for t in self.tasks("Tam").values() if t["rule"] == "haul-coal")
        self.assertEqual(haul["status"], "started")
        # A false rumour reaches Tam: the road is in fact open.
        self.do("a rumour", {"action": "fact", "id": "road-closed", "text": "The pit road is closed.", "place": "Millbridge"},
                {"action": "belief", "holder": "Tam", "fact": "road-closed", "claim": "the pit road is closed",
                 "source": "a drover", "confidence": 0.8})
        haul = self.tasks("Tam")[haul["id"]]
        self.assertEqual(haul["status"], "blocked")
        self.assertIn("postponed: Tam learned road-closed", [l["why"] for l in haul["log"]])
        self.do("a few hours", {"action": "wait", "hours": 5})
        tam = self.thing("agent", "Tam")
        chose_wood = next(d for d in tam["decisions"] if d["task"] and "chop-wood" in d["task"])
        self.assertIn("Tam learned road-closed", chose_wood["skipped"][0]["why"])
        self.assertGreaterEqual(self.items("yard")["wood"], 1)
        self.assertEqual(self.items()["coal"], 0)
        # Word that the road is open: the postponed haul goes again by itself.
        self.do("the truth", {"action": "belief", "holder": "Tam", "fact": "road-closed",
                              "claim": "the pit road was never closed", "source": "the miller", "confidence": 0})
        self.do("two days", {"action": "wait", "days": 2})
        self.assertEqual(self.tasks("Tam")[haul["id"]]["status"], "done")
        self.assertGreaterEqual(self.items()["coal"] + self.items()["iron"], 2)

    def test_work_is_handed_over_when_its_smith_is_called_away(self):
        self.do("coal and a second smith", {"action": "store", "id": "forge", "items": {"coal": 1}},
                {"action": "agent", "name": "Ash", "skills": {"smith": 1}})
        self.do("Bren starts", {"action": "wait", "minutes": 10})
        smelt = next(t for t in self.tasks("Bren").values() if t["rule"] == "smelt")
        self.assertEqual(smelt["status"], "started")
        self.do("Bren is called to the council", {"action": "agent", "name": "Bren", "away": "at the council"})
        smelt = self.tasks()[smelt["id"]]
        self.assertEqual((smelt["status"], smelt["actor"]), ("started", "Ash"))
        self.assertEqual(smelt["handed"][0]["from"], "Bren")
        self.assertIn("Bren is away", smelt["handed"][0]["why"])
        self.do("the day", {"action": "wait", "hours": 9})
        self.assertEqual(self.tasks()[smelt["id"]]["status"], "done")
        self.assertIsNone(self.thing("agent", "Ash")["busy"])

    def test_a_faction_plans_from_what_it_has_heard(self):
        self.do("the Tollmen",
                {"action": "store", "id": "tollhouse", "items": {"walls": 0}},
                {"action": "rule", "id": "raise-toll", "actor": {"right": "toll"}, "minutes": 60,
                 "unless_known": ["guild-arms"],
                 "sets": [{"thing": ["route", "ford|millbridge"], "data": {"access": "toll", "toll": "5 sp"}}]},
                {"action": "rule", "id": "fortify", "actor": {"right": "toll"}, "minutes": 1440,
                 "gives": {"tollhouse": {"walls": 1}}},
                {"action": "belief", "holder": "faction:Tollmen", "fact": "guild-arms",
                 "claim": "the Millers' Guild has hired forty swords", "source": "a spy"},
                {"action": "agent", "name": "Tollmen", "holder": "faction:Tollmen", "rights": ["toll"],
                 "duties": [{"rule": "raise-toll", "priority": 5, "repeat": False}, {"rule": "fortify", "priority": 1, "repeat": False}]})
        self.do("two days", {"action": "wait", "days": 2})
        self.assertEqual(self.items("tollhouse")["walls"], 1)
        self.assertIsNone(self.thing("route", "ford|millbridge"))       # they did not dare raise the toll
        why = self.thing("agent", "Tollmen")["decisions"][0]["skipped"][0]["why"]
        self.assertIn("Tollmen knows guild-arms", why)

    def test_ten_days_at_once_equals_ten_single_days(self):
        shutil.copytree(self.camp, self.root / "campaigns" / "daily")
        self.do("ten days", {"action": "wait", "days": 10})
        for _ in range(10):
            self.do("a day", {"action": "wait", "days": 1}, campaign="daily")
        self.assertEqual(self.wdb.state_hash("oldworld", ("events", "things")),
                         self.wdb.state_hash("daily", ("events", "things")))
