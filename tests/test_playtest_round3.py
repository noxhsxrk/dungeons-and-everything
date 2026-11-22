"""Regressions from the full play-through sessions (round 3): economy, rests, XP, calendar,
registry migration, tracker, combat, character, dice, worldkit, graph, SRD 2014 features."""
from __future__ import annotations

import copy
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "skills" / "dne" / "scripts"
FIXTURE = ROOT / "tests" / "fixtures" / "worldkit-eden.json"
SRD = ROOT / "skills" / "dne" / "data" / "dnd5e_srd.json"
KIT = json.loads(FIXTURE.read_text(encoding="utf-8"))
BASE = ["STR=15", "DEX=13", "CON=14", "INT=8", "WIS=12", "CHA=10"]

SHEET = """# {name}

## Identity
- **Race:** Tunnel-Born | **Class:** {cls} | **Level:** {level} | **XP:** 0

## Combat Stats
- **HP:** {hp} / 13 | **Temp HP:** {temp}
- **AC:** 15 | **Initiative:** +1 | **Speed:** 30
- **Hit Dice:** 1d10 (remaining: 0)
- **Death Saves:** Successes: 1 | Failures: 2

## Spell Slots (if applicable)
| Level | Total | Used |
|-------|-------|------|
| 1st | 1 | 1 |

## Features & Traits
- พระเครื่อง charm: the amulet hums near ghosts

## Equipment & Inventory
**Currency:** 100 sc
**Adventuring Gear:**
- Rope
- พระเครื่อง
"""


class _Camp(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)
        self.camp = self.root / "campaigns" / "eden"
        (self.camp / "characters").mkdir(parents=True)
        (self.camp / "state.md").write_text("**Ruleset:** 2014\n**Session count:** 0\n", encoding="utf-8")
        shutil.copy(FIXTURE, self.camp / "worldkit.json")
        self.env = {**os.environ, "DNE_CAMPAIGN_ROOT": str(self.root),
                    "DNE_RUNTIME_DIR": str(self.root / ".rt")}

    def tearDown(self):
        self._tmp.cleanup()

    def sheet(self, fname="kade", **kw):
        vals = dict(name="Kade", cls="Soldier (fighter chassis)", level=2, hp=13, temp=0)
        vals.update(kw)
        p = self.camp / "characters" / f"{fname}.md"
        p.write_text(SHEET.format(**vals), encoding="utf-8")
        return p

    def run_py(self, script, *args):
        return subprocess.run([sys.executable, str(SCRIPTS / script), *args],
                              capture_output=True, encoding="utf-8", env=self.env)


# ── economy ────────────────────────────────────────────────────────────────
class EconomyTests(_Camp):
    def test_sell_removes_inventory_line_only(self):
        p = self.sheet()
        r = self.run_py("economy.py", "-c", "eden", "sell", "--char", "kade", "--item", "พระเครื่อง", "--value", "5")
        self.assertEqual(r.returncode, 0, r.stderr)
        text = p.read_text(encoding="utf-8")
        self.assertIn("**Level:** 2", text)                     # identity line intact
        self.assertIn("พระเครื่อง charm", text)                 # feature line intact
        inv = text.split("## Equipment & Inventory", 1)[1]
        self.assertNotIn("- พระเครื่อง\n", inv)

    def test_sell_unknown_item_refused(self):
        p = self.sheet()
        before = p.read_text(encoding="utf-8")
        r = self.run_py("economy.py", "-c", "eden", "sell", "--char", "kade", "--item", "Railgun", "--value", "5")
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(p.read_text(encoding="utf-8"), before)

    def test_long_rest_at_zero_hp_does_not_heal(self):
        p = self.sheet(hp=0)
        self.run_py("economy.py", "-c", "eden", "rest", "--char", "kade", "--type", "long")
        text = p.read_text(encoding="utf-8")
        self.assertIn("**HP:** 0 / 13", text)
        self.assertIn("Failures: 2", text)                      # death saves untouched

    def test_long_rest_clears_temp_hp(self):
        p = self.sheet(temp=5)
        r = self.run_py("economy.py", "-c", "eden", "rest", "--char", "kade", "--type", "long")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("**Temp HP:** 0", p.read_text(encoding="utf-8"))

    def test_short_rest_restores_pact_slots(self):
        p = self.sheet(cls="Hexslinger (warlock chassis)")
        r = self.run_py("economy.py", "-c", "eden", "rest", "--char", "kade", "--type", "short")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("| 1st | 1 | 0 |", p.read_text(encoding="utf-8"))

    def test_short_rest_keeps_non_warlock_slots(self):
        p = self.sheet(cls="Mechanic (wizard chassis)")
        self.run_py("economy.py", "-c", "eden", "rest", "--char", "kade", "--type", "short")
        self.assertIn("| 1st | 1 | 1 |", p.read_text(encoding="utf-8"))

    def test_2024_long_rest_restores_all_hit_dice(self):
        (self.camp / "state.md").write_text("**Ruleset:** 2024\n", encoding="utf-8")
        p = self.sheet(level=4)
        text = p.read_text(encoding="utf-8").replace("1d10 (remaining: 0)", "4d10 (remaining: 0)")
        p.write_text(text, encoding="utf-8")
        self.run_py("economy.py", "-c", "eden", "rest", "--char", "kade", "--type", "long")
        self.assertIn("(remaining: 4)", p.read_text(encoding="utf-8"))

    def test_buy_same_item_twice_keeps_one_line_with_quantity(self):
        p = self.sheet()
        for _ in range(2):
            self.run_py("economy.py", "-c", "eden", "buy", "--char", "kade", "--item", "Power Cell", "--cost", "5")
        inv = p.read_text(encoding="utf-8").split("## Equipment & Inventory", 1)[1]
        self.assertEqual(inv.count("Power Cell"), 1)
        self.assertRegex(inv, r"Power Cell.*(×|x)\s*2")

    def test_all_with_individual_heal_refused(self):
        self.sheet()
        r = self.run_py("economy.py", "-c", "eden", "rest", "--char", "all", "--type", "short", "--heal", "5")
        self.assertEqual(r.returncode, 2)


