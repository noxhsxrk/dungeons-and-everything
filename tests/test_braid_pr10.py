"""Braid PR 10: what three AI-GM playtests found — story rolls, player answers, refusals, the build check, the save
checklist, the ruleset lookup, version check/audit, flashback cost, search pacing, the combat gate, sheet show."""
from __future__ import annotations

import contextlib
import io
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _engine_case import SCRIPTS, EngineCase  # noqa: E402
from test_braid_rules import MIRA  # noqa: E402
from test_braid_seam import stamp  # noqa: E402

import turn  # noqa: E402,F401

LADDER = ("critical failure", "failure", "success at a cost", "success", "critical success")
CASE = {"action": "case", "id": "ledger", "truth": "the clerk took it",
        "clues": [{"id": "a", "where": "office", "text": "A torn page.", "obvious": True}]
        + [{"id": f"h{i}", "where": "office", "text": f"Hidden thing {i}.", "obvious": False} for i in range(5)]}


class StoryRolls(EngineCase):
    FLAGS = "- display: none\n- roll_mode: players\n- world_engine: on\n"

    def test_a_roll_with_no_likelihood_asks_the_oracle_and_nobody(self):
        stamp(self.camp, "story")
        for intent in ({"actor": "Mira", "action": "roll", "label": "probe"},
                       {"actor": "Mira", "action": "roll", "approach": "heart", "label": "probe heart"},
                       {"actor": "Mira", "action": "roll", "spec": "1d20", "label": "a d20 by habit"}):
            r = self.do("x", intent)
            self.assertIsNone(r["next_input"], intent)            # story never asks for dice
            d = self.data(r)
            self.assertIn(d["degree"], LADDER)
            self.assertEqual(d["likelihood"], "50/50")            # no sheet: 50/50
            self.assertIn(d["answer"], ("yes-and", "yes", "yes-but", "no-but", "no", "no-and"))
            self.turn.finish("oldworld", "ok")

    def test_a_table_die_still_rolls_but_is_never_asked(self):
        stamp(self.camp, "story")
        r = self.do("x", {"actor": "Mira", "action": "roll", "spec": "1d6", "label": "which door"})
        self.assertIsNone(r["next_input"])
        self.assertTrue(1 <= self.data(r)["total"] <= 6)


class PlayerAnswers(EngineCase):
    FLAGS = "- display: none\n- roll_mode: players\n- world_engine: on\n"

    def test_an_impossible_sum_is_refused_and_the_question_stays_open(self):
        stamp(self.camp, "core")
        r = self.do("x", {"actor": "Mira", "action": "roll", "spec": "2d6+2", "label": "rally"})
        rid = r["next_input"]["request_id"]
        for bad in (15, 1, "lots"):
            out = self.turn.answer("oldworld", rid, bad)
            self.assertEqual(out["status"], "refused", bad)
            self.assertIn("2 to 12", out["error"])
        self.assertEqual(self.turn.status("oldworld")["next_input"]["request_id"], rid)
        out = self.turn.answer("oldworld", rid, 7)
        self.assertEqual(self.data(out)["total"], 9)

    def test_judge_and_search_requests_carry_the_range_too(self):
        stamp(self.camp, "core")
        r = self.do("x", CASE, {"actor": "Theo", "action": "search", "case": "ledger", "where": "office",
                                "roll": {"spec": "2d6"}})
        self.assertEqual(self.turn.answer("oldworld", r["next_input"]["request_id"], 13)["status"], "refused")

    def test_d20_answers_are_not_range_checked(self):          # 5e unchanged
        r = self.do("x", {"actor": "Mira", "action": "roll", "spec": "1d20+3", "dc": 12, "label": "Stealth"})
        out = self.turn.answer("oldworld", r["next_input"]["request_id"], 10)
        self.assertEqual(self.data(out)["total"], 13)


