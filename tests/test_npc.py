"""NPCs get a real record the turn they appear, and grow while the party is away."""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _unicode import needs_unicode_fs  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "skills" / "dne" / "scripts"
DISPLAY = ROOT / "skills" / "dne" / "display"

KAVIN = """# NPCs (full entries) — eden

## Kavin Techaporn
- **Role:** อันดับ 7 ของ Top 10 | **CR/Level:** CR 4 (Rank-A Elite) | **Location:** สนามหญ้า
- **HP:** 65 | **AC:** 16 | **Attack:** Anomaly Burst +6 (3d8 force) | **Notable abilities:** แรงกดอากาศ
- **Attitude toward party:** neutral

### Relationships
- **Knows:** Rina — เด็กใหม่

---
"""


class NpcTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)
        self.rt = self.root / "rt"
        self.rt.mkdir()
        self.camp = self.root / "campaigns" / "eden"
        self.camp.mkdir(parents=True)
        (self.camp / "state.md").write_text("# Campaign: eden\n## Session Flags\n- autorun: true\n", encoding="utf-8")
        (self.camp / "npcs.md").write_text(
            "# NPCs — eden\n\n| Name | Role | Faction | Location | Attitude | Notes |\n|---|---|---|---|---|---|\n"
            "| Kavin Techaporn | อันดับ 7 | Top 10 | สนามหญ้า | neutral | |\n| Malee Worakij | คุณยาย | | บ้าน | allied | |\n",
            encoding="utf-8")
        (self.camp / "npcs-full.md").write_text(KAVIN, encoding="utf-8")
        self.set_date(15, 5)
        (self.rt / ".campaign").write_text("eden", encoding="utf-8")
        self.env = {**os.environ, "DNE_CAMPAIGN_ROOT": str(self.root), "DNE_RUNTIME_DIR": str(self.rt),
                    "DNE_DISPLAY_HOST": "127.0.0.1:9"}

    def tearDown(self):
        self._tmp.cleanup()

    def set_date(self, day, month, year=2026):
        (self.camp / "calendar.json").write_text(json.dumps(
            {"gregorian": True, "day": day, "month": month, "year": year, "hour": 9,
             "months": ["January", "February", "March", "April", "May", "June", "July", "August", "September",
                        "October", "November", "December"]}), encoding="utf-8")

    def flag(self, line):
        (self.camp / "state.md").write_text(f"# Campaign: eden\n## Session Flags\n- autorun: true\n- {line}\n", encoding="utf-8")

    def run_py(self, script, *args, ok=True):
        r = subprocess.run([sys.executable, str(script), *args], capture_output=True, encoding="utf-8",
                           env=self.env, timeout=60)
        if ok:
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r

    def npc(self, *args, ok=True):
        return self.run_py(SCRIPTS / "npc.py", "-c", "eden", *args, ok=ok)

    def full(self):
        return (self.camp / "npcs-full.md").read_text(encoding="utf-8")

    def turn(self, action="[Mira]: looks around"):
        (self.rt / ".input_queue").write_text(action, encoding="utf-8")
        return self.run_py(DISPLAY / "autorun_wait.py").stdout

    @needs_unicode_fs   # Thai on the command line
    def test_add_writes_the_row_and_an_entry_with_stats_for_the_cr(self):
        out = self.npc("add", "--name", "Carlos Vane", "--role", "พลโท", "--cr", "12", "--aliases", "คาลอส, พลโทคาลอส",
                       "--attitude", "hostile").stdout
        self.assertIn("Created Carlos Vane: CR 12, HP 148, AC 16", out)
        self.assertIn("| Carlos Vane | พลโท | independent |  | hostile |  |", (self.camp / "npcs.md").read_text(encoding="utf-8"))
        entry = self.full().split("## Carlos Vane", 1)[1]
        for part in ("**Aliases:** คาลอส, พลโทคาลอส", "**CR/Level:** CR 12", "**HP:** 148 | **AC:** 16", "### History",
                     "**Background:** <fill: background", "15 May 2026: first met the party"):
            self.assertIn(part, entry)
        self.assertIn("## Kavin Techaporn", self.full())                       # earlier entries are untouched
        self.assertEqual(self.npc("add", "--name", "carlos vane", "--role", "x", "--cr", "1", ok=False).returncode, 1)

    @needs_unicode_fs   # Thai on the command line
    def test_a_row_without_an_entry_gets_its_entry_not_a_second_row(self):
        self.npc("add", "--name", "Malee Worakij", "--role", "คุณยาย", "--cr", "0", "--aliases", "คุณยาย")
        self.assertEqual((self.camp / "npcs.md").read_text(encoding="utf-8").count("Malee Worakij"), 1)
        self.assertIn("## Malee Worakij", self.full())

    def test_check_names_what_each_record_lacks(self):
        r = self.npc("check", ok=False)
        self.assertEqual(r.returncode, 1)
        self.assertIn("INCOMPLETE  Kavin Techaporn: history, aliases", r.stdout)
        self.assertIn("INCOMPLETE  Malee Worakij: no entry in npcs-full.md", r.stdout)

    @needs_unicode_fs   # Thai on the command line
    def test_time_away_makes_an_npc_grow_and_never_lowers_a_field(self):
        self.npc("check", ok=False)                                            # growth starts counting today
        self.set_date(17, 5)                                                   # two in-world days: not due
        self.assertNotIn("GROWTH DUE", self.npc("check", ok=False).stdout)
        self.set_date(22, 9)                                                   # 130 days: two 60-day steps
        self.assertIn("GROWTH DUE  Kavin Techaporn: 130 in-world days since they last grew (+2 steps)",
                      self.npc("check", ok=False).stdout)
        out = self.npc("advance", "kavin techaporn", "--what", "ขึ้นอันดับ 5 ของ Top 10").stdout
        self.assertIn("CR 4 to 6; HP 65 to 86; AC 16 to 18", out)
        self.assertNotRegex(out, r"\+-|\+0\b")                           # it names increases only
        entry = self.full()
        self.assertIn("**CR/Level:** CR 6 (Rank-A Elite) | **Location:** สนามหญ้า", entry)
        self.assertIn("**HP:** 86 | **AC:** 18 | **Attack:** Anomaly Burst +6 (3d8 force)", entry)   # prose kept
        self.assertIn("### History\n- 22 September 2026: after 130 days (CR 4 to 6) ขึ้นอันดับ 5 ของ Top 10\n\n---", entry)
        self.assertNotIn("GROWTH DUE", self.npc("check", ok=False).stdout)     # the clock restarts
        self.npc("advance", "Kavin Techaporn", "--levels", "0", "--what", "ย้ายไปอยู่หอใน")
        self.assertIn("**HP:** 86 | **AC:** 18", self.full())                  # a story-only change touches no number

    def test_growth_speed_is_the_tables_dial(self):
        self.npc("check", ok=False)
        self.set_date(20, 6)                                                   # 36 days
        self.assertNotIn("GROWTH DUE", self.npc("check", ok=False).stdout)
        self.flag("npc_growth: fast")
        self.assertIn("GROWTH DUE  Kavin Techaporn: 36 in-world days", self.npc("check", ok=False).stdout)
        self.flag("npc_growth: off")
        self.assertNotIn("GROWTH DUE", self.npc("check", ok=False).stdout)

    def test_each_turn_tells_the_gm_to_record_new_characters_and_finish_them(self):
        out = self.turn()
        self.assertIn(f'{SCRIPTS / "npc.py"}" -c eden add --name', out)
        self.assertNotIn("NPC RECORDS UNFINISHED", out)                        # old gaps are not a per-turn matter
        self.npc("add", "--name", "Carlos Vane", "--role", "general", "--cr", "12")
        self.assertIn("NPC RECORDS UNFINISHED: Carlos Vane (", self.turn())

    @needs_unicode_fs   # Thai on the command line
    def test_an_npc_back_in_the_scene_after_a_long_time_is_flagged_by_alias(self):
        (self.camp / "npcs-full.md").write_text(KAVIN.replace("## Kavin Techaporn\n", "## Kavin Techaporn\n- **Aliases:** กวิน\n"),
                                                encoding="utf-8")
        self.turn()
        self.set_date(22, 9)
        self.assertNotIn("NPC GROWTH DUE", self.turn("[Mira]: เดินไปตลาด"))    # he is not in this scene
        out = self.turn("[Mira]: ไปหากวินที่สนามหญ้า")
        self.assertIn("NPC GROWTH DUE, they are in this scene: Kavin Techaporn (130 in-world days)", out)

    def test_the_clock_on_the_display_must_be_the_calendars(self):
        (self.rt / "stats.json").write_text(json.dumps({"world_time": {"date": "17 May 2026"}}), encoding="utf-8")
        out = self.turn()
        self.assertIn("IN-WORLD CLOCK OUT OF STEP: the display says '17 May 2026' but calendar.json is at 15 May 2026", out)
        self.assertIn("calendar.py", out)                                      # the story is ahead: move the calendar
        self.set_date(17, 5)
        self.assertNotIn("CLOCK OUT OF STEP", self.turn())
        self.set_date(19, 5)                                                   # calendar advanced properly: the display is behind
        out = self.turn()
        self.assertIn("calendar.json is at 19 May 2026", out)
        self.assertIn('--world-time \'{"date": "19 May 2026"', out)           # ...so show the calendar's date, don't advance again

    def test_engine_light_drops_the_fight_and_xp_rules_but_keeps_the_rest(self):
        self.assertIn("- Fights and rests run on the engine", self.turn())
        self.flag("engine: light")
        out = self.turn()
        self.assertNotIn("Fights and rests", out)
        self.assertIn("A named character who enters the story", out)

    def test_save_checklist_holds_the_npc_backlog(self):
        out = self.run_py(SCRIPTS / "save_check.py", "-c", "eden").stdout
        self.assertIn("☐ NPC records", out)
        self.assertIn("Malee Worakij (no entry in npcs-full.md)", out)


if __name__ == "__main__":
    unittest.main()
