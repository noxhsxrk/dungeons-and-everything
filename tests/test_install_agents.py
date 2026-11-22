"""install.py wires the skill into any AI agent: skill-folder agents get a link,
rules-file agents get one idempotent block, and uninstall undoes both."""
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SKILL = ROOT / "skills" / "dne"


class InstallTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = pathlib.Path(self._tmp.name)
        for d in (".claude", ".codex", ".config/amp", ".cursor"):
            (self.home / d).mkdir(parents=True)
        (self.home / ".config/amp/AGENTS.md").write_text("# my rules\n- be terse\n", encoding="utf-8")
        self.env = {**os.environ, "HOME": str(self.home), "USERPROFILE": str(self.home)}

    def tearDown(self):
        self._tmp.cleanup()

    def run_install(self, *args):
        return subprocess.run([sys.executable, str(ROOT / "install.py"), *args],
                              capture_output=True, encoding="utf-8", env=self.env)

    def test_detected_agents_installed_idempotently_and_removed(self):
        for _ in range(2):
            r = self.run_install()
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for d in (".claude/skills/dne", ".codex/skills/dne"):
            self.assertEqual((self.home / d).resolve(), SKILL.resolve())
        self.assertFalse((self.home / ".gemini").exists())             # not detected → untouched
        amp = (self.home / ".config/amp/AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("- be terse", amp)
        self.assertEqual(amp.count("<!-- dne:start -->"), 1)
        self.assertIn(str(SKILL / "SKILL.md"), amp)
        self.assertTrue((self.home / ".cursor/rules/dne.mdc").exists())

        r = self.run_install("--uninstall")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse((self.home / ".claude/skills/dne").exists())
        amp = (self.home / ".config/amp/AGENTS.md").read_text(encoding="utf-8")
        self.assertNotIn("dne:start", amp)
        self.assertIn("- be terse", amp)
        self.assertFalse((self.home / ".cursor/rules/dne.mdc").exists())

    def test_foreign_folder_is_not_overwritten(self):
        (self.home / ".codex/skills/dne").mkdir(parents=True)
        r = self.run_install("codex")
        self.assertIn("SKIPPED", r.stdout)
        self.assertFalse((self.home / ".codex/skills/dne").is_symlink())

    def test_unknown_agent(self):
        self.assertEqual(self.run_install("nonsense").returncode, 2)


if __name__ == "__main__":
    unittest.main()
