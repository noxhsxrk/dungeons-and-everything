"""Braid PR 2, the building blocks (mechanics.py): track, pool, condition, bond, progress, table_roll.

Each one applies once when resent, undoes with the turn, and survives closing the store; thresholds fire on the
crossing; a usage die runs down to gone; a progress roll lands on the ladder; a token steps a result up."""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _engine_case import SCRIPTS, EngineCase  # noqa: E402
from test_braid_seam import stamp  # noqa: E402

import oracle  # noqa: E402
import resolve  # noqa: E402

LADDER = resolve.LADDER

#: One intent per handler, and how to read what it changed.
CHANGES = (
    ({"action": "track", "owner": "Mira", "id": "stress", "mark": 1}, ("track", "mira/stress", "value")),
    ({"action": "pool", "owner": "Mira", "id": "tokens", "gain": 1}, ("pool", "mira/tokens", "value")),
    ({"action": "bond", "a": "Mira", "b": "Theo", "mark": 1}, ("bond", "mira|theo", "value")),
    ({"action": "progress", "owner": "party", "name": "Find the heir", "mark": 1}, ("progress", "party/find the heir", "ticks")),
    ({"action": "condition", "owner": "Mira", "name": "Shaken", "mod": -1}, ("condition", "mira/shaken", "mod")),
)


