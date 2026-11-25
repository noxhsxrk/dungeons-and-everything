"""World plan PR 9: preparation and prevention change the story. The traitor caught early, the betrayal
scene is over; a plan that leaves no risk needs no roll and still earns its reward; a price is the
player's to accept."""
from __future__ import annotations

import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _engine_case import EngineCase  # noqa: E402

BETRAYAL = {"action": "beat", "id": "betrayal-at-the-gate", "text": "Velkyn opens the gate to the Pale Court.",
            "requires": [{"thing": ["state", "Velkyn"], "path": "status", "not": "captured"}]}
CAUGHT = {"action": "set", "thing": ["state", "Velkyn"], "data": {"status": "captured"},
          "cause": "the party caught him at the mill"}
GATE = {"action": "situation", "id": "gate-before-the-storm", "difficulty": "hard",
        "sides": [{"who": "the medicine carrier", "wants": "ten more minutes", "limit": "the cart cannot be left",
                   "will_trade": "the medicine can come in without the cart"},
                  {"who": "the engineer", "wants": "the gate shut now", "limit": "the mechanism fails if it waits",
                   "will_trade": "the mail hatch stays open"}],
        "if_left_alone": "the gate closes on schedule and the medicine stays outside",
        "facts": ["the mail hatch is big enough for a crate"]}
RISKY = {"action": "judge", "situation": "gate-before-the-storm", "actor": "Mira", "plan": "hold the gate with a crowbar",
         "risk": "the crowbar may slip", "if_fails": "the gate drops on the cart", "opens": "the party is locked in with the engineer",
         "cost": "the crowbar is bent for good", "roll": {"spec": "1d20+5", "dc": 13, "label": "Athletics"}}


