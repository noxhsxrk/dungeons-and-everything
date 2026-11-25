"""Braid PR 10, the module seams the AI-GM playtests found: a label or a dangerous foe on the roll, one harm rule for
position against a foe, solo roles never deal the PC the traitor, a revealed deal needs `new`, the loop's `carry`,
genres.py input and conflicts, contest wording, the Braid dials in the turn context, quiet first season/status."""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from test_braid_pr5 import FLAGS, Module  # noqa: E402

import turn  # noqa: E402,F401  (the engine first)
import genres  # noqa: E402
import mod_position_effect  # noqa: E402

SCRIPTS = HERE.parent / "skills" / "dne" / "scripts"
SHEET = "# Mira\n\n## Approaches\n- **Wits:** +2\n- **Force:** +0\n\n## Labels\n- Smuggler: knows every back door\n"


class Edges(Module):
    MODULES, ROLL = "mooks", "auto"

    def setUp(self):
        super().setUp()
        (self.camp / "characters" / "mira.md").write_text(SHEET, encoding="utf-8")

    def test_a_sheet_label_adds_one_and_an_unknown_one_is_refused(self):
        d = self.one({"action": "roll", "actor": "Mira", "approach": "wits", "use_label": "smuggler", "label": "a door"})
        self.assertEqual((d["modifier"], d["edges"]), (3, ["label Smuggler +1"]))
        self.assertIn("no label", self.one({"action": "roll", "actor": "Mira", "approach": "wits", "use_label": "Pilot"})["error"])

    def test_a_threat_4_or_5_foe_is_minus_one_and_a_small_one_is_not(self):
        self.one({"action": "foe", "name": "General Khaan", "threat": 5})
        self.one({"action": "foe", "name": "Thug", "threat": 2})
        self.assertEqual(self.one({"action": "roll", "actor": "Mira", "approach": "wits", "against": "general khaan"})["modifier"], 1)
        self.assertEqual(self.one({"action": "roll", "actor": "Mira", "approach": "wits", "against": "Thug"})["modifier"], 2)
        self.assertIn("no foe", self.one({"action": "roll", "actor": "Mira", "approach": "wits", "against": "Nobody"})["error"])


class PositionAgainstAFoe(Module):
    MODULES, ROLL = "position_effect, mooks", "auto"

    def test_the_larger_of_position_and_the_foes_deals(self):
        self.assertEqual(mod_position_effect.reading("controlled", "standard", "failure", 3)["harm_if_hurt"], 3)
        self.assertEqual(mod_position_effect.reading("desperate", "standard", "failure", 1)["harm_if_hurt"], 3)
        self.assertEqual(mod_position_effect.reading("controlled", "standard", "failure")["harm_if_hurt"], 1)
        self.one({"action": "foe", "name": "Khaan", "threat": 5})
        d = self.one({"action": "position", "actor": "Mira", "spec": "2d6", "position": "controlled", "against": "Khaan"})
        self.assertIn("against Khaan (threat 5) -1", d["edges"])
        if d["degree"] in ("failure", "critical failure"):
            self.assertGreaterEqual(d["reading"]["harm_if_hurt"], 3)


class SoloRoles(Module):
    MODULES, ROLL = "roles", "auto"

    def test_the_only_pc_is_never_the_traitor_and_a_new_deal_is_asked_for(self):
        names = ["Mira", "Vos", "Kell", "Ada"]
        for n in range(8):                                # different action ids: different shuffles
            d = self.one({"action": "roles", "deal": names, "roles": {"traitor": 1}, "new": True, "why": n})
            self.assertNotIn("error", d)
            deal = self.one({"action": "roles", "reveal": True})["deal"]
            self.assertEqual(deal["Mira"], "loyal")
            self.assertEqual(sorted(deal.values()), ["loyal", "loyal", "loyal", "traitor"])
        self.assertIn("new", self.one({"action": "roles", "deal": names})["error"])
        self.one({"action": "roles", "deal": names, "roles": {"traitor": 4}, "new": True, "pc_may_draw": True})
        self.assertEqual(self.one({"action": "roles", "reveal": True})["deal"]["Mira"], "traitor")
        self.assertIn("always loyal", self.one({"action": "roles", "deal": names, "roles": {"traitor": 4}, "new": True})["error"])


