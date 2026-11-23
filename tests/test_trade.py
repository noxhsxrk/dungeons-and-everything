"""World plan PR 6: a bridge, a caravan and a market. From one save, opening the bridge in time gets the
flour to market; leaving it shut empties the market. The last sack goes to exactly one buyer, and an undo
gives back the goods, the coin and the road together."""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
SCRIPTS = ROOT / "skills" / "dne" / "scripts"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(SCRIPTS))
import _old_campaign  # noqa: E402

SHEET = "# {name}\n- **Class:** Medic | **Level:** 3\n- **HP:** 20 / 20\n\n## Equipment & Inventory\n**Currency:** 1 gp\n"


class TradeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)
        self.rt = self.root / "rt"
        self.rt.mkdir()
        self.camp = _old_campaign.make(self.root)
        state = self.camp / "state.md"
        state.write_text(state.read_text(encoding="utf-8").split("## Session Flags")[0]
                         + "## Session Flags\n- display: none\n- roll_mode: auto\n- world_engine: on\n", encoding="utf-8")
        for name in ("Mira", "Theo"):
            (self.camp / "characters" / f"{name.lower()}.md").write_text(SHEET.format(name=name), encoding="utf-8")
        (self.camp / "world-map.json").write_text(json.dumps({
            "party_location": "market",
            "places": {k: {"name": n, "x": x, "y": 0, "biome": "plains", "kind": "town", "desc": "", "secret": "",
                           "hidden": False, "visited": True, "danger": 1}
                       for k, n, x in (("millbridge", "Millbridge", 0), ("market", "Market", 20))},
            "edges": [{"a": "millbridge", "b": "market", "road": True, "miles": 20.0, "kind": "bridge"}]}), encoding="utf-8")
        self._saved = {k: os.environ.get(k) for k in ("DNE_CAMPAIGN_ROOT", "DNE_RUNTIME_DIR", "DNE_OUTBOX_LOG")}
        os.environ.update(DNE_CAMPAIGN_ROOT=str(self.root), DNE_RUNTIME_DIR=str(self.rt), DNE_OUTBOX_LOG=str(self.root / "out.jsonl"))
        import scheduler
        import trade
        import turn
        import world_db
        self.s, self.turn, self.wdb, self.trade = scheduler, turn, world_db, trade
        # The save both runs start from: the Tollmen hold the bridge shut, the market is low on flour,
        # and a caravan with twenty sacks leaves Millbridge in ten hours.
        self.do("oldworld", "setup",
                {"action": "route", "between": ["Millbridge", "Market"], "access": "closed", "owner": "Tollmen",
                 "reason": "the Tollmen hold the bridge"},
                {"action": "market", "at": "Market", "stock": {"flour": 3}, "base": {"flour": 5}, "target": {"flour": 20},
                 "cash": 500, "eats": {"flour": 1}},
                {"action": "caravan", "id": "flour", "from": "Millbridge", "to": "Market", "goods": {"flour": 20},
                 "departs_in_minutes": 600, "owner": "Millers' Guild"})
        self.turn.finish("oldworld", "The market waits for flour.")

    def tearDown(self):
        for k, v in self._saved.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        self._tmp.cleanup()

    def do(self, campaign, text, *intents):
        self.turn.begin(campaign, text)
        return self.turn.resolve(campaign, list(intents))

    def thing(self, campaign, kind, id):
        with self.wdb.reader(campaign) as db:
            return self.wdb.get(db, kind, id)

    def coin(self, campaign="oldworld", who="mira"):
        import economy
        text = (self.root / "campaigns" / campaign / "characters" / f"{who}.md").read_text(encoding="utf-8")
        return economy._read_currency_cp(text)[0], text

    def test_from_one_save_the_bridge_decides_whether_the_market_eats(self):
        shutil.copytree(self.camp, self.root / "campaigns" / "late")
        # Run A: the party gets the bridge opened before the caravan needs it.
        self.do("oldworld", "[Mira]: we talk the Tollmen into opening the bridge",
                {"action": "route", "between": ["Millbridge", "Market"], "access": "open", "owner": "Millers' Guild"})
        a = self.do("oldworld", "three days pass", {"action": "wait", "days": 3})
        # Run B: the same save, and nobody does anything about the bridge.
        b = self.do("late", "three days pass", {"action": "wait", "days": 3})

        arrived = [v for v in a["visible_events"] if v["type"] == "caravan_arrived"]
        self.assertEqual(len(arrived), 1)
        self.assertEqual(arrived[0]["recipient"], "party")              # the party is in the market and sees it roll in
        self.assertEqual(arrived[0]["sold"]["flour"]["qty"], 20)
        self.assertIn("cp base", arrived[0]["sold"]["flour"]["why"])    # the price can be traced
        market_a, market_b = self.thing("oldworld", "market", "market"), self.thing("late", "market", "market")
        self.assertGreater(market_a["stock"]["flour"], 15)
        self.assertLess(market_a["cash"], 500)                          # the market paid for it

        self.assertEqual(market_b["stock"]["flour"], 0)                 # three sacks, three days, no delivery
        self.assertEqual(self.thing("late", "caravan", "flour")["status"], "held")
        self.assertEqual(self.thing("late", "caravan", "flour")["goods"]["flour"], 20)
        texts_b = [v["text"] for v in b["visible_events"]]
        self.assertTrue(any("has run out of flour" in t for t in texts_b))
        self.assertTrue(any("finds the way" in t and "the Tollmen hold the bridge" in t for t in texts_b))
        self.assertGreater(self.trade.price(market_b, "flour")[0], self.trade.price(market_a, "flour")[0])

    def test_a_held_caravan_goes_on_when_the_road_opens(self):
        self.do("oldworld", "a day passes", {"action": "wait", "days": 1})
        self.assertEqual(self.thing("oldworld", "caravan", "flour")["status"], "held")
        self.do("oldworld", "[Mira]: we open the bridge",
                {"action": "route", "between": ["Millbridge", "Market"], "access": "open"})
        self.do("oldworld", "two days pass", {"action": "wait", "days": 2})
        self.assertEqual(self.thing("oldworld", "caravan", "flour")["status"], "arrived")

    def test_a_caravan_takes_another_road_when_there_is_one(self):
        m = json.loads((self.camp / "world-map.json").read_text(encoding="utf-8"))
        m["places"]["ford"] = {"name": "The Ford", "x": 10, "y": 15, "biome": "plains", "kind": "landmark", "desc": "",
                               "secret": "", "hidden": False, "visited": False, "danger": 1}
        m["edges"] += [{"a": "millbridge", "b": "ford", "road": True, "miles": 18.0},
                       {"a": "ford", "b": "market", "road": True, "miles": 18.0}]
        (self.camp / "world-map.json").write_text(json.dumps(m), encoding="utf-8")
        out = self.do("oldworld", "four days pass", {"action": "wait", "days": 4})
        types = [v["type"] for v in out["visible_events"]]
        self.assertLess(types.index("caravan_blocked"), types.index("caravan_rerouted"))
        self.assertIn("caravan_arrived", types)
        self.assertEqual(self.thing("oldworld", "caravan", "flour")["knows_closed"], [["market", "millbridge"]])

    def test_the_last_sack_goes_to_one_buyer(self):
        self.do("oldworld", "stock runs down", {"action": "market", "at": "Market", "stock": {"flour": 1}})
        out = self.do("oldworld", "[Mira] and [Theo] both reach for the last sack",
                      {"actor": "Mira", "action": "buy", "item": "flour", "qty": 1, "at": "Market"},
                      {"actor": "Theo", "action": "buy", "item": "flour", "qty": 1, "at": "Market"})
        bought = [r["data"].get("bought") for r in out["results"]]
        self.assertEqual(sorted(bought), [0, 1])
        self.assertIn("sold out", [r["data"].get("error", "") for r in out["results"] if not r["data"].get("bought")][0])
        self.assertEqual(self.thing("oldworld", "market", "market")["stock"]["flour"], 0)
        self.assertIn("- flour", self.coin(who="mira")[1])
        self.assertNotIn("- flour", self.coin(who="theo")[1])
        self.assertEqual(self.coin(who="theo")[0], 100)                 # the one who lost paid nothing

    def test_two_processes_after_the_last_sack(self):
        self.do("oldworld", "stock runs down", {"action": "market", "at": "Market", "stock": {"flour": 1}})
        self.turn.finish("oldworld", "One sack left.")
        self.turn.begin("oldworld", "both buy at once")
        code = ("import sys, json; sys.path.insert(0, %r); import turn\n"
                "out = turn.resolve('oldworld', [{'actor': sys.argv[1], 'action': 'buy', 'item': 'flour', 'qty': 1, 'at': 'Market'}])\n"
                "print(json.dumps([r['data'].get('bought') for r in out['results'] if r['data'].get('actor') == sys.argv[1] "
                "or 'error' in r['data']]))\n") % str(SCRIPTS)
        procs = [subprocess.Popen([sys.executable, "-c", code, who], stdout=subprocess.PIPE, encoding="utf-8", env=dict(os.environ))
                 for who in ("Mira", "Theo")]
        for p in procs:
            p.communicate(timeout=60)
        self.assertEqual(self.thing("oldworld", "market", "market")["stock"]["flour"], 0)
        owners = [w for w in ("mira", "theo") if "- flour" in self.coin(who=w)[1]]
        self.assertEqual(len(owners), 1)                                # one sack, one owner

    def test_undo_gives_back_the_goods_the_coin_and_the_road_together(self):
        self.do("oldworld", "[Mira]: I buy flour and we have the bridge opened",
                {"actor": "Mira", "action": "buy", "item": "flour", "qty": 2, "at": "Market"},
                {"action": "route", "between": ["Millbridge", "Market"], "access": "open"})
        self.assertEqual(self.thing("oldworld", "market", "market")["stock"]["flour"], 1)
        self.assertLess(self.coin()[0], 100)
        self.assertEqual(self.thing("oldworld", "route", "market|millbridge")["access"], "open")
        r = subprocess.run([sys.executable, str(SCRIPTS / "turn_snapshot.py"), "-c", "oldworld", "undo", "--no-display"],
                           capture_output=True, encoding="utf-8", env=dict(os.environ), timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.thing("oldworld", "market", "market")["stock"]["flour"], 3)
        self.assertEqual(self.coin()[0], 100)
        self.assertNotIn("- flour", self.coin()[1])
        self.assertEqual(self.thing("oldworld", "route", "market|millbridge")["access"], "closed")

    def test_selling_and_the_price_reason(self):
        self.do("oldworld", "[Mira]: I buy two", {"actor": "Mira", "action": "buy", "item": "flour", "qty": 2, "at": "Market"})
        out = self.do("oldworld", "[Mira]: I sell one back", {"actor": "Mira", "action": "sell", "item": "flour", "qty": 1, "at": "Market"})
        deal = out["results"][-1]["data"]
        self.assertEqual(deal["sold"], 1)
        self.assertIn("half of", deal["why"])
        quote = self.do("oldworld", "what does flour cost?", {"action": "market", "at": "Market"})["results"][-1]["data"]["prices"]["flour"]
        self.assertEqual(quote["in_stock"], 2)
        self.assertRegex(quote["why"], r"5 cp base × \d\.\d \(2 in stock, 20 wanted\)")

    def test_a_toll_stops_the_party_to_decide(self):
        self.do("oldworld", "the bridge goes to toll", {"action": "route", "between": ["Millbridge", "Market"],
                                                        "access": "toll", "toll": "2 sp a head", "owner": "Tollmen"})
        out = self.do("oldworld", "[Mira]: we cross to Millbridge", {"action": "travel", "to": "Millbridge"})
        self.assertEqual(out["status"], "waiting_for_player")
        self.assertIn("Tollmen asks a toll of 2 sp a head", out["next_input"]["question"])
        done = self.turn.answer("oldworld", out["next_input"]["request_id"], "continue")
        self.assertEqual(done["results"][0]["data"]["journey"], "arrived")

    def test_a_factions_finished_goal_takes_the_road_if_it_can_afford_to(self):
        factions = json.loads((self.camp / "factions.json").read_text(encoding="utf-8"))
        tollmen = factions["factions"]["Tollmen"]
        tollmen.update(progress=6, clock=6, on_success={"type": "route", "between": ["Millbridge", "Market"],
                                                         "owner": "Tollmen", "access": "toll", "toll": "5 sp",
                                                         "requires": {"force": 3}, "cost": {"wealth": 1}})
        factions["factions"]["Millers' Guild"].update(progress=6, clock=6, on_success={
            "type": "route", "between": ["Millbridge", "Market"], "owner": "Millers' Guild", "access": "open",
            "requires": {"force": 5}})
        (self.camp / "factions.json").write_text(json.dumps(factions), encoding="utf-8")
        out = self.do("oldworld", "a week passes", {"action": "wait", "days": 8})
        after = json.loads((self.camp / "factions.json").read_text(encoding="utf-8"))["factions"]
        route = self.thing("oldworld", "route", "market|millbridge")
        self.assertEqual((route["owner"], route["access"], route["toll"]), ("Tollmen", "toll", "5 sp"))
        self.assertEqual(after["Tollmen"]["wealth"], 3)                 # it paid for the men on the bridge
        self.assertIn("lacks force", after["Millers' Guild"]["on_success_result"])   # too weak: nothing changed for them
        self.assertTrue(any(v["type"] == "route_changed" for v in out["visible_events"]))


if __name__ == "__main__":
    unittest.main()
