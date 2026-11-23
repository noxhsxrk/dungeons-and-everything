"""Round 6: regressions from the Himmapan (2014, Thai) and Perihelion (2024) re-verification runs."""
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
FIXTURE = ROOT / "tests" / "fixtures" / "worldkit-eden.json"
KIT = json.loads(FIXTURE.read_text(encoding="utf-8"))
sys.path.insert(0, str(SCRIPTS))


class _Camp(unittest.TestCase):
    ruleset = "2014"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)
        self.camp = self.root / "campaigns" / "eden"
        (self.camp / "characters").mkdir(parents=True)
        (self.camp / "state.md").write_text(f"**Ruleset:** {self.ruleset}\n", encoding="utf-8")
        kit = copy.deepcopy(KIT)
        for c in kit["classes"]:
            if c["index"] == "soldier":
                c["subclass_label"] = "Posting"
                c["subclasses"] = [{"name": "Line Guard", "description": "Chassis: Champion."},
                                   {"name": "Breach Lead", "description": "Re-skins Battle Master (not SRD)."}]
        (self.camp / "worldkit.json").write_text(json.dumps(kit), encoding="utf-8")
        self.env = {**os.environ, "DNE_CAMPAIGN_ROOT": str(self.root),
                    "DNE_RUNTIME_DIR": str(self.root / ".rt"), "DNE_DICE_PHYSICAL": "0"}

    def tearDown(self):
        self._tmp.cleanup()

    def run_py(self, script, *args):
        return subprocess.run([sys.executable, str(SCRIPTS / script), *args],
                              capture_output=True, encoding="utf-8", env=self.env)

    def levelup(self, *args):
        r = self.run_py("character.py", "levelup", "-c", "eden", "--con-mod", "1", *args)
        self.assertEqual(r.returncode, 0, r.stderr)
        return next((l for l in r.stdout.splitlines() if "New features" in l), "")


class LevelupFeatures2014Tests(_Camp):
    def test_srd_subclass_features_only_for_the_matching_subclass(self):
        self.assertIn("Improved Critical", self.levelup("--class", "Soldier", "--from", "2", "--subclass", "Line Guard"))
        self.assertNotIn("Improved Critical", self.levelup("--class", "Soldier", "--from", "2",
                                                            "--subclass", "Breach Lead"))

    def test_option_subfeatures_not_listed(self):
        kit = json.loads((self.camp / "worldkit.json").read_text(encoding="utf-8"))
        kit["classes"].append({"name": "Hexslinger", "index": "hexslinger", "chassis": "warlock"})
        kit["spells"].append({"name": "Cold Lead", "index": "cold-lead", "level": 1, "classes": ["Hexslinger"],
                              "description": "x (chassis: Hellish Rebuke)"})
        (self.camp / "worldkit.json").write_text(json.dumps(kit), encoding="utf-8")
        line = self.levelup("--class", "Hexslinger", "--from", "2")
        self.assertNotIn("Pact of the Chain", line)


class LevelupFeatures2024Tests(_Camp):
    ruleset = "2024"

    def test_2024_features_come_from_2024_data(self):
        line = self.levelup("--class", "Soldier", "--from", "1")
        self.assertIn("Tactical Mind", line)

    def test_rogue_weapon_mastery_2024(self):
        r = self.run_py("character.py", "levelup", "-c", "eden", "--class", "Infiltrator", "--from", "0", "--con-mod", "1")
        self.assertRegex(r.stdout, r"Weapon Mastery.*2")