class LoopCarry(Module):
    MODULES, ROLL = "loop", "auto"

    def test_carry_keeps_a_named_track_and_the_rest_rewinds(self):
        self.one({"action": "track", "owner": "Mira", "id": "realm", "set": 0, "max": 8})
        self.one({"action": "track", "owner": "Mira", "id": "harm", "mark": 0})
        self.one({"action": "loop", "start": True, "carry": ["Realm"]})
        self.one({"action": "track", "owner": "Mira", "id": "realm", "mark": 2})
        self.one({"action": "track", "owner": "Mira", "id": "harm", "mark": 1})
        d = self.one({"action": "loop", "reset": True, "why": "fell"})
        self.assertEqual(d["carried_tracks"], ["realm"])
        self.assertEqual(self.thing("track", "mira/realm")["value"], 2)
        self.assertEqual(self.thing("track", "mira/harm")["value"], 0)


class Genres(unittest.TestCase):
    def test_space_or_comma_ids_unknown_keys_and_settled_conflicts(self):
        self.assertEqual(genres._ids(["war", "wuxia,timeloop"]), ["war", "wuxia", "timeloop"])
        self.assertEqual(genres._ids("war wuxia"), ["war", "wuxia"])
        with self.assertRaisesRegex(ValueError, "not a key"):
            genres.combine("heist", sets=["foo=bar"])
        mix = genres.combine("heist,cozy,comedy", sets=["dials.storyteller=banter"])
        self.assertEqual(mix["dials"]["storyteller"], "banter")
        self.assertNotIn("dials.storyteller", [c["field"] for c in mix["conflicts"]])
        self.assertTrue(mix["conflicts"])                 # the ones the table did not settle stay
        added = genres.combine("heist,cozy,comedy", sets=["modules=position_effect,engagement,heat,contest"])
        self.assertNotIn("contest", added["optional"])
        self.assertEqual(genres.main(["combine", "war", "wuxia"]), 0)

    def test_no_preset_asks_for_death_saves(self):
        for gid, g in genres.catalog().items():
            self.assertNotEqual(g["dials"].get("when_down"), "saves", gid)


class ContestAndContext(Module):
    MODULES, ROLL = "contest", "auto"

    def run_sub(self, *argv) -> str:
        return subprocess.run([sys.executable, str(SCRIPTS / "subsystem.py"), "-c", "oldworld", *argv],
                              capture_output=True, text=True, encoding="utf-8", env=dict(os.environ), check=True).stdout

    def test_contest_status_counts_rounds_and_scores_the_final_degree(self):
        self.run_sub("start", "Bake-off", "--race", "3", "--sides", "Dot,The vicar")
        self.assertIn("no round limit", self.run_sub("status"))
        self.assertIn("Dot 1", self.run_sub("check", "Bake-off", "--side", "Dot", "--degree", "success at a cost"))

    def test_the_turn_context_carries_the_braid_dials_only_for_braid(self):
        self.flags(FLAGS.format("auto", "contest, seasons") + "- claims: declare\n- storyteller: banter\n")
        import scene_context
        rules = scene_context.build("oldworld", "hello")["rules"]
        self.assertEqual((rules["claims"], rules["storyteller"], rules["modules"]), ("declare", "banter", "contest, seasons"))
        self.system("d20")
        rules = scene_context.build("oldworld", "hello")["rules"]
        self.assertFalse({"claims", "storyteller", "modules"} & set(rules))


class QuietFirsts(Module):
    MODULES, ROLL = "seasons, status_window", "auto"

    def test_first_season_read_and_modules_apply_announce_nothing(self):
        self.turn_with("baseline", {"action": "track", "owner": "party", "id": "x", "set": 0})
        r = self.turn_with("apply", {"action": "modules", "apply": True})     # makes Mira's tokens: noted, not said
        self.assertFalse([e for e in r["visible_events"] if e["type"] == "system"])
        r = self.turn_with("season", {"action": "season"})
        self.assertFalse([e for e in r["visible_events"] if e["type"] == "season" and e["recipient"] == "party"])
        r = self.turn_with("a month", {"action": "wait", "minutes": 60 * 1440})
        self.assertTrue([e for e in r["visible_events"] if "season turns" in e["text"]])


if __name__ == "__main__":
    unittest.main()
