"""Regressions from the full play-through sessions (round 2)."""
from __future__ import annotations

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
DISPLAY = ROOT / "skills" / "dne" / "display"
FIXTURE = ROOT / "tests" / "fixtures" / "worldkit-eden.json"


class _Camp(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)
        self.camp = self.root / "campaigns" / "eden"
        (self.camp / "characters").mkdir(parents=True)
        (self.camp / "state.md").write_text("**Ruleset:** 2014\n", encoding="utf-8")
        shutil.copy(FIXTURE, self.camp / "worldkit.json")
        self.env = {**os.environ, "DNE_CAMPAIGN_ROOT": str(self.root),
                    "DNE_RUNTIME_DIR": str(self.root / ".rt")}

    def tearDown(self):
        self._tmp.cleanup()

    def run_py(self, script, *args, cwd=SCRIPTS):
        return subprocess.run([sys.executable, str(cwd / script), *args],
                              capture_output=True, encoding="utf-8", env=self.env)


class TrackerTests(_Camp):
    def test_clear_and_check_reset_keep_tracker_usable(self):
        self.assertEqual(self.run_py("tracker.py", "-c", "eden", "condition", "add", "Kade", "prone").returncode, 0)
        r = self.run_py("tracker.py", "-c", "eden", "check", "log", "Kade", "Athletics", "--dc", "12", "--result", "15")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("DUPLICATE", self.run_py("tracker.py", "-c", "eden", "check", "seen", "Kade", "Athletics").stdout)
        for cmd in (["clear"], ["check", "reset"]):
            r = self.run_py("tracker.py", "-c", "eden", *cmd)
            self.assertEqual(r.returncode, 0, r.stderr)
            r = self.run_py("tracker.py", "-c", "eden", "status")
            self.assertEqual(r.returncode, 0, r.stderr)
        r = self.run_py("calendar.py", "-c", "eden", "init", "--date", "14 September 2289")
        self.assertEqual(r.returncode, 0, r.stderr)
        r = self.run_py("calendar.py", "-c", "eden", "advance", "1", "hours")
        self.assertEqual(r.returncode, 0, r.stderr)


class EffectUntilTests(_Camp):
    def test_effect_until_caster_survives_target_turn(self):
        t = lambda *a: self.run_py("tracker.py", "-c", "eden", *a)
        t("effect", "start", "Ghoul", "Dead Man's Hand", "1r", "--until", "Silas")
        t("effect", "tick", "Ghoul")
        self.assertIn("Dead Man", t("status").stdout)
        t("effect", "tick", "Silas")
        self.assertNotIn("Dead Man", t("status").stdout)


class PowerDialTests(unittest.TestCase):
    def test_power_dial_warnings(self):
        sys.path.insert(0, str(SCRIPTS))
        import worldkit
        kit = json.loads(FIXTURE.read_text(encoding="utf-8"))
        kit["_meta"]["power"] = "none"
        self.assertTrue(any("power is none" in w for w in worldkit.warnings(kit)))
        kit["_meta"]["power"] = "medium"
        self.assertFalse(any("_meta.power" in w for w in worldkit.warnings(kit)))

    def test_example_kit_is_warning_free(self):
        sys.path.insert(0, str(SCRIPTS))
        import worldkit
        example = json.loads((ROOT / "skills" / "dne" / "templates" / "worldkit.example.json").read_text(encoding="utf-8"))
        self.assertEqual(worldkit.validate(example), [])
        self.assertEqual(worldkit.warnings(example), [])


class SnapshotTests(_Camp):
    def test_undo_restores_calendar_and_xp_ledger(self):
        cal = self.camp / "calendar.json"
        led = self.camp / "xp-ledger.jsonl"
        cal.write_text('{"day": 1}', encoding="utf-8")
        led.write_text('{"xp": 50}\n', encoding="utf-8")
        self.assertEqual(self.run_py("turn_snapshot.py", "-c", "eden", "save", "--label", "t").returncode, 0)
        cal.write_text('{"day": 2}', encoding="utf-8")
        led.write_text('{"xp": 50}\n{"xp": 200}\n', encoding="utf-8")
        r = self.run_py("turn_snapshot.py", "-c", "eden", "undo")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(cal.read_text(encoding="utf-8"), '{"day": 1}')
        self.assertEqual(led.read_text(encoding="utf-8"), '{"xp": 50}\n')
        self.assertTrue((self.camp / "worldkit.json").exists())

    def test_old_snapshot_does_not_delete_newer_tracked_files(self):
        self.assertEqual(self.run_py("turn_snapshot.py", "-c", "eden", "save", "--label", "old").returncode, 0)
        snap = next((self.root / ".rt").rglob("meta.json"), None) or next(self.camp.rglob("meta.json"))
        meta = json.loads(snap.read_text(encoding="utf-8"))
        meta.pop("tracked", None)                    # a snapshot from before "tracked" existed
        for f in ("worldkit.json",):
            p = snap.parent / "campaign" / f
            if p.exists():
                p.unlink()
        snap.write_text(json.dumps(meta), encoding="utf-8")
        (self.camp / "calendar.json").write_text("{}", encoding="utf-8")
        r = self.run_py("turn_snapshot.py", "-c", "eden", "undo")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.camp / "worldkit.json").exists())
        self.assertTrue((self.camp / "calendar.json").exists())


class TailRootTests(_Camp):
    def test_write_canonical_tail_uses_data_root(self):
        r = self.run_py("write_canonical_tail.py", "--help", cwd=DISPLAY)
        self.assertEqual(r.returncode, 0, r.stderr)
        sys.path.insert(0, str(DISPLAY))
        try:
            import importlib
            mod = importlib.import_module("write_canonical_tail")
            old = os.environ.get("DNE_CAMPAIGN_ROOT")
            os.environ["DNE_CAMPAIGN_ROOT"] = str(self.root)
            try:
                self.assertEqual(mod._resolve_campaign_root(), self.root / "campaigns")
            finally:
                if old is None:
                    os.environ.pop("DNE_CAMPAIGN_ROOT", None)
                else:
                    os.environ["DNE_CAMPAIGN_ROOT"] = old
        finally:
            sys.path.remove(str(DISPLAY))

    def test_verify_tail_finds_campaign_under_data_root(self):
        (self.camp / "session_tail.json").write_text("{}", encoding="utf-8")
        r = subprocess.run(["bash", str(DISPLAY / "verify_tail.sh"), "eden"],
                           capture_output=True, encoding="utf-8", env=self.env)
        self.assertNotIn("MISSING", r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()


class Lookup2024DataTests(unittest.TestCase):
    def look(self, *a):
        return subprocess.run([sys.executable, str(SCRIPTS / "lookup.py"), *a, "--ruleset", "2024"],
                              capture_output=True, encoding="utf-8")

    def test_feats_mastery_species(self):
        self.assertIn("Alert", self.look("feat", "alert").stdout)
        self.assertIn("Disadvantage", self.look("mastery", "sap").stdout)
        self.assertIn("Elf", self.look("race", "elf").stdout)
