"""World plan PR 8: NPCs with somewhere to be, and factions that decide from what they know. The
wheelwright goes to market as arranged, cannot be in two towns the same day, changes his plan when he
knows the road is shut, and a faction can sue for peace with no subagent anywhere."""
from __future__ import annotations

import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _engine_case import EngineCase  # noqa: E402

MARKET_DAY = {"action": "appointment", "id": "market-day", "npc": "Bren", "from": "Millbridge", "place": "Market",
              "in_minutes": 2000, "purpose": "sell cartwheels",
              "otherwise": {"place": "Millbridge", "purpose": "mend the mill wheel instead"}}


class RoutineTests(EngineCase):
    def where(self, npc="Bren", **when):
        return self.data(self.do("where?", {"action": "where", "npc": npc, **when}))

    def test_he_goes_to_market_as_arranged(self):
        made = self.data(self.do("Bren plans his market day", MARKET_DAY))
        self.assertTrue(made["made"])
        self.assertEqual(made["at_minute"] - made["departs_minute"], 1440)   # 24 miles on foot: he leaves a day ahead
        self.assertEqual(self.where()["place"], "millbridge")
        self.do("he sets out", {"action": "wait", "minutes": 1000})
        self.assertIsNone(self.where()["place"])                             # on the road, in no town
        self.assertIn("on the way to Market", self.where()["activity"])
        out = self.do("market day", {"action": "wait", "minutes": 1100})
        self.assertEqual(self.where()["place"], "market")
        self.assertEqual(self.thing("appointment", "market-day")["status"], "kept")
        self.assertTrue(any(v["type"] == "npc_arrived" and "sell cartwheels" in v["text"] for v in out["visible_events"]))

    def test_he_cannot_be_in_two_towns_on_the_same_day(self):
        self.do("Bren plans his market day", MARKET_DAY)
        clash = self.data(self.do("and the ford an hour later?", {"action": "appointment", "npc": "Bren", "place": "The Ford",
                                                                    "in_minutes": 2060, "purpose": "meet the ferryman"}))
        self.assertFalse(clash["made"])
        self.assertIn("only 1h00 between the two", clash["error"])
        self.assertIn("takes 12h00", clash["error"])
        fine = self.data(self.do("the ford the next day", {"action": "appointment", "npc": "Bren", "place": "The Ford",
                                                           "in_minutes": 2000 + 800, "purpose": "meet the ferryman"}))
        self.assertTrue(fine["made"])

    def test_knowing_the_road_is_shut_he_changes_his_plan(self):
        self.do("Bren plans his market day", MARKET_DAY)
        self.do("the Tollmen shut the road out of town",
                {"action": "route", "between": ["Millbridge", "The Ford"], "access": "closed", "reason": "the Tollmen hold it"})
        out = self.do("the day he should leave", {"action": "wait", "minutes": 700})
        appt = self.thing("appointment", "market-day")
        self.assertEqual(appt["status"], "changed")
        self.assertIn("knew the road was closed", appt["note"])
        self.assertEqual(self.where()["place"], "millbridge")
        self.assertTrue(any("mend the mill wheel instead" in v.get("text", "") for v in out["visible_events"]))

    def test_not_knowing_he_walks_into_it_and_comes_back(self):
        self.do("Bren plans his market day", MARKET_DAY)
        self.do("far down the road, the second stretch is shut",
                {"action": "route", "between": ["The Ford", "Market"], "access": "closed", "reason": "a rockfall"})
        self.assertEqual(self.data(self.do("?", {"action": "knows", "holder": "place:Millbridge"}))["beliefs"], [])   # nobody told Millbridge
        out = self.do("the day he should leave", {"action": "wait", "minutes": 700})
        appt = self.thing("appointment", "market-day")
        self.assertEqual(appt["status"], "missed")
        self.assertIn("a rockfall", appt["note"])
        self.assertTrue(any(v["type"] == "npc_turned_back" for v in out["visible_events"]))
        self.assertEqual(self.thing("belief", "npc:Bren|route:ford|market")["source"], "saw it")   # now he knows

    def test_a_meeting_passes_news_and_changes_a_relationship(self):
        self.do("a fire, and Rina waits at the market",
                {"action": "fact", "id": "mill-fire", "text": "The mill burned.", "place": "Millbridge", "witnesses": ["npc:Bren"]},
                {"action": "npc_schedule", "npc": "Rina Saelim", "blocks": [{"from": "00:00", "to": "23:59", "place": "Market",
                                                                             "activity": "at her stall"}]},
                {**MARKET_DAY, "on_meet": {"with": "Rina Saelim", "tell": ["mill-fire"], "relation": "owes"}})
        graph = self.read_json("graph.json")
        graph["nodes"] = [{"id": "npc_bren", "type": "npc", "name": "Bren"}, {"id": "npc_rina_saelim", "type": "npc", "name": "Rina Saelim"}]
        (self.camp / "graph.json").write_text(json.dumps(graph), encoding="utf-8")
        self.assertIsNone(self.thing("belief", "npc:Rina Saelim|mill-fire"))
        out = self.do("market day", {"action": "wait", "minutes": 2100})
        self.assertEqual(self.thing("belief", "npc:Rina Saelim|mill-fire")["source"], "told by Bren")
        self.assertEqual(self.thing("relation", "Bren|Rina Saelim")["type"], "owes")
        edge = self.read_json("graph.json")["edges"][-1]
        self.assertEqual((edge["from"], edge["to"], edge["type"]), ("npc_bren", "npc_rina_saelim", "owes"))
        self.assertTrue(any(v["type"] == "meeting" for v in out["visible_events"]))

    def test_a_schedule_says_where_he_is_and_an_exception_overrides_it(self):
        now = self.data(self.do("?", {"action": "ask"}))["minute"]
        self.do("Bren's days", {"action": "npc_schedule", "npc": "Bren",
                                "blocks": [{"from": "06:00", "to": "18:00", "place": "Millbridge", "activity": "at the mill"},
                                           {"from": "18:00", "to": "06:00", "place": "The Ford", "activity": "night fishing"}],
                                "exceptions": [{"day": now // 1440 + 3, "place": "Market", "activity": "market day"}]})
        base = (now // 1440 + 1) * 1440
        self.assertEqual(self.where(at_minute=base + 9 * 60)["activity"], "at the mill")
        self.assertEqual(self.where(at_minute=base + 23 * 60)["place"], "ford")          # a block across midnight
        self.assertEqual(self.where(at_minute=(now // 1440 + 3) * 1440 + 9 * 60)["place"], "market")

    # ── factions ──────────────────────────────────────────────────────────

    def factions(self):
        return self.read_json("factions.json")["factions"]

    def test_a_weaker_faction_that_has_heard_so_sues_for_peace_by_rule(self):
        data = self.read_json("factions.json")
        data["factions"]["Millers' Guild"]["force"] = 5                      # stronger than the Tollmen's 3
        (self.camp / "factions.json").write_text(json.dumps(data), encoding="utf-8")
        self.do("word of the guild's hired swords reaches the Tollmen",
                {"action": "fact", "id": "guild-arms", "text": "The Millers' Guild has hired forty swords.", "place": "Market"},
                {"action": "belief", "holder": "faction:Tollmen", "fact": "guild-arms",
                 "claim": "The Millers' Guild has hired forty swords.", "source": "a spy", "confidence": 0.8})
        out = self.do("a week passes", {"action": "wait", "days": 8})         # no subagent, no GM decision: rules only
        decision = self.thing("decision", "Tollmen|1")
        self.assertEqual((decision["choice"], decision["target"], decision["by"]), ("negotiate", "Millers' Guild", "rules"))
        self.assertEqual(decision["because"], ["guild-arms"])                # the reason is something they really heard
        self.assertTrue(any("sends envoys to Millers' Guild" in v["text"] for v in out["visible_events"]))
        self.assertIsNotNone(self.thing("truce", "Millers' Guild|Tollmen"))

    def test_without_that_news_the_same_faction_does_not_know_to_be_afraid(self):
        data = self.read_json("factions.json")
        data["factions"]["Millers' Guild"]["force"] = 5
        (self.camp / "factions.json").write_text(json.dumps(data), encoding="utf-8")
        self.do("a week passes", {"action": "wait", "days": 8})
        self.assertIsNone(self.thing("decision", "Tollmen|1"))
        self.assertIsNone(self.thing("truce", "Tollmen|Millers' Guild"))

    def test_an_intent_must_be_something_the_faction_could_do(self):
        brief = self.data(self.do("brief", {"action": "faction_brief", "faction": "Tollmen"}))
        self.assertEqual(brief["knows"], [])
        self.assertEqual(brief["stats"]["force"], 3)
        no = self.data(self.do("a move on news they never had", {"action": "faction_intent", "faction": "Tollmen",
                                                               "choice": "defend", "because": ["mill-fire"]}))
        self.assertFalse(no["accepted"])
        self.assertIn("has not heard of 'mill-fire'", no["error"])
        yes = self.data(self.do("a move they can make", {"action": "faction_intent", "faction": "Tollmen", "choice": "negotiate",
                                                         "target": "Millers' Guild", "why": "the bridge is not worth a war", "by": "subagent"}))
        self.assertTrue(yes["accepted"])
        out = self.do("a week passes", {"action": "wait", "days": 8})
        self.assertEqual(self.thing("decision", "Tollmen|1")["by"], "subagent")       # the stored answer is what ran
        self.assertTrue(any("sends envoys" in v["text"] and "the bridge is not worth a war" in v["text"] for v in out["visible_events"]))


if __name__ == "__main__":
    unittest.main()
