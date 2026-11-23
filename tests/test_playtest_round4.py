"""Regressions from the final acceptance runs (round 4)."""
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

from tests._unicode import needs_unicode_fs

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "skills" / "dne" / "scripts"
FIXTURE = ROOT / "tests" / "fixtures" / "worldkit-eden.json"
KIT = json.loads(FIXTURE.read_text(encoding="utf-8"))
BASE = ["STR=15", "DEX=13", "CON=14", "INT=8", "WIS=12", "CHA=10"]
sys.path.insert(0, str(SCRIPTS))

SHEET = """# {name}

## Identity
- **Race:** Tunnel-Born | **Class:** {cls} | **Level:** {level} | **XP:** {xp}

## Combat Stats
- **HP:** 13 / 13 | **Temp HP:** 0
- **Hit Dice:** {level}d10 (remaining: {level})

## Equipment & Inventory
**Weapons:**
-

**Adventuring Gear:**
- Rope

**Currency:** 100 sc
"""


class _Camp(unittest.TestCase):
    ruleset = "2014"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)
        self.camp = self.root / "campaigns" / "eden"
        (self.camp / "characters").mkdir(parents=True)
        (self.camp / "state.md").write_text(
            f"**Ruleset:** {self.ruleset}\n**Party size:** 2  **Starting level:** 1\n", encoding="utf-8")
        shutil.copy(FIXTURE, self.camp / "worldkit.json")
        self.env = {**os.environ, "DNE_CAMPAIGN_ROOT": str(self.root),
                    "DNE_RUNTIME_DIR": str(self.root / ".rt"), "DNE_DICE_PHYSICAL": "0"}

    def tearDown(self):
        self._tmp.cleanup()

    def sheet(self, fname, name, level=1, cls="Soldier (fighter chassis)", xp=0):
        p = self.camp / "characters" / f"{fname}.md"
        p.write_text(SHEET.format(name=name, level=level, cls=cls, xp=xp), encoding="utf-8")
        return p

    def run_py(self, script, *args):
        return subprocess.run([sys.executable, str(SCRIPTS / script), *args],
                              capture_output=True, encoding="utf-8", env=self.env)


# ── character.py ───────────────────────────────────────────────────────────
class Character2014BackgroundTests(_Camp):
    def calc(self, *a):
        return self.run_py("character.py", "calc", "-c", "eden", *a)

    def test_2014_world_origin_plus_background_skills(self):
        r = self.calc("--class", "Soldier", "--race", "Tunnel-Born", "--background", "Hollow Guard", *BASE)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(r.stdout, r"CON\s+14\s+\+2\s+16")      # origin bonus still applies (2014)
        self.assertRegex(r.stdout, r"\*\s+Athletics")             # background skills granted
        self.assertRegex(r.stdout, r"\*\s+Perception")
        self.assertNotIn("background-asi", r.stdout + r.stderr)   # no 2024 advice in 2014

    def test_2014_background_asi_refused(self):
        r = self.calc("--class", "Soldier", "--background", "Hollow Guard", "--background-asi", "STR=2,CON=1", *BASE)
        self.assertEqual(r.returncode, 2)
        self.assertIn("2014", r.stderr)

    def test_bad_damage_string_refused(self):
        r = subprocess.run([sys.executable, str(SCRIPTS / "combat.py"), "attack", "--atk", "5", "--ac", "1",
                            "--roll", "15", "--dmg", "1d8 Slashing+5"], capture_output=True, encoding="utf-8")
        self.assertEqual(r.returncode, 2)

    def test_subclass_must_be_a_world_option(self):
        r = self.calc("--class", "Infiltrator", "--level", "3", "--subclass", "Bogus", *BASE)
        self.assertEqual(r.returncode, 2)
        self.assertIn("Ghost", r.stderr)

    def test_fighting_style_must_exist(self):
        r = self.calc("--class", "Soldier", "--fighting-style", "bogus", *BASE)
        self.assertEqual(r.returncode, 2)

    def test_caster_block(self):
        r = self.calc("--class", "Mechanic", "--level", "1", *BASE)     # wizard chassis, INT 8 (-1)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(r.stdout, r"Spell save DC:\s*9")             # 8 + 2 - 1
        self.assertRegex(r.stdout, r"Spell attack:\s*\+1")
        self.assertRegex(r.stdout, r"1st-level slots:\s*2")

    def test_help_mentions_expertise(self):
        r = subprocess.run([sys.executable, str(SCRIPTS / "character.py"), "calc", "--help"],
                           capture_output=True, encoding="utf-8")
        self.assertIn("--expertise", r.stdout)

    def test_levelup_lists_new_chassis_features(self):
        r = self.run_py("character.py", "levelup", "-c", "eden", "--class", "Soldier", "--from", "1", "--con-mod", "1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Action Surge", r.stdout)

    def test_levelup_names_new_powers_owed(self):
        kit = copy.deepcopy(KIT)
        (self.camp / "worldkit.json").write_text(json.dumps(kit), encoding="utf-8")
        r = self.run_py("character.py", "levelup", "-c", "eden", "--class", "Mechanic", "--from", "1", "--con-mod", "1")
        self.assertRegex(r.stdout, r"(?i)choose|learn")
        self.assertIn("Overclock Shield", r.stdout)                  # lists eligible kit powers

    def test_hitdie_accepts_player_roll(self):
        r = self.run_py("character.py", "hitdie", "--die", "d10", "--con-mod", "2", "--hp", "5", "--max-hp", "20",
                        "--remaining", "2", "--count", "1", "--roll", "7")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertRegex(r.stdout, r"\b14\b")                         # 5 + 7 + 2


