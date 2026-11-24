"""save_check.py: the /dne save checklist is worked out from file times and the session narration."""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import unittest

SCRIPTS = pathlib.Path(__file__).resolve().parent.parent / "skills" / "dne" / "scripts"


class SaveCheckTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)
        self.camp = self.root / "campaigns" / "glitch"
        (self.camp / "characters").mkdir(parents=True)
        files = {
            "state.md": "# Campaign\n## Live State Flags\n- **NPC dispositions:** Rina: friendly\n## Session Flags\n",
            "session-log.md": "# Log\n",
            "npcs.md": "| Name | Role | Attitude |\n| ------ | --- | --- |\n| Rina Saelim | inventor | friendly |\n"
                       "| Kavin Techaporn | rival | neutral |\n",
            "npcs-full.md": "## Rina Saelim\n- **Aliases:** รินะ, Rina\n- **Role:** inventor\n## Kavin Techaporn\n- **Role:** rival\n",
            "graph.json": "{}",
            "characters/nox.md": "# Nox\n",
            "session_tail.json": json.dumps([{"text": "รินะยิ้มให้นอกซ์ แล้วจับมือไว้แน่น"}], ensure_ascii=False),
        }
        old = time.time() - 3600
        for name, body in files.items():
            p = self.camp / name
            p.write_text(body, encoding="utf-8")
            os.utime(p, (old, old))
        self.env = {**os.environ, "DNE_CAMPAIGN_ROOT": str(self.root), "DNE_RUNTIME_DIR": str(self.root / "rt")}
        self.since = time.strftime("%Y-%m-%d %H:%M", time.localtime(time.time() - 600))

    def tearDown(self):
        self._tmp.cleanup()

    def run_check(self):
        r = subprocess.run([sys.executable, str(SCRIPTS / "save_check.py"), "-c", "glitch", "--since", self.since],
                           capture_output=True, encoding="utf-8", env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_untouched_files_and_npcs_seen_by_alias(self):
        out = self.run_check()
        self.assertIn("☐ session-log.md", out)
        self.assertIn("☐ characters/nox.md", out)
        self.assertIn("Relationships for NPCs in this session's narration: Rina Saelim (now: friendly)", out)
        self.assertIn("Other NPCs (didn't match the narration by name; check if they took part): Kavin Techaporn", out)
        self.assertIn("Every ☐ must be updated now", out)

    def test_written_files_tick(self):
        for name in ("session-log.md", "state.md", "npcs.md", "characters/nox.md", "graph.json"):
            os.utime(self.camp / name, None)                      # written now
        (self.camp / "session-tail.md").write_text("tail\n", encoding="utf-8")
        out = self.run_check()
        self.assertIn("✓ session-log.md", out)
        self.assertIn("☐ Relationships for NPCs", out)   # a touched npcs.md proves nothing: never auto-ticked
        self.assertIn("☐ Other NPCs", out)
        self.assertIn("✓ characters/nox.md", out)

    def test_session_log_row_needs_the_entry_for_the_header_count(self):
        today = time.strftime("%Y-%m-%d")
        (self.camp / "state.md").write_text(f"# C\n**Last session:** {today}  **Session count:** 3\n", encoding="utf-8")
        (self.camp / "session-log.md").write_text("# Log\n## Session 2 — old\n", encoding="utf-8")   # written now, wrong entry
        out = self.run_check()
        self.assertIn("✓ state.md header", out)
        self.assertIn("☐ session-log.md: a `## Session 3` entry", out)
        self.assertIn("Earlier sessions with no log entry: 1, 3", out)
        (self.camp / "session-log.md").write_text("# Log\n## Session 1\n## Session 2\n## Session 3 — now\n", encoding="utf-8")
        out = self.run_check()
        self.assertIn("✓ session-log.md: a `## Session 3` entry", out)
        self.assertNotIn("Earlier sessions", out)

    def test_bad_since_is_an_error(self):
        r = subprocess.run([sys.executable, str(SCRIPTS / "save_check.py"), "-c", "glitch", "--since", "yesterday"],
                           capture_output=True, encoding="utf-8", env=self.env)
        self.assertEqual(r.returncode, 1)
