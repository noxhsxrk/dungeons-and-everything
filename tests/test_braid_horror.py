"""Braid PR 4, the horror and mystery modules: composure, panic, doom, clues, make_the_case.

Acceptance (plan §5 PR 4): 1000 cases generated from seeds pass the 95%-solvable check (re-checked here with fresh
trials, not the generator's own), and a scripted cosmic-horror game (core + composure + clues) plays one whole case,
from the first search to the accusation, through engine turns."""
from __future__ import annotations

import copy
import json
import pathlib
import re
import statistics
import sys
import unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _engine_case import EngineCase  # noqa: E402
from test_braid_seam import stamp  # noqa: E402
from test_braid_rules import MIRA, THEO, SEED, BraidCampaign, leaks, no_5e  # noqa: E402

import turn  # noqa: E402,F401  (the engine first)
import modules  # noqa: E402
import story_gen  # noqa: E402

FLAGS = "- display: none\n- roll_mode: players\n- world_engine: on\n- modules: {}\n"


class Module(EngineCase):
    MODULES = "composure, panic, doom"
    FLAGS = FLAGS.format(MODULES)

    def setUp(self):
        super().setUp()
        stamp(self.camp, "core")

    def turn_with(self, text, *intents, answers=()):
        r = self.do(text, *intents)
        for a in answers:
            self.assertEqual(r["status"], "waiting_for_player", r)
            r = self.turn.answer("oldworld", r["next_input"]["request_id"], a)
        self.turn.finish("oldworld", "ok")
        return r

    def fright(self, rating, die=None, **extra):
        return self.data(self.turn_with("fright", {"action": "fright", "actor": "Mira", "rating": rating,
                                                   "spec": "2d6+0", "what": f"{rating} {die}", **extra},
                                        answers=[die] if die else []))


class Composure(Module):
    MODULES = "composure"
    FLAGS = FLAGS.format("composure")

    def test_a_miss_costs_the_rating_and_a_hit_costs_nothing(self):
        d = self.fright("serious", "5")                           # failure: -2
        self.assertEqual((d["degree"], d["lost"], d["composure"]), ("failure", 2, 8))
        self.assertEqual(self.fright("minor", "6")["lost"], 1)     # 7
        self.assertEqual(self.fright("overwhelming", "10")["lost"], 0)
        self.assertEqual(self.fright("overwhelming", "8")["lost"], 0)   # 7-9 holds: the GM names a cost
        d = self.fright("overwhelming", "3")                       # critical failure: 3 + 1
        self.assertEqual((d["lost"], d["composure"]), (4, 3))
        self.assertNotIn("spec", d)

    def test_thresholds_roll_the_module_tables_and_haunted_comes_and_goes(self):
        tables = modules.load("composure")["tables"]
        d = self.fright("overwhelming", "3")                       # 10 → 6: Rattled
        self.assertEqual([c["at"] for c in d["crossed"]], [6])
        self.assertIn(d["crossed"][0]["result"], tables["reactions"])
        d = self.fright("serious", "4")                            # 6 → 4
        self.assertEqual(d["crossed"], [])
        d = self.fright("minor", "5")                              # 4 → 3: Haunted
        self.assertIn(d["crossed"][0]["result"], tables["fears"])
        self.assertEqual(self.thing("condition", "mira/haunted")["approaches"], ["wits", "heart"])
        r = self.turn_with("rest", {"action": "track", "owner": "Mira", "id": "composure", "mark": 1, "why": "a quiet scene"})
        self.assertEqual(self.data(r)["value"], 4)
        self.assertIsNone(self.thing("condition", "mira/haunted"))
        d = self.fright("overwhelming", "2")                       # 4 → 0: Broken
        self.assertEqual(([c["at"] for c in d["crossed"]], d["composure"]), ([3, 0], 0))
        self.assertIn("Broken", d["crossed"][1]["note"])

    def test_heart_and_conditions_from_the_usual_check_and_a_token_cannot_reach_back(self):
        self.turn_with("setup", {"action": "condition", "owner": "Mira", "name": "Shaken", "mod": -1, "approaches": ["heart"]},
                       {"action": "pool", "owner": "Mira", "id": "tokens", "max": 3, "set": 1})
        r = self.do("fright", {"action": "fright", "actor": "Mira", "rating": "minor", "spec": "2d6+1", "push": True})
        self.assertIn("2d6+1", r["next_input"]["question"])          # +1, Shaken -1, push +1
        r = self.turn.answer("oldworld", r["next_input"]["request_id"], "5")
        d = self.data(r)
        self.assertEqual((d["total"], d["lost"]), (6, 1))
        self.assertEqual(self.thing("track", "mira/stress")["value"], 1)
        self.assertEqual(self.thing("track", "mira/composure")["value"], 9)     # once, though the handler ran twice
        self.turn.finish("oldworld", "ok")
        r = self.turn_with("token", {"action": "pool", "owner": "Mira", "id": "tokens", "step_up": True})
        self.assertIn("error", self.data(r))

    def test_refused_when_off_and_under_5e(self):
        self.flags("- world_engine: on\n- roll_mode: players\n")
        self.assertIn("not switched on", self.fright("minor")["error"])
        self.flags(FLAGS.format("composure"))
        state = self.camp / "state.md"
        state.write_text(state.read_text(encoding="utf-8").replace("**System:** core", "**System:** d20"), encoding="utf-8")
        self.assertIn("Braid module", self.fright("minor")["error"])

    def test_story_mode_asks_the_oracle_with_odds_from_the_rating(self):
        state = self.camp / "state.md"
        state.write_text(state.read_text(encoding="utf-8").replace("**System:** core", "**System:** story"), encoding="utf-8")
        r = self.do("fright", {"action": "fright", "actor": "Mira", "rating": "overwhelming"})
        d = self.data(r)
        self.assertEqual(d["likelihood"], "unlikely")
        self.assertEqual(d["lost"], {"failure": 3, "critical failure": 4}.get(d["degree"], 0))


