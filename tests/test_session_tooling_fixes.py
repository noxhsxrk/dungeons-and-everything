"""Script snags from a played session (glitch, 2026-11-25) that a GM tripped over mid-play.

- scene-context failed outright on one NPC missing from the graph, and npc.py add never put anyone in it
- economy.py rest wrote the sheets and left the clock where it was, silently
- character.py hero award rejected --reason
- verify_tail.sh called last session's tail HEALTHY
- calendar.py set could only land on the hour, so fixing 08:15 back to 08:10 took two commands
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
SHEET = ("# Mae\n## Combat Stats\n- **HP:** 5 / 20 | **Temp HP:** 0\n- **Hit Dice:** 2d8 (remaining: 2)\n"
         "- **Death Saves:** Successes: 0 | Failures: 0\n## Equipment & Inventory\n**Currency:** 5\n")


class SessionToolingTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)
        self.rt = self.root / "rt"
        self.rt.mkdir()
        self.camp = self.root / "campaigns" / "eden"
        (self.camp / "characters").mkdir(parents=True)
        (self.camp / "state.md").write_text("# Campaign: eden\n## Session Flags\n", encoding="utf-8")
        (self.camp / "characters" / "mae.md").write_text(SHEET, encoding="utf-8")
        self.env = {**os.environ, "DNE_CAMPAIGN_ROOT": str(self.root), "DNE_RUNTIME_DIR": str(self.rt),
                    "DNE_DISPLAY_HOST": "127.0.0.1:9"}

    def tearDown(self):
        self._tmp.cleanup()

    def run_py(self, script, *args, ok=True):
        r = subprocess.run([sys.executable, str(SCRIPTS / script), *args], capture_output=True,
                           encoding="utf-8", env=self.env)
        if ok:
            self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        return r

    def graph(self, *names):
        nodes = [{"id": "pc_mae", "type": "pc", "name": "Mae"}] + [
            {"id": f"npc_{i}", "type": "npc", "name": n} for i, n in enumerate(names)]
        (self.camp / "graph.json").write_text(json.dumps({"version": 1, "nodes": nodes, "edges": []}), encoding="utf-8")

    def test_scene_context_warns_on_an_unknown_name_and_still_answers(self):
        self.graph("Arthit Worakij")
        out = self.run_py("campaign_graph.py", "scene-context", "--campaign", "eden", "--place", "Worakij House",
                          "--present", "Arthit Worakij,Malee Worakij").stdout
        self.assertIn("present 'Malee Worakij' is not in the graph; add it: campaign_graph.py add-node", out)
        self.assertIn("--type place --name 'Worakij House'", out)
        self.assertIn("# scene context — seeds: npc_0", out)

    def test_npc_add_puts_them_in_the_graph_and_check_names_who_is_missing(self):
        self.graph()
        (self.camp / "npcs.md").write_text("| Name | Role | Attitude |\n|---|---|---|\n| Kavin | rival | neutral |\n",
                                           encoding="utf-8")
        self.run_py("npc.py", "-c", "eden", "add", "--name", "Malee Worakij", "--role", "grandmother", "--cr", "0")
        names = [n["name"] for n in json.loads((self.camp / "graph.json").read_text(encoding="utf-8"))["nodes"]]
        self.assertIn("Malee Worakij", names)
        out = self.run_py("npc.py", "-c", "eden", "check", ok=False).stdout
        self.assertIn("Kavin: no entry in npcs-full.md, not in graph.json", out.replace("not in graph.json, no entry in npcs-full.md", "no entry in npcs-full.md, not in graph.json"))
        self.assertNotIn("Malee Worakij: not in graph", out)

    def test_no_graph_yet_means_no_graph_complaint(self):
        (self.camp / "npcs.md").write_text("| Name | Role | Attitude |\n|---|---|---|\n| Kavin | rival | neutral |\n",
                                           encoding="utf-8")
        out = self.run_py("npc.py", "-c", "eden", "check", ok=False).stdout
        self.assertNotIn("graph", out.split("Incomplete records")[0])

    def test_rest_says_the_clock_is_a_separate_step(self):
        out = self.run_py("economy.py", "-c", "eden", "rest", "--type", "long", "--char", "all").stdout
        self.assertNotIn("Clock not moved", out)                       # no calendar: nothing to move
        self.run_py("calendar.py", "-c", "eden", "init", "--gregorian", "--date", "17 May 2026")
        out = self.run_py("economy.py", "-c", "eden", "rest", "--type", "long", "--char", "all").stdout
        self.assertIn("now run `calendar.py -c eden rest long`", out)

    def test_hero_award_takes_a_reason(self):
        out = self.run_py("character.py", "hero", "award", "--char", "Mae", "-c", "eden", "--reason", "nat 20").stdout
        self.assertIn("Hero Points 1 / 3 (nat 20)", out)

    def test_calendar_set_takes_minutes(self):
        self.run_py("calendar.py", "-c", "eden", "init", "--gregorian", "--date", "18 May 2026")
        out = self.run_py("calendar.py", "-c", "eden", "set", "18 May 2026", "--hour", "8:10").stdout
        self.assertIn("8:10", out)
        self.assertEqual(self.run_py("calendar.py", "-c", "eden", "set", "18 May 2026", "--hour", "8:99",
                                     ok=False).returncode, 2)   # calendar.py: bad input exits 2

    # On Windows, subprocess finds System32\\bash.exe (the WSL stub) before Git Bash, so the script never runs.
    @unittest.skipIf(os.name == "nt", "bash from subprocess is the WSL stub on Windows runners")
    def test_verify_tail_calls_last_sessions_tail_stale(self):
        tail = self.camp / "session_tail.json"
        tail.write_text(json.dumps([{"text": "last session's beat, long enough to pass the size check"}]), encoding="utf-8")
        old = time.time() - 3600
        os.utime(tail, (old, old))
        verify = lambda: subprocess.run(["bash", str(DISPLAY / "verify_tail.sh"), "eden"], capture_output=True,  # noqa: E731
                                        encoding="utf-8", env=self.env)
        r = verify()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)          # no session marker: shape check only
        (self.rt / "active-campaign.json").write_text(json.dumps({"name": "eden"}), encoding="utf-8")
        r = verify()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("STALE", r.stdout)
        os.utime(tail, None)                                           # written this session
        r = verify()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
