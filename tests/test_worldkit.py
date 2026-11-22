"""World Kit: a campaign's own origins, classes, powers, gear and monsters.

Dungeons & Everything lets the players describe any world. `/dne new` writes
`<campaign>/worldkit.json` (SRD-shaped records + a 5e `chassis` per class) and
every rules script given the campaign reads it ahead of the bundled SRD. A
campaign without a worldkit.json must behave exactly as before.

Fixture: tests/fixtures/worldkit-eden.json (the EDEN / Hollow-9 example world).
"""
from __future__ import annotations

import copy
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "skills" / "dne" / "scripts"
FIXTURE = ROOT / "tests" / "fixtures" / "worldkit-eden.json"
sys.path.insert(0, str(SCRIPTS))

import worldkit  # noqa: E402

KIT = json.loads(FIXTURE.read_text(encoding="utf-8"))
EDEN_MONSTERS = {m["name"] for m in KIT["monsters"]}
BASE = ["STR=15", "DEX=13", "CON=14", "INT=8", "WIS=12", "CHA=10"]


class _CampaignRoot(unittest.TestCase):
    """Temp DNE_CAMPAIGN_ROOT with an 'eden' campaign (worldkit) and a 'plain' one (none)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)
        for name in ("eden", "plain"):
            d = self.root / "campaigns" / name
            (d / "characters").mkdir(parents=True)
            (d / "state.md").write_text(f"# {name}\n**Ruleset:** 2014\n", encoding="utf-8")
        (self.root / "campaigns" / "eden" / "worldkit.json").write_text(
            FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
        self.env = {**os.environ, "DNE_CAMPAIGN_ROOT": str(self.root),
                    "DNE_RUNTIME_DIR": str(self.root / ".runtime")}

    def tearDown(self):
        self._tmp.cleanup()

    def run_script(self, script, *args):
        return subprocess.run([sys.executable, str(SCRIPTS / script), *args],
                              capture_output=True, encoding="utf-8", env=self.env)


class ValidateTests(unittest.TestCase):
    def test_fixture_is_valid(self):
        self.assertEqual(worldkit.validate(KIT), [])

    def _errors_after(self, mutate):
        kit = copy.deepcopy(KIT)
        mutate(kit)
        return worldkit.validate(kit)

    def test_unknown_chassis_is_refused(self):
        errs = self._errors_after(lambda k: k["classes"][0].update(chassis="gunslinger"))
        self.assertTrue(any("chassis" in e for e in errs), errs)

    def test_bad_ability_key_is_refused(self):
        errs = self._errors_after(lambda k: k["races"][0].update(ability_bonuses={"LUCK": 2}))
        self.assertTrue(any("LUCK" in e for e in errs), errs)

    def test_monster_xp_must_match_cr(self):
        errs = self._errors_after(lambda k: k["monsters"][1].update(xp=999))
        self.assertTrue(any("Reaper" in e and "xp" in e.lower() for e in errs), errs)

    def test_monster_needs_core_stats(self):
        errs = self._errors_after(lambda k: k["monsters"][0].pop("hp"))
        self.assertTrue(any("Watcher" in e and "hp" in e for e in errs), errs)

    def test_unparseable_armor_ac_is_refused(self):
        errs = self._errors_after(lambda k: k["equipment"][1].update(ac="very tough"))
        self.assertTrue(any("Scrap Plate" in e for e in errs), errs)

    def test_background_needs_three_abilities(self):
        errs = self._errors_after(lambda k: k["backgrounds"][0].update(ability_options=["INT"]))
        self.assertTrue(any("Ex-EDEN Technician" in e for e in errs), errs)

    def test_duplicate_names_in_a_category_are_refused(self):
        errs = self._errors_after(lambda k: k["monsters"].append(copy.deepcopy(k["monsters"][0])))
        self.assertTrue(any("Watcher" in e and "duplicate" in e.lower() for e in errs), errs)

    def test_cli_exit_codes(self):
        ok = subprocess.run([sys.executable, str(SCRIPTS / "worldkit.py"), "validate", str(FIXTURE)],
                            capture_output=True, encoding="utf-8")
        self.assertEqual(ok.returncode, 0, ok.stderr)
        with tempfile.TemporaryDirectory() as td:
            bad = copy.deepcopy(KIT)
            bad["classes"][0]["chassis"] = "gunslinger"
            p = pathlib.Path(td) / "worldkit.json"
            p.write_text(json.dumps(bad), encoding="utf-8")
            r = subprocess.run([sys.executable, str(SCRIPTS / "worldkit.py"), "validate", str(p)],
                               capture_output=True, encoding="utf-8")
            self.assertEqual(r.returncode, 1)
            self.assertIn("chassis", r.stdout + r.stderr)


class ResolveTests(_CampaignRoot):
    def test_load_and_resolve_by_campaign(self):
        os.environ["DNE_CAMPAIGN_ROOT"] = str(self.root)
        try:
            kit = worldkit.load("eden")
            self.assertIsNotNone(kit)
            self.assertIsNone(worldkit.load("plain"))
            self.assertEqual(worldkit.class_chassis("Infiltrator", "eden"), "rogue")
            self.assertEqual(worldkit.class_chassis("rogue", "plain"), "rogue")
        finally:
            os.environ.pop("DNE_CAMPAIGN_ROOT", None)


class LookupTests(_CampaignRoot):
    def test_world_monster_found(self):
        r = self.run_script("lookup.py", "monster", "reaper", "--campaign", "eden")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Reaper", r.stdout)

    def test_srd_monster_hidden_in_custom_world(self):
        r = self.run_script("lookup.py", "monster", "goblin", "--campaign", "eden")
        self.assertNotIn("Goblin", r.stdout.split("Did you mean")[0].replace("No match for 'goblin'", ""))
        self.assertIn("No match", r.stdout)

    def test_category_the_world_does_not_define_falls_through_to_srd(self):
        r = self.run_script("lookup.py", "condition", "poisoned", "--campaign", "eden")
        self.assertIn("Poisoned", r.stdout)

    def test_world_power_found(self):
        r = self.run_script("lookup.py", "spell", "overclock shield", "--campaign", "eden")
        self.assertIn("Overclock Shield", r.stdout)

    def test_campaign_without_worldkit_unchanged(self):
        r = self.run_script("lookup.py", "monster", "goblin", "--campaign", "plain")
        self.assertIn("Goblin", r.stdout)

    def test_programmatic_lookup_record_takes_campaign(self):
        r = subprocess.run([sys.executable, "-c",
                            "import sys; sys.path.insert(0, sys.argv[1]); import lookup; "
                            "rec = lookup.lookup_record('watcher', category='monster', campaign='eden'); "
                            "print(rec['name'] if rec else None); "
                            "print(lookup.lookup_record('watcher', category='monster'))",
                            str(SCRIPTS)], capture_output=True, encoding="utf-8", env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        first, second = r.stdout.strip().splitlines()[:2]
        self.assertEqual(first, "Watcher")
        self.assertNotEqual(second, "Watcher")


class EncounterTests(_CampaignRoot):
    def test_only_world_monsters_are_drawn(self):
        for seed in range(8):
            r = self.run_script("encounter_gen.py", "-c", "eden", "--biome", "surface",
                                "--party-level", "5", "--party-size", "4", "--seed", str(seed), "--json")
            self.assertEqual(r.returncode, 0, r.stderr)
            names = {m["name"] for m in json.loads(r.stdout)["monsters"]}
            self.assertTrue(names and names <= EDEN_MONSTERS, names)

    def test_world_biome_is_free_form(self):
        r = self.run_script("encounter_gen.py", "-c", "eden", "--biome", "tunnels",
                            "--party-level", "5", "--seed", "1", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        names = {m["name"] for m in json.loads(r.stdout)["monsters"]}
        self.assertEqual(names, {"Reaper"})

    def test_no_campaign_still_uses_srd_biomes(self):
        r = self.run_script("encounter_gen.py", "--biome", "forest", "--seed", "1", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse({m["name"] for m in json.loads(r.stdout)["monsters"]} & EDEN_MONSTERS)


class CharacterTests(_CampaignRoot):
    def test_world_origin_bonuses_and_class_chassis(self):
        r = self.run_script("character.py", "calc", "-c", "eden", "--race", "Tunnel-Born",
                            "--class", "Soldier", "--level", "1", *BASE)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = r.stdout
        self.assertIn("Soldier", out)
        self.assertIn("fighter", out.lower())          # chassis is shown
        self.assertRegex(out, r"CON\s+14\s+\+2\s+16")    # CON +2 from Tunnel-Born
        self.assertRegex(out, r"WIS\s+12\s+\+1\s+13")
        self.assertIn("HP (level 1): 13", out)           # d10 fighter chassis + CON +3
        self.assertRegex(out, r"\*\s+STR")              # fighter saves
        self.assertRegex(out, r"\*\s+CON")

    def test_world_skill_names_are_shown(self):
        r = self.run_script("character.py", "calc", "-c", "eden", "--race", "Augmented",
                            "--class", "Mechanic", *BASE)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Systems", r.stdout)
        self.assertIn("EDEN Lore", r.stdout)

    def test_world_armor(self):
        r = self.run_script("character.py", "calc", "-c", "eden", "--race", "Tunnel-Born",
                            "--class", "Soldier", "--armor", "scrap-plate", *BASE)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Armor Class: 15", r.stdout)       # 14 + DEX +1

    def test_world_background_increase(self):
        r = self.run_script("character.py", "calc", "-c", "eden", "--class", "Mechanic",
                            "--background", "Ex-EDEN Technician", "--background-asi", "INT=2,WIS=1", *BASE)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(r.stdout, r"INT\s+8\s+\+2\s+10")
        bad = self.run_script("character.py", "calc", "-c", "eden", "--class", "Mechanic",
                              "--background", "Ex-EDEN Technician", "--background-asi", "STR=2,CON=1", *BASE)
        self.assertEqual(bad.returncode, 2)

    def test_unknown_origin_refused_in_world(self):
        r = self.run_script("character.py", "calc", "-c", "eden", "--race", "elf", *BASE)
        self.assertEqual(r.returncode, 2)

    def test_world_origin_unknown_without_worldkit(self):
        r = self.run_script("character.py", "calc", "-c", "plain", "--race", "Tunnel-Born", *BASE)
        self.assertEqual(r.returncode, 2)

    def test_srd_race_still_works_in_plain_campaign(self):
        r = self.run_script("character.py", "calc", "-c", "plain", "--race", "dwarf", *BASE)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_levelup_uses_chassis(self):
        r = self.run_script("character.py", "levelup", "-c", "eden", "--class", "Infiltrator",
                            "--from", "2", "--con-mod", "2")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("HP gained (avg): 7", r.stdout)    # d8 rogue chassis
        self.assertIn("subclass", r.stdout)               # rogue picks at 3


class SupplementalTests(_CampaignRoot):
    def test_world_campaign_skips_wikidot_fetch(self):
        sheet = self.root / "campaigns" / "eden" / "characters" / "kade.md"
        sheet.write_text("# Kade\n## Spells\n- Overclock Shield\n", encoding="utf-8")
        r = self.run_script("build_supplemental.py", "--character", str(sheet))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("worldkit", (r.stdout + r.stderr).lower())


class ThaiAndRulesTests(_CampaignRoot):
    """Thai names, rules-category merge, world subclasses."""

    def _rewrite_kit(self, mutate):
        p = self.root / "campaigns" / "eden" / "worldkit.json"
        kit = json.loads(p.read_text(encoding="utf-8"))
        mutate(kit)
        p.write_text(json.dumps(kit, ensure_ascii=False), encoding="utf-8")
        return kit

    def test_thai_names_are_distinct_and_resolve(self):
        def add(kit):
            kit["classes"].append({"name": "ทหารราบ", "chassis": "fighter"})
            for src, th in ((0, "ผู้เฝ้ามอง"), (1, "ผู้เก็บเกี่ยว")):
                m = copy.deepcopy(kit["monsters"][src])
                m["name"] = th
                m.pop("index")
                kit["monsters"].append(m)
        kit = self._rewrite_kit(add)
        self.assertEqual(worldkit.validate(kit), [])
        r = self.run_script("lookup.py", "monster", "ผู้เก็บเกี่ยว", "--campaign", "eden")
        self.assertIn("ผู้เก็บเกี่ยว", r.stdout.splitlines()[0])
        r = self.run_script("character.py", "calc", "-c", "eden", "--class", "ทหารราบ", *BASE)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("fighter chassis", r.stdout)

    def test_world_condition_does_not_hide_srd_conditions(self):
        self._rewrite_kit(lambda k: k.__setitem__("conditions", [
            {"name": "Jammed", "index": "jammed", "description": "Your tech fails."}]))
        self.assertIn("Poisoned", self.run_script("lookup.py", "condition", "poisoned",
                                                  "--campaign", "eden").stdout)
        self.assertIn("Jammed", self.run_script("lookup.py", "condition", "jammed",
                                                "--campaign", "eden").stdout)

    def test_world_subclasses_replace_srd_ones(self):
        r = self.run_script("character.py", "levelup", "-c", "eden", "--class", "Infiltrator",
                            "--from", "2", "--con-mod", "2")
        self.assertIn("Infiltration Method", r.stdout)
        self.assertIn("Ghost", r.stdout)
        self.assertNotIn("Roguish Archetype", r.stdout)

    def test_bad_subclasses_refused(self):
        kit = copy.deepcopy(KIT)
        kit["classes"][0]["subclasses"] = ["Ghost"]
        self.assertTrue(any("subclasses" in e for e in worldkit.validate(kit)))


if __name__ == "__main__":
    unittest.main()
