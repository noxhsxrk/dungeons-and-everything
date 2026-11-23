"""World plan PR 7: witnesses, news and belief. A town does not know another town's news until it gets
there; stopping the rider stops that line and no other; a faction acts on what it has actually heard."""
from __future__ import annotations

import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _engine_case import EngineCase  # noqa: E402

FIRE = {"action": "fact", "id": "mill-fire", "text": "The mill burned; Mira was seen leaving.", "place": "Millbridge",
        "witnesses": ["npc:Bren", "faction:Millers' Guild"]}
RIDER = {"action": "news", "fact": "mill-fire", "from": "Millbridge", "to": "place:Market", "channel": "messenger",
         "carrier": "a Tollmen rider"}


class KnowledgeTests(EngineCase):
    def knows(self, holder):
        return [b["fact"] for b in self.data(self.do("who knows?", {"action": "knows", "holder": holder}))["beliefs"]]

    def test_only_those_who_were_there_know(self):
        self.do("the mill burns", FIRE)
        self.assertEqual(self.knows("npc:Bren"), ["mill-fire"])
        self.assertEqual(self.knows("place:Millbridge"), ["mill-fire"])     # common knowledge where it happened
        self.assertEqual(self.knows("place:Market"), [])                    # a day's ride away: nothing
        self.assertEqual(self.knows("faction:Tollmen"), [])

    def test_the_next_town_learns_when_the_rider_arrives_and_not_before(self):
        sent = self.data(self.do("the mill burns, a rider leaves", FIRE, RIDER))
        self.assertTrue(sent["sent"])
        self.do("a few hours pass", {"action": "wait", "minutes": sent["minutes"] - 30})
        self.assertEqual(self.knows("place:Market"), [])
        out = self.do("the rider gets in", {"action": "wait", "minutes": 60})
        self.assertEqual(self.knows("place:Market"), ["mill-fire"])
        belief = self.thing("belief", "place:market|mill-fire")
        self.assertEqual(belief["source"], "messenger (a Tollmen rider)")
        self.assertEqual(belief["learned_at"], sent["arrives_minute"])
        self.assertLess(belief["confidence"], 1.0)                          # hearsay, not a witness
        self.assertTrue(any(v["type"] == "news_arrived" for v in out["visible_events"]))

    def test_stopping_the_rider_stops_that_line_and_the_radio_still_gets_through(self):
        (self.camp / "worldkit.json").write_text(json.dumps({"communication": {"radio": True}}), encoding="utf-8")
        sent = self.data(self.do("the mill burns, a rider leaves", FIRE, RIDER))
        radio = self.data(self.do("someone gets on the radio", {**RIDER, "channel": "radio", "to": "faction:Tollmen", "carrier": ""}))
        stopped = self.data(self.do("[Mira]: we catch the rider on the road",
                                    {"action": "intercept", "event_id": sent["event_id"], "reason": "the party caught the rider"}))
        self.assertTrue(stopped["stopped"])
        self.do("two days pass", {"action": "wait", "days": 2})
        self.assertEqual(self.knows("place:Market"), [])                    # the rider never arrived
        self.assertEqual(self.event(sent["event_id"])["status"], "cancelled")
        self.assertIn("the party caught the rider", self.event(sent["event_id"])["note"])
        self.assertEqual(self.knows("faction:Tollmen"), ["mill-fire"])      # the other line did
        self.assertEqual(self.event(radio["event_id"])["status"], "applied")

    def test_a_world_without_radio_cannot_use_one(self):
        self.do("the mill burns", FIRE)
        refused = self.data(self.do("someone looks for a radio", {**RIDER, "channel": "radio"}))
        self.assertFalse(refused["sent"])
        self.assertIn("no radio", refused["error"])

    def test_news_can_be_held_up(self):
        sent = self.data(self.do("the mill burns, a rider leaves", FIRE, RIDER))
        self.do("the bridge is shut on him", {"action": "intercept", "event_id": sent["event_id"], "delay_minutes": 1440,
                                             "reason": "the bridge was shut"})
        self.do("the day he should have arrived", {"action": "wait", "minutes": sent["minutes"] + 60})
        self.assertEqual(self.knows("place:Market"), [])
        self.do("a day later", {"action": "wait", "days": 1})
        self.assertEqual(self.knows("place:Market"), ["mill-fire"])

    def test_a_wrong_belief_can_be_put_right_and_the_fact_never_moved(self):
        self.do("the mill burns", FIRE)
        self.do("a forged letter", {"action": "belief", "holder": "faction:Tollmen", "fact": "mill-fire",
                                    "claim": "The miller burned it himself.", "source": "a forged letter", "confidence": 0.6})
        self.do("the truth comes out", {"action": "belief", "holder": "faction:Tollmen", "fact": "mill-fire",
                                        "claim": "Mira was seen leaving the mill.", "source": "Bren's testimony", "confidence": 0.9})
        belief = self.thing("belief", "faction:Tollmen|mill-fire")
        self.assertEqual(belief["claim"], "Mira was seen leaving the mill.")
        self.assertEqual(belief["history"][0]["claim"], "The miller burned it himself.")   # what they used to think is kept
        self.assertEqual(self.thing("fact", "mill-fire")["text"], "The mill burned; Mira was seen leaving.")

    def test_a_faction_can_only_act_on_what_it_has_heard(self):
        self.do("the mill burns", FIRE)
        blind = self.data(self.do("the Tollmen look for Mira?", {"action": "heat", "area": "Market", "faction": "Tollmen",
                                                               "fact": "mill-fire", "delta": 2}))
        self.assertFalse(blind["changed"])
        self.assertIn("has not heard of", blind["error"])                   # no belief, no attention
        self.do("word reaches them", {"action": "belief", "holder": "faction:Tollmen", "fact": "mill-fire",
                                      "claim": "Mira was seen leaving the mill.", "source": "a rider", "confidence": 0.5})
        asked = self.data(self.do("now they look", {"action": "heat", "area": "Market", "faction": "Tollmen",
                                                    "fact": "mill-fire", "delta": 2}))
        self.assertTrue(asked["may_question"])
        self.assertFalse(asked["may_seek_arrest"])                          # hearsay is not enough for a warrant
        hot = self.data(self.do("more comes in", {"action": "belief", "holder": "faction:Tollmen", "fact": "mill-fire",
                                                  "claim": "Mira was seen leaving the mill.", "source": "Bren's testimony",
                                                  "confidence": 0.9},
                                {"action": "heat", "area": "Market", "faction": "Tollmen", "fact": "mill-fire", "delta": 2}))
        self.assertTrue(hot["may_seek_arrest"])
        self.assertIsNone(self.thing("heat", "millbridge|Tollmen"))          # heat is local: nothing in the next town
        known = self.data(self.do("why are they doing this?", {"action": "knows", "holder": "faction:Tollmen"}))["beliefs"]
        self.assertEqual([(b["fact"], b["source"]) for b in known], [("mill-fire", "Bren's testimony")])   # their reasons, with sources


if __name__ == "__main__":
    unittest.main()