class Xp2024Tests(_Camp):
    ruleset = "2024"

    def test_award_has_no_multiplier_and_2024_bands(self):
        for name in ("dana", "theo"):
            (self.camp / "characters" / f"{name}.md").write_text(
                f"# {name.title()}\n- **Class:** Soldier | **Level:** 2 | **XP:** 0\n", encoding="utf-8")
        r = self.run_py("xp.py", "award", "--campaign", "eden", "--characters", "Dana,Theo",
                        "--monsters", "a:1/4:2,b:1:1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("×1", r.stdout)
        self.assertNotIn("DEADLY", r.stdout)            # 300 raw vs 2024 L2×2 budgets 200/300/400 → medium

    def test_calc_uses_campaign_ruleset(self):
        r = self.run_py("xp.py", "calc", "-c", "eden", "--level", "2", "--players", "2", "--difficulty", "medium")
        self.assertIn("150", r.stdout)                  # 2024 Moderate at level 2


class Encounter2024MixedTests(_Camp):
    ruleset = "2024"

    def test_mixed_levels_sum_budgets(self):
        for name, lvl in (("a", 3), ("b", 2)):
            (self.camp / "characters" / f"{name}.md").write_text(f"# {name}\n- **Level:** {lvl}\n", encoding="utf-8")
        r = self.run_py("encounter_gen.py", "-c", "eden", "--biome", "surface", "--difficulty", "medium",
                        "--seed", "1", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["xp_budget"], 375)   # 225 + 150


class Lookup2024CampaignTests(_Camp):
    ruleset = "2024"

    def test_fighting_style_in_2024_campaign(self):
        kit = json.loads((self.camp / "worldkit.json").read_text(encoding="utf-8"))
        kit["_meta"]["base_ruleset"] = "2024"
        (self.camp / "worldkit.json").write_text(json.dumps(kit), encoding="utf-8")
        r = self.run_py("lookup.py", "fighting-style", "defense", "--campaign", "eden")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("Defense", r.stdout)


class GraphEdgesTests(_Camp):
    def test_edges_between_shown_nodes_included(self):
        g = lambda *a: self.run_py("campaign_graph.py", *a)
        g("init", "--campaign", "eden")
        for nid, typ, name in (("place_dock", "location", "Dock"), ("npc_a", "npc", "Ana"),
                               ("faction_x", "faction", "Order X"), ("npc_b", "npc", "Bo")):
            g("add-node", "--campaign", "eden", "--id", nid, "--type", typ, "--name", name)
        g("add-edge", "--campaign", "eden", "--from", "npc_a", "--to", "place_dock", "--type", "located_at", "--since", "1")
        g("add-edge", "--campaign", "eden", "--from", "npc_a", "--to", "npc_b", "--type", "knows", "--since", "1")
        g("add-edge", "--campaign", "eden", "--from", "npc_b", "--to", "faction_x", "--type", "member_of", "--since", "1")
        g("add-edge", "--campaign", "eden", "--from", "npc_a", "--to", "faction_x", "--type", "hostile_to", "--since", "1")
        r = g("scene-context", "--campaign", "eden", "--place", "place_dock", "--hops", "1", "--at-session", "1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        if "Order X" in r.stdout and "Bo" in r.stdout:
            self.assertIn("member_of", r.stdout)


class RestAndRegistryTests(_Camp):
    def test_short_rest_at_zero_hp_spends_nothing(self):
        p = self.camp / "characters" / "bua.md"
        p.write_text("# Bua\n## Combat Stats\n- **HP:** 0 / 11 | **Temp HP:** 0\n- **Hit Dice:** 1d8 (remaining: 1)\n"
                     "## Equipment & Inventory\n**Currency:** 5\n", encoding="utf-8")
        self.run_py("economy.py", "-c", "eden", "rest", "--char", "bua", "--type", "short", "--hit-dice", "1", "--heal", "5")
        text = p.read_text(encoding="utf-8")
        self.assertIn("**HP:** 0 / 11", text)
        self.assertIn("(remaining: 1)", text)

    def test_teacher_and_healer_titles(self):
        import name_registry as nr
        for titled in ("อาจารย์คง", "แม่หมอคง", "พ่อหมอคง"):
            self.assertEqual(nr.slug(titled), nr.slug("คง"), titled)
        self.assertEqual(nr.slug("หมอก"), "หมอก")                   # "fog", not a title + ก

    def test_dead_shows_dead(self):
        t = lambda *a: self.run_py("tracker.py", "-c", "eden", *a)
        t("condition", "add", "Theo", "unconscious")
        for _ in range(3):
            t("saves", "Theo", "failure")
        self.assertIn("Theo: DEAD", t("status").stdout)


if __name__ == "__main__":
    unittest.main()


class RedoSafetyTests(_Camp):
    def test_redo_refuses_after_play_continued(self):
        st = self.camp / "state.md"
        snap = lambda *a: self.run_py("turn_snapshot.py", "-c", "eden", *a)
        snap("save", "--label", "t1")
        st.write_text("turn 2\n", encoding="utf-8")
        self.assertEqual(snap("undo").returncode, 0)
        st.write_text("new timeline after undo\n", encoding="utf-8")
        r = snap("redo")
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(st.read_text(encoding="utf-8"), "new timeline after undo\n")

    def test_redo_still_works_right_after_undo(self):
        st = self.camp / "state.md"
        snap = lambda *a: self.run_py("turn_snapshot.py", "-c", "eden", *a)
        snap("save", "--label", "t1")
        st.write_text("turn 2\n", encoding="utf-8")
        snap("undo")
        r = snap("redo")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(st.read_text(encoding="utf-8"), "turn 2\n")
        self.assertIn("Redid", r.stdout)


class SellQuantityFormatTests(_Camp):
    def test_sell_from_parenthesised_quantity(self):
        p = self.camp / "characters" / "dech.md"
        p.write_text("# Dech\n## Equipment & Inventory\n**Weapons:**\n- หอก (×2)\n\n**Currency:** 5\n", encoding="utf-8")
        r = self.run_py("economy.py", "-c", "eden", "sell", "--char", "dech", "--item", "หอก", "--value", "1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("- หอก ×1", p.read_text(encoding="utf-8"))


class Final2024Tests(_Camp):
    ruleset = "2024"

    def test_2024_fighting_style_text(self):
        kit = json.loads((self.camp / "worldkit.json").read_text(encoding="utf-8"))
        kit["_meta"]["base_ruleset"] = "2024"
        (self.camp / "worldkit.json").write_text(json.dumps(kit), encoding="utf-8")
        r = self.run_py("lookup.py", "fighting-style", "great weapon fighting", "--campaign", "eden")
        self.assertIn("as a 3", r.stdout)               # 2024 rule, not the 2014 reroll

    def test_2024_expertise_at_rogue_6(self):
        r = self.run_py("character.py", "levelup", "-c", "eden", "--class", "Infiltrator", "--from", "5", "--con-mod", "1")
        self.assertIn("Expertise", r.stdout)

    def test_2024_bands(self):
        for name, lvl in (("a", 3), ("b", 2)):
            (self.camp / "characters" / f"{name}.md").write_text(f"# {name}\n- **Level:** {lvl}\n", encoding="utf-8")
        r = self.run_py("encounter_gen.py", "-c", "eden", "--biome", "surface", "--difficulty", "deadly", "--seed", "1")
        self.assertIn("2024 has no Deadly tier", r.stdout)
        self.assertNotIn("TRIVIAL", r.stdout)
        r = self.run_py("xp.py", "calc", "-c", "eden", "--level", "3", "--players", "2", "--difficulty", "deadly")
        self.assertIn("HIGH", r.stdout)


class FinalRestCalendarTests(_Camp):
    def sheet(self, hp, rem, cls="Hexslinger (warlock chassis)"):
        p = self.camp / "characters" / "mae.md"
        p.write_text(f"# Mae\n- **Class:** {cls} | **Level:** 1\n## Combat Stats\n- **HP:** {hp} / 13 | **Temp HP:** 0\n"
                     f"- **Hit Dice:** 1d8 (remaining: {rem})\n## Spell Slots\n| Level | Total | Used |\n|---|---|---|\n"
                     "| 1st | 1 | 1 |\n## Equipment & Inventory\n**Currency:** 5\n", encoding="utf-8")
        return p

    def test_zero_hp_short_rest_gives_nothing(self):
        p = self.sheet(0, 1)
        self.run_py("economy.py", "-c", "eden", "rest", "--char", "mae", "--type", "short")
        self.assertIn("| 1st | 1 | 1 |", p.read_text(encoding="utf-8"))     # pact slot NOT restored

    def test_no_dice_left_no_healing(self):
        p = self.sheet(5, 0, cls="Soldier (fighter chassis)")
        r = self.run_py("economy.py", "-c", "eden", "rest", "--char", "mae", "--type", "short",
                        "--hit-dice", "1", "--heal", "9")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("**HP:** 5 / 13", p.read_text(encoding="utf-8"))

    def test_gregorian_with_thai_names(self):
        months = "มกราคม,กุมภาพันธ์,มีนาคม,เมษายน,พฤษภาคม,มิถุนายน,กรกฎาคม,สิงหาคม,กันยายน,ตุลาคม,พฤศจิกายน,ธันวาคม"
        days = "จันทร์,อังคาร,พุธ,พฤหัสบดี,ศุกร์,เสาร์,อาทิตย์"
        r = self.run_py("calendar.py", "-c", "eden", "init", "--gregorian", "--date", "14 พฤศจิกายน 2077",
                        "--months", months, "--day-names", days)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("อาทิตย์, 14 พฤศจิกายน 2077", r.stdout)
        r = self.run_py("calendar.py", "-c", "eden", "advance", "17", "days")
        self.assertIn("1 ธันวาคม 2077", r.stdout)


class ZeroHpTrackerTests(_Camp):
    ruleset = "2024"

    def test_long_rest_keeps_exhaustion_at_zero_hp_and_death_saves_take_penalty(self):
        (self.camp / "characters" / "tamsin-vey.md").write_text(
            "# Tamsin Vey\n## Combat Stats\n- **HP:** 0 / 17 | **Temp HP:** 0\n", encoding="utf-8")
        t = lambda *a: self.run_py("tracker.py", "-c", "eden", *a)
        t("condition", "add", "Tamsin Vey", "exhausted")
        t("condition", "add", "Tamsin Vey", "unconscious")
        t("clear")
        self.assertIn("nconscious", t("status").stdout)                  # still down after combat
        self.run_py("calendar.py", "-c", "eden", "init", "--date", "1 Alpha 1", "--months", "Alpha")
        r = self.run_py("calendar.py", "-c", "eden", "rest", "long")
        self.assertNotIn("exhaustion 1 → 0", r.stdout)
        import tracker
        os.environ["DNE_CAMPAIGN_ROOT"] = str(self.root)
        try:
            mods = tracker.active_modifiers("eden", "Tamsin Vey", "death")
        finally:
            os.environ.pop("DNE_CAMPAIGN_ROOT", None)
        self.assertIn(("Exhaustion 1", "-2"), mods)


class FinalPolishTests(_Camp):
    def test_sell_prefix_quantity_and_note(self):
        p = self.camp / "characters" / "klaa.md"
        p.write_text("# จ่ากล้า เหล็กเพชร\n## Equipment & Inventory\n**Adventuring Gear:**\n- 2× เซลล์ไฟ\n- กระสุนเรล (20 นัด)\n\n"
                     "**Currency:** 5\n", encoding="utf-8")
        for item in ("เซลล์ไฟ", "กระสุนเรล"):
            r = self.run_py("economy.py", "-c", "eden", "sell", "--char", "กล้า", "--item", item, "--value", "1")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        text = p.read_text(encoding="utf-8")
        self.assertIn("เซลล์ไฟ ×1", text)
        self.assertNotIn("กระสุนเรล", text)
        ledger = json.loads((self.camp / ".economy_ledger.json").read_text(encoding="utf-8"))
        self.assertEqual({e["character"] for e in ledger}, {"จ่ากล้า เหล็กเพชร"})

    def test_world_subclass_lookup(self):
        r = self.run_py("lookup.py", "subclass", "Line Guard", "-c", "eden")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("Champion", r.stdout)

    def test_long_rest_reports_slots_and_temp_hp(self):
        p = self.camp / "characters" / "mae.md"
        p.write_text("# Mae\n## Combat Stats\n- **HP:** 10 / 10 | **Temp HP:** 2\n- **Hit Dice:** 1d8 (remaining: 1)\n"
                     "## Spell Slots\n| Level | Total | Used |\n|---|---|---|\n| 1st | 2 | 2 |\n"
                     "## Equipment & Inventory\n**Currency:** 5\n", encoding="utf-8")
        r = self.run_py("economy.py", "-c", "eden", "rest", "--char", "mae", "--type", "long")
        self.assertIn("spell_slots_restored=2", r.stdout)
        self.assertIn("temp_hp=2->0", r.stdout)


class RoughEdgeTests(unittest.TestCase):
    def test_thai_graph_extraction(self):
        import graph_extract_deterministic as g
        with tempfile.TemporaryDirectory() as d:
            d = pathlib.Path(d)
            (d / "npcs.md").write_text("| Name | Role |\n|---|---|\n| เจ๊หงส์ | x |\n| หลวงพี่ไบต์ | y |\n| ผู้กองสายชล | z |\n",
                                       encoding="utf-8")
            (d / "session-log.md").write_text(
                "## Session 1\n\nเจ๊หงส์พบกับหลวงพี่ไบต์ที่ท่าเรือ ผู้กองสายชลจับตาดูเจ๊หงส์ตลอดคืน.\n", encoding="utf-8")
            got = {(p["from"], p["type"], p["to"]) for p in g.extract_proposals(d)}
        self.assertTrue({("เจ๊หงส์", "met", "หลวงพี่ไบต์"), ("หลวงพี่ไบต์", "met", "เจ๊หงส์")} & got)  # symmetric
        self.assertIn(("ผู้กองสายชล", "watches", "เจ๊หงส์"), got)

    def test_srd_subclass_lookup(self):
        r = subprocess.run([sys.executable, str(SCRIPTS / "lookup.py"), "subclass", "champion", "--ruleset", "2014"],
                           capture_output=True, text=True)
        self.assertIn("Improved Critical", r.stdout)

    def test_origin_trait_skill_auto(self):
        import character
        kit = {"skills": {}}
        self.assertEqual(character._origin_skills({"traits": ["หูตลาด: ชำนาญทักษะ Sleight of Hand"]}, kit),
                         ["Sleight of Hand"])
        self.assertEqual(character._origin_skills({"skills": ["Stealth"], "traits": []}, kit), ["Stealth"])

    def test_thai_time_labels(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("dne_calendar", SCRIPTS / "calendar.py")
        cal = importlib.util.module_from_spec(spec); spec.loader.exec_module(cal)
        self.assertEqual(cal._time_hour("กลางคืน"), 22)
