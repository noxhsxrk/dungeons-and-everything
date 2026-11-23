"""Optional table rules, Part B: World Kit fields (tech level, status, rarity/traits, playbook moves,
quick-build templates, disadvantages, valued kit conditions, focus powers) and the per-CR monster table."""
from __future__ import annotations

import copy
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from test_playtest_round6 import KIT, ROOT, SCRIPTS, _Camp  # noqa: E402,F401

import worldkit  # noqa: E402

EXAMPLE = ROOT / "skills" / "dne" / "templates" / "worldkit.example.json"


def _kit(**extra):
    kit = copy.deepcopy(KIT)
    for k, v in extra.items():
        kit[k] = v
    return kit


class KitFieldValidationTests(_Camp):
    def errors(self, kit):
        return worldkit.validate(kit)

    def test_valid_new_fields_pass(self):
        kit = _kit(disadvantages=[{"name": "Debt to the Syndicate", "kind": "disadvantage",
                                   "description": "They will come to collect."},
                                  {"name": "Hums when nervous", "kind": "quirk", "description": "Always."}],
                   conditions=[{"name": "Static", "description": "-1 per point to checks.", "valued": True,
                                "decay": True, "penalty_on": ["check"]}])
        kit["_meta"].update(tech_level=10, status_levels=["Tunnel rat", "Colonist", "Council"])
        cls = kit["classes"][0]
        cls["moves"] = [{"name": "Read the Room", "level": 1, "trigger": "When you size up a tense scene",
                         "description": "Ask the GM two questions."}]
        cls["template"] = {"abilities": {"STR": 15, "DEX": 14, "CON": 13, "INT": 8, "WIS": 12, "CHA": 10},
                           "skills": ["Athletics", "Perception"], "equipment": ["Rail Pistol"]}
        kit["equipment"][0].update(rarity="rare", traits=["loud"], tl=11)
        kit["spells"][0]["focus"] = True
        self.assertEqual(self.errors(kit), [])

    def test_bad_new_fields_fail(self):
        bad = [
            lambda k: k["_meta"].update(tech_level=13),
            lambda k: k["_meta"].update(status_levels="Council"),
            lambda k: k["equipment"][0].update(rarity="legendary"),
            lambda k: k["equipment"][0].update(traits="loud"),
            lambda k: k["equipment"][0].update(tl="eleven"),
            lambda k: k["classes"][0].update(moves=[{"name": "X", "level": 0, "trigger": "t", "description": "d"}]),
            lambda k: k["classes"][0].update(template={"abilities": {"STR": 25}}),
            lambda k: k["classes"][0].update(template={"abilities": {"STR": 15, "DEX": 14, "CON": 13, "INT": 8,
                                                                     "WIS": 12, "CHA": 10}, "skills": ["Hacking"]}),
            lambda k: k.update(disadvantages=[{"name": "X", "kind": "flaw", "description": "d"}]),
            lambda k: k.update(conditions=[{"name": "Static", "description": "d", "penalty_on": ["damage"]}]),
            lambda k: k["spells"][0].update(focus="yes"),
        ]
        for i, mutate in enumerate(bad):
            kit = _kit()
            mutate(kit)
            self.assertTrue(self.errors(kit), f"case {i} should fail")

    def test_tech_level_warning(self):
        kit = _kit()
        kit["_meta"]["tech_level"] = 4
        kit["equipment"][0]["tl"] = 9
        self.assertTrue(any("tech" in w.lower() for w in worldkit.warnings(kit)))
        kit["equipment"][0]["rarity"] = "unique"            # a relic out of its era is allowed
        self.assertFalse(any("tech" in w.lower() for w in worldkit.warnings(kit)))


class MonsterTableTests(_Camp):
    def test_table_built_from_srd(self):
        table = json.loads((ROOT / "skills" / "dne" / "data" / "monster_stats_by_cr.json").read_text(encoding="utf-8"))
        for cr in ("0.25", "1", "5", "10"):
            row = table[cr]
            for stat in ("ac", "hp", "attack"):
                lo, mid, hi = row[stat]
                self.assertLessEqual(lo, mid)
                self.assertLessEqual(mid, hi)
        self.assertLess(table["1"]["hp"][1], table["10"]["hp"][1])
        self.assertLess(table["1"]["attack"][1], table["10"]["attack"][1])

    def test_monster_stats_cli_and_warning(self):
        r = self.run_py("worldkit.py", "monster-stats", "--cr", "3")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("HP", r.stdout)
        kit = _kit()
        kit["monsters"][0]["hp"] = 900
        self.assertTrue(any(kit["monsters"][0]["name"] in w and "HP" in w for w in worldkit.warnings(kit)))

    def test_example_kit_stays_clean(self):
        kit = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        self.assertEqual(worldkit.validate(kit), [])
        self.assertEqual(worldkit.warnings(kit), [])
        self.assertIn("tech_level", kit["_meta"])
        self.assertTrue(kit.get("disadvantages"))
        self.assertTrue(any(c.get("moves") for c in kit["classes"]))
        self.assertTrue(any(c.get("template") for c in kit["classes"]))


class KitUseTests(_Camp):
    def setUp(self):
        super().setUp()
        kit = json.loads((self.camp / "worldkit.json").read_text(encoding="utf-8"))
        soldier = next(c for c in kit["classes"] if c["index"] == "soldier")
        soldier["moves"] = [{"name": "Hold the Hatch", "level": 1, "trigger": "When you block a doorway",
                             "description": "Enemies must go through you."},
                            {"name": "Covering Fire", "level": 3, "trigger": "When an ally runs",
                             "description": "They take no opportunity attacks."}]
        soldier["template"] = {"abilities": {"STR": 15, "DEX": 14, "CON": 13, "INT": 8, "WIS": 12, "CHA": 10},
                               "skills": ["Athletics", "Perception"]}
        kit["disadvantages"] = [{"name": "Oxygen Debt", "kind": "disadvantage", "description": "Owes the plant."}]
        self.relic = kit["equipment"][0]["name"]
        kit["equipment"][0]["rarity"] = "rare"
        (self.camp / "worldkit.json").write_text(json.dumps(kit), encoding="utf-8")

    def test_lookup_moves_disadvantages_template(self):
        r = self.run_py("lookup.py", "move", "Covering Fire", "-c", "eden")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("When an ally runs", r.stdout)
        self.assertIn("Oxygen Debt", self.run_py("lookup.py", "disadvantage", "oxygen debt", "-c", "eden").stdout)
        self.assertIn("Quick build", self.run_py("lookup.py", "class", "Soldier", "-c", "eden").stdout)

    def test_levelup_lists_moves_at_new_level(self):
        r = self.run_py("character.py", "levelup", "--class", "Soldier", "--from", "2", "--con-mod", "1", "-c", "eden")
        self.assertIn("Covering Fire", r.stdout)
        self.assertNotIn("Hold the Hatch", r.stdout)

    def test_buying_a_rare_item_needs_force(self):
        (self.camp / "characters" / "mae.md").write_text(
            "# Mae\n## Equipment & Inventory\n**Currency:** 500\n", encoding="utf-8")
        r = self.run_py("economy.py", "-c", "eden", "buy", "--char", "Mae", "--item", self.relic, "--cost", "50gp")
        self.assertEqual(r.returncode, 1)
        self.assertIn("rare", (r.stdout + r.stderr).lower())
        r = self.run_py("economy.py", "-c", "eden", "buy", "--char", "Mae", "--item", self.relic, "--cost", "50gp",
                        "--force")
        self.assertEqual(r.returncode, 0, r.stderr)
