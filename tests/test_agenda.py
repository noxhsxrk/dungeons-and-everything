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
        hauls = self.thing("agent", "Tam")["done_count"]["haul-coal"]
        smelts = self.thing("agent", "Bren")["done_count"]["smelt"]
        self.assertGreaterEqual(hauls, 3)
        self.assertEqual(smelts, 3)                                     # six ore, two a time: then he stops
        self.assertEqual(forge["iron"], 3)
        self.assertEqual(forge["ore"], 0)
        self.assertEqual(forge["coal"], 2 * hauls - 3)                  # nothing used twice, nothing lost
        self.assertEqual([t for t in self.tasks().values() if t["status"] == "done"], [])   # routine work is not kept
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
        self.assertNotIn(haul["id"], self.tasks("Tam"))                  # done, and routine work is not kept
        self.assertGreaterEqual(self.thing("agent", "Tam")["done_count"]["haul-coal"], 1)
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

    def test_a_shut_road_is_not_tried_again_and_again(self):
        self.do("the road is shut", {"action": "route", "between": ["Millbridge", "The Ford"], "access": "closed"},
                {"action": "rule", "id": "haul-coal", "label": "haul coal", "actor": {"skill": "haul"}, "minutes": 1440,
                 "gives": {"forge": {"coal": 2}}, "cancel_if": [{"thing": ["route", "ford|millbridge"], "path": "access", "equals": "closed"}]})
        self.do("five days", {"action": "wait", "days": 5})
        self.assertEqual([t for t in self.tasks("Tam").values() if t["rule"] == "haul-coal"], [])
        skipped = [s for d in self.thing("agent", "Tam")["decisions"] for s in d["skipped"] if s["rule"] == "haul-coal"]
        self.assertIn("cannot be done while route/ford|millbridge.access equals closed", skipped[0]["why"])

    def test_routine_work_is_quiet_and_a_long_run_stays_small(self):
        import time
        start = time.monotonic()
        out = self.do("a month", {"action": "wait", "days": 30})
        tasks = [v for v in out["visible_events"] if v["type"] in ("task", "decision")]
        self.assertLessEqual(len(tasks), 2, [v["text"] for v in tasks])
        out = self.do("a season", {"action": "wait", "days": 90, "batch": 2000})
        self.assertEqual(out["elapsed_minutes"], 90 * 1440)
        self.assertLess(len(self.tasks()), 5)                           # finished routine work is a counter, not records
        self.assertLess(time.monotonic() - start, 30)

    def test_a_busy_world_says_plainly_when_one_wait_is_not_enough(self):
        self.do("Tam chops all day", {"action": "agent", "name": "Tam", "duties": [{"rule": "chop-wood", "priority": 1}]})
        out = self.data(self.do("sixty days", {"action": "wait", "days": 60}))
        self.assertTrue(out["remaining"])
        self.assertIn("Run wait again", out["note"])
        passed, left = 0, out["left_minutes"]
        passed = 60 * 1440 - left
        while left:
            more = self.data(self.do("and more", {"action": "wait", "minutes": left}))
            passed += more["to"] - more["from"]
            left = more.get("left_minutes", 0)
        self.assertEqual(passed, 60 * 1440)

    def test_an_appointment_elsewhere_takes_a_worker_off_their_work(self):
        self.do("Bren works at Millbridge, and has business at the market",
                {"action": "agent", "name": "Bren", "at": "Millbridge"},
                {"action": "store", "id": "forge", "items": {"coal": 1}},
                {"action": "appointment", "id": "bren-market", "npc": "Bren", "from": "Millbridge", "place": "Market",
                 "in_minutes": 1500, "stays_minutes": 600})
        self.do("he sets out", {"action": "wait", "minutes": 100})
        smelt = next(t for t in self.tasks("Bren").values() if t["rule"] == "smelt")
        self.assertEqual(smelt["status"], "blocked")
        self.assertIn("appointment bren-market", smelt["why"])

    def test_a_call_for_help_is_answered_by_someone_free(self):
        self.do("a smith who asks for help when called away",
                {"action": "rule", "id": "smelt", "label": "smelt iron", "actor": {"skill": "smith"},
                 "cost": {"forge": {"ore": 2, "coal": 1}}, "minutes": 480, "gives": {"forge": {"iron": 1}},
                 "on_actor_gone": "ask_help"},
                {"action": "store", "id": "forge", "items": {"coal": 1}})
        self.do("Bren starts", {"action": "wait", "minutes": 10})
        smelt = next(t for t in self.tasks("Bren").values() if t["rule"] == "smelt")
        out = self.do("Bren is called away", {"action": "agent", "name": "Bren", "away": "a fire at home"})
        held = self.tasks()[smelt["id"]]
        self.assertEqual(held["help_wanted"], "Bren")
        self.assertTrue(any("asking for help" in l["why"] for l in held["log"]))
        self.do("Ash arrives", {"action": "agent", "name": "Ash", "skills": {"smith": 1}, "duties": []})
        self.do("Ash looks for work", {"action": "agent", "name": "Ash", "duties": [{"rule": "smelt", "priority": 1}]})
        got = self.tasks()[smelt["id"]]
        self.assertEqual(got["actor"], "Ash")
        self.assertEqual(got["handed"][-1]["why"], "came to help")