class Mechanics(EngineCase):
    def value(self, kind, id, field):
        rec = self.thing(kind, id)
        return rec and rec[field]

    def test_a_resent_intent_applies_once(self):
        self.turn.begin("oldworld", "setup")
        for intent, (kind, id, field) in CHANGES:
            first = self.turn.resolve("oldworld", [intent])
            again = self.turn.resolve("oldworld", [intent])             # same turn, same intent: a retry
            self.assertNotIn("error", self.data(first), intent)
            self.assertEqual(self.data(again), self.data(first), intent)
            want = {"value": 1, "ticks": 8, "mod": -1}[field]
            self.assertEqual(self.value(kind, id, field), want, intent)
        # a deliberate second mark in the same turn carries its own why
        self.turn.resolve("oldworld", [{"action": "track", "owner": "Mira", "id": "stress", "mark": 1, "why": "again"}])
        self.assertEqual(self.value("track", "mira/stress", "value"), 2)

    def test_a_resent_table_roll_rolls_once(self):
        self.turn.begin("oldworld", "setup")
        intent = {"action": "table_roll", "table": [f"entry {n}" for n in range(50)], "why": "the house stirs"}
        first = self.data(self.turn.resolve("oldworld", [intent]))
        self.assertNotIn("error", first)
        self.assertIn("entry ", json.dumps(first))
        for _ in range(5):                                                 # retries never roll again
            self.assertEqual(self.data(self.turn.resolve("oldworld", [intent])), first)

    def test_undo_restores_the_previous_values(self):
        self.do("first", *[i for i, _ in CHANGES])
        self.turn.finish("oldworld", "One.")
        before = {id: self.thing(kind, id) for _, (kind, id, _f) in CHANGES}
        self.do("second", *[{**i, "why": "more"} for i, _ in CHANGES],
                {"action": "condition", "owner": "Mira", "name": "Shaken", "clear": True})
        self.turn.finish("oldworld", "Two.")
        self.assertEqual(self.value("track", "mira/stress", "value"), 2)
        self.assertIsNone(self.thing("condition", "mira/shaken"))
        import turn_snapshot
        turn_snapshot.undo_snapshot("oldworld", notify_display=False)
        self.assertEqual({id: self.thing(kind, id) for _, (kind, id, _f) in CHANGES}, before)

    def test_values_survive_closing_the_store(self):
        env = {**os.environ}
        run = [sys.executable, str(SCRIPTS / "turn.py"), "-c", "oldworld"]
        subprocess.run(run + ["begin", "--text", "setup"], env=env, capture_output=True, check=True, timeout=60)
        out = subprocess.run(run + ["resolve", "--intents", json.dumps([i for i, _ in CHANGES])], env=env,
                             capture_output=True, encoding="utf-8", check=True, timeout=60)
        self.assertNotIn('"error"', out.stdout)
        for _, (kind, id, field) in CHANGES:                            # a new connection in this process
            self.assertEqual(self.value(kind, id, field), {"value": 1, "ticks": 8, "mod": -1}[field], kind)

    def test_thresholds_fire_once_on_each_crossing(self):
        panic = ["freeze", "flee", "scream"]
        self.turn.begin("oldworld", "setup")

        def mark(n, why):
            out = self.turn.resolve("oldworld", [{"action": "track", "owner": "Mira", "id": "stress", "mark": n, "why": why}])
            return self.data(out)["crossed"]
        self.turn.resolve("oldworld", [{"action": "track", "owner": "Mira", "id": "stress", "max": 6,
                                        "thresholds": [{"at": 4, "note": "panic", "table": panic}]}])
        self.assertEqual(mark(3, "a"), [])
        hit = mark(1, "b")                                              # 3 → 4: crossed
        self.assertEqual([(c["at"], c["dir"], c["note"]) for c in hit], [(4, "up", "panic")])
        self.assertIn(hit[0]["result"], panic)
        self.assertEqual(mark(1, "c"), [])                              # 4 → 5: still beyond, nothing
        self.assertEqual(mark(-3, "d"), [])                             # going back down does not fire an up threshold
        self.assertEqual(len(mark(5, "e")), 1)                          # 2 → 6: a new crossing fires again
        # falling tracks: composure breaks at 0
        self.turn.resolve("oldworld", [{"action": "track", "owner": "Mira", "id": "composure", "max": 99, "set": 3,
                                        "thresholds": [{"at": 0, "dir": "down", "note": "breaks"}]}])
        out = self.turn.resolve("oldworld", [{"action": "track", "owner": "Mira", "id": "composure", "mark": -5}])
        self.assertEqual([c["note"] for c in self.data(out)["crossed"]], ["breaks"])
        self.assertEqual(self.data(out)["value"], 0)

    def test_table_roll_from_a_file_and_names_are_checked(self):
        import mechanics
        tables = self.root / "tables"
        tables.mkdir()
        (tables / "omens.json").write_text(json.dumps({"entries": ["a crow", "a cold wind"]}), encoding="utf-8")
        with mock.patch.object(mechanics, "TABLES", tables):
            out = self.do("omen", {"action": "table_roll", "table": "omens"}, {"action": "table_roll", "table": "../x"})
        self.assertIn(self.data(out, 0)["result"], ("a crow", "a cold wind"))
        self.assertIn("error", self.data(out, 1))

    def test_a_usage_die_steps_down_to_gone(self):
        self.turn.begin("oldworld", "torches")
        self.turn.resolve("oldworld", [{"action": "pool", "owner": "party", "id": "torches", "die": "d12"}])
        use = lambda why: self.data(self.turn.resolve(  # noqa: E731
            "oldworld", [{"action": "pool", "owner": "party", "id": "torches", "use": True, "why": why}]))
        with mock.patch.object(self.turn.Ctx, "roll", return_value=[3]):
            self.assertEqual(use("high")["die"], "d12")                 # 3+: the die holds
        seen = []
        with mock.patch.object(self.turn.Ctx, "roll", return_value=[2]):
            for n in range(5):
                seen.append(use(f"low {n}")["die"])
        self.assertEqual(seen, ["d10", "d8", "d6", "d4", None])
        self.assertTrue(self.thing("pool", "party/torches")["gone"])
        self.assertIn("no usage die left", use("after")["error"])
        import mechanics
        self.assertIn({"name": "party torches gone", "filled": 0, "size": 5}, mechanics.board("oldworld"))

    def test_spend_is_refused_when_short_and_refill_follows_the_cadence(self):
        self.do("setup", {"action": "pool", "owner": "Mira", "id": "tokens", "max": 3, "set": 1, "cadence": "scene"},
                {"action": "pool", "owner": "Mira", "id": "luck", "max": 2, "set": 0, "cadence": "session"},
                {"action": "condition", "owner": "Mira", "name": "Winded", "mod": -1, "clears": "scene"},
                {"action": "condition", "owner": "Mira", "name": "Cursed", "mod": -1, "clears": "a priest"})
        out = self.turn.resolve("oldworld", [{"action": "pool", "owner": "Mira", "id": "tokens", "spend": 2}])
        self.assertIn("not enough", self.data(out)["error"])
        self.assertEqual(self.thing("pool", "mira/tokens")["value"], 1)
        out = self.turn.resolve("oldworld", [{"action": "pool", "refill": "scene"}])
        self.assertEqual(self.data(out)["refilled"], ["Mira tokens"])
        self.assertEqual(self.thing("pool", "mira/tokens")["value"], 3)
        self.assertEqual(self.thing("pool", "mira/luck")["value"], 0)
        self.assertIsNone(self.thing("condition", "mira/winded"))
        self.assertIsNotNone(self.thing("condition", "mira/cursed"))

    def test_the_display_board_and_state_line(self):
        import mechanics
        self.assertEqual(mechanics.board("oldworld"), [])               # nothing made, nothing shown
        self.do("setup", {"action": "track", "owner": "Mira", "id": "stress", "mark": 2},
                {"action": "track", "owner": "Mira", "id": "composure", "max": 99, "set": 63},
                {"action": "pool", "owner": "Mira", "id": "tokens", "set": 2},
                {"action": "progress", "owner": "party", "name": "Find the heir", "rank": "hard", "mark": 3})
        rows = mechanics.board("oldworld")
        self.assertIn({"name": "Mira stress", "filled": 2, "size": 6}, rows)
        self.assertIn({"name": "Mira composure 63/99", "filled": 6, "size": 10}, rows)   # scaled to fit the panel
        self.assertIn({"name": "Mira tokens", "filled": 2, "size": 3}, rows)
        self.assertIn({"name": "Find the heir (hard)", "filled": 3, "size": 10}, rows)
        self.turn.finish("oldworld", "Noted.")
        state = (self.camp / "state.md").read_text(encoding="utf-8")
        self.assertIn("- **Tracks and pools:** Mira composure 63/99; Mira stress 2/6; Mira tokens 2/3; Find the heir 3/10 boxes",
                      state)


