"""On a host with no hooks the GM can move time without the engine (a hand edit of calendar.json, a turn answered
without the scripts). The next engine turn says so, and a zero-minute wait runs what came due in between."""
from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _engine_case import EngineCase  # noqa: E402


class ClockOutsideTests(EngineCase):
    def test_a_hand_moved_clock_is_flagged_and_caught_up(self):
        import gm_guide
        self.do("an hour", {"action": "wait", "hours": 1},
                {"action": "schedule", "in_minutes": 60, "text": "The rider reaches the mill.", "event_id": "rider"})
        self.turn.finish("oldworld", "An hour goes by.")
        view = self.turn.begin("oldworld", "[Mira]: we wait")
        self.assertFalse(any("OUTSIDE THE ENGINE" in x for x in gm_guide.engine_lines("oldworld", view)))
        self.turn.finish("oldworld", "Nothing yet.")
        cal = json.loads((self.camp / "calendar.json").read_text(encoding="utf-8"))
        mod = self.s._calendar_module()
        mod._advance_minutes(cal, 180)                                   # the GM writes three hours by hand
        (self.camp / "calendar.json").write_text(json.dumps(cal), encoding="utf-8")
        view = self.turn.begin("oldworld", "[Mira]: later that day")
        line = [x for x in gm_guide.engine_lines("oldworld", view) if "OUTSIDE THE ENGINE" in x]
        self.assertTrue(line and "+180 min" in line[0] and '"minutes": 0' in line[0], line)
        self.assertEqual(self.event("rider")["status"], "pending")         # the rider never came
        out = self.turn.resolve("oldworld", [{"action": "wait", "minutes": 0}])
        self.assertEqual(self.event("rider")["status"], "applied")
        self.assertEqual(out["results"][0]["data"]["to"], out["results"][0]["data"]["from"])   # no extra time
        self.turn.finish("oldworld", "The rider arrives.")
        view = self.turn.begin("oldworld", "[Mira]: and now?")
        self.assertFalse(any("OUTSIDE THE ENGINE" in x for x in gm_guide.engine_lines("oldworld", view)))

    def no_alarm(self, text):
        import gm_guide
        view = self.turn.begin("oldworld", text)
        lines = [x for x in gm_guide.engine_lines("oldworld", view) if "OUTSIDE THE ENGINE" in x]
        self.assertEqual(lines, [], text)
        return view

    def test_time_the_engine_moves_never_raises_it(self):
        self.flags(self.FLAGS + "- ooc_minutes: 5\n")
        steps = [("[Mira]: we rest", {"action": "rest", "type": "short"}),
                 ("[Mira]: we walk to the ford", {"action": "travel", "to": "The Ford"}),
                 ("[Mira]: what time is it?", {"action": "ask", "question": "what time is it?"}),
                 ("an hour", {"action": "wait", "hours": 1})]
        for text, intent in steps:
            self.no_alarm(text)
            out = self.turn.resolve("oldworld", [intent])
            self.assertNotEqual(out["status"], "waiting_for_player", text)
            self.assertGreater(out["elapsed_minutes"], 0, text)
            self.turn.finish("oldworld", "On we go.")
        self.no_alarm("[Mira]: and then?")
        self.turn.finish("oldworld", "Quiet.")
        import turn_snapshot
        turn_snapshot.undo_snapshot("oldworld", notify_display=False)     # back a turn: clock and store go back together
        self.no_alarm("[Mira]: again")

