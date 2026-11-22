"""Round 5: the 2024 (SRD 5.2) paths, from the Perihelion acceptance run."""
from __future__ import annotations

import copy
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "skills" / "dne" / "scripts"
DATA24 = ROOT / "skills" / "dne" / "data" / "dnd5e_srd_2024.json"
FIXTURE = ROOT / "tests" / "fixtures" / "worldkit-eden.json"
KIT = json.loads(FIXTURE.read_text(encoding="utf-8"))
sys.path.insert(0, str(SCRIPTS))


def run(script, *args, env=None):
    return subprocess.run([sys.executable, str(SCRIPTS / script), *args], capture_output=True,
                          encoding="utf-8", env=env or os.environ)


class _Camp24(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)
        self.camp = self.root / "campaigns" / "peri"
        (self.camp / "characters").mkdir(parents=True)
        (self.camp / "state.md").write_text("**Ruleset:** 2024\n", encoding="utf-8")
        kit = copy.deepcopy(KIT)
        kit["_meta"]["base_ruleset"] = "2024"
        (self.camp / "worldkit.json").write_text(json.dumps(kit), encoding="utf-8")
        self.env = {**os.environ, "DNE_CAMPAIGN_ROOT": str(self.root),
                    "DNE_RUNTIME_DIR": str(self.root / ".rt"), "DNE_DICE_PHYSICAL": "0"}

    def tearDown(self):
        self._tmp.cleanup()


class Lookup2024Tests(unittest.TestCase):
    def test_class_options_fall_back_to_2014(self):
        for args, needle in ((("invocation", "agonizing blast"), "Agonizing Blast"),
                             (("pact-boon", "pact of the tome"), "Tome"),
                             (("fighting-style", "defense"), "Defense")):
            r = run("lookup.py", *args, "--ruleset", "2024")
            self.assertEqual(r.returncode, 0, (args, r.stdout))
            self.assertIn(needle, r.stdout)

    def test_mastery_without_ruleset_routes_to_2024(self):
        r = run("lookup.py", "mastery", "topple")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Topple", r.stdout)

    def test_item_prints_mastery_and_no_empty_brackets(self):
        r = run("lookup.py", "item", "longsword", "--ruleset", "2024")
        self.assertIn("Sap", r.stdout)
        self.assertNotIn("[]", r.stdout)
        self.assertNotIn("/? ft", r.stdout)


class Data2024Tests(unittest.TestCase):
    def test_weapons_carry_mastery_and_category(self):
        eq = {r["name"]: r for r in json.loads(DATA24.read_text(encoding="utf-8"))["equipment"]}
        self.assertEqual(eq["Longsword"].get("mastery"), "Sap")
        self.assertEqual(eq["Greataxe"].get("mastery"), "Cleave")
        self.assertTrue(eq["Longsword"].get("category"))


