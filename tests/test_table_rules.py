"""Optional table rules borrowed from PbtA, GURPS and Pathfinder 2e (ideas only, own numbers).

Part A: the degree ladder, valued conditions, Victory Points, reaction rolls,
Treat Wounds, the treasure curve, Hero Points and Focus Points.
"""
from __future__ import annotations

import json
import re

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from test_playtest_round6 import SCRIPTS, _Camp  # noqa: E402,F401  (shared campaign fixture)

SHEET = ("# Mae\n## Combat Stats\n- **HP:** 5 / 20 | **Temp HP:** 0\n- **Hit Dice:** 2d8 (remaining: 2)\n"
         "- **Death Saves:** Successes: 0 | Failures: 0\n## Equipment & Inventory\n**Currency:** 5\n")


class DegreeLadderTests(_Camp):
    def test_ladder(self):
        import dice
        cases = [((10, 25, 15), "critical success"), ((10, 15, 15), "success"),
                 ((10, 12, 15), "success at a cost"), ((10, 11, 15), "success at a cost"),
                 ((10, 10, 15), "failure"), ((10, 5, 15), "critical failure"),
                 ((20, 14, 15), "success at a cost"),   # nat 20 steps a failure up one
                 ((20, 16, 15), "critical success"),    # ... and a success up one
                 ((1, 16, 15), "success at a cost"),    # nat 1 steps a success down one
                 ((1, 10, 15), "critical failure")]
        for (raw, total, dc), want in cases:
            self.assertEqual(dice.degree(raw, total, dc, "check"), want, (raw, total, dc))
        self.assertIsNone(dice.degree(20, 5, 15, "attack"))   # attacks keep 5e rules
        self.assertIsNone(dice.degree(20, 5, 10, "death"))

    def test_cli_prints_degree_without_crit_wording(self):
        r = self.run_py("dice.py", "d20+40", "--vs", "check", "--dc", "15")
        # a natural 1 (1 in 20) steps the critical success down to a plain success
        self.assertRegex(r.stdout, r"· critical success|\(natural 1\)[\s\S]*· success")
        self.assertNotIn("CRITICAL HIT", r.stdout)   # the display flashes on that text


class ValuedConditionTests(_Camp):
    def test_value_decay_and_penalty(self):
        import tracker
        add = lambda *a: self.run_py("tracker.py", "-c", "eden", "condition", "add", *a)
        self.assertEqual(add("Bob", "frightened", "2", "--decay", "--penalty", "attack,save,check").returncode, 0)
        import os
        old = os.environ.get("DNE_CAMPAIGN_ROOT")
        os.environ["DNE_CAMPAIGN_ROOT"] = str(self.root)
        try:
            self.assertEqual(tracker.active_modifiers("eden", "Bob", "save"), [("frightened 2", "-2")])
            self.assertEqual(tracker.active_modifiers("eden", "Bob", "damage"), [])
        finally:
            if old is None:
                os.environ.pop("DNE_CAMPAIGN_ROOT")
            else:
                os.environ["DNE_CAMPAIGN_ROOT"] = old
        add("Bob", "frightened", "1")                       # a lower value never lowers it
        self.assertIn("frightened 2", self.run_py("tracker.py", "-c", "eden", "status").stdout)
        self.run_py("tracker.py", "-c", "eden", "effect", "tick", "Bob")
        self.assertIn("frightened 1", self.run_py("tracker.py", "-c", "eden", "status").stdout)
        self.run_py("tracker.py", "-c", "eden", "effect", "tick", "Bob")
        self.assertNotIn("frightened", self.run_py("tracker.py", "-c", "eden", "status").stdout)


class VictoryPointTests(_Camp):
    def vp(self, *a):
        return self.run_py("subsystem.py", "-c", "eden", *a)

    def test_points_goal_and_limit(self):
        self.assertEqual(self.vp("start", "Chase", "--goal", "4", "--limit", "3").returncode, 0)
        self.assertIn("2/4", self.vp("check", "Chase", "--degree", "critical-success").stdout)
        self.assertIn("2/4", self.vp("check", "Chase", "--degree", "failure").stdout)
        out = self.vp("check", "Chase", "--total", "9", "--dc", "15").stdout   # 9 vs 15 → failure
        self.assertIn("OUT OF TIME", out)
        self.assertTrue((self.camp / "subsystems.json").exists())
        import turn_snapshot
        self.assertIn("subsystems.json", turn_snapshot.CAMPAIGN_FILES)

    def test_complete_and_floor(self):
        self.vp("start", "Heist", "--goal", "2")
        self.assertIn("0/2", self.vp("check", "Heist", "--degree", "critical-failure").stdout)   # never below 0
        self.vp("check", "Heist", "--degree", "success")
        self.assertIn("COMPLETE", self.vp("check", "Heist", "--degree", "success at a cost").stdout)
        self.assertIn("Heist", self.vp("status").stdout)
        self.vp("end", "Heist")
        self.assertNotIn("Heist", self.vp("status").stdout)


