"""Braid PR 3, the rules (SKILL-core.md, sheet.py) and a 5e-free path through a core campaign.

Acceptance: a fresh core campaign goes campaign_init → gm_guide start → a full engine turn with a roll → sheet.py
check → campaign_version audit, and nothing it prints points at a 5e script or stat, and no 5e module is touched.
A scripted scene plays one character from creation to the end of a fight on the same sheet and the same roll."""
from __future__ import annotations

import contextlib
import importlib
import io
import json
import os
import pathlib
import re
import sys
import tempfile
import types
import unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _engine_case import SCRIPTS, EngineCase  # noqa: E402,F401
from test_braid_seam import stamp  # noqa: E402

import turn  # noqa: E402,F401  (the engine first: importing journey before it trips the old circular import)

#: Words that would send the GM to 5e rules. Script names as substrings; stats as whole words (AC, not "ACtion").
FORBIDDEN = [r"combat\.py", r"xp\.py", r"character\.py", r"encounter_gen\.py", r"lookup\.py", r"(?i)spell slot",
             r"\bAC\b", r"\bDC\b", r"\bHP\b", r"(?i)hit dice", r"(?i)\bhit die\b", r"--cr\b", r"(?i)challenge rating",
             r"(?i)classic SRD", r"(?i)death save"]
FIVE_E = ("character", "xp", "combat", "encounter_gen", "lookup", "ability-scores")


def leaks(text: str) -> list:
    return [p for p in FORBIDDEN if re.search(p, text)]


class _Spy(types.ModuleType):
    """Stands in for a 5e module: any use is recorded (an exception would be swallowed by the callers)."""
    used: list = []

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        _Spy.used.append(f"{self.__name__}.{name}")
        raise AttributeError(f"5e module {self.__name__} used: {name}")


#: 5e entry points inside modules Braid also uses (travel, buy/sell, generic conditions): spied one by one.
FIVE_E_ACTIONS = ("fight", "combatant", "advise", "move", "spend", "damage", "area", "prop", "round", "rest")
FIVE_E_FUNCS = {"tracker": ("cmd_saves", "cmd_rest"), "economy": ("apply_rest", "treat_wounds", "treasure_budget")}


def _watch(name, fn):
    def watched(*a, **k):
        _Spy.used.append(name)
        return fn(*a, **k)
    return watched


@contextlib.contextmanager
def no_5e():
    _Spy.used = []
    import journey  # noqa: F401  (registers travel and rest)
    import skirmish  # noqa: F401
    mods = {m: importlib.import_module(m) for m in FIVE_E_FUNCS}
    saved = {m: sys.modules.get(m) for m in FIVE_E}
    handlers = {a: turn.HANDLERS[a] for a in FIVE_E_ACTIONS}
    funcs = {(m, f): getattr(mods[m], f) for m, names in FIVE_E_FUNCS.items() for f in names}
    sys.modules.update({m: _Spy(m) for m in FIVE_E})
    turn.HANDLERS.update({a: _watch(f"action {a}", h) for a, h in handlers.items()})
    for (m, f), fn in funcs.items():
        setattr(mods[m], f, _watch(f"{m}.{f}", fn))
    try:                       # only these keys are swapped back: the engine modules imported meanwhile stay loaded
        yield _Spy.used
    finally:
        for m, mod in saved.items():
            sys.modules.pop(m) if mod is None else sys.modules.__setitem__(m, mod)
        turn.HANDLERS.update(handlers)
        for (m, f), fn in funcs.items():
            setattr(mods[m], f, fn)


SEED = {"seed_version": 1, "campaign": "braid", "system": "core",
        "flags": {"display": "none", "roll_mode": "players"},
        "calendar": {"date": "1 Thaw 412", "time": "morning", "months": ["Thaw", "Bloom"], "month_length": 30},
        "map": {"party_location": "ford", "places": {"ford": {"name": "The Ford"}, "market": {"name": "Market"}},
                "edges": [{"a": "ford", "b": "market", "miles": 12}]},
        "npcs": [{"name": "Captain Hale", "role": "toll captain", "threat": 3, "location": "The Ford"}]}