# ── xp ─────────────────────────────────────────────────────────────────────
class XpTests(_Camp):
    def test_award_splits_raw_xp_and_finds_named_sheet(self):
        self.sheet("walt-brennan", name="Walt Brennan")
        self.sheet("rita-okafor", name="Rita Okafor")
        r = self.run_py("xp.py", "award", "--campaign", "eden", "--characters", "Walt Brennan,Rita Okafor",
                        "--monsters", "thug:1/8:3")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        # 3 × 25 raw = 75; split by 2 → 37 each (the ×2 multiplier only rates difficulty)
        self.assertRegex(r.stdout, r"\b37\b")
        self.assertNotRegex(r.stdout, r"Per player:\s+75")


    def test_small_party_uses_next_multiplier_for_difficulty(self):
        r = self.run_py("xp.py", "calc", "--level", "3", "--players", "2", "--monsters", "a:1/8:1,b:1/4:4")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("2.5", r.stdout)                         # 5 monsters (×2) bumped to ×2.5 for <3 PCs


class EncounterPartyTests(_Camp):
    def test_party_size_defaults_from_state_header(self):
        (self.camp / "state.md").write_text("**Ruleset:** 2014\n**Party size:** 2  **Starting level:** 5\n",
                                            encoding="utf-8")
        r = self.run_py("encounter_gen.py", "-c", "eden", "--biome", "surface", "--seed", "1", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        enc = json.loads(r.stdout)
        self.assertEqual((enc["party_size"], enc["party_level"]), (2, 5))


# ── calendar ───────────────────────────────────────────────────────────────
class CalendarTests(_Camp):
    def cal(self, *a):
        return self.run_py("calendar.py", "-c", "eden", *a)

    def test_unknown_time_and_bad_date_refused(self):
        self.assertEqual(self.cal("init", "--date", "14 September 2289", "--time", "23:40x").returncode, 2)
        self.assertEqual(self.cal("init", "--date", "แรม 3 ค่ำ เดือน 12").returncode, 2)

    def test_weekday_runs_on_across_months(self):
        r = self.cal("init", "--date", "30 Alpha 1", "--months", "Alpha,Beta", "--month-length", "30",
                     "--day-names", "D1,D2,D3,D4,D5,D6,D7")
        self.assertEqual(r.returncode, 0, r.stderr)
        r = self.cal("advance", "1", "days")
        # day 31 of the year → index 30 % 7 = 2 → D3 (not D1 again)
        self.assertIn("D3", r.stdout)

    def test_gregorian_calendar(self):
        r = self.cal("init", "--gregorian", "--date", "14 September 2077", "--time", "night")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Tuesday", r.stdout)
        r = self.cal("advance", "17", "days")
        self.assertIn("1 October 2077", r.stdout)               # September has 30 days

    def test_set_exact_hour(self):
        self.cal("init", "--date", "14 September 2289")
        r = self.cal("set", "14 September 2289", "--hour", "23")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("23", self.cal("now").stdout)


# ── name registry ──────────────────────────────────────────────────────────
class RegistryMigrationTests(_Camp):
    def test_stale_slug_keys_are_rekeyed_on_load(self):
        reg = {"entries": {"เจหงส": {"name": "เจ๊หงส์", "type": "npc", "campaigns": ["eden"],
                                     "currently_active_in": ["eden"], "first_used": "eden S0"}}}
        (self.root / ".name_registry.json").write_text(json.dumps(reg, ensure_ascii=False), encoding="utf-8")
        r = self.run_py("name_registry.py", "check", "เจ๊หงส์")
        self.assertNotEqual(r.returncode, 0, r.stdout)          # duplicate found
        r = self.run_py("name_registry.py", "add", "--name", "เจ๊หงส์", "--type", "npc",
                        "--campaign", "eden", "--session", "1")
        data = json.loads((self.root / ".name_registry.json").read_text(encoding="utf-8"))
        self.assertEqual(sum(1 for e in data["entries"].values() if e["name"] == "เจ๊หงส์"), 1)

    def test_mae_ying_honorific(self):
        sys.path.insert(0, str(SCRIPTS))
        import name_registry
        self.assertEqual(name_registry.slug("แม่หญิงจันทร์เพ็ญ"), name_registry.slug("จันทร์เพ็ญ"))


# ── tracker ────────────────────────────────────────────────────────────────
class TrackerTests(_Camp):
    def test_clear_keeps_unconscious_on_dying_or_stable_pc(self):
        t = lambda *a: self.run_py("tracker.py", "-c", "eden", *a)
        t("condition", "add", "Rita", "unconscious")
        t("saves", "Rita", "stable")
        t("condition", "add", "Thug", "prone")
        r = t("clear")
        self.assertEqual(r.returncode, 0, r.stderr)
        status = t("status").stdout
        self.assertRegex(status, r"Rita.*unconscious")

    def test_enemy_set_for_martial_omits_slot_talk(self):
        r = self.run_py("tracker.py", "-c", "eden", "enemy", "set", "Reaper", "--role", "brute")
        self.assertNotIn("slots=0", r.stdout)


# ── combat ─────────────────────────────────────────────────────────────────
class CombatTests(unittest.TestCase):
    def combat(self, *a):
        return subprocess.run([sys.executable, str(SCRIPTS / "combat.py"), *a],
                              capture_output=True, encoding="utf-8")

    def test_player_supplied_roll(self):
        r = self.combat("attack", "--atk", "5", "--ac", "15", "--dmg", "1d8+3", "--roll", "9")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("d20(9) + 5 = 14 vs AC 15 — MISS", r.stdout)

    def test_advantage_with_player_rolls(self):
        r = self.combat("attack", "--atk", "5", "--ac", "15", "--dmg", "1d8+3", "--roll", "4,17", "--adv")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("d20(17)", r.stdout)
        r = self.combat("attack", "--atk", "5", "--ac", "15", "--dmg", "1d8+3", "--roll", "4,17", "--dis")
        self.assertIn("d20(4)", r.stdout)

    def test_compound_damage(self):
        r = self.combat("attack", "--atk", "30", "--ac", "1", "--dmg", "1d6+5+1d4 bludgeoning")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(r.stdout, r"\(1d6\+5\+1d4\) = \d+ bludgeoning damage")

    def test_init_max_hp_and_initiative_bonus(self):
        r = self.combat("init", json.dumps([
            {"name": "Joss", "dex_mod": 2, "init_bonus": 2, "hp": 12, "max_hp": 24, "ac": 19, "type": "pc", "roll": 10}]))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Joss: d20(10) + 4 = 14", r.stdout)
        state = json.loads(r.stdout.split("STATE_JSON:", 1)[1].strip().splitlines()[0])
        self.assertEqual((state[0]["hp"], state[0]["max_hp"]), (12, 24))

    def test_crit_range(self):
        r = self.combat("attack", "--atk", "5", "--ac", "30", "--dmg", "1d8", "--roll", "19", "--crit-range", "19")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("CRITICAL HIT", r.stdout)

    def test_help(self):
        r = self.combat("attack", "--help")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Usage", r.stdout)

    def test_init_accepts_player_roll_and_keeps_thai_readable(self):
        r = self.combat("init", json.dumps([
            {"name": "ทองดี", "dex_mod": 1, "hp": 13, "ac": 17, "type": "pc", "roll": 18},
            {"name": "ขี้ยาเรือ", "dex_mod": 2, "hp": 7, "ac": 11, "type": "npc"}], ensure_ascii=False))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("ทองดี: d20(18) + 1 = 19", r.stdout)
        state = r.stdout.split("STATE_JSON:", 1)[1]
        self.assertIn("ทองดี", state)
        self.assertNotIn("\\u0e", state)


# ── character ──────────────────────────────────────────────────────────────
class CharacterTests(_Camp):
    def calc(self, *a):
        return self.run_py("character.py", "calc", "-c", "eden", *a)

    def test_unknown_flag_refused(self):
        r = self.calc("--class", "Soldier", "--armour", "scrap-plate", *BASE)
        self.assertEqual(r.returncode, 2)
        self.assertIn("--armour", r.stderr)

    def test_expertise_and_passive_perception(self):
        r = self.calc("--class", "Infiltrator", "--proficient", "Perception", "Stealth",
                      "--expertise", "Perception", *BASE)
        self.assertEqual(r.returncode, 0, r.stderr)
        # WIS 12 (+1), prof +2 doubled → +5; passive 15
        self.assertRegex(r.stdout, r"Perception\s+\(WIS\)\s+\+5")
        self.assertIn("Passive Perception: 15", r.stdout)

    def test_level_one_subclass_owed_at_creation(self):
        r = self.calc("--class", "Medic", "--level", "1", *BASE)     # cleric chassis, 2014
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("subclass", r.stdout.lower())

    def test_levelup_lists_spell_progression(self):
        kit = copy.deepcopy(KIT)
        kit["classes"].append({"name": "Hexslinger", "index": "hexslinger", "chassis": "warlock"})
        kit["spells"].append({"name": "Cold Lead", "index": "cold-lead", "level": 1, "school": "Evocation",
                              "classes": ["Hexslinger"], "description": "x (chassis: Hellish Rebuke)"})
        (self.camp / "worldkit.json").write_text(json.dumps(kit), encoding="utf-8")
        r = self.run_py("character.py", "levelup", "-c", "eden", "--class", "Hexslinger", "--from", "1", "--con-mod", "1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(r.stdout, r"[Pp]act slots?:?\s*1\s*→\s*2")
        self.assertRegex(r.stdout, r"[Ss]pells known:?\s*2\s*→\s*3")
        r = self.run_py("character.py", "levelup", "-c", "eden", "--class", "Mechanic", "--from", "1", "--con-mod", "1")
        self.assertRegex(r.stdout, r"1st[- ]level slots?:?\s*2\s*→\s*3")

    def test_levelup_with_subclass_given_does_not_ask_again(self):
        r = self.run_py("character.py", "levelup", "-c", "eden", "--class", "Infiltrator", "--from", "2",
                        "--con-mod", "1", "--subclass", "Ghost")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("choose a subclass", r.stdout)
        self.assertIn("Ghost", r.stdout)

    def test_levelup_lists_world_pact_boons(self):
        kit = copy.deepcopy(KIT)
        kit["classes"].append({"name": "Hexslinger", "index": "hexslinger", "chassis": "warlock"})
        kit["spells"].append({"name": "Cold Lead", "index": "cold-lead", "level": 1, "school": "Evocation",
                              "classes": ["Hexslinger"], "description": "x (chassis: Hellish Rebuke)"})
        kit["class_options"] = [{"name": "Pact of the Spike", "index": "pact-of-the-spike", "kind": "pact_boon",
                                 "level": 3, "description": "x (chassis: Pact of the Blade)"}]
        (self.camp / "worldkit.json").write_text(json.dumps(kit), encoding="utf-8")
        r = self.run_py("character.py", "levelup", "-c", "eden", "--class", "Hexslinger", "--from", "2", "--con-mod", "1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Pact of the Spike", r.stdout)
        self.assertNotIn("Chain, Blade", r.stdout)
        r = self.run_py("lookup.py", "pact-boon", "chain")
        self.assertNotIn("Chains of Carceri", r.stdout)

    def test_long_rest_message_has_no_spell_slots_for_martial(self):
        r = self.run_py("character.py", "rest", "long", "-c", "eden", "--class", "Soldier",
                        "--level", "2", "--hd-remaining", "0", "--hp", "5", "--max-hp", "20")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("Spell slots", r.stdout)


# ── dice ───────────────────────────────────────────────────────────────────
class DiceTests(unittest.TestCase):
    def dice(self, *a):
        return subprocess.run([sys.executable, str(SCRIPTS / "dice.py"), *a],
                              capture_output=True, encoding="utf-8", env={**os.environ, "DNE_DICE_PHYSICAL": "0"})

    def test_bad_notation_is_a_clean_error(self):
        r = self.dice("2d4x5")
        self.assertEqual(r.returncode, 2)
        self.assertNotIn("Traceback", r.stderr)

    def test_advantage_output_is_readable(self):
        r = self.dice("d20+6", "adv")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotRegex(r.stdout, r"Roll A: \[\d+\] = \d+ \+ 6")


# ── worldkit ───────────────────────────────────────────────────────────────
class WorldkitWarningTests(unittest.TestCase):
    def warnings(self, mutate):
        sys.path.insert(0, str(SCRIPTS))
        import worldkit
        kit = copy.deepcopy(KIT)
        mutate(kit)
        return worldkit.warnings(kit)

    def test_warlock_without_class_options_warns(self):
        def add(k):
            k["classes"].append({"name": "Hexslinger", "index": "hexslinger", "chassis": "warlock"})
            k["spells"].append({"name": "Cold Lead", "index": "cold-lead", "level": 1, "classes": ["Hexslinger"],
                                "description": "x (chassis: Hellish Rebuke)"})
        self.assertTrue(any("Hexslinger" in w and "class_options" in w for w in self.warnings(add)))

    def test_per_class_power_counts_warn(self):
        self.assertTrue(any("Mechanic" in w for w in self.warnings(lambda k: None)))  # wizard has 1 L1 power

    def test_biome_without_low_cr_warns(self):
        self.assertTrue(any("tunnels" in w for w in self.warnings(lambda k: None)))   # only the CR 5 Reaper

    def test_bad_class_option_kind_is_an_error(self):
        sys.path.insert(0, str(SCRIPTS))
        import worldkit
        kit = copy.deepcopy(KIT)
        kit["class_options"] = [{"name": "Odd", "index": "odd", "kind": "superpower", "description": "x"}]
        self.assertTrue(any("kind" in e for e in worldkit.validate(kit)))


class LookupClassFormatTests(_Camp):
    def test_class_prints_text_not_json(self):
        r = self.run_py("lookup.py", "class", "Soldier", "--campaign", "eden")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Soldier", r.stdout)
        self.assertNotIn('"chassis":', r.stdout)
        self.assertIn("fighter", r.stdout)


# ── graph ──────────────────────────────────────────────────────────────────
class GraphTests(_Camp):
    def g(self, *a):
        return self.run_py("campaign_graph.py", *a)

    def test_session_zero_shows_seed_edges_and_unknown_place_is_not_fatal(self):
        self.assertEqual(self.g("init", "--campaign", "eden").returncode, 0)
        self.g("add-node", "--campaign", "eden", "--id", "npc_a", "--type", "npc", "--name", "Ana")
        self.g("add-node", "--campaign", "eden", "--id", "npc_b", "--type", "npc", "--name", "Bo")
        self.g("add-node", "--campaign", "eden", "--id", "place_x", "--type", "location", "--name", "Dock")
        self.g("add-edge", "--campaign", "eden", "--from", "npc_a", "--to", "npc_b", "--type", "knows", "--since", "1")
        r = self.g("scene-context", "--campaign", "eden", "--place", "place_x", "--present", "npc_a,npc_b",
                   "--at-session", "0")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("knows", r.stdout)
        r = self.g("scene-context", "--campaign", "eden", "--place", "Some new alley", "--present", "npc_a",
                   "--at-session", "1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Ana", r.stdout)


# ── SRD 2014 features are 2014 text ────────────────────────────────────────
class Srd2014FeatureTests(unittest.TestCase):
    def test_features_are_2014(self):
        feats = {f["name"]: f for f in json.loads(SRD.read_text(encoding="utf-8"))["features"]}
        self.assertNotIn("twice", feats["Second Wind"]["description"])
        self.assertNotIn("Magic action", feats["Action Surge"]["description"])
        self.assertNotIn("Brutal Strike", feats)                 # a 2024-only feature
        self.assertNotIn("Weapon Mastery", feats)


if __name__ == "__main__":
    unittest.main()