class Panic(Module):
    MODULES = "panic"
    FLAGS = FLAGS.format("panic")

    def test_shared_stress_rolls_the_panic_tables_and_keeps_the_breaking_point(self):
        tables = modules.load("panic")["tables"]
        self.turn_with("apply", {"action": "modules", "apply": True})
        self.turn_with("push", {"action": "roll", "actor": "Mira", "spec": "2d6+0", "push": True}, answers=["8"])
        self.assertEqual(self.thing("track", "mira/stress")["value"], 1)              # a push marks the same track
        d = self.data(self.turn_with("shock", {"action": "track", "owner": "Mira", "id": "stress", "mark": 2, "why": "lights out"}))
        self.assertEqual([c["at"] for c in d["crossed"]], [3])
        self.assertIn(d["crossed"][0]["result"], tables["jitters"])
        d = self.data(self.turn_with("it's here", {"action": "track", "owner": "Mira", "id": "stress", "mark": 3, "why": "in the room"}))
        crossed = {c["at"]: c for c in d["crossed"]}
        self.assertEqual(sorted(crossed), [5, 6])
        self.assertIn(crossed[5]["result"], tables["panic"])
        self.assertIn("Breaking point", crossed[6]["note"])


class Doom(Module):
    MODULES = "doom"
    FLAGS = "- display: none\n- roll_mode: auto\n- world_engine: on\n- modules: doom\n"

    def test_every_check_adds_and_the_script_checks(self):
        r = self.turn_with("roll", {"action": "roll", "actor": "Mira", "spec": "2d6+1", "label": "climb"})
        d = self.data(r)["doom"]
        self.assertEqual(d["die"], "d20")
        self.assertEqual(d["rolled"] <= 1, d["disaster"] is not None)
        self.assertEqual(self.thing("track", "party/doom")["value"], 1)          # 1, or a disaster's floor of 1
        self.assertEqual("floor" in d, d["disaster"] is not None)
        r = self.turn_with("damage", {"action": "roll", "actor": "Mira", "spec": "1d6"})       # not a check: no doom
        self.assertNotIn("doom", self.data(r))

    def test_never_at_zero_always_at_the_top_and_the_floor_rises(self):
        for n in range(30):
            d = self.data(self.turn_with("nothing", {"action": "doom", "add": 0, "why": f"calm {n}"}))
            self.assertIsNone(d["disaster"])
        self.turn_with("set", {"action": "track", "owner": "party", "id": "doom", "set": 19})
        for floor in (1, 2):
            if floor == 2:
                self.turn_with("set", {"action": "track", "owner": "party", "id": "doom", "set": 20, "why": "again"})
            d = self.data(self.turn_with("risk", {"action": "doom", "add": 1, "why": f"risk {floor}"}))
            self.assertIn(d["disaster"], modules.load("doom")["tables"]["disasters"])
            self.assertEqual((d["doom"], d["floor"]), (floor, floor))
        self.assertEqual(self.thing("track", "party/doom")["min"], 2)

    def test_nothing_when_off(self):
        self.flags("- world_engine: on\n- roll_mode: auto\n")
        self.assertIn("not switched on", self.data(self.turn_with("x", {"action": "doom", "add": 1}))["error"])
        r = self.turn_with("roll", {"action": "roll", "actor": "Mira", "spec": "2d6+1"})
        self.assertNotIn("doom", self.data(r))


