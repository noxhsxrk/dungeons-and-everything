"""The rules that keep a campaign sound must reach a GM that reads no docs.

A GM played 30 turns with only send.py, push_stats.py and autorun_wait.py: fights won by
narration, XP typed onto the display, nothing written to disk, /dne load from memory. So
those scripts carry the rules in their own output (scripts/gm_guide.py).
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "skills" / "dne" / "scripts"
DISPLAY = ROOT / "skills" / "dne" / "display"


class GuideTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)
        self.rt = self.root / "rt"
        self.rt.mkdir()
        self.camp = self.root / "campaigns" / "eden"
        (self.camp / "characters").mkdir(parents=True)
        self.state = self.camp / "state.md"
        self.state.write_text("# Campaign: eden\n## Session Flags\n- autorun: true\n", encoding="utf-8")
        self.sheet = self.camp / "characters" / "mira.md"
        self.set_sheet(1150)
        (self.rt / ".campaign").write_text("eden", encoding="utf-8")
        self.env = {**os.environ, "DNE_CAMPAIGN_ROOT": str(self.root), "DNE_RUNTIME_DIR": str(self.rt),
                    "DNE_DISPLAY_HOST": "127.0.0.1:9", "DNE_AUTOSAVE_EVERY": "3"}

    def tearDown(self):
        self._tmp.cleanup()

    def set_sheet(self, xp):
        self.sheet.write_text(f"# Mira\n- **Class:** Medic | **Level:** 3\n- **XP:** {xp} / 2700\n", encoding="utf-8")

    def show_xp(self, xp):
        (self.rt / "stats.json").write_text(json.dumps(
            {"players": [{"name": "Mira", "xp": {"current": xp, "next": 2700}}]}), encoding="utf-8")

    def run_py(self, script, *args):
        r = subprocess.run([sys.executable, str(script), *args], capture_output=True, encoding="utf-8",
                           env=self.env, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def guide(self, what):
        return self.run_py(SCRIPTS / "gm_guide.py", "-c", "eden", what)

    def player_turn(self):
        (self.rt / ".input_queue").write_text("[Mira]: opens the door", encoding="utf-8")
        return self.run_py(DISPLAY / "autorun_wait.py")

    def test_every_turn_says_how_a_fight_is_run_with_real_paths(self):
        out = self.player_turn()
        self.assertTrue(out.startswith("[Mira]: opens the door\n[[GM note"))
        self.assertIn("autorun_wait.py running again", out)             # the relaunch rule stays first
        self.assertLess(out.index("autorun_wait.py running again"), out.index("- Fights and rests"))
        self.assertIn(f'{SCRIPTS / "combat.py"}" init', out)
        self.assertIn("--roll <the d20 before bonuses>", out)           # a typed roll is still the player's roll
        self.assertRegex(out, r"SKILL-commands\.md lines \d+-\d+")
        self.assertNotIn("SAVE DUE", out)
        self.assertNotIn("XP NOT", out)

    def test_save_is_due_after_n_turns_until_state_md_is_written(self):
        outs = [self.player_turn() for _ in range(4)]
        self.assertNotIn("SAVE DUE", outs[1])
        self.assertIn("SAVE DUE: 3 player turns", outs[2])
        self.assertIn("SAVE DUE: 4 player turns", outs[3])              # repeats until it is done
        later = time.time() + 5
        os.utime(self.state, (later, later))                            # the GM wrote state.md
        self.assertNotIn("SAVE DUE", self.player_turn())

    def test_autosave_off_means_no_save_reminder(self):
        self.state.write_text("## Session Flags\n- autorun: true\n- autosave: off\n", encoding="utf-8")
        self.assertNotIn("SAVE DUE", "".join(self.player_turn() for _ in range(4)))

    def test_xp_shown_but_not_on_the_sheet_is_flagged(self):
        self.show_xp(2000)
        out = self.guide("turn")
        self.assertIn("XP NOT AWARDED BY THE ENGINE (Mira: display 2000, sheet 1150, awarded by xp.py 1150)", out)
        self.assertIn(f'{SCRIPTS / "xp.py"}" award --campaign eden', out)
        self.show_xp(1150)
        self.assertNotIn("XP NOT", self.guide("turn"))

    def test_xp_written_into_the_sheet_by_hand_is_flagged_and_an_award_is_not(self):
        self.guide("start")                                             # session opens at 1150
        self.set_sheet(2000)
        self.show_xp(2000)
        self.assertIn("display 2000, sheet 2000, awarded by xp.py 1150", self.guide("turn"))
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(time.time() + 5))
        (self.camp / "xp-ledger.jsonl").write_text(json.dumps(
            {"at": stamp, "character": "Mira", "awarded": 850, "total_after": 2000}) + "\n", encoding="utf-8")
        self.assertNotIn("XP NOT", self.guide("turn"))                  # xp.py award gave it

    def test_session_start_marks_the_campaign_and_lists_the_load_steps(self):
        (self.camp / "factions.json").write_text("{}", encoding="utf-8")
        out = self.run_py(DISPLAY / "push_stats.py", "--set-campaign", "eden")   # what a GM runs at /dne load
        marker = json.loads((self.rt / "active-campaign.json").read_text(encoding="utf-8"))
        self.assertEqual(marker["name"], "eden")
        self.assertEqual(marker["xp"], {"mira": 1150})
        self.assertIn("SESSION START: eden", out)
        self.assertRegex(out, r"SKILL\.md lines \d+-\d+ \(the rules for the whole session\)")
        self.assertRegex(out, r"SKILL-commands\.md lines \d+-\d+ \(/dne load, all of it\)")
        for script in ("migrate_ruleset.py", "campaign_version.py", "faction.py", "campaign_graph.py"):
            self.assertIn(script, out)
        self.assertNotIn("calendar.py", out)                            # no calendar.json in this campaign

    def test_session_start_flags_a_session_the_header_counts_but_the_log_lacks(self):
        # A GM bumped Session count to 2 at /dne end and wrote no log: the session's wins were lost.
        self.state.write_text("# Campaign: eden\n**Session count:** 2\n## Session Flags\n", encoding="utf-8")
        (self.camp / "session-log-archive.md").write_text("# Archive\n## Session 1 — x\n### Recap\nok\n", encoding="utf-8")
        out = self.run_py(DISPLAY / "push_stats.py", "--set-campaign", "eden")
        self.assertIn("1. LOG GAP", out)
        self.assertIn("entry for session 2.", out)
        (self.camp / "session-log.md").write_text("# Log\n## Session 2 — y\n### Recap\nok\n", encoding="utf-8")
        self.assertNotIn("LOG GAP", self.run_py(DISPLAY / "push_stats.py", "--set-campaign", "eden"))

    def test_the_line_ranges_point_at_the_right_sections(self):
        sys.path.insert(0, str(SCRIPTS))
        import gm_guide
        for doc, heading, first in (("SKILL.md", "Four rules", "Four rules"),
                                    ("SKILL-commands.md", "/dne load", "## `/dne load"),
                                    ("SKILL-commands.md", "/dne combat start", "## `/dne combat start`"),
                                    ("SKILL-commands.md", "/dne rest", "## `/dne rest")):
            ref = gm_guide.section_lines(doc, heading)
            a, b = map(int, ref.rsplit(" ", 1)[1].split("-"))
            lines = (ROOT / "skills" / "dne" / doc).read_text(encoding="utf-8").splitlines()
            self.assertIn(first, lines[a - 1], ref)
            self.assertGreater(b, a, ref)
            self.assertFalse(any(l.startswith("## ") for l in lines[a:b]), ref)   # stops before the next section


if __name__ == "__main__":
    unittest.main()