KIT = {"_meta": {"name": "Ford", "genre": ["mystery"], "premise": "a toll bridge"},
       "labels": [{"name": "Smuggler", "description": "knows every back door"}],
       "equipment": [{"name": "Forged papers"}],
       "threats": [{"name": "Toll Guard", "threat": 2, "moves": ["blows the whistle"]}]}

MIRA = ["new", "--name", "Mira Vale", "--concept", "A smuggler who owes everyone", "--drive", "Get her brother out",
        "--flaw", "Can't walk away from a bet", "--approaches", "wits=2,finesse=1,heart=1,force=0,grit=-1",
        "--labels", "Smuggler: knows every back door,Ex-navy pilot", "--gear", "knife,forged papers",
        "--bonds", "Theo: he covered for her"]
THEO = ["new", "--name", "Theo", "--concept", "A clerk with a conscience", "--drive", "Expose the toll",
        "--flaw", "Trusts paperwork over people", "--approaches", "heart=2,wits=1,grit=1,finesse=0,force=-1",
        "--labels", "Freight clerk,Reads any ledger"]


class BraidCampaign(unittest.TestCase):
    """A real core campaign made by campaign_init, players rolling their own dice."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)
        self._saved = {k: os.environ.get(k) for k in ("DNE_CAMPAIGN_ROOT", "DNE_RUNTIME_DIR", "DNE_DISPLAY_HOST",
                                                       "DNE_OUTBOX_LOG", "DNE_NOTE_BUDGET")}
        os.environ.update(DNE_CAMPAIGN_ROOT=str(self.root), DNE_RUNTIME_DIR=str(self.root / "rt"),
                          DNE_DISPLAY_HOST="127.0.0.1:9", DNE_OUTBOX_LOG=str(self.root / "out.jsonl"))
        (self.root / "rt").mkdir()
        self.out = []

    def tearDown(self):
        for k, v in self._saved.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        self._tmp.cleanup()

    def run_main(self, module, argv) -> int:
        buf, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
            code = module.main(argv)
        self.out.append(buf.getvalue() + err.getvalue())
        return code

    def build(self, **extra) -> None:
        import campaign_init
        built = campaign_init.build({**SEED, **extra})
        self.assertTrue(built.get("ok"), built)
        self.out.append(json.dumps(built))

    def sheet(self, *argv) -> int:
        import sheet
        return self.run_main(sheet, ["-c", "braid", *argv])

    def turn_with(self, text, *intents, answers=()):
        """One engine turn; each answer goes to the request that is open."""
        import gm_guide
        import turn
        turn.begin("braid", text)
        r = turn.resolve("braid", list(intents))
        self.out += gm_guide.engine_lines("braid", r) + [line for _p, line in gm_guide.turn_parts("braid", False, text, r)]
        for a in answers:
            self.assertEqual(r["status"], "waiting_for_player", r)
            r = turn.answer("braid", r["next_input"]["request_id"], a)
            self.out += [line for _p, line in gm_guide.turn_parts("braid", False, text, r)]
        self.out.append(json.dumps(r, ensure_ascii=False))
        turn.finish("braid", "ok")
        return r

    def data(self, r, i=-1):
        return r["results"][i]["data"]

    def thing(self, kind, key):
        import world_db as wdb
        with wdb.reader("braid") as db:
            return wdb.get(db, kind, key)


class NoFiveEOnTheWay(BraidCampaign):
    def test_init_start_turn_check_audit_say_nothing_5e(self):
        with no_5e() as used:
            self.build(worldkit=KIT)
            import campaign_version
            import gm_guide
            self.out += gm_guide.session_start("braid")
            self.assertEqual(self.sheet(*MIRA), 0)
            r = self.turn_with("[Mira]: I slip past the toll captain",
                               {"action": "roll", "actor": "Mira", "approach": "finesse", "label": "slip past"},
                               answers=["8"])
            self.assertEqual(self.data(r)["total"], 9)                  # 8 + Finesse +1 from the sheet
            self.assertEqual(self.sheet("check"), 0)
            self.out += campaign_version.audit("braid")
            npcs = (self.root / "campaigns" / "braid" / "npcs-full.md").read_text(encoding="utf-8")
            self.out.append(npcs)
            self.assertIn("**Threat:** 3", npcs)
        said = "\n".join(self.out)
        self.assertIn("SKILL-core.md", said)
        self.assertIn("worldkit.json: review warning: labels", said)        # the Braid kit branch ran
        self.assertEqual(leaks(said), [], said)
        self.assertEqual(used, [])

    def test_story_mode_the_same_way(self):
        with no_5e() as used:
            self.build(system="story", worldkit=KIT)
            import campaign_version
            import gm_guide
            self.out += gm_guide.session_start("braid")
            self.assertEqual(self.sheet(*MIRA), 0)
            r = self.turn_with("[Mira]: is the captain asleep?",
                               {"action": "roll", "actor": "Mira", "likelihood": "likely", "label": "asleep?"})
            self.assertIn(self.data(r)["degree"], ("critical failure", "failure", "success at a cost", "success",
                                                   "critical success"))
            self.assertEqual(self.sheet("check"), 0)
            self.out += campaign_version.audit("braid")
        said = "\n".join(self.out)
        self.assertIn("the oracle answers", said)
        self.assertEqual(leaks(said), [], said)
        self.assertEqual(used, [])

    def test_the_matcher_finds_5e_in_a_d20_campaign(self):
        """Positive control: the same words and the same chain on a 5e campaign are found."""
        import campaign_init
        import gm_guide
        built = campaign_init.build({**SEED, "system": "d20", "ruleset": "2014",
                                     "npcs": [{"name": "Captain Hale", "role": "toll captain", "cr": "1"}]})
        self.assertTrue(built["ok"], built)
        said = "\n".join(gm_guide.session_start("braid") + [l for _p, l in gm_guide.turn_parts("braid", False, "hi")])
        self.assertIn(r"combat\.py", leaks(said))
        self.assertIn(r"\bAC\b", leaks(said))
        import worldkit
        with no_5e() as used:                                                # and the spy sees a 5e module used
            with self.assertRaises(ImportError):
                worldkit.validate({"_meta": {}}, system="d20")
        self.assertTrue(used)
        with no_5e() as used:                                                # ... and a 5e entry point in a shared one
            import economy
            economy.treasure_budget(3)
        self.assertEqual(used, ["economy.treasure_budget"])


class ScriptedScene(BraidCampaign):
    """One scene, played by script: two characters made, a bond, a push, help, a fight with a threat-2 guard, harm
    that brings its condition, XP and an advance. Same sheet, same roll throughout; no 5e module touched."""

    def test_creation_to_the_end_of_a_fight(self):
        with no_5e() as used:
            self.build()
            self.assertEqual(self.sheet(*MIRA), 0)
            self.assertEqual(self.sheet(*THEO), 0)
            self.turn_with("setup",
                           {"action": "bond", "a": "Mira", "b": "Theo", "set": 1, "note": "he covered for her"},
                           {"action": "pool", "owner": "Mira", "id": "tokens", "max": 3, "set": 1, "cadence": "session"},
                           {"action": "track", "owner": "Gate Guard", "id": "harm", "max": 2, "why": "threat 2"})

            # A risky plan with a named cost: Finesse +1, pushed +1, Theo helps +1 → the player's 6 is a 9.
            r = self.turn_with("[Mira]: I go over the gate while Theo distracts the guard",
                               {"action": "judge", "actor": "Mira", "plan": "over the gate", "risk": "the guard sees",
                                "if_fails": "the guard raises the alarm", "cost": "she tears her coat on the spikes",
                                "approach": "finesse", "push": True, "help": "Theo"},
                               answers=["6", "accept"])
            self.assertEqual(self.data(r)["outcome"], "success_at_a_cost")
            self.assertEqual(self.thing("track", "mira/stress")["value"], 1)          # the push, marked once

            # The guard hits back: 2 harm, and Wounded comes with it.
            r = self.turn_with("[GM]: the guard's club", {"action": "track", "owner": "Mira", "id": "harm", "mark": 2,
                                                          "why": "the guard's club"})
            self.assertEqual([c["at"] for c in self.data(r)["crossed"]], [2])
            self.assertEqual(self.thing("condition", "mira/wounded")["mod"], -1)

            # Force is Wounded; the same roll reads it. 7 + Force 0 - 1 = 6: a failure, then a token steps it up.
            r = self.turn_with("[Mira]: I shove him off the bridge",
                               {"action": "roll", "actor": "Mira", "approach": "force", "label": "shove"}, answers=["7"])
            d = self.data(r)
            self.assertEqual((d["total"], d["degree"]), (6, "failure"))
            self.assertIn("Wounded -1", d["edges"])
            r = self.turn_with("[Mira]: I spend a token", {"action": "pool", "owner": "Mira", "id": "tokens", "step_up": True})
            self.assertEqual(self.data(r)["degree"], "success at a cost")
            r = self.turn_with("[Mira]: a token on the gate too?", {"action": "pool", "owner": "Mira", "id": "tokens",
                                                                     "step_up": True, "why": "again"})
            self.assertIn("error", self.data(r))                                # no tokens left
            r = self.turn_with("[GM]: the guard goes down", {"action": "track", "owner": "Gate Guard", "id": "harm",
                                                             "mark": 2, "why": "over the rail"})
            self.assertEqual(self.data(r)["value"], self.data(r)["max"])
            self.assertIsNone(self.thing("condition", "gate guard/wounded"))     # its own track: no PC thresholds

            # Recovery heals the harm and the condition goes with it.
            self.turn_with("[GM]: a night at the inn", {"action": "wait", "hours": 8},
                           {"action": "track", "owner": "Mira", "id": "harm", "mark": -1, "why": "a night's rest"})
            self.assertIsNone(self.thing("condition", "mira/wounded"))

            # XP and an advance on the same sheet.
            self.assertEqual(self.sheet("xp", "Mira", "--why", "went over the gate for her brother", "--event", "s1-drive"), 0)
            self.assertEqual(self.sheet("xp", "Mira", "--why", "went over the gate", "--event", "s1-drive"), 1)
            self.assertEqual(self.sheet("xp", "Mira", "--mark", "4", "--why", "the toll is broken", "--event", "s1-ms"), 0)
            self.assertEqual(self.sheet("advance", "Mira", "--raise", "force"), 0)
            self.assertEqual(self.sheet("check"), 0)
            self.assertEqual(self.sheet("show", "Mira"), 0)
            self.assertIn("Harm 1/4 | Stress 1/6", self.out[-1])
            self.assertIn("Force +1", self.out[-1])
        self.assertEqual(used, [])
        self.assertEqual(leaks("\n".join(self.out)), [])


class EdgesOnEveryCheck(EngineCase):
    """push / help / approach reach judge, flashback, bargain and search through mechanics.edged, under core only."""
    FLAGS = "- display: none\n- roll_mode: players\n- world_engine: on\n"

    def setUp(self):
        super().setUp()
        stamp(self.camp, "core")

    def answer_all(self, r, *answers):
        for a in answers:
            r = self.turn.answer("oldworld", r["next_input"]["request_id"], a)
        return r

    def test_judge_push_at_the_last_box_marks_once_through_the_cost(self):
        self.do("setup", {"action": "track", "owner": "Mira", "id": "stress", "set": 5})
        self.turn.finish("oldworld", "ok")
        r = self.do("judge", {"action": "judge", "actor": "Mira", "plan": "p", "risk": "r", "if_fails": "f", "cost": "c",
                              "roll": {"spec": "2d6+0", "push": True}})
        self.assertIn("2d6+1", r["next_input"]["question"])
        r = self.answer_all(r, "7", "accept")                       # 7 + 1 = 8: success at a cost, accepted
        self.assertEqual(self.data(r)["outcome"], "success_at_a_cost")
        self.assertEqual(self.thing("track", "mira/stress")["value"], 6)

    def test_bargain_stacks_with_push_and_flashback_takes_help(self):
        self.do("setup", {"action": "bond", "a": "Mira", "b": "Theo", "set": 1},
                {"action": "condition", "owner": "Mira", "name": "Shaken", "mod": -1, "approaches": ["heart"]})
        self.turn.finish("oldworld", "ok")
        r = self.do("bargain", {"action": "bargain", "actor": "Mira", "offer": "the guard remembers her",
                                "roll": {"spec": "2d6+1", "push": True}})
        r = self.turn.answer("oldworld", r["next_input"]["request_id"], "accept")
        self.assertIn("2d6+3", r["next_input"]["question"])           # +1 spec, +1 push, +1 bargain
        r = self.answer_all(r, "6")
        self.assertEqual(self.data(r)["total"], 9)
        self.turn.finish("oldworld", "ok")
        r = self.do("flashback", {"action": "flashback", "actor": "Mira", "claim": "I bribed the cook",
                                  "roll": {"spec": "2d6+1", "approach": "heart", "help": "Theo"}})
        self.assertIn("2d6+1", r["next_input"]["question"])           # +1, Shaken -1, Theo +1
        r = self.answer_all(r, "6")
        self.assertEqual(self.data(r)["edges"], ["Shaken -1", "Theo helps +1 (and shares what goes wrong)"])

    def test_search_pushes_and_d20_ignores_conditions(self):
        self.do("setup", {"action": "case", "id": "ledger", "question": "who took it",
                          "clues": [{"id": "ink", "text": "ink", "where": "office", "obvious": False}]})
        self.turn.finish("oldworld", "ok")
        r = self.do("search", {"action": "search", "actor": "Theo", "case": "ledger", "where": "office",
                               "roll": {"spec": "2d6+0", "push": True}})
        r = self.answer_all(r, "6")                               # 6 + push = 7: it helps
        self.assertTrue(self.data(r)["roll_helped"])
        self.assertEqual(self.thing("track", "theo/stress")["value"], 1)

    def test_d20_judge_is_untouched_by_conditions(self):
        stamp(self.camp, "d20")
        self.do("setup", {"action": "condition", "owner": "Mira", "name": "Shaken", "mod": -1})
        self.turn.finish("oldworld", "ok")
        r = self.do("judge", {"action": "judge", "actor": "Mira", "plan": "p", "risk": "r", "if_fails": "f",
                              "roll": {"spec": "1d20+5", "dc": 13, "push": True}})
        self.assertIn("1d20+5 (DC 13)", r["next_input"]["question"])
        r = self.answer_all(r, "8")
        self.assertEqual(self.data(r)["total"], 13)
        self.assertIsNone(self.thing("track", "mira/stress"))


class SheetRules(BraidCampaign):
    def test_check_catches_what_the_rules_forbid_and_accepts_an_advanced_sheet(self):
        import sheet
        self.build()
        self.assertEqual(self.sheet(*MIRA), 0)
        self.assertEqual(self.sheet(*MIRA), 1)                                    # never overwrites
        self.assertEqual(self.sheet(*[a if a != "heart=2,wits=1,grit=1,finesse=0,force=-1" else "heart=3,wits=1,grit=1,finesse=0,force=-2"
                                      for a in THEO]), 1)                         # not the starting array
        path = self.root / "campaigns" / "braid" / "characters" / "mira-vale.md"
        text = path.read_text(encoding="utf-8")
        self.assertEqual(sheet.problems(text), [])
        bad = text.replace("- **Wits:** +2", "- **Wits:** +4")
        self.assertTrue(any("Wits is +4" in p for p in sheet.problems(bad)))
        self.assertTrue(any("add up to" in p for p in sheet.problems(bad)))
        self.assertEqual(self.sheet("xp", "Mira", "--mark", "5", "--why", "m", "--event", "e1"), 0)
        self.assertEqual(self.sheet("advance", "Mira", "--raise", "wits"), 0)     # +3: the most
        self.assertEqual(self.sheet("xp", "Mira", "--mark", "5", "--why", "m", "--event", "e2"), 0)
        self.assertEqual(self.sheet("advance", "Mira", "--raise", "wits"), 1)
        self.assertEqual(self.sheet("advance", "Mira", "--label", "Card sharp: reads a bluff"), 0)
        self.assertEqual(self.sheet("advance", "Mira", "--move", "x"), 1)       # no XP left
        self.assertEqual(sheet.problems(path.read_text(encoding="utf-8")), [])
        self.assertEqual(sheet.approach("braid", "Mira", "wits"), 3)
        theo = self.root / "campaigns" / "braid" / "characters" / "theo.md"
        self.assertEqual(self.sheet(*THEO), 0)
        self.assertEqual(sheet.parse(theo.read_text(encoding="utf-8"))["bonds"], [])   # no bond invented

    def test_a_token_does_not_reach_back_past_a_judge(self):
        self.build()
        self.sheet(*MIRA)
        self.turn_with("t", {"action": "pool", "owner": "Mira", "id": "tokens", "max": 3, "set": 2},
                       {"action": "roll", "actor": "Mira", "approach": "wits"}, answers=["5"])
        self.turn_with("j", {"action": "judge", "actor": "Mira", "plan": "p", "risk": "r", "if_fails": "f",
                             "approach": "wits"}, answers=["2"])
        r = self.turn_with("tok", {"action": "pool", "owner": "Mira", "id": "tokens", "step_up": True})
        self.assertIn("error", self.data(r))
        self.assertEqual(self.thing("pool", "mira/tokens")["value"], 2)

    def test_a_d20_campaign_is_refused(self):
        self.build(system="d20", ruleset="2014", npcs=[])
        self.assertEqual(self.sheet(*MIRA), 2)

    def test_recap_reads_the_sheet_and_the_engine(self):
        import session_recap
        self.build()
        self.sheet(*MIRA)
        camp = self.root / "campaigns" / "braid"
        before = session_recap.snapshot_party(camp)
        self.turn_with("hit", {"action": "track", "owner": "Mira", "id": "harm", "mark": 2})
        self.sheet("xp", "Mira", "--mark", "2", "--why", "m", "--event", "e1")
        after = session_recap.snapshot_party(camp)
        said = session_recap.render_summary(session_recap.diff_party(before, after))
        self.assertIn("took 2 harm (0→2)", said)
        self.assertIn("XP 0→2", said)
        self.assertIn("Wounded", said)


class BraidKits(unittest.TestCase):
    def test_a_braid_kit_needs_no_5e_chassis(self):
        import worldkit
        kit = {"_meta": {"name": "Ash", "genre": ["horror"], "premise": "p"},
               "labels": [{"name": "Medic", "description": "patches people up"}],
               "equipment": [{"name": "Flare gun"}],
               "threats": [{"name": "Hollow Man", "threat": 3, "moves": ["drags someone into the dark"]}]}
        self.assertEqual(worldkit.validate(kit, system="core"), [])
        bad = {**kit, "monsters": [{"name": "Orc", "cr": 1}], "threats": [{"name": "X", "threat": 9}]}
        errs = worldkit.validate(bad, system="core")
        self.assertTrue(any("monsters: a 5e part" in e for e in errs))
        self.assertTrue(any("threat must be an integer 1–5" in e for e in errs))
        self.assertTrue(any("moves must list" in e for e in errs))

    def test_seed_npcs_take_a_threat_under_braid(self):
        import campaign_init
        errs = campaign_init.check({**SEED, "campaign": "x", "npcs": [{"name": "A", "role": "r", "cr": "1"}]})
        self.assertIn("npcs[0].threat", [e["path"] for e in errs])


if __name__ == "__main__":
    unittest.main()