class ReactionRollTests(_Camp):
    def test_bands_and_apply(self):
        (self.camp / "npcs.md").write_text(
            "| Name | Role | Attitude | Notes |\n|---|---|---|---|\n| Vell | fixer | neutral | x |\n", encoding="utf-8")
        r = self.run_py("reaction.py", "-c", "eden", "--roll", "4,3", "--cha-mod", "2", "--status-diff", "1")
        self.assertIn("10", r.stdout)
        self.assertIn("friendly", r.stdout)
        for roll, band in (("1,1", "hostile"), ("2,2", "unfriendly"), ("3,4", "indifferent"), ("6,6", "helpful")):
            self.assertIn(band, self.run_py("reaction.py", "-c", "eden", "--roll", roll).stdout)
        self.run_py("reaction.py", "-c", "eden", "--roll", "1,1", "--npc", "Vell", "--apply")
        self.assertIn("| Vell | fixer | hostile |", (self.camp / "npcs.md").read_text(encoding="utf-8"))


class TreatWoundsTests(_Camp):
    def setUp(self):
        super().setUp()
        self.sheet = self.camp / "characters" / "mae.md"
        self.sheet.write_text(SHEET, encoding="utf-8")

    def treat(self, *a):
        return self.run_py("economy.py", "-c", "eden", "treat", "--char", "Mae", *a)

    def test_heals_by_degree_and_caps(self):
        r = self.treat("--total", "16", "--heal", "9")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("**HP:** 14 / 20", self.sheet.read_text(encoding="utf-8"))
        r = self.treat("--total", "30", "--heal", "40", "--force")   # crit; capped at max
        self.assertIn("**HP:** 20 / 20", self.sheet.read_text(encoding="utf-8"))

    def test_failure_heals_nothing_and_zero_hp_refused(self):
        self.treat("--total", "9", "--heal", "9")
        self.assertIn("**HP:** 5 / 20", self.sheet.read_text(encoding="utf-8"))
        self.sheet.write_text(SHEET.replace("5 / 20", "0 / 20"), encoding="utf-8")
        self.assertEqual(self.treat("--total", "20", "--heal", "5").returncode, 1)

    def test_once_per_hour_with_calendar(self):
        self.run_py("calendar.py", "-c", "eden", "init", "--date", "1 Frostfall 1000", "--time", "morning",
                    "--months", "Frostfall,Thaw", "--month-length", "30", "--day-names", "A,B,C,D,E,F,G")
        self.assertEqual(self.treat("--total", "16", "--heal", "3").returncode, 0)
        again = self.treat("--total", "16", "--heal", "3")
        self.assertEqual(again.returncode, 1)
        self.assertIn("hour", (again.stdout + again.stderr).lower())
        self.run_py("calendar.py", "-c", "eden", "advance", "1", "hour")
        self.assertEqual(self.treat("--total", "16", "--heal", "3").returncode, 0)


class TreasureTests(_Camp):
    def test_curve_shape(self):
        import economy
        prev = None
        for lvl in range(1, 20):
            b = economy.treasure_budget(lvl, 4, 7)
            self.assertGreater(b["per_encounter"], 0)
            if prev:
                self.assertGreater(b["wealth_per_char"], prev["wealth_per_char"])
                self.assertGreaterEqual(b["per_encounter"], prev["per_encounter"])
            prev = b
        out = self.run_py("economy.py", "-c", "eden", "treasure", "--level", "3", "--party", "4").stdout
        self.assertIn("house", out.lower())


class HeroFocusPointTests(_Camp):
    def setUp(self):
        super().setUp()
        self.sheet = self.camp / "characters" / "mae.md"
        self.sheet.write_text(SHEET, encoding="utf-8")

    def ch(self, *a):
        return self.run_py("character.py", *a, "--char", "Mae", "-c", "eden")

    def text(self):
        return self.sheet.read_text(encoding="utf-8")

    def test_hero_points(self):
        self.assertEqual(self.ch("hero", "reset").returncode, 0)
        self.assertIn("**Hero Points:** 1 / 3", self.text())
        for _ in range(4):
            self.ch("hero", "award")
        self.assertIn("**Hero Points:** 3 / 3", self.text())
        self.ch("hero", "use")
        self.assertIn("**Hero Points:** 2 / 3", self.text())
        self.sheet.write_text(self.text().replace("5 / 20", "0 / 20").replace("Failures: 0", "Failures: 2"),
                              encoding="utf-8")
        r = self.ch("hero", "recover")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("**Hero Points:** 0 / 3", self.text())
        self.assertIn("Successes: 0 | Failures: 0", self.text())
        self.assertEqual(self.ch("hero", "use").returncode, 1)

    def test_focus_points_and_rests(self):
        self.assertEqual(self.ch("focus", "reset", "--max", "2").returncode, 0)
        self.ch("focus", "use")
        self.ch("focus", "use")
        self.assertIn("**Focus Points:** 0 / 2", self.text())
        self.assertEqual(self.ch("focus", "use").returncode, 1)
        self.run_py("economy.py", "-c", "eden", "rest", "--char", "Mae", "--type", "short", "--hit-dice", "0")
        self.assertIn("**Focus Points:** 1 / 2", self.text())
        self.run_py("economy.py", "-c", "eden", "rest", "--char", "Mae", "--type", "long")
        self.assertIn("**Focus Points:** 2 / 2", self.text())