class Refusals(EngineCase):
    def test_a_braid_refusal_is_marked_and_listed(self):
        stamp(self.camp, "core")
        r = self.do("x", {"actor": "Mira", "action": "roll", "spec": "1d20+5", "dc": 13})
        self.assertEqual(r["results"][0]["status"], "refused")
        self.assertIn("2d6", r["refused"][0]["error"])
        self.assertEqual(self.turn.finish("oldworld", "ok")["status"], "finished")   # the turn still closes

    def test_a_d20_refusal_reads_as_before(self):
        r = self.do("x", {"actor": "Mira", "action": "search", "case": "nope", "where": "office"})
        self.assertEqual(r["results"][0]["status"], "done")
        self.assertNotIn("refused", r)


class FlashbackAndSearch(EngineCase):
    def test_a_braid_flashback_costs_one_stress_or_a_token(self):
        stamp(self.camp, "core")
        r = self.do("x", {"actor": "Mira", "action": "flashback", "claim": "I oiled the door",
                          "roll": {"spec": "2d6+1", "label": "oil"}})
        self.assertEqual(self.data(r)["cost"], "1 stress")
        self.assertEqual(self.thing("track", "mira/stress")["value"], 1)
        self.turn.finish("oldworld", "ok")
        r = self.do("y", {"actor": "Mira", "action": "flashback", "claim": "I paid the guard", "cost": "token"})
        self.assertEqual(r["results"][0]["status"], "refused")          # no tokens yet
        self.turn.finish("oldworld", "ok")
        self.do("z", {"action": "pool", "owner": "Mira", "id": "tokens", "max": 3, "set": 1},
                {"actor": "Mira", "action": "flashback", "claim": "I paid the guard", "cost": "token"})
        self.assertEqual(self.thing("pool", "mira/tokens")["value"], 0)
        self.assertEqual(self.thing("track", "mira/stress")["value"], 1)

    def test_one_search_turns_up_hidden_clues_by_degree(self):
        stamp(self.camp, "core")
        r = self.do("x", CASE, {"actor": "Theo", "action": "search", "case": "ledger", "where": "office",
                                "roll": {"spec": "2d6+10", "push": True}})
        d = self.data(r)
        self.assertEqual(d["check"]["degree"], "critical success")
        self.assertIn("+1 (pushed)", d["check"]["stress"])
        self.assertEqual(len(d["found"]), 1 + 3)                          # the plain clue + 3 hidden
        self.turn.finish("oldworld", "ok")
        r = self.do("y", {"actor": "Theo", "action": "search", "case": "ledger", "where": "office",
                          "roll": {"spec": "2d6+10"}})
        self.assertEqual({f["id"] for f in self.data(r)["found"]} >= {"h3", "h4"}, True)

    def test_d20_search_finds_every_hidden_clue_as_before(self):
        r = self.do("x", CASE, {"actor": "Theo", "action": "search", "case": "ledger", "where": "office",
                                "roll": {"spec": "1d20+30", "dc": 10}})
        self.assertEqual(len(self.data(r)["found"]), 6)
        self.assertNotIn("check", self.data(r))


