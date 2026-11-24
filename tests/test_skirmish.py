"""World plan PR 11: fights on the map. An enemy does not pick a target it cannot see when its attack
needs sight, a creature has one reaction a round, and an escort ends when the witness is safe whatever
HP the enemies have left."""
from __future__ import annotations

import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _engine_case import EngineCase  # noqa: E402


class SkirmishTests(EngineCase):
    FLAGS = EngineCase.FLAGS.replace("roll_mode: auto", "roll_mode: players")

    def setUp(self):
        super().setUp()
        (self.camp / "characters" / "mira.md").write_text("# Mira\n- **Level:** 3\n- **HP:** 20 / 20\n", encoding="utf-8")
        (self.camp / "battlemap.json").write_text(json.dumps({
            "width": 12, "height": 10, "title": "Platform",
            "terrain": {"5,4": "wall", "5,5": "wall", "5,6": "wall", "8,5": "cover"}, "tokens": []}), encoding="utf-8")
        self.do("the platform",
                {"action": "fight", "objective": "get the witness onto the train",
                 "end_when": [{"token": "Witness", "at": [[11, 5]], "outcome": "the witness is on the train"},
                              {"all_down": "enemy", "outcome": "the platform is clear"}],
                 "props": [{"name": "luggage cart", "effect": "rolls 30 ft in a line: DC 12 Dex or prone"}],
                 "round_triggers": {"2": "the train starts to move"}},
                {"action": "combatant", "name": "Mira", "kind": "pc", "side": "party", "x": 3, "y": 5, "hp": "20/20"},
                {"action": "combatant", "name": "Witness", "kind": "npc", "side": "party", "x": 2, "y": 5, "hp": "6/6"},
                {"action": "combatant", "name": "Guard", "kind": "enemy", "side": "enemy", "x": 7, "y": 5, "hp": "18/18",
                 "reach": 5, "range": 60, "needs_sight": True, "resist": ["fire"], "vulnerable": ["cold"], "immune": ["poison"],
                 "concentrating": "Hold Person", "con_mod": 1, "orders": "let nobody board"},
                {"action": "combatant", "name": "Sniper", "kind": "enemy", "side": "enemy", "x": 6, "y": 1, "hp": "12/12",
                 "range": 120, "needs_sight": True})
        self.turn.finish("oldworld", "Steam on the platform.")

    def advise(self, enemy):
        return self.data(self.do("?", {"action": "advise", "enemy": enemy}))

    def test_an_attack_that_needs_sight_never_picks_someone_behind_the_wall(self):
        guard = self.advise("Guard")                                    # the wall at x=5 stands between them
        self.assertEqual(guard["can_target"], [])
        self.assertEqual(sorted(guard["cannot_see"]), ["Mira", "Witness"])
        self.assertTrue(any("cannot see Witness" in o for o in guard["options"]))    # it knows what it was sent to stop
        sniper = self.advise("Sniper")                                  # a clear line past the end of the wall
        self.assertEqual([t["name"] for t in sniper["can_target"]], ["Mira", "Witness"])
        self.do("a blind-firing mortar crew", {"action": "combatant", "name": "Guard", "needs_sight": False})
        self.assertEqual(sorted(t["name"] for t in self.advise("Guard")["can_target"]), ["Mira", "Witness"])   # no sight needed

    def test_cover_and_distance_come_from_the_map(self):
        self.do("Mira steps round the wall", {"actor": "Mira", "action": "move", "to": [9, 5]})
        target = [t for t in self.advise("Guard")["can_target"] if t["name"] == "Mira"][0]
        self.assertEqual(target["feet"], 10)
        self.assertEqual((target["cover"], target["ac_bonus"]), ("half", 2))      # the crate at 8,5 is between them
        self.flags(self.FLAGS + "- cover_rule: off\n")
        self.assertEqual([t for t in self.advise("Guard")["can_target"] if t["name"] == "Mira"][0]["ac_bonus"], 0)

    def test_one_reaction_a_round(self):
        first = self.data(self.do("[Mira]: reaction!", {"actor": "Mira", "action": "spend", "use": "reaction"}))
        again = self.data(self.do("[Mira]: again!", {"actor": "Mira", "action": "spend", "use": "reaction"}))
        self.assertTrue(first["spent"])
        self.assertFalse(again["spent"])
        self.assertIn("already used their reaction this round", again["error"])
        out = self.do("next round", {"action": "round"})
        self.assertEqual(self.data(out)["trigger"], "the train starts to move")
        self.assertTrue(self.data(self.do("[Mira]: reaction", {"actor": "Mira", "action": "spend", "use": "reaction"}))["spent"])

    def test_leaving_a_players_reach_asks_that_player_once(self):
        self.do("the guard comes round and stands by Mira", {"actor": "Guard", "action": "move", "to": [4, 6]},
                {"actor": "Sniper", "action": "move", "to": [4, 4]})
        asked = self.do("the guard backs off", {"actor": "Guard", "action": "move", "to": [7, 8]})
        self.assertEqual(asked["status"], "waiting_for_player")
        self.assertEqual(asked["next_input"]["expected"], "Mira")
        self.assertEqual(self.read_json("battlemap.json")["tokens"][2]["x"], 4)      # not moved until she has answered
        moved = self.turn.answer("oldworld", asked["next_input"]["request_id"], "yes")
        self.assertEqual(self.data(moved)["reactions"], [{"who": "Mira", "used": True}])
        self.turn.finish("oldworld", "She swings.")
        second = self.do("the sniper backs off too", {"actor": "Sniper", "action": "move", "to": [8, 2]})
        self.assertEqual(second["status"], "open")                      # her reaction is spent: nobody is asked
        self.assertEqual(self.data(second)["provokes"], [])

    def test_moving_respects_walls_speed_and_disengage(self):
        far = self.data(self.do("[Mira]: I run to the train", {"actor": "Mira", "action": "move", "to": [11, 5], "speed": 30}))
        self.assertFalse(far["moved"])
        self.assertIn("ft of movement", far["error"])
        wall = self.data(self.do("[Mira]: into the wall", {"actor": "Mira", "action": "move", "to": [5, 5]}))
        self.assertIn("impassable", wall["error"])

    def test_the_escort_ends_when_the_witness_is_safe(self):
        out = self.do("the witness reaches the train door", {"actor": "Witness", "action": "move", "to": [11, 5]})
        over = [v for v in out["visible_events"] if v["type"] == "fight_over"][0]
        self.assertIn("the witness is on the train", over["text"])
        self.assertIn("Still standing: Guard, Sniper", over["text"])
        fight = self.thing("fight", "current")
        self.assertEqual((fight["status"], fight["outcome"]), ("ended", "the witness is on the train"))
        hp = {t["name"]: t["hp"] for t in self.read_json("battlemap.json")["tokens"]}
        self.assertEqual((hp["Guard"], hp["Sniper"]), ("18/18", "12/12"))            # nobody had to be beaten

    def test_damage_goes_through_resistance_to_hp_concentration_and_morale(self):
        fire = self.data(self.do("fire", {"action": "damage", "target": "Guard", "amount": 13, "type": "fire"}))
        self.assertEqual((fire["dealt"], fire["hp"]), (6, "12/18"))
        self.assertIn("resists fire", fire["why"])
        self.assertEqual(fire["concentration_save"], {"spell": "Hold Person", "dc": 10, "con_mod": 1})
        self.assertEqual(self.data(self.do("poison", {"action": "damage", "target": "Guard", "amount": 9, "type": "poison"}))["dealt"], 0)
        cold = self.data(self.do("cold", {"action": "damage", "target": "Guard", "amount": 4, "type": "cold"}))
        self.assertEqual((cold["dealt"], cold["hp"]), (8, "4/18"))
        self.assertIn("at half HP or less", cold["morale_check"])
        pc = self.data(self.do("the sniper hits Mira", {"action": "damage", "target": "Mira", "amount": 7, "type": "piercing"}))
        self.assertEqual(pc["hp"], "13/20")
        self.assertIn("**HP:** 13 / 20", (self.camp / "characters" / "mira.md").read_text(encoding="utf-8"))

    def test_an_area_is_sheltered_by_a_wall_and_a_prop_works_once(self):
        blast = self.data(self.do("a blast on the far side", {"action": "area", "shape": "sphere", "at": [7, 5], "feet": 20}))
        self.assertEqual(blast["inside"], ["Guard", "Sniper"])
        self.assertEqual(blast["sheltered"], ["Mira"])                  # in the radius, behind the wall
        used = self.data(self.do("[Mira]: I kick the cart", {"actor": "Mira", "action": "prop", "name": "luggage cart"}))
        self.assertIn("DC 12 Dex or prone", used["effect"])
        self.assertIn("already been used", self.data(self.do("again", {"actor": "Mira", "action": "prop", "name": "luggage cart"}))["error"])

    def test_a_cone_spreads_from_its_origin_and_a_wall_still_shelters(self):
        back = self.data(self.do("Mira breathes fire behind her", {"action": "area", "shape": "cone", "at": [3, 5], "to": [0, 5], "feet": 15}))
        self.assertEqual(back["inside"], ["Witness"])                   # not Mira herself, not the Guard behind her
        roar = self.data(self.do("the Guard's cone at Mira", {"action": "area", "shape": "cone", "at": [7, 5], "to": [3, 5], "feet": 30}))
        self.assertEqual(roar["inside"], [])
        self.assertEqual(sorted(roar["sheltered"]), ["Mira", "Witness"])  # in the cone, behind the wall; the Sniper is off to the side

    def test_a_fight_told_in_words_uses_zones(self):
        self.do("a stairwell fight, no grid",
                {"action": "fight", "objective": "reach the street",
                 "end_when": [{"token": "Mira", "zone": "street", "outcome": "Mira is out"}],
                 "zones": {"platform": {"next": ["stairs"], "sees": ["stairs"]},
                           "stairs": {"next": ["platform", "street"], "sees": ["platform", "street"]},
                           "street": {"next": ["stairs"], "sees": ["stairs"]}}},
                {"action": "combatant", "name": "Mira", "kind": "pc", "side": "party", "zone": "platform"},
                {"action": "combatant", "name": "Sniper", "kind": "enemy", "side": "enemy", "zone": "street", "needs_sight": True, "range": 120},
                {"action": "combatant", "name": "Guard", "kind": "enemy", "side": "enemy", "zone": "stairs", "needs_sight": True, "range": 60},
                {"action": "combatant", "name": "Witness", "kind": "npc", "side": "party", "zone": "platform"})
        self.assertNotIn("Mira", [t["name"] for t in self.advise("Sniper")["can_target"]])   # the street cannot see the platform
        seen = [t for t in self.advise("Guard")["can_target"] if t["name"] == "Mira"][0]
        self.assertEqual(seen["feet"], 30)
        out = self.do("[Mira]: down the stairs and out", {"actor": "Mira", "action": "move", "to": "stairs"},
                      {"actor": "Mira", "action": "move", "to": "street"})
        self.assertTrue(any(v["type"] == "fight_over" and "Mira is out" in v["text"] for v in out["visible_events"]))


if __name__ == "__main__":
    unittest.main()
