"""Section 7 of the plan, played by script: the bridge at Millbridge (docs/world-engine-playtest.md).
One save; round A the party rests three days, round B the same save and the players open the bridge first,
round C the party splits and the turn waits for the one who has not decided. The human part of the playtest
(asking each player what they changed, timing the table) is still for a real table; this checks that every
round produces what those questions are about, through the engine alone."""
from __future__ import annotations

import pathlib
import shutil
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _engine_case import EngineCase  # noqa: E402

SETUP = [
    {"action": "route", "between": ["Millbridge", "The Ford"], "access": "closed", "owner": "Tollmen",
     "reason": "the Tollmen are deciding what to charge"},
    {"action": "market", "at": "Market", "stock": {"flour": 3}, "base": {"flour": 5}, "target": {"flour": 20},
     "cash": 500, "eats": {"flour": 1}},
    {"action": "caravan", "id": "flour", "from": "Millbridge", "to": "Market", "goods": {"flour": 20},
     "departs_in_minutes": 600, "owner": "Millers' Guild"},
    {"action": "fact", "id": "toll-talk", "text": "The Tollmen mean to charge a toll at the bridge.", "place": "Millbridge"},
    {"action": "remember", "id": "clerk-debt", "owner": "Mira", "kind": "bond", "tone": "either",
     "text": "The toll clerk owes Mira for getting his brother out of the cells.", "about": ["clerk", "toll"],
     "payoff": {"place": "Millbridge"}},
    {"action": "situation", "id": "the-bridge", "difficulty": "hard",
     "sides": [{"who": "Tollmen", "wants": "coin from every cart", "limit": "too few men to hold it against the Guild",
                "will_trade": "a quiet payment instead of a public toll"},
               {"who": "Millers' Guild", "wants": "the flour through today", "limit": "cannot be seen to pay",
                "will_trade": "a share of the mill's winter contract"}],
     "if_left_alone": "the bridge stays shut, the caravan waits, the market runs out in three days"},
    {"action": "notice", "scene": "the bridge office",
     "details": {"Theo": "The freight board says the flour caravan is due across at the tenth hour."}},
]


class BridgePlaytest(EngineCase):
    def setUp(self):
        super().setUp()
        (self.camp / "characters" / "theo.md").write_text(
            "# Theo\n- **Class:** Tinker | **Background:** Freight clerk | **Level:** 3\n", encoding="utf-8")
        self.do("the save all three rounds start from", *SETUP)
        self.turn.finish("oldworld", "Millbridge waits on its bridge.")
        for name in ("round-b", "round-c"):
            shutil.copytree(self.camp, self.root / "campaigns" / name)

    def test_round_a_the_world_moves_while_the_party_rests(self):
        out = self.do("[Mira]: we rest three days at the inn", {"action": "wait", "days": 3})
        self.turn.finish("oldworld", "Three quiet days.")
        kinds = [v["type"] for v in out["visible_events"]]
        self.assertIn("caravan_blocked", kinds)                       # evidence the party can find later
        self.assertIn("sold_out", kinds)
        caravan = self.thing("caravan", "flour")
        self.assertEqual(caravan["status"], "held")
        self.assertIn("deciding what to charge", caravan["log"][0]["reason"])   # traced back to its cause
        self.assertEqual(self.thing("market", "market")["stock"]["flour"], 0)
        self.assertIsNone(self.thing("belief", "place:market|toll-talk"))      # Market has not heard of the toll

    def test_round_b_the_players_open_the_bridge_and_live_in_another_world(self):
        self.do("[Mira]: I remind the clerk what he owes me; the Guild pays quietly",
                {"action": "route", "between": ["Millbridge", "The Ford"], "access": "open", "owner": "Tollmen",
                 "reason": "a quiet payment from the Guild"}, campaign="round-b")
        self.turn.finish("round-b", "The bar lifts before dawn.")
        self.do("three days", {"action": "wait", "days": 3}, campaign="round-b")
        self.do("three days", {"action": "wait", "days": 3})
        a_market, b_market = self.thing("market", "market"), self.thing("market", "market", campaign="round-b")
        self.assertEqual(self.thing("caravan", "flour", campaign="round-b")["status"], "arrived")
        self.assertGreater(b_market["stock"]["flour"], a_market["stock"]["flour"])
        import trade
        self.assertLess(trade.price(b_market, "flour")[0], trade.price(a_market, "flour")[0])
        with self.wdb.reader("round-b") as db:
            heard = [k for k in self.wdb.all_of(db, "belief") if "ford|millbridge" in k]
        self.assertTrue(heard)                                            # the road's state is news at its ends

    def test_round_c_the_party_splits_and_the_turn_waits_for_the_last_to_decide(self):
        out = self.do("[Mira]: I stall the Tollmen at the bridge while Theo does something",
                      {"action": "group", "id": "split", "goal": "get the flour across", "lead": "Mira",
                       "members": {"Mira": "keeps the toll captain talking about her old debt", "Theo": ""}},
                      campaign="round-c")
        self.assertEqual(out["status"], "waiting_for_player")
        self.assertEqual(out["next_input"]["expected"], "Theo")
        done = self.turn.answer("round-c", out["next_input"]["request_id"], "rides ahead to warn the Guild")
        self.assertTrue(self.data(done)["ready"])
        self.do("[Theo]: word goes to the Guild",
                {"action": "news", "fact": "toll-talk", "from": "Millbridge", "to": "faction:Millers' Guild",
                 "channel": "messenger"}, campaign="round-c")
        self.turn.finish("round-c", "Theo's horse is already on the road.")
        self.do("a day", {"action": "wait", "days": 1}, campaign="round-c")
        self.assertIsNotNone(self.thing("belief", "faction:Millers' Guild|toll-talk", campaign="round-c"))

    def test_the_numbers_the_playtest_asks_for(self):
        self.do("[Mira]: we rest", {"action": "wait", "days": 3})
        self.turn.finish("oldworld", "Rest.")
        m = self.turn.metrics("oldworld")
        self.assertEqual(m["turns_closed_through_the_runner"], m["turns"])
        self.assertEqual(m["turns_the_gm_narrated_around_the_runner"], 0)
        self.assertGreater(m["background_events_applied"], 0)