def written(case: dict) -> dict:
    """The GM's clue texts: plain things seen, never what they prove."""
    for n, c in enumerate(case["clues"], 1):
        c["text"] = f"Thing {n} seen at {c['where']}."
    return case


class Clues(Module):
    MODULES = "clues"
    FLAGS = "- display: none\n- roll_mode: auto\n- world_engine: on\n- modules: clues\n"

    def skeleton(self, seed=7, write=True) -> dict:
        skel = story_gen.generate(["mystery"], seed=seed, record=False)
        if write:
            written(skel["threads"][0]["case"])
        (self.camp / "story-skeleton.json").write_text(json.dumps(skel), encoding="utf-8")
        return skel["threads"][0]["case"]

    def test_case_from_a_skeleton_runs_the_validator(self):
        case = self.skeleton(write=False)
        d = self.data(self.turn_with("case", {"action": "case", "skeleton": True}))
        self.assertGreaterEqual(d["solve_rate"], 0.95)
        self.assertEqual(len(d["unwritten"]), len(case["clues"]))           # stand-ins listed for the GM to write
        stored = self.thing("case", case["id"])
        self.assertEqual((stored["culprit"], stored["places"]), (case["culprit"], case["places"]))

    def test_an_unsolvable_case_is_refused_unless_forced(self):
        case = self.skeleton()
        cut = [c for c in case["clues"] if c.get("leads") != case["places"][1]]     # nothing leads to the 2nd place
        broken = {**case, "id": "broken", "clues": cut}
        d = self.data(self.turn_with("case", {"action": "case", **broken}))
        self.assertIn("cannot be solved", d["error"])
        self.assertIn("cannot be reached", d["error"])
        self.assertIsNone(self.thing("case", "broken"))
        d = self.data(self.turn_with("case", {"action": "case", **broken, "force": True}))
        self.assertTrue(d["warnings"])
        self.assertIsNotNone(self.thing("case", "broken"))

    def test_a_case_without_places_is_as_before(self):
        d = self.data(self.turn_with("case", {"action": "case", "id": "ledger", "truth": "t",
                                               "clues": [{"id": "ink", "text": "ink", "where": "office"}]}))
        self.assertEqual(d, {"case": "ledger", "clues": 1})

    def test_core_clues_without_a_roll_leads_shown_and_secrets_kept(self):
        case = self.skeleton()
        self.turn_with("case", {"action": "case", "skeleton": True})
        start = case["places"][0]
        r = self.turn_with("look", {"action": "search", "actor": "Mira", "case": case["id"], "where": start})
        d = self.data(r)
        core = [c["id"] for c in case["clues"] if c["where"] == start and c["obvious"]]
        self.assertTrue(core)
        self.assertEqual(sorted(f["id"] for f in d["found"]) , sorted(core))           # no roll: the core clues only
        self.assertIsNone(d["roll_helped"])
        leads = [c["leads"] for c in case["clues"] if c["id"] in core and c.get("leads") and c["leads"] != start]
        told = json.dumps(r, ensure_ascii=False)
        for place in leads:
            self.assertIn(f"This points to {place}.", told)
        roles = [s["role"] for s in case["suspects"]]
        for secret in ["proves", "clears:", "culprit", "suspects", *roles]:
            self.assertNotIn(secret, told)


