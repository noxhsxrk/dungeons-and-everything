"""World plan PR 12: supplies, season and weather. Running short stops the party while there is still a
choice to make, a long skip and the same days one at a time leave the same stores, and a campaign that
never turned survival on plays as it always did."""
from __future__ import annotations

import json
import pathlib
import shutil
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _engine_case import EngineCase  # noqa: E402

CLIMATE = {"climate": {
    "seasons": [{"name": "summer", "months": [5, 6, 7], "travel": 1.0, "light_hours": 14, "supplies": {"water": 2},
                 "weather": [["clear", 1]]},
                {"name": "winter", "months": [12, 1, 2], "travel": 1.5, "light_hours": 8, "supplies": {"fuel": 2},
                 "weather": [["fog", 1]]}],
    "weather": {"fog": {"travel": 1.2, "sight_feet": 30}}}}
STORES = {"action": "upkeep", "stores": {"food": 20, "water": 40, "coin": 500, "ammo": 12},
          "per_day": {"food": 2, "water": 1.5, "coin": 20}, "warn_days": 2}


class UpkeepTests(EngineCase):
    FLAGS = EngineCase.FLAGS + "- survival: on\n"

    def stores(self, campaign="oldworld"):
        return self.thing("upkeep", "party", campaign)["stores"]

    def set_month(self, month):
        cal = self.read_json("calendar.json")
        cal["month"] = month
        (self.camp / "calendar.json").write_text(json.dumps(cal), encoding="utf-8")

    def test_a_campaign_that_never_turned_it_on_is_unchanged(self):
        self.flags(EngineCase.FLAGS)
        refused = self.data(self.do("supplies?", STORES))
        self.assertIn("survival is off", refused["error"])
        out = self.do("a week passes", {"action": "wait", "days": 7})
        self.assertIsNone(self.thing("upkeep", "party"))
        self.assertFalse([v for v in out["visible_events"] if v["type"].startswith("upkeep")])
        legs = self.data(self.do("travel time as ever", {"action": "travel", "to": "The Ford"}))
        self.assertEqual(legs["journey"], "arrived")

    def test_a_long_skip_and_the_same_days_one_by_one_leave_the_same_stores(self):
        (self.camp / "worldkit.json").write_text(json.dumps(CLIMATE), encoding="utf-8")
        self.set_month(6)                                              # summer: water goes twice as fast
        self.do("pack up", {**STORES, "stores": {"food": 200, "water": 400, "coin": 5000, "ammo": 12}})
        self.turn.finish("oldworld", "Packed.")
        shutil.copytree(self.camp, self.root / "campaigns" / "daily")
        self.do("twenty-three days at once", {"action": "wait", "days": 23, "hours": 7})
        for _ in range(23):
            self.do("a day", {"action": "wait", "days": 1}, campaign="daily")
            self.turn.finish("daily", ".")
        self.do("and seven hours", {"action": "wait", "hours": 7}, campaign="daily")
        self.assertEqual(self.stores(), self.stores("daily"))
        self.assertEqual(self.stores()["food"], 200 - 46)             # 2 a day for 23 days and a bit
        self.assertEqual(self.stores()["water"], 400 - 69)            # 1.5 a day, doubled by the summer: 3 a day
        self.assertEqual(self.stores()["ammo"], 12)                   # no rate: only spent by hand

    def test_running_short_stops_the_journey_while_there_is_still_a_choice(self):
        self.do("pack light", {**STORES, "stores": {"food": 5, "water": 40, "coin": 500}})
        out = self.do("[Mira]: we walk to the market", {"action": "travel", "to": "Market"})     # a full day's walk
        self.assertEqual(out["status"], "waiting_for_player")
        self.assertIn("food for about 2.0 more days", out["next_input"]["question"])
        self.assertGreater(self.stores()["food"], 0)                  # warned with food still in the pack
        self.assertEqual(self.read_json("world-map.json")["party_location"], "millbridge")
        self.assertLess(out["elapsed_minutes"], 1440)
        done = self.turn.answer("oldworld", out["next_input"]["request_id"], "back")
        self.assertEqual(self.read_json("world-map.json")["party_location"], "millbridge")
        self.assertEqual(self.data(done)["journey"], "arrived")

    def test_it_says_so_again_when_a_store_is_gone(self):
        self.do("pack almost nothing", {**STORES, "stores": {"food": 3, "water": 40, "coin": 500}, "warn_days": 1})
        first = self.do("we wait", {"action": "wait", "days": 3})
        self.assertTrue(any(v["type"] == "upkeep_low" for v in first["visible_events"]))
        second = self.do("we keep waiting", {"action": "wait", "days": 3})
        self.assertTrue(any(v["type"] == "upkeep_out" and "food has run out" in v["text"] for v in second["visible_events"]))
        self.assertEqual(self.stores()["food"], 0)

    def test_buying_supplies_moves_the_warning(self):
        self.do("pack light", {**STORES, "stores": {"food": 5, "water": 40, "coin": 500}})
        self.do("[Mira]: we buy food first", {"action": "supply", "item": "food", "qty": 20})
        out = self.do("we walk to the market", {"action": "travel", "to": "Market"})
        self.assertEqual(out["status"], "open")                       # plenty now: nothing stops them
        self.assertEqual(self.read_json("world-map.json")["party_location"], "market")

    def test_spending_by_the_piece(self):
        self.do("pack", STORES)
        self.assertEqual(self.data(self.do("three shots", {"action": "use", "item": "ammo", "qty": 3}))["left"], 9)
        short = self.data(self.do("a long burst", {"action": "use", "item": "ammo", "qty": 30}))
        self.assertIn("only 9 ammo left", short["error"])

    def test_season_and_weather_slow_the_road_and_shorten_sight(self):
        (self.camp / "worldkit.json").write_text(json.dumps(CLIMATE), encoding="utf-8")
        summer = self.do("a summer walk", {"action": "travel", "to": "The Ford"})["elapsed_minutes"]
        self.assertEqual(summer, 720)
        self.do("walk back", {"action": "travel", "to": "Millbridge"})
        self.set_month(1)
        winter = self.do("the same walk in a winter fog", {"action": "travel", "to": "The Ford"})["elapsed_minutes"]
        self.assertEqual(winter, round(720 * 1.5 * 1.2))
        now = self.data(self.do("?", {"action": "conditions"}))
        self.assertEqual((now["season"], now["weather"], now["sight_feet"]), ("winter", "fog", 30))
        (self.camp / "battlemap.json").write_text(json.dumps({"width": 20, "height": 10, "terrain": {}, "tokens": []}), encoding="utf-8")
        self.do("shapes in the fog",
                {"action": "fight", "objective": "get past"},
                {"action": "combatant", "name": "Mira", "kind": "pc", "side": "party", "x": 1, "y": 5, "hp": "20/20"},
                {"action": "combatant", "name": "Near", "kind": "enemy", "side": "enemy", "x": 5, "y": 5, "hp": "9/9", "range": 120},
                {"action": "combatant", "name": "Far", "kind": "enemy", "side": "enemy", "x": 15, "y": 5, "hp": "9/9", "range": 120})
        self.assertEqual([t["name"] for t in self.data(self.do("?", {"action": "advise", "enemy": "Near"}))["can_target"]], ["Mira"])
        self.assertEqual(self.data(self.do("?", {"action": "advise", "enemy": "Far"}))["cannot_see"], ["Mira"])   # 70 ft of fog

    def test_an_overloaded_party_is_slow(self):
        self.do("pack far too much", {**STORES, "carry": {"limit": 300, "load": 420}})
        out = self.do("we walk to the ford", {"action": "travel", "to": "The Ford"})
        self.assertEqual(out["elapsed_minutes"], 1080)                # half as long again

    def test_a_market_makes_restocks_and_charges_for_what_was_carried_in(self):
        self.do("the market", {"action": "market", "at": "Market", "stock": {"bread": 2, "salt": 0}, "base": {"bread": 4, "salt": 10},
                               "target": {"bread": 10, "salt": 10}, "cash": 100, "eats": {"bread": 3}, "makes": {"bread": 5},
                               "restock": {"salt": {"every_days": 2, "amount": 6}}, "when_broke": "credit"},
                {"action": "caravan", "id": "spice", "from": "Millbridge", "to": "Market", "goods": {"salt": 20}, "transport": 3})
        self.do("four days", {"action": "wait", "days": 4})
        market = self.thing("market", "market")
        self.assertEqual(market["stock"]["bread"], 2 + 4 * (5 - 3))   # baked and eaten every day
        self.assertEqual(market["stock"]["salt"], 20 + 12)            # the caravan's twenty and two deliveries
        self.assertGreater(market["owes"], 0)                         # it could not pay for all twenty: the rest is on account
        import trade
        each, why = trade.price(market, "salt")
        self.assertIn("+ 3 cp transport", why)

    def test_rationing_when_stock_is_low(self):
        self.do("a lean market", {"action": "market", "at": "Millbridge", "stock": {"flour": 2}, "base": {"flour": 5},
                                  "target": {"flour": 20}, "cash": 100, "when_out": "ration"})
        (self.camp / "characters" / "mira.md").write_text("# Mira\n- **Level:** 3\n\n## Equipment & Inventory\n**Currency:** 5 gp\n", encoding="utf-8")
        two = self.data(self.do("[Mira]: two sacks", {"actor": "Mira", "action": "buy", "item": "flour", "qty": 2, "at": "Millbridge"}))
        self.assertIn("rationed", two["error"])
        one = self.data(self.do("[Mira]: one, then", {"actor": "Mira", "action": "buy", "item": "flour", "qty": 1, "at": "Millbridge"}))
        self.assertEqual(one["bought"], 1)


if __name__ == "__main__":
    unittest.main()
