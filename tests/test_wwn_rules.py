"""Ideas from Worlds Without Number (own numbers and text): faction turns,
Morale / Instinct for enemies, and place tags."""
from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from test_playtest_round6 import SCRIPTS, _Camp  # noqa: E402  (shared campaign fixture)

sys.path.insert(0, str(SCRIPTS))


class FactionTests(_Camp):
    def f(self, *a):
        return self.run_py("faction.py", "-c", "eden", *a)

    def add_two(self):
        self.assertEqual(self.f("add", "Jade Guild", "--force", "2", "--wealth", "4", "--influence", "3",
                                "--goal", "Take the docks", "--clock", "4", "--goal-stat", "wealth",
                                "--rivals", "Iron Syndicate").returncode, 0)
        self.assertEqual(self.f("add", "Iron Syndicate", "--force", "4", "--wealth", "2", "--influence", "2",
                                "--rivals", "Jade Guild").returncode, 0)

    def data(self):
        return json.loads((self.camp / "factions.json").read_text(encoding="utf-8"))

    def test_no_factions_is_harmless(self):
        r = self.f("turn")
        self.assertEqual(r.returncode, 0)
        self.assertIn("No factions", r.stdout)
        self.assertFalse((self.camp / "factions.json").exists())

    def test_add_status_and_stability(self):
        self.add_two()
        out = self.f("status").stdout
        self.assertIn("Jade Guild: F2 W4 I3 · Stability 13/13", out)
        self.assertIn("goal \"Take the docks\" 0/4 (wealth)", out)
        self.assertIn("Iron Syndicate: F4 W2 I2 · Stability 12/12 · no goal", out)
        self.assertNotEqual(self.f("add", "jade guild", "--force", "1", "--wealth", "1", "--influence", "1").returncode, 0)
        self.assertNotEqual(self.f("add", "X", "--force", "6", "--wealth", "1", "--influence", "1").returncode, 0)

    def test_turn_needs_a_calendar_or_force(self):
        self.add_two()
        r = self.f("turn")
        self.assertIn("No calendar", r.stdout)
        r = self.f("turn", "--force-turn", "--seed", "1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(sum(l.startswith("- ") for l in r.stdout.splitlines()), 2)
        self.assertIn("Faction Moves", r.stdout)

    def test_weekly_guard_and_catch_up(self):
        self.add_two()
        self.assertEqual(self.run_py("calendar.py", "-c", "eden", "init").returncode, 0)
        self.assertIn("- ", self.f("turn", "--seed", "2").stdout)            # first turn always runs
        self.assertIn("No faction turn yet", self.f("turn").stdout)          # same day: refused
        self.run_py("calendar.py", "-c", "eden", "advance", "15", "days")
        self.assertIn("Week 2 of 2", self.f("turn", "--seed", "3").stdout)   # two weeks owed
        self.assertIn("No faction turn yet", self.f("turn").stdout)
        self.run_py("calendar.py", "-c", "eden", "advance", "70", "days")
        out = self.f("turn", "--seed", "4").stdout
        self.assertIn("Week 4 of 4", out)                                    # capped
        self.assertIn("No faction turn yet", self.f("turn").stdout)          # the rest is not owed later

    def test_first_turn_waits_a_week_when_a_calendar_exists(self):
        self.run_py("calendar.py", "-c", "eden", "init")
        self.add_two()
        self.assertIn("No faction turn yet", self.f("turn").stdout)
        self.run_py("calendar.py", "-c", "eden", "advance", "7", "days")
        self.assertIn("- ", self.f("turn", "--seed", "1").stdout)

    def test_goal_completion_raises_the_stat(self):
        import faction, random
        data = {"factions": {}, "last_turn": None}
        data["factions"]["A"] = {"force": 1, "wealth": 5, "influence": 1, "goal": "g", "clock": 4,
                                 "goal_stat": "wealth", "progress": 3, "rivals": [], "stability": 11}
        line = faction.act("A", data, random.Random(0), "advance")
        f = data["factions"]["A"]
        if "GOAL COMPLETE" in line:
            self.assertEqual(f["wealth"], 5)                  # capped at 5
            self.assertEqual(f["progress"], 4)
        with self.assertRaises(ValueError):
            faction.act("A", {"factions": {"A": {**f, "goal": None}}}, random.Random(0), "advance")

    def test_attack_collapse_and_adjust(self):
        import faction, random
        data = {"factions": {
            "A": {"force": 5, "wealth": 1, "influence": 1, "goal": None, "clock": 6, "goal_stat": "force",
                  "progress": 0, "rivals": ["B"], "stability": 11},
            "B": {"force": 1, "wealth": 1, "influence": 1, "goal": None, "clock": 6, "goal_stat": "force",
                  "progress": 0, "rivals": [], "stability": 1}}, "last_turn": None}
        rng = random.Random(0)
        for _ in range(20):
            if data["factions"]["B"]["stability"] == 0:
                break
            faction.act("A", data, rng, "attack", "b")
        self.assertEqual(data["factions"]["B"]["stability"], 0)
        self.assertIn("collapsed", faction.act("B", data, rng))
        with self.assertRaises(ValueError):
            faction.act("A", data, rng, "attack", "B")        # can't hit a collapsed faction
        self.add_two()
        out = self.f("adjust", "Jade Guild", "--stability", "-5", "--progress", "2").stdout
        self.assertIn("Stability 8/13", out)
        self.assertIn("2/4", out)
        self.assertNotEqual(self.f("adjust", "Iron Syndicate", "--progress", "1").returncode, 0)  # no goal

    def test_set_remove_and_snapshot(self):
        self.add_two()
        out = self.f("set", "Iron Syndicate", "--goal", "Own the night market", "--clock", "8",
                     "--goal-stat", "force").stdout
        self.assertIn("0/8 (force)", out)
        self.assertEqual(self.f("remove", "Jade Guild").returncode, 0)
        self.assertEqual(self.data()["factions"]["Iron Syndicate"]["rivals"], [])
        import turn_snapshot
        self.assertIn("factions.json", turn_snapshot.CAMPAIGN_FILES)


class MoraleInstinctTests(_Camp):
    def e(self, *a):
        return self.run_py("tracker.py", "-c", "eden", "enemy", *a)

    def test_defaults_and_supplied_rolls(self):
        out = self.e("morale", "Goblin", "--roll", "9").stdout
        self.assertIn("vs morale 8 (default) → BREAKS", out)
        self.assertIn("HOLDS", self.e("morale", "Goblin", "--roll", "6", "--mod", "2").stdout)   # 8 is not above 8
        self.assertIn("INSTINCT this round", self.e("instinct", "Goblin", "--roll", "3").stdout)
        self.assertIn("full cunning", self.e("instinct", "Goblin", "--roll", "4").stdout)
        self.assertNotEqual(self.e("morale", "Goblin", "--roll", "13").returncode, 0)

    def test_set_keeps_what_was_not_passed(self):
        self.e("set", "Boss", "--role", "caster", "--morale-score", "10", "--instinct", "1",
               "--instincts", "screams at the sky;tears off its mask")
        out = self.e("set", "Boss", "--slots", "1:2").stdout
        self.assertIn("role=caster", out)
        self.assertIn("morale 10", out)
        self.assertIn("instinct 1", out)
        r = self.e("instinct", "Boss", "--roll", "1").stdout
        self.assertTrue("screams at the sky" in r or "tears off its mask" in r, r)
        self.assertNotEqual(self.e("set", "Boss", "--morale-score", "13").returncode, 0)

    def test_from_world_kit_and_never_breaks(self):
        kit = json.loads((self.camp / "worldkit.json").read_text(encoding="utf-8"))
        mon = kit["monsters"][0]
        mon.update(morale=12, instinct=6, instincts=["hunts the warmest body"])
        (self.camp / "worldkit.json").write_text(json.dumps(kit), encoding="utf-8")
        out = self.e("set", "It", "--kit", mon["name"]).stdout
        self.assertIn("morale 12", out)
        self.assertIn(f"role={mon['role']}", out)
        self.assertIn("never breaks", self.e("morale", "It").stdout)
        self.assertIn("hunts the warmest body", self.e("instinct", "It", "--roll", "2").stdout)
        self.assertNotEqual(self.e("set", "It", "--kit", "No Such Thing").returncode, 0)

    def test_advise_points_at_the_morale_roll(self):
        self.e("set", "Orc", "--morale", "40")
        self.assertIn("enemy morale", self.e("advise", "Orc", "--hp-pct", "30").stdout)
        self.e("set", "Bot", "--morale", "40", "--morale-score", "12")
        out = self.e("advise", "Bot", "--hp-pct", "10").stdout
        self.assertIn("FIGHTS TO THE END", out)
        self.assertNotIn("enemy morale", out)

    def test_advise_names_who_is_down(self):
        self.e("set", "Orc")
        self.assertNotIn("DOWN AT 0 HP", self.e("advise", "Orc").stdout)
        state = json.loads((self.camp / "tracker.json").read_text(encoding="utf-8"))
        state["mira"] = {"name": "Mira", "conditions": ["unconscious"], "effects": [],
                         "death_saves": {"successes": 0, "failures": 1, "stable": False}}
        (self.camp / "tracker.json").write_text(json.dumps(state), encoding="utf-8")
        self.assertIn("DOWN AT 0 HP: Mira", self.e("advise", "Orc").stdout)

    def test_kit_validation_and_lookup(self):
        import worldkit
        kit = json.loads((self.camp / "worldkit.json").read_text(encoding="utf-8"))
        kit["monsters"][0]["morale"] = 1
        kit["monsters"][0]["instinct"] = 11
        errs = "\n".join(worldkit.validate(kit))
        self.assertIn("morale must be an integer 2–12", errs)
        self.assertIn("instinct must be an integer 0–10", errs)
        kit["monsters"][0].update(morale=9, instinct=2)
        (self.camp / "worldkit.json").write_text(json.dumps(kit), encoding="utf-8")
        out = self.run_py("lookup.py", "monster", kit["monsters"][0]["name"], "-c", "eden").stdout
        self.assertIn("morale 9", out)


class PlaceTagTests(_Camp):
    TAG = {"name": "Signal Bleed", "description": "The AI's signal leaks in.",
           "enemies": ["a listener"], "friends": ["a scavenger"], "complications": ["the pumps"],
           "things": ["a relay"], "places": ["the cable run"]}

    def test_generic_roll_is_seeded_and_distinct(self):
        a = self.run_py("tags.py", "roll", "--n", "3", "--seed", "7")
        b = self.run_py("tags.py", "roll", "--n", "3", "--seed", "7")
        self.assertEqual(a.returncode, 0, a.stderr)
        self.assertEqual(a.stdout, b.stdout)
        names = [l for l in a.stdout.splitlines() if l.startswith("## ")]
        self.assertEqual(len(names), 3)
        self.assertEqual(len(set(names)), 3)
        self.assertEqual(a.stdout.count("- Enemies: "), 3)

    def test_generic_library_is_complete(self):
        import tags
        lib = tags.generic()
        self.assertGreaterEqual(len(lib), 20)
        for t in lib:
            for part in tags.PARTS:
                self.assertTrue(t[part], (t["name"], part))

    def test_world_tags_come_first(self):
        kit = json.loads((self.camp / "worldkit.json").read_text(encoding="utf-8"))
        kit["place_tags"] = [self.TAG, {**self.TAG, "name": "Last Greenhouse"}]
        (self.camp / "worldkit.json").write_text(json.dumps(kit), encoding="utf-8")
        out = self.run_py("tags.py", "-c", "eden", "roll", "--seed", "1").stdout
        self.assertIn("## Signal Bleed", out)
        self.assertIn("## Last Greenhouse", out)
        self.assertIn("World tags: ", self.run_py("tags.py", "-c", "eden", "list").stdout)
        self.assertIn("a relay", self.run_py("tags.py", "-c", "eden", "show", "signal bleed").stdout)
        self.assertNotEqual(self.run_py("tags.py", "show", "Nope").returncode, 0)

    def test_place_tag_validation(self):
        import worldkit
        kit = json.loads((self.camp / "worldkit.json").read_text(encoding="utf-8"))
        kit["place_tags"] = [{"name": "Bad", "enemies": "not a list"}]
        errs = "\n".join(worldkit.validate(kit))
        self.assertIn("description is required", errs)
        self.assertIn("enemies must be a list of strings", errs)
        kit["place_tags"] = [{"name": "Empty", "description": "x"}]
        self.assertIn("needs at least one of", "\n".join(worldkit.validate(kit)))

    def test_lookup_with_a_kit_that_has_place_tags(self):
        example = SCRIPTS.parent / "templates" / "worldkit.example.json"
        (self.camp / "worldkit.json").write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
        r = self.run_py("lookup.py", "monster", "Scav Raider", "-c", "eden")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("morale 7", r.stdout)
        self.assertIn("instinct 5", r.stdout)

    def test_example_kit_is_valid(self):
        import worldkit
        example = SCRIPTS.parent / "templates" / "worldkit.example.json"
        kit = json.loads(example.read_text(encoding="utf-8"))
        self.assertEqual(worldkit.validate(kit), [])
        self.assertTrue(kit["place_tags"])
        self.assertTrue(any("morale" in m for m in kit["monsters"]))
