"""Braid modules (PR 4): the module format and its loader, modules.py.

Every module in data/modules/ is checked here by the same rules, so a module added later (PR 5, PR 6) is held to the
format without touching this file: valid fields, rules text of 40 lines or less, no trade names, tables that exist,
genre ids that are story_axes ids, and `apply` that gives the same state twice as once and never resets a track."""
from __future__ import annotations

import contextlib
import io
import json
import pathlib
import re
import sys
import tempfile
import unittest
from unittest import mock

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _engine_case import EngineCase  # noqa: E402
from test_braid_seam import stamp  # noqa: E402

import turn  # noqa: E402,F401  (the engine first)
import modules  # noqa: E402

#: Names that belong to published games: a module never uses them (plan §6: neutral names, our own words).
TRADE = [r"Sanity", r"Cthulhu", r"Theori[sz]e", r"Brindlewood", r"Ten Candles", r"Jenga", r"GUMSHOE", r"Mythos",
         r"Delta Green", r"Mothership", r"Year Zero", r"Blades in the Dark", r"Apocalypse World", r"Ironsworn",
         r"Keeper", r"\bSAN\b", r"Trophy", r"Kult"]


def call(*argv) -> "tuple[int, str]":
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        code = modules.main(list(argv))
    return code, buf.getvalue()


def fake(folder: pathlib.Path, mid: str, **extra) -> None:
    body = {"id": mid, "name": mid.title(), "use_when": "Use when testing.", "genres": ["horror"], "requires": [],
            "conflicts": [], "tracks": [], "pools": [], "tables": {}, "numbers": {}, **extra}
    (folder / f"{mid}.json").write_text(json.dumps(body), encoding="utf-8")
    (folder / f"{mid}.md").write_text("Rules.\n", encoding="utf-8")