class MakeTheCase(Module):
    MODULES = "make_the_case"
    FLAGS = FLAGS.format("make_the_case")
    CLUES = [{"id": f"c{n}", "text": f"odd thing {n}", "where": "lighthouse", "obvious": True} for n in range(1, 6)]

    def open_case(self):
        return self.turn_with("case", {"action": "case", "id": "light", "open": True, "complexity": 4, "clues": self.CLUES})

    def test_no_hidden_answer_from_the_start(self):
        r = self.open_case()
        self.assertIn("no hidden answer", json.dumps(r["visible_events"]))
        self.assertTrue(self.thing("case", "light")["open"])
        self.assertIn("error", self.data(self.turn_with("t", {"action": "case", "id": "light", "truth": "the keeper"})))
        self.assertIn("error", self.data(self.turn_with("o", {"action": "case", "id": "light", "open": False})))
        d = self.data(self.turn_with("a", {"action": "accuse", "actor": "Mira", "case": "light", "claim": "the keeper"}))
        self.assertIn("make_the_case", d["note"])

    def test_found_clues_count_and_a_case_that_holds_becomes_the_truth(self):
        self.open_case()
        self.turn_with("look", {"action": "search", "actor": "Mira", "case": "light", "where": "lighthouse"})
        self.turn_with("more", {"action": "case", "id": "light", "clues": [{"id": "c9", "text": "x", "where": "cellar"}]})
        r = self.do("theory", {"action": "make_the_case", "actor": "Mira", "case": "light", "spec": "2d6+1",
                               "theory": "The keeper faked his drowning.", "explains": ["c1", "c2", "c3", "c9"]})
        self.assertIn("2d6 (send", r["next_input"]["question"])     # +1 + 3 found clues − complexity 4 = +0
        r = self.turn.answer("oldworld", r["next_input"]["request_id"], "8")
        d = self.data(r)
        self.turn.finish("oldworld", "ok")
        self.assertEqual((d["explains"], d["not_counted"], d["degree"], d["holds"]), (["c1", "c2", "c3"], ["c9"], "success at a cost", True))
        self.assertEqual(self.thing("case", "light")["truth"], "The keeper faked his drowning.")
        again = self.data(self.turn_with("again", {"action": "make_the_case", "actor": "Mira", "case": "light", "spec": "2d6+1",
                                                   "theory": "Someone else.", "explains": ["c1"]}))
        self.assertIn("already settled", again["error"])

    def test_a_case_that_fails_leaves_no_truth(self):
        self.open_case()
        self.turn_with("look", {"action": "search", "actor": "Mira", "case": "light", "where": "lighthouse"})
        d = self.data(self.turn_with("theory", {"action": "make_the_case", "actor": "Mira", "case": "light", "spec": "2d6+0",
                                                "theory": "Ghosts.", "explains": ["c1"]}, answers=["7"]))   # 7 − 3 = 4
        self.assertEqual((d["total"], d["holds"]), (4, False))
        self.assertEqual(self.thing("case", "light")["truth"], "")
        self.assertEqual(len(self.thing("case", "light")["theories"]), 1)

    def test_fixed_cases_and_unfound_clues_are_refused(self):
        self.open_case()
        d = self.data(self.turn_with("theory", {"action": "make_the_case", "actor": "Mira", "case": "light", "spec": "2d6",
                                                "theory": "x", "explains": ["c1"]}))
        self.assertIn("at least one clue the party has found", d["error"])
        self.turn_with("fixed", {"action": "case", "id": "fixed", "truth": "t", "clues": self.CLUES})
        d = self.data(self.turn_with("theory", {"action": "make_the_case", "actor": "Mira", "case": "fixed", "spec": "2d6",
                                                "theory": "x", "explains": ["c1"]}))
        self.assertIn("fixed answer", d["error"])


class ThousandCases(unittest.TestCase):
    """Plan §5 PR 4 'passes when': 1000 cases built from seeds by the story generator, each solvable in 95% of games
    with a third of the clues missed. The generator checks (and repairs) on its own trial seed; this re-checks every
    case on a fresh one, so the figure is not the generator grading itself. Reading of 95%: every case passes as
    generated; on fresh trials at least 99% of cases still reach 95% (sampling noise is about ±0.6 points)."""

    def test_1000_seeded_cases(self):
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            saved = os.environ.get("DNE_CAMPAIGN_ROOT")
            os.environ["DNE_CAMPAIGN_ROOT"] = tmp            # empty history: nothing recorded, nothing read
            try:
                rates, generated_ok = [], 0
                for seed in range(1000):
                    skel = story_gen.generate(["mystery"], seed=seed, record=False)
                    generated_ok += skel["checked"]["ok"]
                    case = skel["threads"][0]["case"]
                    rep = story_gen.check_case(copy.deepcopy(case), f"acceptance-{seed}")
                    self.assertEqual([p for p in rep["problems"] if p[0] != "fragile"], [], seed)
                    rates.append(rep["solve_rate"])
            finally:
                os.environ.pop("DNE_CAMPAIGN_ROOT") if saved is None else os.environ.__setitem__("DNE_CAMPAIGN_ROOT", saved)
        self.assertEqual(generated_ok, 1000)
        self.assertGreaterEqual(sum(r >= 0.95 for r in rates), 990)
        self.assertGreaterEqual(statistics.mean(rates), 0.97)
        self.assertGreaterEqual(min(rates), 0.93)