class StakesTests(EngineCase):
    SHEET = "# Mira\n- **Class:** Medic | **Level:** 3\n- **XP:** 1150 / 2700\n- **HP:** 20 / 20\n"

    def setUp(self):
        super().setUp()
        (self.camp / "characters" / "mira.md").write_text(self.SHEET, encoding="utf-8")

    def players_roll(self):
        self.flags(self.FLAGS.replace("roll_mode: auto", "roll_mode: players"))

    def test_catching_the_traitor_early_ends_the_betrayal_scene(self):
        self.do("the GM plans a betrayal", BETRAYAL)
        out = self.do("[Mira]: we grab Velkyn before he reaches the gate", CAUGHT)
        beat = self.thing("beat", "betrayal-at-the-gate")
        self.assertEqual(beat["status"], "prevented")
        self.assertEqual(beat["prevented_by"]["cause"], "the party caught him at the mill")   # what made it impossible
        notice = [v for v in out["visible_events"] if v["type"] == "beat_prevented"][0]
        self.assertEqual(notice["recipient"], "dm")
        self.assertIn("Build the next scene from what actually happened", notice["text"])
        self.assertIn("Do not bring it back in another form", notice["text"])

    def test_an_imported_story_reshapes_the_beat_instead(self):
        (self.camp / "arc.md").write_text("# Arc\n", encoding="utf-8")       # a campaign with a written arc
        self.do("the GM plans a betrayal", BETRAYAL)
        out = self.do("[Mira]: we grab Velkyn", CAUGHT)
        self.assertEqual(self.thing("beat", "betrayal-at-the-gate")["status"], "needs_revision")
        self.assertTrue(any("Its consequence still has to land" in v["text"] for v in out["visible_events"]))
        self.flags(self.FLAGS + "- beat_policy: players_can_prevent\n")       # ...unless the table says otherwise
        self.do("another one", {**BETRAYAL, "id": "second", "requires": [{"thing": ["state", "Velkyn"], "path": "status", "not": "captured"}]})
        self.assertEqual(self.thing("beat", "second")["status"], "prevented")

    def test_time_passing_can_close_a_beat_too(self):
        self.do("a beat that needs the bridge shut", {"action": "beat", "id": "ambush", "text": "Ambush at the shut bridge.",
                                                      "requires": [{"thing": ["bridge", "b"], "path": "status", "equals": "closed"}]})
        self.assertEqual(self.thing("beat", "ambush")["status"], "prevented")   # it was never shut: said at once
        self.do("set it up", {"action": "set", "thing": ["bridge", "b"], "data": {"status": "closed"}},
                {"action": "beat", "id": "ambush2", "text": "Ambush at the shut bridge.",
                 "requires": [{"thing": ["bridge", "b"], "path": "status", "equals": "closed"}]})
        with self.wdb.writer("oldworld") as db:
            world = self.s.World("oldworld", db)
            self.s.schedule(db, "opens", world.minute + 60, {"type": "set", "thing": ["bridge", "b"], "data": {"status": "open"}})
        out = self.do("an hour later the Guild opens it", {"action": "wait", "hours": 2})
        self.assertEqual(self.thing("beat", "ambush2")["status"], "prevented")
        self.assertTrue(any(v["type"] == "beat_prevented" for v in out["visible_events"]))

    def test_a_plan_that_leaves_no_risk_needs_no_roll_and_still_earns_its_reward(self):
        self.do("the storm gate", GATE)
        out = self.do("[Mira]: only the medicine comes in, through the mail hatch",
                      {"action": "judge", "situation": "gate-before-the-storm", "actor": "Mira",
                       "plan": "only the medicine comes in, through the mail hatch"})
        self.assertEqual(out["status"], "open")                              # no roll was asked for
        self.assertEqual(self.data(out)["outcome"], "success_no_roll")
        self.assertEqual(self.thing("situation", "gate-before-the-storm")["plans"][0]["by"], "Mira")
        paid = self.data(self.do("reward", {"action": "reward", "encounter": "gate-before-the-storm", "characters": ["Mira"],
                                            "note": "listened to both sides"}))
        self.assertTrue(paid["awarded"])
        self.assertEqual(paid["difficulty"], "hard")                         # the difficulty of the whole problem
        self.assertEqual(paid["outcome"], "success_no_roll")
        gain = paid["characters"][0]["awarded"]
        self.assertGreater(gain, 0)
        self.assertIn(f"**XP:** {1150 + gain} / 2700", (self.camp / "characters" / "mira.md").read_text(encoding="utf-8"))
        self.assertIn("gate-before-the-storm", (self.camp / "xp-ledger.jsonl").read_text(encoding="utf-8"))
        again = self.data(self.do("reward again", {"action": "reward", "encounter": "gate-before-the-storm", "characters": ["Mira"]}))
        self.assertFalse(again["awarded"])
        self.assertIn("already rewarded", again["error"])
        self.assertIn(f"**XP:** {1150 + gain} / 2700", (self.camp / "characters" / "mira.md").read_text(encoding="utf-8"))

    def test_an_encounter_already_paid_by_xp_py_is_not_paid_again(self):
        self.do("the storm gate", GATE)
        (self.camp / "xp-ledger.jsonl").write_text(json.dumps({"character": "Mira", "awarded": 450, "total_after": 1150,
                                                                "event": "Gate-Before-The-Storm"}) + "\n", encoding="utf-8")
        again = self.data(self.do("reward", {"action": "reward", "encounter": "gate-before-the-storm", "characters": ["Mira"]}))
        self.assertFalse(again["awarded"])
        self.assertIn("xp.py award", again["error"])
        self.assertIn("**XP:** 1150 / 2700", (self.camp / "characters" / "mira.md").read_text(encoding="utf-8"))

    def test_a_risky_plan_must_say_what_is_at_stake(self):
        self.do("the storm gate", GATE)
        vague = self.data(self.do("a risk with nothing behind it",
                                  {"action": "judge", "situation": "gate-before-the-storm", "plan": "hold the gate",
                                   "risk": "it may slip", "roll": {"spec": "1d20+5", "dc": 13}}))
        self.assertIn("say what could go wrong and what changes if it does", vague["error"])

    def test_success_at_a_cost_waits_for_the_player_to_take_the_price(self):
        self.players_roll()
        self.do("the storm gate", GATE)
        asked = self.do("[Mira]: I jam the gate with a crowbar", RISKY)
        self.assertEqual(asked["next_input"]["kind"], "roll")
        self.assertIn("At stake: the crowbar may slip", asked["next_input"]["question"])    # the risk is known before the roll
        priced = self.turn.answer("oldworld", asked["next_input"]["request_id"], 7)          # 7 + 5 = 12 against 13
        self.assertEqual(priced["status"], "waiting_for_player")
        self.assertEqual(priced["next_input"]["kind"], "decision")
        self.assertIn("the crowbar is bent for good", priced["next_input"]["question"])
        self.assertIsNone(self.thing("encounter", "gate-before-the-storm"))                  # nothing decided for them yet
        done = self.turn.answer("oldworld", priced["next_input"]["request_id"], "accept")
        self.assertEqual(self.data(done)["outcome"], "success_at_a_cost")
        self.assertEqual(self.data(done)["cost"], "the crowbar is bent for good")

    def test_refusing_the_price_is_a_failure_that_opens_something(self):
        self.players_roll()
        self.do("the storm gate", GATE)
        asked = self.do("[Mira]: I jam the gate with a crowbar", RISKY)
        priced = self.turn.answer("oldworld", asked["next_input"]["request_id"], 7)
        done = self.turn.answer("oldworld", priced["next_input"]["request_id"], "refuse")
        result = self.data(done)
        self.assertEqual(result["outcome"], "failure")
        self.assertEqual(result["if_fails"], "the gate drops on the cart")
        self.assertEqual(result["opens"], "the party is locked in with the engineer")       # what they can do now

    def test_a_clean_success_and_a_clean_failure(self):
        self.players_roll()
        self.do("the storm gate", GATE)
        asked = self.do("[Mira]: I jam the gate", RISKY)
        self.assertEqual(self.data(self.turn.answer("oldworld", asked["next_input"]["request_id"], 15))["outcome"], "success")
        self.turn.finish("oldworld", "It holds.")
        asked = self.do("[Mira]: again, another gate", {**RISKY, "plan": "the second gate"})
        self.assertEqual(self.data(self.turn.answer("oldworld", asked["next_input"]["request_id"], 2))["outcome"], "failure")


if __name__ == "__main__":
    unittest.main()
