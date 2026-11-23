"""World plan PR 5: rests and journeys the world can interrupt. Woken in the night, nobody has the
rest's benefit yet; carrying on follows the same ruleset; a journey stopped half-way has not reached,
revealed or paid for the rest of the road."""
from __future__ import annotations

import json
import os
import pathlib
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
SCRIPTS = ROOT / "skills" / "dne" / "scripts"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(SCRIPTS))
import _old_campaign  # noqa: E402

SHEET = ("# Mira\n- **Class:** Medic | **Level:** 3\n- **XP:** 1150 / 2700\n- **HP:** 7 / 20 | **Temp HP:** 0\n"
         "- **Hit Dice:** 3d8 (remaining: 1)\n")


class JourneyTests(unittest.TestCase):
    RULESET = "2014"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)
        self.rt = self.root / "rt"
        self.rt.mkdir()
        self.camp = _old_campaign.make(self.root)
        state = self.camp / "state.md"
        head = state.read_text(encoding="utf-8").split("## Session Flags")[0].replace(
            "**Session count:** 3", f"**Session count:** 3  **Ruleset:** {self.RULESET}")
        state.write_text(head + "## Session Flags\n- display: none\n- roll_mode: auto\n- world_engine: on\n", encoding="utf-8")
        (self.camp / "characters" / "mira.md").write_text(SHEET, encoding="utf-8")
        (self.camp / "calendar.json").write_text(json.dumps(
            {"gregorian": True, "day": 15, "month": 5, "year": 2026, "hour": 22, "minute": 0,
             "months": ["January", "February", "March", "April", "May", "June", "July", "August", "September",
                        "October", "November", "December"]}), encoding="utf-8")
        (self.camp / "world-map.json").write_text(json.dumps({
            "party_location": "millbridge",
            "places": {k: {"name": n, "x": x, "y": 0, "biome": "plains", "kind": "town", "desc": d, "secret": "",
                           "hidden": k != "millbridge", "visited": k == "millbridge", "danger": 1}
                       for k, n, x, d in (("millbridge", "Millbridge", 0, "a mill town"),
                                          ("ford", "The Ford", 12, "a river crossing"),
                                          ("market", "Market", 24, "the grain market with the red awnings"))},
            "edges": [{"a": "millbridge", "b": "ford", "road": True, "miles": 12.0},
                      {"a": "ford", "b": "market", "road": True, "miles": 12.0}]}), encoding="utf-8")
        self._saved = {k: os.environ.get(k) for k in ("DNE_CAMPAIGN_ROOT", "DNE_RUNTIME_DIR", "DNE_OUTBOX_LOG")}
        os.environ.update(DNE_CAMPAIGN_ROOT=str(self.root), DNE_RUNTIME_DIR=str(self.rt), DNE_OUTBOX_LOG=str(self.root / "out.jsonl"))
        import paths
        import scheduler
        import turn
        import world_db
        self.s, self.turn, self.wdb, self.paths = scheduler, turn, world_db, paths
        self.assertEqual(paths.campaign_ruleset("oldworld"), self.RULESET)

    def tearDown(self):
        for k, v in self._saved.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        self._tmp.cleanup()

    def later(self, minutes, text, event_id, interrupt=True):
        with self.wdb.writer("oldworld") as db:
            now = self.s.World("oldworld", db).minute
            self.s.schedule(db, event_id, now + minutes, {"type": "note", "text": text, "interrupt": interrupt})

    def sheet(self):
        return (self.camp / "characters" / "mira.md").read_text(encoding="utf-8")

    def clock(self):
        cal = json.loads((self.camp / "calendar.json").read_text(encoding="utf-8"))
        return cal["day"], cal["hour"], cal.get("minute", 0)

    def map(self):
        return json.loads((self.camp / "world-map.json").read_text(encoding="utf-8"))

    def act(self, text, intent):
        self.turn.begin("oldworld", text)
        return self.turn.resolve("oldworld", [intent])

    def answer(self, view, value):
        return self.turn.answer("oldworld", view["next_input"]["request_id"], value)

    # ── rest ──────────────────────────────────────────────────────────────

    def test_woken_at_two_the_party_has_not_rested_yet(self):
        self.later(240, "someone knocks at the door", "knock")
        out = self.act("[Mira]: we sleep at the inn", {"action": "rest", "type": "long", "resting": ["Mira"]})
        self.assertEqual(out["status"], "waiting_for_player")
        self.assertEqual(out["elapsed_minutes"], 240)
        self.assertEqual(self.clock(), (16, 2, 0))                      # it is two in the morning, not six
        self.assertEqual(out["next_input"]["kind"], "decision")
        self.assertIn("someone knocks at the door", out["next_input"]["question"])
        self.assertIn("**HP:** 7 / 20", self.sheet())                   # no benefit yet
        self.assertEqual(out["results"][0]["pending"], ["adjudicate_interruption", "resolve_remaining_rest"])

    def test_carrying_on_finishes_the_same_rest_by_the_same_rules(self):
        self.later(240, "someone knocks at the door", "knock")
        waiting = self.act("[Mira]: we sleep", {"action": "rest", "type": "long", "resting": ["Mira"]})
        done = self.answer(waiting, "continue")
        self.assertEqual(done["status"], "open")
        self.assertEqual(done["elapsed_minutes"], 240)                  # only the four hours that were left
        self.assertEqual(self.clock(), (16, 6, 0))
        self.assertIn("**HP:** 20 / 20", self.sheet())
        result = done["results"][0]["data"]
        self.assertEqual((result["rest"], result["ruleset"]), ("complete", self.RULESET))
        self.assertEqual(len(result["interruptions"]), 1)               # what happened on the way is on record

    def test_a_strenuous_interruption_starts_the_rest_again(self):
        self.later(240, "raiders at the gate", "raid")
        waiting = self.act("[Mira]: we sleep", {"action": "rest", "type": "long", "resting": ["Mira"]})
        done = self.answer(waiting, "restart")
        self.assertEqual(done["elapsed_minutes"], 480)                  # the full eight hours, from now
        self.assertEqual(self.clock(), (16, 10, 0))
        self.assertIn("**HP:** 20 / 20", self.sheet())

    def test_getting_up_gives_what_the_ruleset_gives(self):
        self.later(240, "raiders at the gate", "raid")
        waiting = self.act("[Mira]: we sleep", {"action": "rest", "type": "long", "resting": ["Mira"]})
        done = self.answer(waiting, "stop")
        self.assertEqual(done["results"][0]["data"]["rest"], "abandoned")
        self.assertIn("**HP:** 7 / 20", self.sheet())                   # 2014: an unfinished long rest is nothing
        self.assertEqual(self.clock(), (16, 2, 0))

    def test_an_undisturbed_rest_takes_its_time_once(self):
        (self.camp / "tracker.json").write_text(json.dumps({"mira": {
            "name": "Mira", "conditions": [], "concentration": "Bless", "exhaustion": 2,
            "effects": [{"name": "Bless", "duration_type": "hours", "remaining_minutes": 600.0, "concentration": True}]}}),
            encoding="utf-8")
        out = self.act("[Mira]: we sleep", {"action": "rest", "type": "long"})
        self.assertEqual((out["status"], out["elapsed_minutes"]), ("open", 480))
        self.assertEqual(self.clock(), (16, 6, 0))                      # eight hours, not sixteen
        mira = json.loads((self.camp / "tracker.json").read_text(encoding="utf-8"))["mira"]
        self.assertEqual(mira["exhaustion"], 1)                         # one level, once
        self.assertIsNone(mira["concentration"])
        self.assertEqual(mira["effects"], [])

    def test_someone_on_watch_stays_awake(self):
        (self.camp / "tracker.json").write_text(json.dumps({"bren": {
            "name": "Bren", "conditions": [], "concentration": "Alarm", "exhaustion": 0,
            "effects": [{"name": "Alarm", "duration_type": "hours", "remaining_minutes": 6000.0, "concentration": True}]}}),
            encoding="utf-8")
        self.act("[Mira]: I sleep, Bren keeps watch", {"action": "rest", "type": "long", "resting": ["Mira"], "watch": ["Bren"]})
        bren = json.loads((self.camp / "tracker.json").read_text(encoding="utf-8"))["bren"]
        self.assertEqual(bren["concentration"], "Alarm")

    # ── travel ────────────────────────────────────────────────────────────

    def test_a_clear_road_is_walked_leg_by_leg(self):
        out = self.act("[Mira]: we go to the market", {"action": "travel", "to": "Market"})
        self.assertEqual(out["status"], "open")
        self.assertEqual(out["elapsed_minutes"], 1440)                  # 24 miles on foot
        m = self.map()
        self.assertEqual(m["party_location"], "market")
        self.assertTrue(m["places"]["ford"]["visited"] and m["places"]["market"]["visited"])
        self.assertNotIn("party_en_route", m)

    def test_stopped_on_the_road_the_destination_is_neither_reached_nor_revealed(self):
        self.later(300, "a rider waves you down", "rider")
        out = self.act("[Mira]: we go to the market", {"action": "travel", "to": "Market"})
        self.assertEqual(out["status"], "waiting_for_player")
        self.assertEqual(out["elapsed_minutes"], 300)                   # five hours of road, not the whole day
        m = self.map()
        self.assertEqual(m["party_location"], "millbridge")             # not standing anywhere new yet
        self.assertEqual(m["party_en_route"]["to"], "ford")
        self.assertFalse(m["places"]["market"]["visited"])
        self.assertTrue(m["places"]["market"]["hidden"])
        shown = json.dumps([out["next_input"], out["visible_events"]], ensure_ascii=False)
        self.assertNotIn("Market", shown)                               # the players are told about this stretch only
        self.assertNotIn("red awnings", shown)

    def test_going_on_reaches_it_and_turning_back_costs_the_way_back(self):
        self.later(300, "a rider waves you down", "rider")
        waiting = self.act("[Mira]: we go to the market", {"action": "travel", "to": "Market"})
        done = self.answer(waiting, "continue")
        self.assertEqual(done["elapsed_minutes"], 1440 - 300)
        self.assertEqual(self.map()["party_location"], "market")

    def test_turning_back_returns_to_the_last_place(self):
        self.later(300, "a rider waves you down", "rider")
        waiting = self.act("[Mira]: we go to the market", {"action": "travel", "to": "Market"})
        done = self.answer(waiting, "back")
        self.assertEqual(done["elapsed_minutes"], 300)                  # as long back as it took to get here
        m = self.map()
        self.assertEqual(m["party_location"], "millbridge")
        self.assertFalse(m["places"]["ford"]["visited"])

    def test_a_closed_road_stops_the_party_before_it(self):
        m = self.map()
        m["edges"][1].update(closed=True, closed_reason="the Tollmen hold the ford")
        (self.camp / "world-map.json").write_text(json.dumps(m), encoding="utf-8")
        out = self.act("[Mira]: we go to the market", {"action": "travel", "to": "Market"})
        self.assertEqual(out["status"], "waiting_for_player")
        self.assertEqual(out["elapsed_minutes"], 720)                   # they walked to the ford and no further
        self.assertEqual(self.map()["party_location"], "ford")
        self.assertIn("the Tollmen hold the ford", out["next_input"]["question"])
        stayed = self.answer(out, "stop")
        self.assertEqual(stayed["results"][0]["data"]["journey"], "stopped")
        self.assertFalse(self.map()["places"]["market"]["visited"])

    def test_an_event_waiting_at_a_place_meets_the_party_there(self):
        with self.wdb.writer("oldworld") as db:
            self.s.schedule(db, "ferryman", None, {"type": "note", "text": "the ferryman names his price"},
                            trigger={"enter": "The Ford"})
        out = self.act("[Mira]: we go to the market", {"action": "travel", "to": "Market"})
        texts = [v.get("text") for v in out["visible_events"]]
        self.assertLess(texts.index("the ferryman names his price"), texts.index("You reach Market."))


class JourneyTests2024(JourneyTests):
    RULESET = "2024"

    def test_getting_up_gives_what_the_ruleset_gives(self):
        self.later(240, "raiders at the gate", "raid")
        waiting = self.act("[Mira]: we sleep", {"action": "rest", "type": "long", "resting": ["Mira"]})
        done = self.answer(waiting, "stop")
        benefit = done["results"][0]["data"]["benefit"]
        self.assertEqual(benefit[0]["character"], "Mira")               # 2024: an hour or more counts as a short rest
        self.assertNotIn("**HP:** 20 / 20", self.sheet())               # ...which is not a long rest's full heal


if __name__ == "__main__":
    unittest.main()
