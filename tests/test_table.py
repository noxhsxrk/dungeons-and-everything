"""World plan PR 10: the people at the table. A quiet character learns something alone and decides who
hears it; a wrong accusation changes no fact; an old thread returns after a reload as an opening, not
an order."""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _engine_case import SCRIPTS, EngineCase  # noqa: E402

CASE = {"action": "case", "id": "missing-ledger", "truth": "The clerk hid the ledger to protect his daughter.",
        "clues": [{"id": "ash", "text": "Fresh ash in a cold grate.", "where": "clerk's office", "obvious": True,
                   "detail": "A corner of ledger paper survives."},
                  {"id": "key", "text": "The strongbox key is worn on one side.", "where": "clerk's office", "obvious": False}]}
TAPS = {"action": "remember", "id": "two-taps", "owner": "Mira", "kind": "habit", "tone": "warm",
        "text": "Her father taps the relay cover twice before he switches it on.",
        "about": ["father", "relay"], "knows": ["Mira", "Theo"], "payoff": {"place": "Market"}}


class TableTests(EngineCase):
    def setUp(self):
        super().setUp()
        (self.camp / "characters" / "theo.md").write_text(
            "# Theo\n- **Class:** Tinker | **Background:** Hotel porter | **Level:** 3\n- **XP:** 900 / 2700\n", encoding="utf-8")

    def sent(self):
        path = self.root / "out.jsonl"
        return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []

    def knows(self, who, fact):
        return self.thing("belief", f"pc:{who}|{fact}")

    def note(self, text="[Mira]: we look around"):
        import gm_guide
        return "\n".join(gm_guide.turn_notes("oldworld", count=False, text=text))

    def test_what_the_quiet_one_finds_is_theirs_to_share(self):
        self.do("a mystery", CASE)
        out = self.do("[Theo]: I look around the clerk's office",
                      {"actor": "Theo", "action": "search", "case": "missing-ledger", "where": "clerk's office"})
        self.assertEqual([f["id"] for f in self.data(out)["found"]], ["ash"])          # plainly there: no roll needed
        private = [m for m in self.sent() if "Fresh ash" in m["body"]]
        self.assertEqual([m["audience"] for m in private], ["Theo"])                    # his phone only
        self.assertIsNotNone(self.knows("Theo", "clue:ash"))
        self.assertIsNone(self.knows("Mira", "clue:ash"))                               # nobody told her
        self.do("[Theo]: I show Mira the ash", {"actor": "Theo", "action": "tell", "to": ["Mira"], "clue": "ash"})
        self.assertEqual(self.knows("Mira", "clue:ash")["source"], "told by Theo")
        nothing = self.data(self.do("[Mira]: I tell them about the key", {"actor": "Mira", "action": "tell", "to": ["Theo"], "clue": "key"}))
        self.assertIn("does not know that", nothing["error"])                           # she cannot pass on what she never learned

    def test_a_roll_changes_how_much_and_how_long_not_whether(self):
        self.flags(self.FLAGS.replace("roll_mode: auto", "roll_mode: players"))
        self.do("a mystery", CASE)
        roll = {"spec": "1d20+3", "dc": 13, "label": "Investigation"}
        asked = self.do("[Theo]: I search", {"actor": "Theo", "action": "search", "case": "missing-ledger",
                                             "where": "clerk's office", "minutes": 10, "roll": roll})
        poor = self.turn.answer("oldworld", asked["next_input"]["request_id"], 2)
        self.assertEqual([f["id"] for f in self.data(poor)["found"]], ["ash"])          # the plain clue is still found
        self.assertEqual(self.data(poor)["took_minutes"], 20)                           # it just took twice as long
        self.turn.finish("oldworld", "He finds ash.")
        asked = self.do("[Mira]: I search too", {"actor": "Mira", "action": "search", "case": "missing-ledger",
                                                 "where": "clerk's office", "minutes": 10, "roll": roll})
        good = self.data(self.turn.answer("oldworld", asked["next_input"]["request_id"], 18))
        self.assertEqual([f["id"] for f in good["found"]], ["ash", "key"])
        self.assertIn("A corner of ledger paper survives.", good["found"][0]["text"])   # the finer detail

    def test_a_wrong_accusation_changes_no_fact(self):
        self.do("a mystery", CASE)
        out = self.data(self.do("[Mira]: it was the toll captain!",
                                {"actor": "Mira", "action": "accuse", "case": "missing-ledger", "claim": "The toll captain stole it."}))
        case = self.thing("case", "missing-ledger")
        self.assertEqual(case["truth"], "The clerk hid the ledger to protect his daughter.")
        self.assertEqual(case["accusations"][0]["claim"], "The toll captain stole it.")
        self.assertEqual(len(case["clues"]), 2)
        self.assertEqual(out["truth_for_the_gm"], case["truth"])
        self.assertNotIn("right", json.dumps(out["recorded"]))                          # nothing tells the players

    def test_each_character_sees_the_room_their_own_way(self):
        self.do("the too-clean room", {"action": "notice", "scene": "the room that is too clean",
                                       "details": {"Mira": "The vent screws were turned lately.",
                                                   "Theo": "The bed was made from the door side."}})
        by_reader = {m["audience"]: m["body"] for m in self.sent()}
        self.assertIn("vent screws", by_reader["Mira"])
        self.assertIn("door side", by_reader["Theo"])
        self.assertNotIn("door side", by_reader["Mira"])

    def test_an_old_thread_returns_after_a_reload_as_an_opening_and_stays_if_left(self):
        self.do("[Mira]: a story about her father", TAPS)
        self.turn.finish("oldworld", "She smiles.")
        self.assertNotIn("CAN COME BACK", self.note())                                  # not here: wrong place, nothing touches it
        m = self.read_json("world-map.json")
        m["party_location"] = "market"
        (self.camp / "world-map.json").write_text(json.dumps(m), encoding="utf-8")
        out = subprocess.run([sys.executable, str(SCRIPTS / "gm_guide.py"), "-c", "oldworld", "turn"],   # a new session
                             capture_output=True, encoding="utf-8", env=dict(os.environ), timeout=60).stdout
        self.assertIn("SOMETHING OF MIRA'S CAN COME BACK (habit, a kindness, not a clue; you are where it belongs)", out)
        self.assertIn("taps the relay cover twice", out)
        self.assertIn("It is an opening, not a quest", out)
        self.assertEqual(self.turn.status("oldworld")["waiting"], [])                   # nothing is asked of the players
        self.assertEqual(self.thing("thread", "two-taps")["status"], "open")            # ignored, it is still there
        self.do("the knock on the relay", {"action": "payoff", "id": "two-taps", "note": "two taps from the other side of the door"})
        self.assertEqual(self.thing("thread", "two-taps")["used"], 1)
        self.assertNotIn("CAN COME BACK", self.note())                                  # just used: it rests a while

    def test_a_thread_comes_to_mind_when_the_scene_touches_it(self):
        self.do("[Mira]: a story about her father", {**TAPS, "payoff": {}})
        self.assertIn("the scene touches relay", self.note("[Theo]: I open the relay cabinet"))
        self.assertNotIn("CAN COME BACK", self.note("[Theo]: I open the pantry"))

    def test_the_gm_is_told_who_has_not_had_a_turn_in_the_light(self):
        for i in range(5):
            self.do(f"[Mira]: plan {i}", {"action": "judge", "actor": "Mira", "plan": f"plan {i}"})
            self.turn.finish("oldworld", "It works.")
        self.assertIn("SPOTLIGHT: Theo has not driven anything for 5 turns", self.note())
        self.do("[Theo]: I pick the lock", {"action": "judge", "actor": "Theo", "plan": "pick the lock"})
        self.assertNotIn("SPOTLIGHT", self.note())

    def test_a_group_waits_for_the_one_who_has_not_said_what_they_do(self):
        out = self.do("[Mira]: we hold the gate", {"action": "group", "id": "hold-the-gate", "goal": "keep the gate open",
                                                   "lead": "Mira", "members": {"Mira": "jams it with a crowbar", "Theo": ""}})
        self.assertEqual(out["status"], "waiting_for_player")
        self.assertEqual(out["next_input"]["expected"], "Theo")
        done = self.turn.answer("oldworld", out["next_input"]["request_id"], "I talk the engineer into waiting")
        self.assertTrue(self.data(done)["ready"])
        self.assertEqual(self.thing("group", "hold-the-gate")["members"]["Theo"], "I talk the engineer into waiting")
        self.assertIsNotNone(self.thing("spotlight", "Theo"))                           # his part counts as his moment


if __name__ == "__main__":
    unittest.main()