class BraidChecks(EngineCase):
    """Checks under System: core (roll_mode auto unless a test says otherwise)."""
    SYSTEM = "core"

    def setUp(self):
        super().setUp()
        stamp(self.camp, self.SYSTEM)

    def roll(self, **extra):
        return self.turn.resolve("oldworld", [{"action": "roll", "actor": "Mira", "spec": "2d6+1", "label": "climb", **extra}])

    def test_progress_roll_lands_on_the_ladder_with_the_boxes_as_modifier(self):
        self.turn.begin("oldworld", "the heir")
        self.turn.resolve("oldworld", [{"action": "progress", "owner": "party", "name": "Find the heir", "rank": "easy"}])
        for marks, mod in ((0, -2), (2, 1), (4, 3)):                    # 0, 6 and 10 boxes (easy = 3 a mark, capped)
            if marks:
                self.turn.resolve("oldworld", [{"action": "progress", "owner": "party", "name": "Find the heir",
                                                "mark": 2, "why": f"m{marks}"}])
            d = self.data(self.turn.resolve("oldworld", [{"action": "progress", "owner": "party", "name": "Find the heir",
                                                          "roll": True, "actor": "Mira", "why": f"r{marks}"}]))
            self.assertEqual((d["modifier"], d["spec"]), (mod, f"2d6{mod:+d}"))
            self.assertEqual(d["total"], sum(d["dice"]) + mod)
            self.assertEqual(d["degree"], resolve.resolve("core", d["spec"], None, d["dice"])["degree"])
            self.assertIn(d["degree"], LADDER)

    def test_a_progress_roll_waits_for_the_players_dice(self):
        self.flags(self.FLAGS.replace("auto", "players"))
        self.do("setup", {"action": "progress", "owner": "party", "name": "Escape", "rank": "hard", "mark": 4})
        asked = self.turn.resolve("oldworld", [{"action": "progress", "owner": "party", "name": "Escape", "roll": True,
                                                "actor": "Mira"}])
        self.assertIn("2d6", asked["next_input"]["question"])
        d = self.data(self.turn.answer("oldworld", asked["next_input"]["request_id"], 8))
        self.assertEqual((d["total"], d["degree"], d["boxes"]), (8, "success at a cost", 4))   # 4 boxes: +0

    def test_a_token_steps_the_result_up_once(self):
        self.do("setup", {"action": "pool", "owner": "Mira", "id": "tokens", "set": 2})
        d = self.data(self.roll())
        start = LADDER.index(d["degree"])
        spend = {"action": "pool", "owner": "Mira", "id": "tokens", "step_up": True}
        up = self.data(self.turn.resolve("oldworld", [spend]))
        again = self.data(self.turn.resolve("oldworld", [spend]))       # a resend: no second token
        if start == 4:
            self.assertIn("already a critical success", up["error"])
            return
        self.assertEqual((up["was"], up["degree"]), (d["degree"], LADDER[start + 1]))
        self.assertEqual(up["degree"], resolve.resolve("core", d["spec"], None, d["dice"], step_up=1)["degree"])
        self.assertEqual(again, up)
        self.assertEqual(self.thing("pool", "mira/tokens")["value"], 1)
        second = self.data(self.turn.resolve("oldworld", [{**spend, "why": "again"}]))   # a second token, a second step
        if start + 1 == 4:
            self.assertIn("already a critical success", second["error"])
        else:
            self.assertEqual(second["degree"], LADDER[start + 2])
            self.assertEqual(self.thing("pool", "mira/tokens")["value"], 0)

    def test_no_token_no_step(self):
        self.do("setup", {"action": "pool", "owner": "Mira", "id": "tokens", "set": 0})
        check = self.roll()["action_id"]
        out = self.data(self.turn.resolve("oldworld", [{"action": "pool", "owner": "Mira", "id": "tokens", "step_up": True}]))
        self.assertIn("not enough", out["error"])
        self.assertIsNone(self.thing("step_up", check))

    def test_push_marks_one_stress_even_when_the_turn_waits_for_the_dice(self):
        self.flags(self.FLAGS.replace("auto", "players"))
        self.turn.begin("oldworld", "[Mira]: I push it")
        asked = self.roll(push=True)
        self.assertIn("2d6+2", asked["next_input"]["question"])
        self.assertIsNone(self.thing("track", "mira/stress"))           # nothing marked while waiting
        d = self.data(self.turn.answer("oldworld", asked["next_input"]["request_id"], 7))
        self.assertEqual((d["total"], d["modifier"]), (9, 2))
        self.assertEqual(self.thing("track", "mira/stress")["value"], 1)
        self.turn.resume("oldworld")
        self.assertEqual(self.thing("track", "mira/stress")["value"], 1)

    def test_help_needs_a_bond_and_conditions_hit_their_approaches(self):
        self.turn.begin("oldworld", "setup")
        self.assertIn("no bond", self.data(self.roll(help="Theo"))["error"])
        self.turn.resolve("oldworld", [{"action": "bond", "a": "Theo", "b": "Mira", "set": 1},
                                       {"action": "condition", "owner": "Mira", "name": "Shaken", "mod": -1,
                                        "approaches": ["heart"]}])
        helped = self.data(self.roll(help="Theo", why="2"))
        self.assertEqual(helped["modifier"], 2)                          # +1 base, +1 help
        self.assertEqual(self.data(self.roll(approach="heart", why="3"))["modifier"], 0)
        self.assertEqual(self.data(self.roll(approach="force", why="4"))["modifier"], 1)

    def test_bond_points_are_held_per_side(self):
        self.turn.begin("oldworld", "setup")
        out = self.turn.resolve("oldworld", [{"action": "bond", "a": "Mira", "b": "Theo", "gain": 2},
                                             {"action": "bond", "a": "Theo", "b": "Mira", "spend": 1}])
        self.assertEqual(self.data(out, 0)["points"], {"mira": 2})
        self.assertIn("not enough", self.data(out, 1)["error"])


