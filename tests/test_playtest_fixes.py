"""Regressions from the five /dne new play-test sessions (neon-krung, perihelion,
iron-hymn, himmapan, cedar-falls). Each class pins one reported defect.
"""
from __future__ import annotations

import copy
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "skills" / "dne" / "scripts"
FIXTURE = ROOT / "tests" / "fixtures" / "worldkit-eden.json"
sys.path.insert(0, str(SCRIPTS))

import name_registry  # noqa: E402
import worldkit  # noqa: E402

KIT = json.loads(FIXTURE.read_text(encoding="utf-8"))
BASE = ["STR=15", "DEX=13", "CON=14", "INT=8", "WIS=12", "CHA=10"]


class _Root(unittest.TestCase):
    """Temp DNE_CAMPAIGN_ROOT. make(name, ruleset, kit) creates a campaign."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)
        self.env = {**os.environ, "DNE_CAMPAIGN_ROOT": str(self.root),
                    "DNE_RUNTIME_DIR": str(self.root / ".runtime")}

    def tearDown(self):
        self._tmp.cleanup()

    def make(self, name, ruleset="2014", kit=None):
        d = self.root / "campaigns" / name
        (d / "characters").mkdir(parents=True)
        (d / "state.md").write_text(f"# {name}\n**Ruleset:** {ruleset}\n", encoding="utf-8")
        if kit is not None:
            (d / "worldkit.json").write_text(json.dumps(kit, ensure_ascii=False), encoding="utf-8")
        return d

    def run_script(self, script, *args):
        return subprocess.run([sys.executable, str(SCRIPTS / script), *args],
                              capture_output=True, encoding="utf-8", env=self.env)


# ── 1. 2024 campaigns: lookups fall back to the 2014 dataset when 2024 isn't built ──
class Ruleset2024FallbackTests(_Root):
    def test_world_kit_lookup_in_2024_campaign(self):
        kit = copy.deepcopy(KIT)
        kit["_meta"]["base_ruleset"] = "2024"
        self.make("eden24", "2024", kit)
        r = self.run_script("lookup.py", "monster", "reaper", "--campaign", "eden24")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Reaper", r.stdout)

    def test_plain_2024_campaign_lookup(self):
        self.make("plain24", "2024")
        r = self.run_script("lookup.py", "condition", "poisoned", "--campaign", "plain24")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Poisoned", r.stdout)


# ── 2. srd_fallback:false hides every player-facing SRD category, defined or not ──
class NoLeakTests(_Root):
    def setUp(self):
        super().setUp()
        kit = copy.deepcopy(KIT)
        kit.pop("spells")                      # a no-powers world
        self.make("nopowers", kit=kit)

    def test_srd_spell_hidden_when_kit_has_no_spells(self):
        r = self.run_script("lookup.py", "spell", "fireball", "--campaign", "nopowers")
        self.assertNotIn("8d6", r.stdout)

    def test_srd_magic_items_hidden(self):
        r = self.run_script("lookup.py", "magic_item", "bag of holding", "--campaign", "nopowers")
        self.assertNotIn("Bag of Holding", r.stdout.split("Did you mean")[0].replace("bag of holding", ""))
        r = self.run_script("lookup.py", "item", "longsword", "--campaign", "nopowers")
        self.assertNotIn("Dancing Sword", r.stdout)

    def test_rules_categories_still_merge(self):
        r = self.run_script("lookup.py", "condition", "grappled", "--campaign", "nopowers")
        self.assertIn("Grappled", r.stdout)

    def test_no_match_exits_nonzero(self):
        r = self.run_script("lookup.py", "monster", "goblin", "--campaign", "nopowers")
        self.assertEqual(r.returncode, 1)
        self.assertIn("No match", r.stdout)

    def test_thai_origin_prints_readable_text(self):
        kit = copy.deepcopy(KIT)
        kit["races"].append({"name": "ลูกแพ", "index": "raft-born", "ability_bonuses": {"CON": 2, "WIS": 1},
                             "speed": 30, "size": "Medium", "traits": ["ว่ายน้ำ 30 ฟุต"]})
        self.make("thai", kit=kit)
        r = self.run_script("lookup.py", "origin", "ลูกแพ", "--campaign", "thai")
        self.assertIn("ลูกแพ", r.stdout)
        self.assertNotIn("\\u0e", r.stdout)


# ── 3. name_registry keeps Thai vowels/tone marks and strips Thai honorifics ──
class ThaiRegistryTests(_Root):
    def test_slug_keeps_combining_marks(self):
        self.assertNotEqual(name_registry.slug("ขุนรามเดชะ"), name_registry.slug("ขนรามเดชะ"))
        self.assertNotEqual(name_registry.slug("หลวงพี่นนท์"), name_registry.slug("หลวงพี่นันท์"))
        self.assertIn("ุ", name_registry.slug("สุดารัตน์"))
        # short words that also begin ordinary names are not treated as titles
        self.assertEqual(name_registry.slug("อานนท์"), "อานนท์")
        self.assertEqual(name_registry.slug("พันธุ์ทิพย์"), "พันธุ์ทิพย์")

    def test_ascii_slug_unchanged(self):
        self.assertEqual(name_registry.slug("Vedra Ceth (V.C.)"), "vedra_ceth")

    def test_thai_honorific_prefix_is_ignored_for_duplicates(self):
        self.assertEqual(name_registry.slug("นางจันทร์เพ็ญ"), name_registry.slug("จันทร์เพ็ญ"))
        self.assertEqual(name_registry.slug("หลวงพี่นนท์"), name_registry.slug("นนท์"))

    def test_npcs_full_section_headings_are_not_names(self):
        d = self.make("reg")
        (d / "npcs-full.md").write_text(
            "## Marla Venn\n### Personality\n- calm\n### Relationships\n- x\n### Notes\n-\n"
            "## Osk the Tall\n### Personality\n", encoding="utf-8")
        names = name_registry._scan_campaign_npcs(d)
        self.assertIn("Marla Venn", names)
        self.assertIn("Osk the Tall", names)
        for heading in ("Personality", "Relationships", "Notes"):
            self.assertNotIn(heading, names)


# ── 4. character.py in a World Kit campaign ──
class CharacterWorldTests(_Root):
    def setUp(self):
        super().setUp()
        self.make("eden", kit=KIT)
        kit24 = copy.deepcopy(KIT)
        kit24["_meta"]["base_ruleset"] = "2024"
        self.make("eden24", "2024", kit24)
        shield = copy.deepcopy(KIT)
        shield["equipment"].append({"name": "Riot Shield", "index": "riot-shield", "category": "Armor",
                                    "ac": "AC +2", "weight": 6})
        self.make("shield", kit=shield)

    def calc(self, camp, *args):
        return self.run_script("character.py", "calc", "-c", camp, *args)

    def test_srd_class_refused_in_world(self):
        r = self.calc("eden", "--class", "wizard", *BASE)
        self.assertEqual(r.returncode, 2)
        self.assertIn("Soldier", r.stderr)          # lists the world's classes

    def test_level_n_hp_is_shown(self):
        r = self.calc("eden", "--class", "Soldier", "--race", "Tunnel-Born", "--level", "3", *BASE)
        self.assertEqual(r.returncode, 0, r.stderr)
        # d10 + CON(+3); levels 2-3 average 6+3 each → 13 + 18 = 31
        self.assertIn("HP (level 3): 31", r.stdout)

    def test_shield_as_armor_refused(self):
        r = self.calc("shield", "--class", "Soldier", "--armor", "riot-shield", *BASE)
        self.assertEqual(r.returncode, 2)
        self.assertIn("--shield", r.stderr)

    def test_world_shield_with_shield_flag(self):
        r = self.calc("shield", "--class", "Soldier", "--armor", "scrap-plate", "--shield", *BASE)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Armor Class: 17", r.stdout)   # 14 + DEX 1 + 2

    def test_unknown_armor_message_lists_world_armor_once(self):
        r = self.calc("eden", "--class", "Soldier", "--armor", "chain-mail", *BASE)
        self.assertEqual(r.returncode, 2)
        self.assertNotIn("SRD armor", r.stderr)
        self.assertEqual(r.stderr.count("scrap-plate"), 1)

    def test_background_skills_are_proficient(self):
        r = self.calc("eden24", "--class", "Soldier", "--background", "Hollow Guard",
                      "--background-asi", "STR=2,CON=1", *BASE)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(r.stdout, r"\*\s+Athletics")
        self.assertRegex(r.stdout, r"\*\s+Perception")

    def test_2024_world_origin_with_background(self):
        r = self.calc("eden24", "--class", "Soldier", "--race", "Tunnel-Born", "--background", "Hollow Guard",
                      "--background-asi", "STR=2,CON=1", *BASE)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(r.stdout, r"STR\s+15\s+\+2\s+17")
        self.assertRegex(r.stdout, r"WIS\s+12\s+[—-]?\s*12")   # origin's WIS +1 NOT applied in 2024

    def test_help_prints_usage_not_a_fighter(self):
        for sub in ("calc", "levelup"):
            r = subprocess.run([sys.executable, str(SCRIPTS / "character.py"), sub, "--help"],
                               capture_output=True, encoding="utf-8", env=self.env)
            self.assertEqual(r.returncode, 0)
            self.assertIn("usage", r.stdout.lower())
            self.assertNotIn("Level Up: Fighter", r.stdout)
            self.assertNotIn("Fighter Level", r.stdout)

    def test_warlock_world_invocations_from_kit(self):
        kit = copy.deepcopy(KIT)
        kit["classes"].append({"name": "Signal Priest", "index": "signal-priest", "chassis": "warlock"})
        kit["spells"].append({"name": "Feedback Lance", "index": "feedback-lance", "level": 0, "school": "Evocation",
                              "classes": ["Signal Priest"], "description": "1d10 force. (chassis: Eldritch Blast)"})
        kit["spells"].append({"name": "Static Hymn", "index": "static-hymn", "level": 1, "school": "Necromancy",
                              "classes": ["Signal Priest"], "description": "Retaliate. (chassis: Hellish Rebuke)"})
        kit["class_options"] = [{"name": "Amplified Lance", "index": "amplified-lance", "kind": "invocation",
                                 "level": 2, "description": "Add CHA to Feedback Lance damage. (chassis: Agonizing Blast)"}]
        self.make("warlock", kit=kit)
        r = self.run_script("character.py", "levelup", "-c", "warlock", "--class", "Signal Priest",
                            "--from", "1", "--con-mod", "1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Amplified Lance", r.stdout)
        self.assertNotIn("Agonizing Blast,", r.stdout)


# ── 5. worldkit.py validate enforces the step-7 rules ──
class DeepValidateTests(unittest.TestCase):
    def errs(self, mutate):
        kit = copy.deepcopy(KIT)
        mutate(kit)
        return worldkit.validate(kit)

    def assertCaught(self, mutate, *needles):
        errs = self.errs(mutate)
        self.assertTrue(any(all(n in e for n in needles) for e in errs), (needles, errs))

    def test_fixture_still_valid(self):
        self.assertEqual(worldkit.validate(KIT), [])

    def test_origin_bonus_total(self):
        self.assertCaught(lambda k: k["races"][0].update(ability_bonuses={"CON": 2, "WIS": 2, "STR": 1}),
                          "Tunnel-Born", "+3")

    def test_background_skills(self):
        self.assertCaught(lambda k: k["backgrounds"][0].update(skills=["Arcana"]), "Ex-EDEN Technician", "skills")
        self.assertCaught(lambda k: k["backgrounds"][0].update(skills=["Arcana", "Hacking"]), "Hacking")

    def test_background_skill_may_use_world_name(self):
        self.assertEqual(self.errs(lambda k: k["backgrounds"][0].update(skills=["Systems", "Deception"])), [])

    def test_spell_class_must_exist(self):
        self.assertCaught(lambda k: k["spells"][0].update(classes=["Netrunner"]), "Static Burst", "Netrunner")

    def test_monster_role_and_biomes(self):
        self.assertCaught(lambda k: k["monsters"][0].pop("role"), "Watcher", "role")
        self.assertCaught(lambda k: k["monsters"][0].update(role="tank"), "Watcher", "role")
        self.assertCaught(lambda k: k["monsters"][0].pop("biomes"), "Watcher", "biomes")

    def test_monster_hp_within_hit_dice(self):
        self.assertCaught(lambda k: k["monsters"][0].update(hp=999), "Watcher", "hp")

    def test_duplicate_and_non_ascii_index(self):
        self.assertCaught(lambda k: k["spells"][1].update(index="static-burst"), "duplicate", "static-burst")
        self.assertCaught(lambda k: k["monsters"][0].update(index="ผู้เฝ้ามอง"), "Watcher", "index")

    def test_weapon_damage_format(self):
        self.assertCaught(lambda k: k["equipment"][0].update(damage="banana"), "Rail Pistol", "damage")

    def test_chassis_spell_must_exist_in_srd(self):
        self.assertCaught(lambda k: k["spells"][1].update(
            description="+5 AC. (chassis: Hex)"), "Overclock Shield", "Hex")

    def test_casting_class_needs_powers(self):
        def drop_medic_powers(k):
            k["spells"] = [s for s in k["spells"] if "Medic" not in s.get("classes", [])]
        self.assertCaught(drop_medic_powers, "Medic")

    def test_shield_ac_only_on_shields(self):
        self.assertEqual(self.errs(lambda k: k["equipment"].append(
            {"name": "Riot Shield", "index": "riot-shield", "category": "Armor", "ac": "AC +2"})), [])

    def test_cli_prints_warnings_but_exits_zero(self):
        kit = copy.deepcopy(KIT)
        kit["lexicon"] = {"spell": "protocol"}          # fewer than 8 → warning, not error
        with tempfile.TemporaryDirectory() as td:
            p = pathlib.Path(td) / "worldkit.json"
            p.write_text(json.dumps(kit), encoding="utf-8")
            r = subprocess.run([sys.executable, str(SCRIPTS / "worldkit.py"), "validate", str(p)],
                               capture_output=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("warning", (r.stdout + r.stderr).lower())
        self.assertIn("lexicon", r.stdout + r.stderr)


class ShowTests(_Root):
    def test_show_is_a_tour(self):
        self.make("eden", kit=KIT)
        r = self.run_script("worldkit.py", "show", "eden")
        self.assertEqual(r.returncode, 0, r.stderr)
        for needle in ("Tunnel-Born", "CON +2", "Infiltration Method", "Ghost",
                       "Hollow Guard", "Reaper", "CR 5", "CR 1/4", "Scrip"):
            self.assertIn(needle, r.stdout)


# ── 6. encounter_gen in World Kit campaigns ──
class EncounterWorldTests(_Root):
    def setUp(self):
        super().setUp()
        self.make("eden", kit=KIT)

    def test_unknown_world_biome_is_an_error(self):
        r = self.run_script("encounter_gen.py", "-c", "eden", "--biome", "forest", "--seed", "1")
        self.assertEqual(r.returncode, 2)
        self.assertIn("surface", r.stderr)          # lists the kit's biomes

    def test_budget_is_reasonably_used(self):
        for seed in range(10):
            r = self.run_script("encounter_gen.py", "-c", "eden", "--biome", "surface",
                                "--party-level", "5", "--party-size", "4", "--seed", str(seed), "--json")
            self.assertEqual(r.returncode, 0, r.stderr)
            enc = json.loads(r.stdout)
            self.assertGreaterEqual(enc["adjusted_xp"], enc["xp_budget"] * 0.5, (seed, enc))

    def test_cr_printed_as_fraction(self):
        r = self.run_script("encounter_gen.py", "-c", "eden", "--biome", "surface",
                            "--party-level", "1", "--seed", "1")
        self.assertNotRegex(r.stdout, r"CR 0\.\d")


# ── 7. dice.py --help ──
class DiceHelpTests(unittest.TestCase):
    def test_help(self):
        r = subprocess.run([sys.executable, str(SCRIPTS / "dice.py"), "--help"],
                           capture_output=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Usage", r.stdout)


if __name__ == "__main__":
    unittest.main()