# ── xp.py / encounter_gen.py party levels ──────────────────────────────────
class PartyLevelTests(_Camp):
    def test_mixed_level_party_uses_per_character_thresholds(self):
        self.sheet("jo", "Jo", level=3)
        self.sheet("zeke", "Zeke", level=4)
        r = self.run_py("xp.py", "award", "--campaign", "eden", "--characters", "Jo,Zeke", "--difficulty", "easy")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        # DMG easy: L3 75, L4 125 → each PC gets their own threshold
        self.assertRegex(r.stdout, r"Jo\D+75\b")
        self.assertRegex(r.stdout, r"Zeke\D+125\b")

    def test_encounter_party_from_sheets(self):
        self.sheet("jo", "Jo", level=3)
        self.sheet("zeke", "Zeke", level=4)
        r = self.run_py("encounter_gen.py", "-c", "eden", "--biome", "surface", "--seed", "1", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        enc = json.loads(r.stdout)
        self.assertEqual(enc["party_size"], 2)
        self.assertEqual(enc["party_level"], 4)                       # round-half-up of 3.5

    def test_label_matches_actual_band(self):
        r = self.run_py("encounter_gen.py", "-c", "eden", "--biome", "tunnels", "--party-level", "3",
                        "--party-size", "4", "--difficulty", "deadly", "--seed", "1")
        out = r.stdout + r.stderr
        if r.returncode == 0:
            m = re.search(r"\[[^\]·]+·\s*([A-Z]+)\]", r.stdout)
            self.assertTrue(m)
            if "under budget" not in out.lower():
                self.assertEqual(m.group(1), "DEADLY")


# ── calendar ───────────────────────────────────────────────────────────────
class CalendarMinuteTests(_Camp):
    def test_advance_minutes_and_time_labels_listed(self):
        cal = lambda *a: self.run_py("calendar.py", "-c", "eden", *a)
        self.assertEqual(cal("init", "--gregorian", "--date", "14 May 1881", "--time", "morning").returncode, 0)
        self.assertIn("Saturday", cal("now").stdout)
        r = cal("advance", "30", "minutes")
        self.assertEqual(r.returncode, 0, r.stderr)
        r = cal("init", "--date", "1 May 1881", "--time", "dusk-ish")
        self.assertEqual(r.returncode, 2)
        self.assertIn("dawn", r.stderr)                               # lists valid labels


# ── dice / combat output ───────────────────────────────────────────────────
class RollOutputTests(unittest.TestCase):
    def test_dice_player_without_server_is_marked_local(self):
        r = subprocess.run([sys.executable, str(SCRIPTS / "dice.py"), "d20", "--player", "jo", "--label", "x"],
                           capture_output=True, encoding="utf-8",
                           env={**os.environ, "DNE_DICE_PHYSICAL": "0"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("local", (r.stdout + r.stderr).lower())

    def test_combat_adv_shows_both_dice(self):
        r = subprocess.run([sys.executable, str(SCRIPTS / "combat.py"), "attack", "--atk", "5", "--ac", "10",
                            "--dmg", "1d6", "--roll", "4,17", "--adv"], capture_output=True, encoding="utf-8")
        self.assertIn("4", r.stdout.split("vs AC")[0])
        self.assertIn("17", r.stdout.split("vs AC")[0])

    def test_combat_help_documents_player_rolls(self):
        r = subprocess.run([sys.executable, str(SCRIPTS / "combat.py"), "--help"], capture_output=True, encoding="utf-8")
        for flag in ("--roll", "--adv", "--crit-range", '"roll"'):
            self.assertIn(flag, r.stdout)


# ── graph ──────────────────────────────────────────────────────────────────
class GraphThaiIdTests(unittest.TestCase):
    def test_slug_keeps_thai_marks(self):
        import campaign_graph
        self.assertNotEqual(campaign_graph._slug("ตลาดน้ำมืด"), campaign_graph._slug("ตลาดนามด"))
        self.assertNotIn("_", campaign_graph._slug("เจ๊หงส์"))


# ── snapshots ──────────────────────────────────────────────────────────────
class RedoTests(_Camp):
    def test_undo_then_redo(self):
        st = self.camp / "state.md"
        self.assertEqual(self.run_py("turn_snapshot.py", "-c", "eden", "save", "--label", "a").returncode, 0)
        st.write_text("changed\n", encoding="utf-8")
        self.assertEqual(self.run_py("turn_snapshot.py", "-c", "eden", "undo").returncode, 0)
        self.assertNotEqual(st.read_text(encoding="utf-8"), "changed\n")
        r = self.run_py("turn_snapshot.py", "-c", "eden", "redo")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(st.read_text(encoding="utf-8"), "changed\n")

    def test_session_tail_is_tracked(self):
        import turn_snapshot
        self.assertIn("session_tail.json", turn_snapshot.CAMPAIGN_FILES)


# ── session recap ──────────────────────────────────────────────────────────
class RecapLevelUpTests(unittest.TestCase):
    def test_level_up_is_not_healing(self):
        import session_recap
        before = {"name": "Ray", "level": 1, "hp": 12, "max_hp": 12, "hit_dice_total": 1, "hit_dice_remaining": 1}
        after = {"name": "Ray", "level": 2, "hp": 22, "max_hp": 22, "hit_dice_total": 2, "hit_dice_remaining": 2}
        text = session_recap.describe_change(before, after) if hasattr(session_recap, "describe_change") else None
        if text is None:
            self.skipTest("session_recap exposes no describe_change; covered by CLI test below")
        self.assertNotIn("healed", text)


class RecapCliTests(_Camp):
    def test_recap_diff_level_up_wording(self):
        p = self.sheet("ray", "Ray", level=1)
        self.assertEqual(self.run_py("session_recap.py", "-c", "eden", "snapshot").returncode, 0)
        p.write_text(p.read_text(encoding="utf-8").replace("**Level:** 1", "**Level:** 2")
                     .replace("13 / 13", "22 / 22").replace("1d10 (remaining: 1)", "2d10 (remaining: 2)"),
                     encoding="utf-8")
        r = self.run_py("session_recap.py", "-c", "eden", "diff")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("healed", r.stdout)
        self.assertNotIn("recovered", r.stdout)
        self.assertIn("max HP 13→22", r.stdout)


# ── worldkit ───────────────────────────────────────────────────────────────
class WorldkitRound4Tests(_Camp):
    def test_show_formatting(self):
        r = self.run_py("worldkit.py", "show", "eden")
        self.assertNotIn("AC AC", r.stdout)
        self.assertNotIn("['", r.stdout)

    def test_more_validation(self):
        import worldkit
        def errs(mutate):
            k = copy.deepcopy(KIT)
            mutate(k)
            return worldkit.validate(k)
        self.assertTrue(any("level" in e for e in errs(
            lambda k: k["spells"][0].update(level=3))))               # Static Burst = Fire Bolt (cantrip)
        self.assertTrue(any("power" in e for e in errs(lambda k: k["_meta"].update(power="bogus"))))
        self.assertTrue(any("speed" in e for e in errs(lambda k: k["races"][0].update(speed="fast"))))
        self.assertTrue(any("biome" in e for e in errs(lambda k: k["monsters"][0].update(biomes=["surface "]))))

    def test_unicode_damage_type_allowed(self):
        import worldkit
        k = copy.deepcopy(KIT)
        k["equipment"][0]["damage"] = "1d10 แทง"
        self.assertEqual(worldkit.validate(k), [])

    def test_lexicon_warning_threshold(self):
        import worldkit
        k = copy.deepcopy(KIT)
        k["lexicon"] = dict(list(k["lexicon"].items())[:5])
        self.assertFalse(any("lexicon" in w for w in worldkit.warnings(k)))


# ── name registry ──────────────────────────────────────────────────────────
class RegistryHonorificTests(_Camp):
    @needs_unicode_fs
    def test_titles_do_not_hide_duplicates(self):
        self.run_py("name_registry.py", "add", "--name", "Pastor Gideon Ashby", "--type", "npc",
                    "--campaign", "eden", "--session", "0")
        for probe in ("Gideon Ashby", "Reverend Gideon Ashby"):
            self.assertNotEqual(self.run_py("name_registry.py", "check", probe).returncode, 0, probe)
        self.run_py("name_registry.py", "add", "--name", "ผู้กองสายชล", "--type", "npc",
                    "--campaign", "eden", "--session", "0")
        self.assertNotEqual(self.run_py("name_registry.py", "check", "สายชล").returncode, 0)

    def test_ayutthaya_titles_and_no_overstrip(self):
        import name_registry as nr
        for titled, bare in (("คุณหญิงจำปา", "จำปา"), ("ออกญาเดชา", "เดชา"), ("พระครูทองคำ", "ทองคำ"),
                             ("ผู้กองสายชล", "สายชล"), ("เจ้าพระยาจักรี", "จักรี")):
            self.assertEqual(nr.slug(titled), nr.slug(bare), titled)
        self.assertEqual(nr.slug("คุณากร"), "คุณากร")                 # sara aa after คุณ: not a title

    @needs_unicode_fs
    def test_duplicate_message_names_the_existing_entry(self):
        self.run_py("name_registry.py", "add", "--name", "หมื่นเดชา", "--type", "pc",
                    "--campaign", "eden", "--session", "0")
        r = self.run_py("name_registry.py", "check", "นายเดชา")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("หมื่นเดชา", r.stdout + r.stderr)

    @needs_unicode_fs
    def test_accents_fold(self):
        self.run_py("name_registry.py", "add", "--name", "Inés Calloway", "--type", "npc",
                    "--campaign", "eden", "--session", "0")
        self.assertNotEqual(self.run_py("name_registry.py", "check", "Ines Calloway").returncode, 0)


# ── economy / tracker ──────────────────────────────────────────────────────
class EconomyTrackerRound4Tests(_Camp):
    def test_char_by_unique_first_name_and_weapon_section(self):
        p = self.sheet("nora-castellanos", "Nora Castellanos")
        r = self.run_py("economy.py", "-c", "eden", "buy", "--char", "Nora", "--item", "Rail Pistol", "--cost", "50")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        text = p.read_text(encoding="utf-8")
        weapons = text.split("**Weapons:**", 1)[1].split("**Adventuring Gear:**", 1)[0]
        self.assertIn("Rail Pistol", weapons)                         # kit category Weapon → Weapons list

    def test_clear_prunes_enemies_and_expired_effect_conditions(self):
        t = lambda *a: self.run_py("tracker.py", "-c", "eden", *a)
        t("enemy", "set", "Reaper", "--role", "brute")
        t("condition", "add", "Reaper", "prone")
        t("clear")
        self.assertNotIn("Reaper", t("status").stdout)


if __name__ == "__main__":
    unittest.main()