class StoryChecks(BraidChecks):
    SYSTEM = "story"

    def roll(self, **extra):
        return self.turn.resolve("oldworld", [{"action": "roll", "actor": "Mira", "likelihood": "unlikely",
                                               "label": "climb", **extra}])

    def test_a_token_steps_the_result_up_once(self):
        self.do("setup", {"action": "pool", "owner": "Mira", "id": "tokens", "set": 1})
        d = self.data(self.roll())
        rung = resolve.STORY_STEPS[oracle.verdict(d["dice"][0], "unlikely", oracle.CHAOS_DEFAULT)]
        self.assertEqual(d["degree"], LADDER[rung])
        up = self.data(self.turn.resolve("oldworld", [{"action": "pool", "owner": "Mira", "id": "tokens", "step_up": True}]))
        if rung == 4:
            self.assertIn("error", up)
        else:
            self.assertEqual(up["degree"], LADDER[rung + 1])
            self.assertEqual(self.thing("pool", "mira/tokens")["value"], 0)

    def test_progress_roll_lands_on_the_ladder_with_the_boxes_as_modifier(self):
        self.do("setup", {"action": "progress", "owner": "party", "name": "Find the heir", "rank": "easy", "mark": 2})
        d = self.data(self.turn.resolve("oldworld", [{"action": "progress", "owner": "party", "name": "Find the heir",
                                                      "roll": True, "actor": "Mira"}]))
        self.assertEqual((d["boxes"], d["likelihood"]), (6, "likely"))
        self.assertEqual(d["degree"], LADDER[resolve.STORY_STEPS[oracle.verdict(d["dice"][0], "likely", oracle.CHAOS_DEFAULT)]])

    def test_a_progress_roll_waits_for_the_players_dice(self):
        self.skipTest("story mode asks the oracle: nobody rolls")

    def test_push_marks_one_stress_even_when_the_turn_waits_for_the_dice(self):
        self.turn.begin("oldworld", "[Mira]: I push it")
        self.assertIn("story mode has no modifiers", self.data(self.roll(push=True))["error"])

    def test_help_needs_a_bond_and_conditions_hit_their_approaches(self):
        self.skipTest("story mode has no modifiers")


class D20Untouched(EngineCase):
    def test_a_progress_roll_is_refused_under_5e(self):
        out = self.do("setup", {"action": "progress", "owner": "party", "name": "Escape"},
                      {"action": "progress", "owner": "party", "name": "Escape", "roll": True})
        self.assertIn("Braid checks", self.data(out)["error"])


if __name__ == "__main__":
    unittest.main()
