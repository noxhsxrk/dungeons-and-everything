"""A concentration spell on several targets ends on all of them together.

WHY
===
Effects were stored per creature with no link to whoever cast them. Bless on
three allies was three `conc` effects, each of which also marked its *target*
as concentrating. Breaking the cleric's concentration (damage, a new spell, a
long rest, dropping unconscious) cleared the cleric's field and left Bless on
every ally. `effect start ... conc --caster <who>` now names the caster, and
every way concentration ends goes through `tracker.drop_concentration`.
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "skills" / "dne" / "scripts"
sys.path.insert(0, str(SCRIPTS))

_spec = importlib.util.spec_from_file_location("tracker", SCRIPTS / "tracker.py")
tracker = importlib.util.module_from_spec(_spec)
sys.modules["tracker"] = tracker
_spec.loader.exec_module(tracker)

CAMP = "unittest-conc-targets"


class ConcentrationTargets(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.td.name)
        (self.root / "campaigns" / CAMP).mkdir(parents=True)
        patches = [mock.patch.dict(os.environ, {"DNE_CAMPAIGN_ROOT": str(self.root)}),
                   mock.patch.object(tracker, "_push_conditions", lambda *a, **k: None),
                   mock.patch.object(tracker, "_send_announce", lambda *a, **k: None),
                   mock.patch("sys.stdout", new_callable=io.StringIO)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self.td.cleanup)

    def state(self) -> dict:
        return json.loads((self.root / "campaigns" / CAMP / "tracker.json").read_text(encoding="utf-8"))

    def bless(self, *targets):
        for t in targets:
            tracker.cmd_effect(CAMP, "start", t, spell="Bless", duration="10r", is_conc=True,
                               mod="+1d4", on="attack,save", caster="Cleric")

    def effects(self, who):
        return [e["name"] for e in self.state()[who.lower()]["effects"]]

    def test_the_caster_concentrates_not_the_targets(self):
        self.bless("Ana", "Bo")
        s = self.state()
        self.assertEqual(s["cleric"]["concentration"], "Bless")
        self.assertIsNone(s["ana"]["concentration"])
        self.assertEqual(tracker.active_modifiers(CAMP, "Cleric", "attack"), [])

    def test_breaking_concentration_ends_it_on_every_target(self):
        self.bless("Ana", "Bo")
        tracker.cmd_concentrate(CAMP, "Cleric", "break")
        self.assertEqual(self.effects("Ana"), [])
        self.assertEqual(self.effects("Bo"), [])
        self.assertEqual(self.effects("Cleric"), [])

    def test_a_new_concentration_spell_ends_the_old_one_everywhere(self):
        self.bless("Ana")
        tracker.cmd_effect(CAMP, "start", "Orc", spell="Hold Person", duration="10r", is_conc=True,
                           caster="Cleric")
        self.assertEqual(self.effects("Ana"), [])
        self.assertEqual(self.effects("Orc"), ["Hold Person"])
        self.assertEqual(self.state()["cleric"]["concentration"], "Hold Person")

    def test_falling_unconscious_ends_it(self):
        self.bless("Ana")
        tracker.cmd_condition(CAMP, "Cleric", "add", "unconscious")
        self.assertEqual(self.effects("Ana"), [])

    def test_a_long_rest_ends_it(self):
        self.bless("Ana")
        tracker.cmd_rest(CAMP, "long")
        self.assertEqual(self.effects("Ana"), [])

    def test_ending_on_one_target_leaves_the_others(self):
        self.bless("Ana", "Bo")
        tracker.cmd_effect(CAMP, "end", "Ana", spell="Bless")
        self.assertEqual(self.effects("Bo"), ["Bless"])
        self.assertEqual(self.state()["cleric"]["concentration"], "Bless")

    def test_another_casters_bless_survives(self):
        self.bless("Ana")
        tracker.cmd_effect(CAMP, "start", "Bo", spell="Bless", duration="10r", is_conc=True, caster="Paladin")
        tracker.cmd_concentrate(CAMP, "Cleric", "break")
        self.assertEqual(self.effects("Bo"), ["Bless"])

    def test_running_out_frees_the_caster(self):
        self.bless("Ana")
        tracker.cmd_effect(CAMP, "advance", "2m")
        self.assertIsNone(self.state()["cleric"]["concentration"])
        self.assertEqual(self.effects("Ana"), [])

    def test_a_self_spell_without_caster_works_as_before(self):
        tracker.cmd_effect(CAMP, "start", "Wiz", spell="Haste", duration="10r", is_conc=True)
        self.assertEqual(self.state()["wiz"]["concentration"], "Haste")
        tracker.cmd_concentrate(CAMP, "Wiz", "break")
        self.assertEqual(self.effects("Wiz"), [])


if __name__ == "__main__":
    unittest.main()
