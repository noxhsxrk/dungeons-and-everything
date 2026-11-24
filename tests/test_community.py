"""A community that keeps itself alive: Hollow-9 run for 30 days with no players, three times from one save.
Normal, the mechanic gone, spare parts stocked beforehand. Each run must say who did what, why they could,
and what it left in the world."""
from __future__ import annotations

import json
import pathlib
import shutil
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _engine_case import EngineCase  # noqa: E402

import community  # noqa: E402,F401  (registers its actions and its day)

AT = "The Ford"          # the party stands in Millbridge: these are runs with no players


class CommunityTests(EngineCase):
    def setUp(self):
        super().setUp()
        self.do("setup", {"action": "settlement", "at": AT, "template": "hollow-9"})
        self.turn.finish("oldworld", "Hollow-9 goes on.")

    def run_month(self, campaign="oldworld"):
        self.do("a month passes", {"action": "wait", "days": 30}, campaign=campaign)
        return self.data(self.do("report", {"action": "community", "at": AT, "since_day": 0}, campaign=campaign))

    def first(self, rows, who=None, did=""):
        hits = [r for r in rows if (who is None or r["who"] == who) and did in r["did"]]
        return hits[0] if hits else None

    def test_three_runs_from_one_save(self):
        for name in ("nomech", "parts"):
            shutil.copytree(self.camp, self.root / "campaigns" / name)
        self.do("Jonas is called away", {"action": "settlement", "at": AT, "workers": {"Jonas": {"away": True}}},
                campaign="nomech")
        self.do("spares bought last season", {"action": "settlement", "at": AT, "stores": {"parts": 4}}, campaign="parts")
        a, b, c = self.run_month(), self.run_month("nomech"), self.run_month("parts")
        ra, rb, rc = a["chronicle"], b["chronicle"], c["chronicle"]

        # Normal: the mechanic sees it coming, the council puts the harvest first, the filter fails, the pump is
        # stripped to save the air, water runs short, the neighbour trades parts for the cart.
        asked = self.first(ra, "Jonas", "asked to stop the main air filter")
        self.assertIn("38%", asked["why"])
        delayed = self.first(ra, "Maren", "delayed stopping")
        self.assertIn("harvest is due", delayed["why"])
        failed = self.first(ra, "main air filter", "failed")
        self.assertGreater(failed["day"], delayed["day"])
        stripped = self.first(ra, "Jonas", "pulled 2 parts from the water pump")
        self.assertIn("comes before the water pump", stripped["why"])
        self.assertIn("water pump is stopped", stripped["left"])
        rota = self.first(ra, "Maren", "set a water rota")
        moved = self.first(ra, "3 households", "moved in with relatives")
        carried = self.first(ra, "Tomas", "began carrying water")
        self.assertIn("market gets its goods late", carried["left"])
        pact = self.first(ra, "Maren", "agreed a pact with Deepwell")
        self.assertLess(rota["day"], pact["day"])
        self.assertEqual(moved["day"], rota["day"])
        trained = self.first(ra, "Pim", "can now repair at level 2")
        self.assertIn("beside Jonas", trained["why"])
        # a month on, what the trouble made is still there
        self.assertIn("water", a["rota"])
        self.assertIn("Deepwell", a["pacts"])
        self.assertEqual(a["skills"]["Pim"]["repair"], 2)
        self.assertEqual(a["buffer"]["parts"], 2)
        self.assertTrue(all(x["status"] == "running" for x in a["assets"].values()))
        self.assertTrue(self.first(ra, "Tomas", "ran the cart for Deepwell"))

        # Mechanic gone: the apprentice takes over his rounds and his keys, covers the repair at half speed,
        # and his own hauling falls behind.
        self.assertIn("Jonas away", self.first(rb, "Pim", "took over the rounds on the main air filter")["why"])
        self.assertIn("Pim read it at 38%", self.first(rb, "Pim", "asked to stop")["why"])
        self.assertEqual(self.first(rb, "Pim", "holds the workshop keys")["day"], 1)
        fixed_b = self.first(rb, "Pim", "repaired the main air filter")
        self.assertIn("half speed", fixed_b["why"])
        self.assertIn("Jonas is away", self.first(rb, "Pim", "left their own work undone")["why"])
        self.assertTrue(self.first(rb, "grow-house", "lost its air"))
        self.assertIn("doing the work", self.first(rb, "Pim", "can now repair")["why"])
        fixed_a = self.first(ra, "Jonas", "repaired the main air filter")
        self.assertLess(fixed_a["day"], fixed_b["day"])
        self.assertGreater(a["stores"]["food"], b["stores"]["food"])      # the day without air cost food

        # Spares stocked: the same failure is fixed from the store; the conflicts after it never happen.
        fixed_c = self.first(rc, "Jonas", "repaired the main air filter")
        self.assertIn("from the store", fixed_c["why"])
        for did in ("pulled", "rota", "moved in", "pact", "carrying"):
            self.assertIsNone(self.first(rc, did=did), did)
        self.assertEqual(c["rota"], {})
        self.assertEqual(c["pacts"], {})
        self.assertEqual(c["moved_households"], 0)

        for row in ra + rb + rc:                     # every row answers who, did what, why
            self.assertTrue(row["who"] and row["did"] and row["why"], row)

    def test_an_appointment_elsewhere_takes_the_mechanic_away(self):
        self.do("Jonas has business at the market",
                {"action": "appointment", "id": "jonas-market", "npc": "Jonas", "from": AT, "place": "Market",
                 "in_minutes": 1500, "stays_minutes": 3000, "purpose": "buy filter cloth"})
        self.do("two days", {"action": "wait", "days": 2})
        rows = self.data(self.do("report", {"action": "community", "at": AT, "since_day": 0}))["chronicle"]
        self.assertIn("appointment jonas-market", self.first(rows, "Jonas", "is away")["why"])
        self.assertTrue(self.first(rows, "Pim", "took over the rounds"))   # someone else reads the machines
        self.assertTrue(self.first(rows, "Pim", "holds the workshop keys"))
        where = self.data(self.do("where is Pim", {"action": "where", "npc": "Pim"}))
        self.assertEqual((where["place"], where["why"]), ("ford", "works in Hollow-9"))

    def test_with_nobody_to_read_the_machines_the_failure_comes_unseen(self):
        self.do("all the mechanics are gone", {"action": "settlement", "at": AT, "workers": {
            "Jonas": {"away": True}, "Pim": {"away": True}, "Bo": {"away": True}}})
        self.do("two days", {"action": "wait", "days": 2})
        rows = self.data(self.do("report", {"action": "community", "at": AT, "since_day": 0}))["chronicle"]
        self.assertIn("nobody had seen it coming", self.first(rows, "main air filter", "failed")["why"])
        self.assertIn("no one present has repair", self.first(rows, "nobody", "could start on the main air filter")["why"])

    def test_an_approved_service_waits_for_parts_and_a_ruling_is_used_once(self):
        self.do("Jonas asks on day 1", {"action": "wait", "days": 1})
        self.do("the GM rules", {"action": "community_decide", "at": AT, "matter": "service:filter-main",
                                 "decision": "approve", "why": "the party will cover the grow-house"})
        s = self.thing("settlement", "ford")
        self.assertEqual(s["decisions"], {})
        self.assertEqual(s["assets"]["filter-main"]["status"], "running")    # no parts yet: it keeps going

    def test_a_month_at_once_equals_a_month_of_days(self):
        shutil.copytree(self.camp, self.root / "campaigns" / "daily")
        self.do("a month", {"action": "wait", "days": 30})
        for _ in range(30):
            self.do("a day", {"action": "wait", "days": 1}, campaign="daily")
        self.assertEqual(self.wdb.state_hash("oldworld", ("events", "things")),
                         self.wdb.state_hash("daily", ("events", "things")))

    def test_no_seal_holder_means_no_ruling(self):
        self.do("the council is away", {"action": "settlement", "at": AT,
                                        "workers": {"Maren": {"away": True}, "Ilse": {"away": True}}})
        self.do("a day", {"action": "wait", "days": 1})
        rows = self.data(self.do("report", {"action": "community", "at": AT, "since_day": 0}))["chronicle"]
        self.assertIn("no one present holds the council seal", self.first(rows, "nobody", "can rule")["why"])
        self.assertIsNone(self.first(rows, did="delayed"))

    def test_with_the_party_there_the_council_waits_for_them(self):
        m = self.read_json("world-map.json")
        m["party_location"] = "ford"
        (self.camp / "world-map.json").write_text(json.dumps(m), encoding="utf-8")
        out = self.do("a week", {"action": "wait", "days": 7})
        stop = [v for v in out["visible_events"] if v.get("type") == "community_matter"]
        self.assertEqual([v["matter"] for v in stop], ["service:filter-main"])
        self.assertTrue(out["results"][-1]["data"].get("interrupted") or stop[0]["interrupt"])
        self.assertEqual(self.thing("settlement", "ford")["day"], 1)          # time stopped on day 1
        self.do("[Mira]: shut it down, we'll pay for the harvest",
                {"action": "community_decide", "at": AT, "matter": "service:filter-main", "decision": "approve",
                 "why": "the party talked the council round"})
        self.do("a day", {"action": "wait", "days": 1})
        rows = self.data(self.do("report", {"action": "community", "at": AT, "since_day": 0}))["chronicle"]
        ok = self.first(rows, did="approved stopping the main air filter")
        self.assertIn("the GM's ruling: the party talked the council round", ok["why"])

    def test_arrival_line_tells_what_changed(self):
        import gm_guide
        self.do("a month", {"action": "wait", "days": 30})
        m = self.read_json("world-map.json")
        m["party_location"] = "ford"
        (self.camp / "world-map.json").write_text(json.dumps(m), encoding="utf-8")
        lines = [t for _p, t in gm_guide.turn_parts("oldworld", False, "we arrive")]
        self.assertTrue(any("HOLLOW-9 CHANGED" in t and "Deepwell" in t for t in lines), lines)

    def test_a_world_with_no_map_keys_it_by_name(self):
        (self.camp / "world-map.json").write_text("{}", encoding="utf-8")
        out = self.do("setup", {"action": "settlement", "at": "Hollow-9", "template": "hollow-9"})
        self.assertEqual(self.data(out)["settlement"], "hollow-9")
        self.do("two days", {"action": "wait", "days": 2})
        self.assertEqual(self.thing("settlement", "hollow-9")["day"], 2)

    def test_no_line_where_there_is_no_settlement(self):
        import community as cm
        self.assertEqual(cm._provider("oldworld", "hello", None), [])


if __name__ == "__main__":
    unittest.main()