class BuiltWorld(unittest.TestCase):
    """A Braid world fresh from campaign_init: check and build agree, and the save tools tell the truth about it."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)
        (self.root / "rt").mkdir()
        self.env = {**os.environ, "DNE_CAMPAIGN_ROOT": str(self.root), "DNE_RUNTIME_DIR": str(self.root / "rt"),
                    "DNE_DISPLAY_HOST": "127.0.0.1:9", "PYTHONIOENCODING": "utf-8"}
        self.seed = {"seed_version": 1, "campaign": "monsoon", "system": "core", "flags": {"display": "none"},
                     "calendar": {"date": "14 September 2026", "time": "dusk", "gregorian": True,
                                  "months": ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.",
                                             "ต.ค.", "พ.ย.", "ธ.ค."]}}

    def tearDown(self):
        self._tmp.cleanup()

    def py(self, script, *args, stdin=None):
        r = subprocess.run([sys.executable, str(SCRIPTS / script), *args], input=stdin, capture_output=True,
                           encoding="utf-8", env=self.env)
        return r.returncode, r.stdout + r.stderr

    def build(self, seed=None, check=False):
        code, out = self.py("campaign_init.py", "--seed", "-", *(["--check"] if check else []),
                            stdin=json.dumps(seed or self.seed))
        return json.loads(out)

    def test_check_and_build_agree_on_the_calendar(self):
        bad = {**self.seed, "calendar": {"date": "1 Thaw 412", "time": "teatime"}}
        res = self.build(bad, check=True)
        self.assertFalse(res["ok"])
        self.assertIn("Valid labels", res["errors"][0]["error"])
        self.assertTrue(self.build(check=True)["ok"])                      # dusk + English month with local names
        self.assertTrue(self.build()["ok"])
        cal = json.loads((self.root / "campaigns" / "monsoon" / "calendar.json").read_text(encoding="utf-8"))
        self.assertEqual((cal["day"], cal["month"], cal["hour"]), (14, 9, 19))     # dusk = evening

    def test_a_fresh_world_is_not_saved_and_says_so_in_braid_words(self):
        self.assertTrue(self.build()["ok"])
        marker = json.loads((self.root / "rt" / "active-campaign.json").read_text(encoding="utf-8"))
        self.assertEqual(marker["name"], "monsoon")
        code, out = self.py("save_check.py", "-c", "monsoon")
        self.assertEqual(code, 0, out)
        for row in ("☐ session-log.md", "☐ state.md: Current Situation", "☐ state.md → Live State Flags",
                    "☐ calendar.json", "☐ world.md"):
            self.assertIn(row, out)
        self.assertIn("harm, stress, tokens", out)
        self.assertNotIn("Inspiration", out)
        state = (self.root / "campaigns" / "monsoon" / "state.md").read_text(encoding="utf-8")
        for flag in ("show_dc", "hero_points", "degrees", "when_down", "success_at_cost"):
            self.assertNotIn(f"- {flag}:", state)
        world = (self.root / "campaigns" / "monsoon" / "world.md").read_text(encoding="utf-8")
        self.assertNotIn("5e spells", world)

    def test_a_template_session_log_never_ticks(self):
        self.assertTrue(self.build()["ok"])
        camp = self.root / "campaigns" / "monsoon"
        time.sleep(0.01)
        (camp / "session-log.md").write_text((camp / "session-log.md").read_text(encoding="utf-8") + "\n",
                                             encoding="utf-8")                      # touched, still the template
        self.assertIn("☐ session-log.md", self.py("save_check.py", "-c", "monsoon")[1])
        (camp / "session-log.md").write_text("# Log\n## Session 1 — 2026-11-26\nThey found the body.\n", encoding="utf-8")
        self.assertIn("✓ session-log.md", self.py("save_check.py", "-c", "monsoon")[1])

    def test_ruleset_version_and_combat_gate(self):
        self.assertTrue(self.build()["ok"])
        self.assertEqual(self.py("paths.py", "campaign-ruleset", "monsoon")[1].strip(), "not-applicable (system: core)")
        self.assertIn("up to date", self.py("campaign_version.py", "-c", "monsoon", "check")[1])
        self.assertIn("Nothing to change", self.py("campaign_version.py", "-c", "monsoon", "audit")[1])
        code, out = self.py("combat.py", "init", '[{"name": "Gareth", "hp": 9, "ac": 10}]')   # no -c: the active world
        self.assertEqual(code, 2, out)
        self.assertIn("5e (d20) rules", out)

    def test_sheet_show_lists_every_engine_track(self):
        self.assertTrue(self.build()["ok"])
        self.assertEqual(self.py("sheet.py", "-c", "monsoon", *MIRA)[0], 0)
        code, out = self.py("turn.py", "-c", "monsoon", "begin", "--text", "x")
        self.assertEqual(code, 0, out)
        code, out = self.py("turn.py", "-c", "monsoon", "resolve", "--intents", json.dumps([
            {"action": "track", "owner": "Mira Vale", "id": "composure", "min": 0, "max": 10, "set": 8},
            {"action": "pool", "owner": "Mira Vale", "id": "tokens", "max": 3, "set": 2}]))
        self.assertEqual(code, 0, out)
        out = self.py("sheet.py", "-c", "monsoon", "show", "Mira Vale")[1]
        self.assertIn("Composure 8/10", out)
        self.assertIn("Tokens 2/3", out)


if __name__ == "__main__":
    unittest.main()