class Format(unittest.TestCase):
    """Every module file there is, now and later."""

    def test_every_module_keeps_the_format(self):
        found = modules.catalog()
        self.assertGreaterEqual(len(found), 5)
        for mid in found:
            self.assertEqual(modules.validate(mid), [], mid)

    def test_no_trade_names_in_any_module(self):
        for path in sorted(modules.DIR.glob("*.*")):
            text = path.read_text(encoding="utf-8")
            self.assertEqual([t for t in TRADE if re.search(t, text)], [], path.name)

    def test_validate_catches_a_broken_module(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(modules, "DIR", pathlib.Path(tmp)):
            fake(pathlib.Path(tmp), "bad", id="wrong", genres=["noir"], requires=["ghost"],
                 tracks=[{"id": "fear", "owner": "everyone", "thresholds": [{"at": 2, "table": "missing"}]}],
                 tables={"empty": []}, script="mod_nothing")
            (pathlib.Path(tmp) / "bad.md").write_text("line\n" * 41, encoding="utf-8")
            got = "\n".join(modules.validate("bad"))
        for bit in ("is not the file name", "longer than 40", "unknown module 'ghost'", "'noir' is not a story_axes",
                    "table empty", "owner pc|party", "'missing' is not in tables", "mod_nothing.py does not exist"):
            self.assertIn(bit, got)


class Loader(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self._tmp.name)
        fake(self.dir, "alpha", requires=["beta"])
        fake(self.dir, "beta")
        fake(self.dir, "gamma", conflicts=["alpha"])
        for n in range(8):
            fake(self.dir, f"m{n}")
        self._patch = mock.patch.object(modules, "DIR", self.dir)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self._tmp.cleanup()

    def test_requires_conflicts_unknown_and_the_limit(self):
        self.assertEqual(modules.problems(["alpha", "beta"]), ([], []))
        self.assertEqual(modules.problems(["alpha"])[0], ["alpha requires beta: switch it on too"])
        self.assertEqual(modules.problems(["alpha", "beta", "gamma"])[0], ["alpha and gamma conflict: pick one"])
        self.assertEqual(modules.problems(["gamma", "alpha", "beta"])[0], ["alpha and gamma conflict: pick one"])
        self.assertEqual(modules.problems(["beta", "nope"])[0], ["unknown module 'nope'"])
        eight = [f"m{n}" for n in range(8)]
        self.assertEqual(modules.problems(eight), ([], []))
        errors, warnings = modules.problems(eight + ["beta"])
        self.assertEqual((errors, len(warnings)), ([], 1))
        self.assertIn("more than 8", warnings[0])

    def test_cli_check_and_rules(self):
        self.assertEqual(call("check", "alpha,beta")[0], 0)
        code, out = call("check", "alpha", "gamma")
        self.assertEqual(code, 1)
        self.assertIn("ERROR: alpha requires beta", out)
        self.assertEqual(call("show", "nope")[0], 2)
        self.assertEqual(call("rules")[0], 2)                       # nothing named, no campaign


class RealModules(unittest.TestCase):
    def test_the_pr4_set_and_its_one_conflict(self):
        self.assertTrue({"composure", "panic", "doom", "clues", "make_the_case"} <= set(modules.catalog()))
        self.assertEqual(modules.problems(["composure", "panic", "doom", "clues"]), ([], []))
        self.assertEqual(modules.problems(["clues", "make_the_case"])[0], ["clues and make_the_case conflict: pick one"])

    def test_rules_text_prints_only_what_is_named(self):
        code, out = call("rules", "composure", "clues")
        self.assertEqual(code, 0)
        self.assertIn("## Composure (`composure`)", out)
        self.assertIn("## Clues (`clues`)", out)
        self.assertNotIn("## Panic", out)
        self.assertIn(modules.rules_of("composure").splitlines()[0], out)


class Campaign(EngineCase):
    """The Session Flag, `apply` through the engine, and session start."""
    FLAGS = "- display: none\n- roll_mode: auto\n- world_engine: on\n- modules: composure, panic,  doom\n"

    def setUp(self):
        super().setUp()
        stamp(self.camp, "core")

    def state(self) -> dict:
        with self.wdb.reader("oldworld") as db:
            return {k: self.wdb.all_of(db, k) for k in ("track", "pool", "condition")}

    def apply(self, why="apply"):
        out = self.do(why, {"action": "modules", "apply": True, "why": why})
        self.turn.finish("oldworld", "ok")
        return self.data(out)

    def test_flag_is_a_list(self):
        self.assertEqual(modules.enabled("oldworld"), ["composure", "panic", "doom"])
        self.flags("- world_engine: on\n- modules: none\n")
        self.assertEqual(modules.enabled("oldworld"), [])
        self.flags("- world_engine: on\n")
        self.assertEqual(modules.enabled("oldworld"), [])

    def test_a_change_of_the_set_is_logged(self):
        self.assertEqual(self.apply()["changed"], {"added": ["composure", "panic", "doom"], "removed": []})
        self.assertNotIn("changed", self.apply("again"))                         # same set: nothing to log
        self.flags("- display: none\n- roll_mode: auto\n- world_engine: on\n- modules: composure, clues\n")
        self.assertEqual(self.apply("switch")["changed"], {"added": ["clues"], "removed": ["panic", "doom"]})
        log = self.thing("modules", "campaign")["log"]
        self.assertEqual([e["added"] for e in log], [["composure", "panic", "doom"], ["clues"]])
        import turn_snapshot
        turn_snapshot.undo_snapshot("oldworld", notify_display=False)               # undo takes the entry back
        self.assertEqual(len(self.thing("modules", "campaign")["log"]), 1)

    def test_apply_gives_each_pc_the_tracks_and_keeps_the_breaking_point(self):
        d = self.apply()
        self.assertEqual(d["pcs"], ["Mira"])
        comp, stress, doom = (self.thing("track", k) for k in ("mira/composure", "mira/stress", "party/doom"))
        self.assertEqual((comp["value"], comp["min"], comp["max"]), (10, 0, 10))
        self.assertEqual([(t["at"], t["dir"]) for t in comp["thresholds"]], [(6, "down"), (3, "down"), (0, "down")])
        self.assertIsInstance(comp["thresholds"][0]["table"], list)               # inlined: the record stands alone
        self.assertEqual((stress["value"], stress["max"]), (0, 6))
        self.assertEqual(sorted(t["at"] for t in stress["thresholds"]), [3, 5, 6])  # panic's two + Braid's breaking point
        self.assertEqual((doom["value"], doom["max"]), (0, 20))
        once = self.state()
        self.apply("again")
        self.assertEqual(self.state(), once)

    def test_apply_never_resets_a_track_and_merges_into_one_in_play(self):
        self.flags("- display: none\n- roll_mode: auto\n- world_engine: on\n- modules: composure\n")
        self.apply()
        self.do("hurt", {"action": "track", "owner": "Mira", "id": "composure", "mark": -2, "why": "x"},
                {"action": "track", "owner": "Mira", "id": "stress", "mark": 2, "why": "y"})
        self.turn.finish("oldworld", "ok")
        self.flags("- display: none\n- roll_mode: auto\n- world_engine: on\n- modules: composure, panic\n")
        self.apply("panic on mid-campaign")
        self.assertEqual(self.thing("track", "mira/composure")["value"], 8)
        stress = self.thing("track", "mira/stress")
        self.assertEqual(stress["value"], 2)
        self.assertEqual(sorted(t["at"] for t in stress["thresholds"]), [3, 5, 6])

    def test_every_module_applies_the_same_twice_as_once(self):
        for mid, mod in modules.catalog().items():
            with self.subTest(mid):
                self.flags(f"- display: none\n- roll_mode: auto\n- world_engine: on\n- modules: {', '.join([mid] + mod['requires'])}\n")
                d = self.apply(f"{mid} 1")
                self.assertNotIn("error", d)
                for kind, decls in (("track", mod["tracks"]), ("pool", mod["pools"])):
                    for decl in decls:
                        owner = "party" if decl["owner"] == "party" else "mira"
                        self.assertIsNotNone(self.thing(kind, f"{owner}/{decl['id']}".casefold()), (mid, decl["id"]))
                once = self.state()
                self.apply(f"{mid} 2")
                self.assertEqual(self.state(), once)

    def test_switching_a_module_off_takes_its_thresholds_back(self):
        self.apply()
        self.flags("- display: none\n- roll_mode: auto\n- world_engine: on\n- modules: composure\n")
        d = self.apply("panic off")
        self.assertEqual(d["dropped"], ["Mira stress"])
        self.assertEqual([t["at"] for t in self.thing("track", "mira/stress")["thresholds"]], [6])
        self.assertEqual(len(self.thing("track", "mira/composure")["thresholds"]), 3)

    def test_pools_are_made_once(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(modules, "DIR", pathlib.Path(tmp)):
            fake(pathlib.Path(tmp), "luck", pools=[{"id": "luck", "owner": "pc", "max": 3, "set": 2, "cadence": "session"},
                                                   {"id": "supplies", "owner": "party", "die": "d8"}])
            self.flags("- world_engine: on\n- modules: luck\n")
            self.apply()
            self.do("spend", {"action": "pool", "owner": "Mira", "id": "luck", "spend": 1, "why": "x"})
            self.turn.finish("oldworld", "ok")
            self.apply("again")
        self.assertEqual((self.thing("pool", "mira/luck")["value"], self.thing("pool", "party/supplies")["die"]), (1, "d8"))

    def test_refusals(self):
        self.flags("- world_engine: on\n- modules: clues, make_the_case\n")
        self.assertIn("conflict", self.apply()["error"])
        self.flags("- world_engine: on\n- modules: composure\n")
        stamp_d20 = (self.camp / "state.md").read_text(encoding="utf-8").replace("**System:** core", "**System:** d20")
        (self.camp / "state.md").write_text(stamp_d20, encoding="utf-8")
        self.assertIn("Braid", self.apply("d20")["error"])
        self.assertIsNone(self.thing("track", "mira/composure"))

    def test_session_start_names_the_rules_command_for_core_only(self):
        import gm_guide
        steps = "\n".join(gm_guide.session_start("oldworld"))
        self.assertIn("modules.py\" -c oldworld rules", steps)
        self.assertIn("composure, panic, doom", steps)
        from test_braid_rules import leaks
        self.assertEqual(leaks(steps.split("modules.py")[1].splitlines()[0]), [])
        self.flags("- world_engine: on\n")
        self.assertNotIn("modules.py", "\n".join(gm_guide.session_start("oldworld")))
        self.flags("- world_engine: on\n- modules: composure\n")
        state = self.camp / "state.md"
        state.write_text(state.read_text(encoding="utf-8").replace("**System:** core", "**System:** d20"), encoding="utf-8")
        self.assertNotIn("modules.py", "\n".join(gm_guide.session_start("oldworld")))

    def test_cli_reads_the_campaign(self):
        code, out = call("-c", "oldworld", "rules")
        self.assertEqual(code, 0)
        self.assertIn("## Doom (`doom`)", out)
        self.assertNotIn("## Clues", out)
        code, out = call("-c", "oldworld", "apply")
        self.assertIn('"action": "modules", "apply": true', out)


if __name__ == "__main__":
    unittest.main()