class CosmicHorror(BraidCampaign):
    """A whole case, scripted: a core campaign with composure and clues, two investigators made with sheet.py, a case
    from the story generator, every place searched by following only what the searches told the players, frights on
    the way, and the accusation. Nothing 5e is touched or printed."""

    def test_one_case_from_the_first_search_to_the_accusation(self):
        with no_5e() as used:
            self.build(flags={**SEED["flags"], "modules": "composure, clues"})
            self.assertEqual(self.sheet(*MIRA), 0)
            self.assertEqual(self.sheet(*THEO), 0)
            camp = self.root / "campaigns" / "braid"
            self.assertEqual(story_gen.main(["-c", "braid", "skeleton", "--genre", "mystery,horror", "--seed", "1926"]), 0)
            skel = json.loads((camp / "story-skeleton.json").read_text(encoding="utf-8"))
            case = written(skel["threads"][0]["case"])                     # the GM writes every clue
            (camp / "story-skeleton.json").write_text(json.dumps(skel), encoding="utf-8")
            self.assertEqual(story_gen.main(["-c", "braid", "check"]), 0)
            ladder = [s["text"] for s in skel["threads"][1]["ladder"]]

            r = self.turn_with("the letter from the coast", {"action": "modules", "apply": True},
                               {"action": "case", "skeleton": True})
            self.assertEqual(sorted(self.data(r, 0)["pcs"]), ["Mira Vale", "Theo"])
            self.assertEqual(self.data(r)["unwritten"], [])
            self.assertEqual(self.thing("track", "theo/composure")["value"], 10)

            # Search: every place the players have heard of, until nothing new is pointed to. A careful search
            # (Wits, the player's dice 10) turns up the hidden clues too.
            known, todo, found, who = set(), [case["places"][0]], set(), ["Mira Vale", "Theo"]
            while todo:
                place = todo.pop(0)
                known.add(place)
                actor = who[len(known) % 2]
                r = self.turn_with(f"[{actor}]: I search {place}",
                                   {"action": "search", "actor": actor, "case": case["id"], "where": place,
                                    "roll": {"approach": "wits"}}, answers=["10"])
                d = self.data(r)
                self.assertTrue(d["roll_helped"])
                found |= {f["id"] for f in d["found"]}
                for place_named in re.findall(r"This points to (.+?)\.\)", " ".join(f["text"] for f in d["found"])):
                    if place_named not in known and place_named not in todo:
                        todo.append(place_named)
                r = self.turn_with(f"[{actor}]: I tell the others", {"action": "tell", "actor": actor,
                                                                      "to": [w for w in who if w != actor],
                                                                      "fact": f"clue:{d['found'][0]['id']}"} if d["found"] else
                                   {"action": "ask"})
                if len(known) <= len(ladder):                                 # the horror climbs, a step per place
                    r = self.turn_with(f"[GM]: {ladder[len(known) - 1]}",
                                       {"action": "fright", "actor": "Theo", "rating": "serious",
                                        "what": ladder[len(known) - 1]}, answers=["4"])
                    self.assertEqual(self.data(r)["degree"], "failure")       # 4 + Heart 2 = 6
            self.assertEqual(known, set(case["places"]))
            self.assertEqual(found, {c["id"] for c in case["clues"]})

            theo = self.thing("track", "theo/composure")
            self.assertEqual(theo["value"], 10 - 2 * min(len(ladder), len(case["places"])))
            if theo["value"] <= 6:
                self.assertTrue(any(e.get("crossed") for e in theo["log"]))   # the threshold fired and was rolled

            # The players can now name the culprit: who, how and why are all reached with what they found.
            missed, _ = story_gen._solved([c for c in case["clues"] if c["id"] in found], case["places"][0],
                                          [s["id"] for s in case["suspects"] if s["id"] != case["culprit"]])
            self.assertEqual(missed, [])
            culprit = next(s for s in case["suspects"] if s["id"] == case["culprit"])
            r = self.turn_with("[Mira Vale]: it was them", {"action": "accuse", "actor": "Mira Vale", "case": case["id"],
                                                             "claim": f"The {culprit['role']} did it."})
            d = self.data(r)
            self.assertEqual(d["culprit_for_the_gm"]["role"], culprit["role"])
            self.assertIn(culprit["role"], d["recorded"]["claim"])
            self.assertEqual(len(self.thing("case", case["id"])["accusations"]), 1)
        self.assertEqual(used, [])
        self.assertEqual(leaks("\n".join(self.out)), [])


if __name__ == "__main__":
    unittest.main()