class Levelup2024Tests(_Camp24):
    def test_weapon_mastery_owed(self):
        r = run("character.py", "levelup", "-c", "peri", "--class", "Soldier", "--from", "0", "--con-mod", "1",
                env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(r.stdout, r"Weapon Mastery.*3")
        self.assertIn("Topple", r.stdout)                              # lists the properties

    def test_calc_prints_origin_feat(self):
        kit = json.loads((self.camp / "worldkit.json").read_text(encoding="utf-8"))
        kit["backgrounds"][1]["feat"] = "Alert"
        (self.camp / "worldkit.json").write_text(json.dumps(kit), encoding="utf-8")
        r = run("character.py", "calc", "-c", "peri", "--class", "Soldier", "--background", "Hollow Guard",
                "--background-asi", "STR=2,CON=1", "STR=15", "DEX=13", "CON=14", "INT=8", "WIS=12", "CHA=10",
                env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Origin feat: Alert", r.stdout)
        self.assertIn("Initiative: +3", r.stdout)                      # DEX +1, Alert adds proficiency +2


class Exhaustion2024Tests(_Camp24):
    def test_exhaustion_penalty_applies_to_d20_tests(self):
        run("tracker.py", "-c", "peri", "condition", "add", "Rook", "exhausted", env=self.env)
        run("tracker.py", "-c", "peri", "condition", "add", "Rook", "exhausted", env=self.env)
        import tracker
        os.environ["DNE_CAMPAIGN_ROOT"] = str(self.root)
        try:
            mods = tracker.active_modifiers("peri", "Rook", "attack")
        finally:
            os.environ.pop("DNE_CAMPAIGN_ROOT", None)
        self.assertIn(("Exhaustion 2", "-4"), mods)
        r = run("combat.py", "attack", "--atk", "5", "--ac", "10", "--dmg", "1d6", "--roll", "10",
                "--effects", "Rook", "-c", "peri", env=self.env)
        self.assertIn("Exhaustion 2", r.stdout)


class Worldkit2024Tests(unittest.TestCase):
    def kit24(self):
        k = copy.deepcopy(KIT)
        k["_meta"]["base_ruleset"] = "2024"
        return k

    def test_2024_spells_accepted_as_chassis(self):
        import worldkit
        k = self.kit24()
        k["spells"][1]["description"] = "Mark. (chassis: Hex)"     # SRD 5.2 has Hex
        self.assertFalse(any("Hex" in e for e in worldkit.validate(k)))

    def test_mastery_and_feat_fields_checked(self):
        import worldkit
        k = self.kit24()
        k["equipment"][0]["mastery"] = "Bogus"
        k["backgrounds"][0]["feat"] = "Lucky"
        errs = worldkit.validate(k)
        self.assertTrue(any("mastery" in e for e in errs), errs)
        self.assertTrue(any("feat" in e for e in errs), errs)


class Combat2024Tests(unittest.TestCase):
    def test_unknown_mastery_is_an_error(self):
        r = run("combat.py", "attack", "--atk", "5", "--ac", "1", "--roll", "15", "--dmg", "1d8", "--mastery", "bogus")
        self.assertEqual(r.returncode, 2)

    def test_mastery_refused_under_2014(self):
        r = run("combat.py", "attack", "--atk", "5", "--ac", "1", "--roll", "15", "--dmg", "1d8",
                "--mastery", "topple", "--ruleset", "2014")
        self.assertEqual(r.returncode, 2)

    def test_cleave_text_is_a_new_attack_roll(self):
        r = run("combat.py", "attack", "--atk", "5", "--ac", "1", "--roll", "15", "--dmg", "1d12+3",
                "--mastery", "cleave")
        self.assertNotIn("same roll", r.stdout)
        self.assertIn("attack roll", r.stdout.lower())


class Encounter2024Tests(_Camp24):
    def test_2024_budget_has_no_group_multiplier(self):
        r = run("encounter_gen.py", "-c", "peri", "--biome", "surface", "--party-level", "5", "--party-size", "4",
                "--difficulty", "medium", "--seed", "1", "--json", env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        enc = json.loads(r.stdout)
        self.assertEqual(enc["xp_budget"], 3000)                       # 2024 Moderate 750 × 4
        self.assertEqual(enc["adjusted_xp"], enc["raw_xp"])            # no multiplier in 2024


class EconomyPactLabelTests(unittest.TestCase):
    def test_pact_slot_row_with_label_suffix(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            camp = root / "campaigns" / "c"
            (camp / "characters").mkdir(parents=True)
            (camp / "state.md").write_text("**Ruleset:** 2014\n", encoding="utf-8")
            sheet = camp / "characters" / "wren.md"
            sheet.write_text("# Wren\n## Identity\n- **Class:** Listener (warlock chassis) | **Level:** 3\n"
                             "## Combat Stats\n- **HP:** 9 / 20 | **Temp HP:** 0\n- **Hit Dice:** 3d8 (remaining: 3)\n"
                             "## Spell Slots\n| Level | Total | Used |\n|---|---|---|\n| 2nd (pact) | 2 | 2 |\n"
                             "## Equipment & Inventory\n**Currency:** 5\n", encoding="utf-8")
            env = {**os.environ, "DNE_CAMPAIGN_ROOT": str(root), "DNE_RUNTIME_DIR": str(root / ".rt")}
            r = run("economy.py", "-c", "c", "rest", "--char", "wren", "--type", "short", env=env)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("| 2nd (pact) | 2 | 0 |", sheet.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
