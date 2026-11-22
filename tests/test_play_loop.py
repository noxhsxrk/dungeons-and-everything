"""In-play scripts in a World Kit campaign: world currency in economy.py, typed damage in combat.py."""
from __future__ import annotations

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


class WorldCurrencyTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = pathlib.Path(self._tmp.name)
        self.camp = root / "campaigns" / "eden"
        (self.camp / "characters").mkdir(parents=True)
        (self.camp / "state.md").write_text("**Ruleset:** 2014\n", encoding="utf-8")
        shutil.copy(FIXTURE, self.camp / "worldkit.json")
        self.sheet = self.camp / "characters" / "kade.md"
        self.sheet.write_text("# Kade\n## Equipment & Inventory\n**Currency:** 100 sc\n"
                              "**Adventuring Gear:**\n- Rope\n", encoding="utf-8")
        self.env = {**os.environ, "DNE_CAMPAIGN_ROOT": str(root), "DNE_RUNTIME_DIR": str(root / ".rt")}

    def tearDown(self):
        self._tmp.cleanup()

    def econ(self, *args):
        return subprocess.run([sys.executable, str(SCRIPTS / "economy.py"), "-c", "eden", *args],
                              capture_output=True, encoding="utf-8", env=self.env)

    def test_buy_in_world_currency(self):
        r = self.econ("buy", "--char", "kade", "--item", "Rail Pistol", "--cost", "50 sc")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("**Currency:** 50 sc", self.sheet.read_text(encoding="utf-8"))

    def test_decimal_amounts(self):
        r = self.econ("gold", "--char", "kade", "--delta", "12.5", "--reason", "salvage")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("**Currency:** 112.50 sc", self.sheet.read_text(encoding="utf-8"))

    def test_insufficient_funds_refused(self):
        r = self.econ("buy", "--char", "kade", "--item", "Titan Core", "--cost", "500")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("**Currency:** 100 sc", self.sheet.read_text(encoding="utf-8"))


class TypedDamageTests(unittest.TestCase):
    def attack(self, dmg):
        return subprocess.run([sys.executable, str(SCRIPTS / "combat.py"), "attack", "--atk", "30",
                               "--ac", "1", "--dmg", dmg], capture_output=True, encoding="utf-8")

    def test_weapon_damage_string_with_type(self):
        r = self.attack("1d10 Piercing")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(r.stdout, r"\(1d10\) = \d+ piercing damage")

    def test_plain_notation(self):
        r = self.attack("2d6+4")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(r.stdout, r"\(2d6\+4\) = \d+ damage")
        self.assertNotIn("dmg", r.stdout)


if __name__ == "__main__":
    unittest.main()
