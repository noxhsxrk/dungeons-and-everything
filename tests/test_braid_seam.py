"""Braid PR 1, the system seam: one `resolve()` grades every check for d20, core and story; a campaign's system is
read from its state.md header (none = d20); 5e-only scripts refuse a Braid campaign; old saves stamp as d20."""
from __future__ import annotations

import copy
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _engine_case import SCRIPTS, EngineCase  # noqa: E402
import _old_campaign  # noqa: E402

import dice  # noqa: E402
import paths  # noqa: E402
import resolve  # noqa: E402
from test_d20_golden import CASE, SITUATION  # noqa: E402

LADDER = resolve.LADDER
#: (2d6 sum before the modifier, the step it lands on with +0): the edges of 3- / 4-6 / 7-9 / 10-11 / 12+.
EDGES = ((2, 0), (3, 0), (4, 1), (6, 1), (7, 2), (9, 2), (10, 3), (11, 3), (12, 4))


def stamp(camp: pathlib.Path, system: str) -> None:
    state = camp / "state.md"
    text = state.read_text(encoding="utf-8")
    state.write_text(text.replace("**Session count:** 3", f"**Session count:** 3  **System:** {system}"), encoding="utf-8")


class Resolve(unittest.TestCase):
    def test_core_ladder_thresholds(self):
        for total, step in EDGES:
            r = resolve.resolve("core", "2d6", None, [total - 1, 1])
            self.assertEqual((r["degree"], r["total"], r["passed"]), (LADDER[step], total, step >= 2), total)
        self.assertEqual(resolve.resolve("core", "2d6+2", 99, [5, 3])["degree"], "success")   # target ignored
        self.assertEqual(resolve.resolve("core", "2d6-1", None, [2, 2])["degree"], "critical failure")

    def test_d20_is_dice_degree(self):
        for raw in (1, 5, 10, 14, 20):
            for dc in (8, 12, 15, 25):
                r = resolve.resolve("d20", "1d20+3", dc, [raw])
                self.assertEqual(r["degree"], dice.degree(raw, raw + 3, dc))
                self.assertEqual(r["passed"], raw + 3 >= dc)

    def test_story_maps_the_oracle_and_a_token_steps_up(self):
        import oracle
        seen = {}
        for roll in range(1, 101):
            seen[oracle.verdict(roll)] = resolve.resolve("story", None, None, [roll])["degree"]
        self.assertEqual(seen, {"yes-and": "critical success", "yes": "success", "yes-but": "success at a cost",
                                "no-but": "failure", "no": "failure", "no-and": "critical failure"})
        self.assertEqual(resolve.resolve("story", None, None, [99], step_up=1)["degree"], "failure")   # no-and → no
        self.assertEqual(resolve.resolve("core", "2d6", None, [6, 6], step_up=1)["degree"], "critical success")

    def test_core_spec_must_be_2d6(self):
        self.assertIsNone(resolve.spec_error("core", "2d6+1"))
        self.assertIn("2d6", resolve.spec_error("core", "1d20+5"))
        self.assertIsNone(resolve.spec_error("d20", "1d20+5"))


class CampaignSystem(EngineCase):
    def test_old_save_without_the_field_is_d20(self):
        self.assertEqual(paths.campaign_system("oldworld"), "d20")
        self.assertEqual(paths.campaign_system("no-such-campaign"), "d20")

    def test_unknown_system_is_an_error_not_a_guess(self):
        stamp(self.camp, "gurps")
        with self.assertRaisesRegex(ValueError, "gurps"):
            paths.campaign_system("oldworld")

    def test_only_the_header_counts(self):
        with open(self.camp / "state.md", "a", encoding="utf-8") as f:
            f.write("\n## Notes\n- the GM wrote **System:** core here once\n")
        self.assertEqual(paths.campaign_system("oldworld"), "d20")
        stamp(self.camp, "core")
        self.assertEqual(paths.campaign_system("oldworld"), "core")


class CoreChecks(EngineCase):
    """Under core, judge, search and flashback (and roll) sum both d6 and add the modifier."""

    def setUp(self):
        super().setUp()
        stamp(self.camp, "core")
        self.n = 0

    def turn_of(self, *intents):
        self.n += 1
        r = self.do(f"t{self.n}", *intents)
        if r["status"] == "waiting_for_player" and r["next_input"]["kind"] == "decision":
            first = r
            r = self.turn.answer("oldworld", r["next_input"]["request_id"], "accept")
            r["first"] = first
        self.turn.finish("oldworld", "ok")
        return r

    def stored_dice(self, action_id: str) -> list:
        with self.wdb.reader("oldworld") as db:
            return json.loads(db.execute("SELECT result FROM rolls WHERE action_id=?", (action_id,)).fetchone()["result"])["dice"]

    def test_auto_rolls_sum_two_dice(self):
        for n in range(12):
            mod = n % 3 - 1
            spec = f"2d6{mod:+d}"
            r = self.turn_of(SITUATION if n == 0 else {"action": "ask"},
                             {"action": "judge", "situation": "gate", "actor": "Mira", "plan": f"p{n}", "risk": "r",
                              "if_fails": "f", "cost": "c", "roll": {"spec": spec, "label": "Athletics"}})
            d = (r.get("first") or r)["results"][-1]["data"]
            self.assertEqual(len(d["dice"]), 2)
            self.assertTrue(all(1 <= x <= 6 for x in d["dice"]))
            self.assertEqual(d["total"], sum(d["dice"]) + mod)
            self.assertEqual(d["degree"], resolve.resolve("core", spec, None, d["dice"])["degree"])
            self.assertNotIn("dc", d)

            r = self.turn_of({"actor": "Mira", "action": "flashback", "claim": "I hid a key", "roll": {"spec": spec}})
            d = self.data(r)
            self.assertEqual(len(d["dice"]), 2)
            self.assertEqual(d["total"], sum(d["dice"]) + mod)
            self.assertEqual(d["worked"], d["total"] >= 7)

            r = self.turn_of(CASE if n == 0 else {"action": "ask"},
                             {"actor": "Theo", "action": "search", "case": "ledger", "where": "office", "roll": {"spec": spec}})
            got = self.stored_dice(r["results"][-1]["action_id"])
            self.assertEqual(len(got), 2)
            self.assertEqual(self.data(r)["roll_helped"], sum(got) + mod >= 7)

            r = self.turn_of({"actor": "Mira", "action": "roll", "spec": spec, "label": "Stealth"})
            d = self.data(r)
            self.assertEqual((len(d["dice"]), d["total"]), (2, sum(d["dice"]) + mod))

    def test_players_answer_the_sum_and_each_edge_lands_on_its_step(self):
        self.flags("- display: none\n- roll_mode: players\n- world_engine: on\n")
        for i, (total, step) in enumerate(EDGES):
            r = self.do(f"j{i}", SITUATION if i == 0 else {"action": "ask"},
                        {"action": "judge", "situation": "gate", "actor": "Mira", "plan": f"p{i}", "risk": "the gate drops",
                         "if_fails": "f", "cost": "c", "roll": {"spec": "2d6", "dc": 14, "label": "Athletics"}})
            q = r["next_input"]["question"]
            self.assertIn("2d6 (send the two dice added together)", q)
            self.assertNotIn("DC", q)
            r = self.turn.answer("oldworld", r["next_input"]["request_id"], total)
            if step == 2:
                self.assertEqual(r["next_input"]["kind"], "decision")
                self.assertIn(f"{total} on 2d6", r["next_input"]["question"])
                r = self.turn.answer("oldworld", r["next_input"]["request_id"], "accept")
                self.assertEqual(self.data(r)["outcome"], "success_at_a_cost")
            else:
                self.assertEqual(self.data(r)["degree"], LADDER[step])
                self.assertEqual(self.data(r)["outcome"], "success" if step >= 3 else "failure")
            self.turn.finish("oldworld", "ok")

            r = self.do(f"f{i}", {"actor": "Mira", "action": "flashback", "claim": "I hid a key", "roll": {"spec": "2d6+0"}})
            self.assertIn("2d6", r["next_input"]["question"])
            r = self.turn.answer("oldworld", r["next_input"]["request_id"], total)
            self.assertEqual((self.data(r)["degree"], self.data(r)["worked"]), (LADDER[step], step >= 2))
            self.turn.finish("oldworld", "ok")

            r = self.do(f"s{i}", CASE if i == 0 else {"action": "ask"},
                        {"actor": "Theo", "action": "search", "case": "ledger", "where": "office", "roll": {"spec": "2d6"}})
            self.assertIn("2d6", r["next_input"]["question"])
            r = self.turn.answer("oldworld", r["next_input"]["request_id"], total)
            self.assertEqual(self.data(r)["roll_helped"], step >= 2)
            self.turn.finish("oldworld", "ok")

    def test_a_d20_spec_is_refused_not_scaled(self):
        r = self.do("x", {"actor": "Mira", "action": "flashback", "claim": "c", "roll": {"spec": "1d20+5", "dc": 13}})
        self.assertIn("2d6", self.data(r)["error"])

    def test_a_d20_roll_is_refused_but_damage_dice_roll(self):
        r = self.do("x", {"actor": "Mira", "action": "roll", "spec": "1d20+5", "label": "Stealth"},
                    {"actor": "Mira", "action": "roll", "spec": "1d8+2", "label": "damage"})
        self.assertIn("2d6", r["results"][0]["data"]["error"])
        self.assertNotIn("degree", r["results"][1]["data"])

    def test_bargain_edge_is_plus_one(self):
        self.flags("- display: none\n- roll_mode: players\n- world_engine: on\n")
        r = self.do("x", {"actor": "Mira", "action": "bargain", "offer": "the guard remembers you",
                          "roll": {"spec": "2d6+1", "label": "Deception"}})
        self.assertIn("+1 on this roll", r["next_input"]["question"])
        r = self.turn.answer("oldworld", r["next_input"]["request_id"], "accept")
        self.assertIn("2d6+2", r["next_input"]["question"])
        r = self.turn.answer("oldworld", r["next_input"]["request_id"], 7)
        d = self.data(r)
        self.assertEqual((d["total"], d["degree"], d["accepted"]), (9, "success at a cost", True))

    def test_5e_rest_and_reward_refuse(self):
        r = self.do("x", {"action": "rest", "type": "long"}, {"action": "reward", "encounter": "gate", "characters": ["Mira"]})
        self.assertIn("Braid", r["results"][0]["data"]["error"])
        self.assertIn("wait", r["results"][0]["data"]["error"])
        self.assertIn("Braid", r["results"][1]["data"]["error"])


class StoryChecks(EngineCase):
    FLAGS = "- display: none\n- roll_mode: players\n- world_engine: on\n"

    def test_the_oracle_answers_and_nobody_rolls(self):
        stamp(self.camp, "story")
        r = self.do("x", {"actor": "Mira", "action": "flashback", "claim": "I hid a key", "roll": {"likelihood": "likely"}})
        self.assertIsNone(r["next_input"])
        d = self.data(r)
        self.assertIn(d["degree"], LADDER)
        self.assertEqual(d["worked"], LADDER.index(d["degree"]) >= 2)
        self.turn.finish("oldworld", "ok")
        r = self.do("y", SITUATION, {"action": "judge", "situation": "gate", "actor": "Mira", "plan": "p", "risk": "r",
                                     "if_fails": "f", "cost": "c"})
        self.assertIn(self.data(r).get("degree") or r["next_input"]["kind"], LADDER + ("decision",))


class D20BadByte(EngineCase):
    def test_a_stray_byte_in_state_md_does_not_stop_a_d20_check(self):
        state = self.camp / "state.md"
        state.write_bytes(state.read_bytes().replace(b"## Active Quests", b"\xff\n## Active Quests"))
        r = self.do("x", {"actor": "Mira", "action": "flashback", "claim": "c", "roll": {"spec": "1d20+2", "dc": 12}})
        self.assertIn("worked", self.data(r))


class D20RequestsUnchanged(EngineCase):
    """What a 5e player is asked to roll, word for word as 1.8.6 asked it."""
    FLAGS = "- display: none\n- roll_mode: players\n- world_engine: on\n"

    def test_request_texts(self):
        out = []
        for intents in ([{"actor": "Mira", "action": "roll", "spec": "1d20+3", "dc": 12, "label": "Stealth"}],
                        [SITUATION, {"action": "judge", "situation": "gate", "actor": "Mira", "plan": "p", "risk": "the gate drops",
                                     "if_fails": "f", "cost": "c", "roll": {"spec": "1d20+2", "dc": 14, "label": "Athletics"}}],
                        [{"actor": "Mira", "action": "flashback", "claim": "I hid a key",
                          "roll": {"spec": "1d20+1", "dc": 13, "label": "Sleight"}}],
                        [CASE, {"actor": "Theo", "action": "search", "case": "ledger", "where": "office",
                                "roll": {"spec": "1d20+4", "dc": 13, "label": "Investigation"}}]):
            r = self.do("x", *intents)
            out.append(r["next_input"]["question"])
            r = self.turn.answer("oldworld", r["next_input"]["request_id"], 10)
            if r.get("next_input"):
                out.append(r["next_input"]["question"])
                self.turn.answer("oldworld", r["next_input"]["request_id"], "accept")
            self.turn.finish("oldworld", "ok")
        self.assertEqual(out, ["Mira: roll Stealth — 1d20+3 (DC 12)",
                               "Mira: roll Athletics — 1d20+2 (DC 14). At stake: the gate drops",
                               "Mira: 12 against 14 — it works, at a price: c. Accept the price? (accept / refuse)",
                               "Mira: flashback: Sleight — 1d20+1.",
                               "Theo: roll Investigation — 1d20+4"])


class Refusals(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)
        stamp(_old_campaign.make(self.root, "braid"), "core")
        _old_campaign.make(self.root, "fivee")
        self.env = {**os.environ, "DNE_CAMPAIGN_ROOT": str(self.root), "DNE_RUNTIME_DIR": str(self.root / "rt"),
                    "DNE_DISPLAY_HOST": "127.0.0.1:9", "PYTHONIOENCODING": "utf-8"}

    def tearDown(self):
        self._tmp.cleanup()

    def run_py(self, script: str, *args: str):
        return subprocess.run([sys.executable, str(SCRIPTS / script), *args], capture_output=True, text=True,
                              encoding="utf-8", env=self.env, timeout=60)

    def test_5e_scripts_refuse_a_core_campaign(self):
        calls = [("character.py", "hitdie", "--char", "mira", "--remaining", "3", "-c", "braid"),
                 ("xp.py", "award", "--campaign", "braid", "--characters", "Mira", "--monsters", "goblin"),
                 ("combat.py", "attack", "--effects", "Mira", "-c", "braid"),
                 ("encounter_gen.py", "-c", "braid"),
                 ("lookup.py", "goblin", "--campaign", "braid"),
                 ("economy.py", "-c", "braid", "rest", "--type", "long", "--char", "all"),
                 ("tracker.py", "-c", "braid", "saves", "Mira", "failure")]
        for call in calls:
            r = self.run_py(*call)
            self.assertEqual(r.returncode, 2, (call, r.stdout, r.stderr))
            self.assertIn("Braid", r.stderr, call)
            self.assertIn("`roll` and `judge`", r.stderr, call)
            self.assertEqual(r.stdout.strip(), "", call)

    def test_without_c_the_campaign_in_play_decides(self):
        calls = [("xp.py", "calc", "--party", "4", "--monsters", "goblin"),
                 ("encounter_gen.py", "--party", "4", "--level", "2"),
                 ("character.py", "hitdie", "--char", "mira", "--remaining", "3"),
                 ("lookup.py", "goblin"),
                 ("combat.py", "attack", "--effects", "Mira")]
        rt = self.root / "rt"
        rt.mkdir(exist_ok=True)
        (rt / "active-campaign.json").write_text(json.dumps({"name": "braid"}), encoding="utf-8")
        for call in calls:
            r = self.run_py(*call)
            self.assertEqual(r.returncode, 2, (call, r.stdout, r.stderr))
            self.assertIn("Braid", r.stderr, call)
        (rt / "active-campaign.json").write_text(json.dumps({"name": "fivee"}), encoding="utf-8")
        self.assertEqual(self.run_py("lookup.py", "goblin").returncode, 0)   # a 5e world in play passes

    def test_braid_buy_never_sorts_by_the_srd(self):
        code = ("import economy; print(economy._inventory_section('braid', 'Longsword'), "
                "economy._inventory_section('fivee', 'Longsword'))")
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, encoding="utf-8",
                           env=self.env, cwd=SCRIPTS, timeout=60)
        self.assertEqual(r.stdout.split(), ["Adventuring", "Gear", "Weapons"], r.stderr)

    def test_a_5e_campaign_is_not_refused(self):
        r = self.run_py("xp.py", "check", "--campaign", "fivee")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_subsystem_grades_a_braid_total_without_a_dc(self):
        self.assertEqual(self.run_py("subsystem.py", "-c", "braid", "start", "escape", "--goal", "3").returncode, 0)
        r = self.run_py("subsystem.py", "-c", "braid", "check", "escape", "--total", "8")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("escape: 1/3", r.stdout)                         # 8 = success at a cost = 1 point


class MigrateSystem(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)
        self.camp = _old_campaign.make(self.root)
        self.env = {**os.environ, "DNE_CAMPAIGN_ROOT": str(self.root), "PYTHONIOENCODING": "utf-8"}

    def tearDown(self):
        self._tmp.cleanup()

    def mig(self, *args):
        return subprocess.run([sys.executable, str(SCRIPTS / "migrate_system.py"), *args], capture_output=True,
                              text=True, encoding="utf-8", env=self.env, timeout=60)

    def test_check_then_stamp_d20_with_a_backup(self):
        before = (self.camp / "state.md").read_text(encoding="utf-8")
        self.assertEqual(self.mig("oldworld", "--check").returncode, 1)
        self.assertEqual(self.mig("oldworld", "--system", "core", "--yes").returncode, 2)   # an old save is 5e
        r = self.mig("oldworld", "--system", "d20", "--yes")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([p.read_text(encoding="utf-8") for p in self.camp.glob("state.md.backup-pre-system-*")], [before])
        after = (self.camp / "state.md").read_text(encoding="utf-8")
        self.assertEqual(after.replace("**System:** d20\n", "", 1), before)
        self.assertEqual(self.mig("oldworld", "--check").returncode, 0)
        self.assertIn("Already migrated", self.mig("oldworld", "--yes").stdout)
        self.assertEqual(self.mig("missing", "--check").returncode, 2)

    def test_stamp_goes_on_the_created_line(self):
        (self.camp / "state.md").write_text("# Campaign: x\n**Created:** 2026-01-01  **Ruleset:** 2014\n\n## Session Flags\n",
                                            encoding="utf-8")
        self.assertEqual(self.mig("oldworld", "--yes").returncode, 0)
        self.assertIn("**Ruleset:** 2014  **System:** d20\n", (self.camp / "state.md").read_text(encoding="utf-8"))


class InitAndLoad(unittest.TestCase):
    SEED = {"seed_version": 1, "campaign": "braidtown", "system": "core", "flags": {"display": "none"},
            "calendar": {"date": "1 Thaw 412", "months": ["Thaw", "Bloom"], "month_length": 30}}

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)
        self._saved = {k: os.environ.get(k) for k in ("DNE_CAMPAIGN_ROOT", "DNE_RUNTIME_DIR", "DNE_DISPLAY_HOST", "DNE_OUTBOX_LOG")}
        os.environ.update(DNE_CAMPAIGN_ROOT=str(self.root), DNE_RUNTIME_DIR=str(self.root / "rt"),
                          DNE_DISPLAY_HOST="127.0.0.1:9", DNE_OUTBOX_LOG=str(self.root / "out.jsonl"))
        import campaign_init
        self.ci = campaign_init

    def tearDown(self):
        for k, v in self._saved.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        self._tmp.cleanup()

    def test_core_seed_writes_the_header_and_runs_on_the_engine(self):
        out = self.ci.build(copy.deepcopy(self.SEED))
        self.assertTrue(out["ok"], out)
        state = (self.root / "campaigns" / "braidtown" / "state.md").read_text(encoding="utf-8")
        self.assertIn("**System:** core", state)
        self.assertNotIn("**Ruleset:**", state)
        self.assertIn("- world_engine: on", state)
        self.assertEqual(paths.campaign_system("braidtown"), "core")
        import gm_guide
        steps = "\n".join(gm_guide.session_start("braidtown"))
        self.assertIn("migrate_system.py", steps)
        self.assertNotIn("migrate_ruleset.py", steps)
        r = subprocess.run([sys.executable, str(SCRIPTS / "migrate_ruleset.py"), "braidtown", "--check"],
                           capture_output=True, text=True, encoding="utf-8", env=os.environ.copy(), timeout=60)
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "not-applicable (system: core)"))

    def test_seed_errors(self):
        bad = {**copy.deepcopy(self.SEED), "flags": {"world_engine": "off"}}
        self.assertIn("flags.world_engine", [e["path"] for e in self.ci.check(bad)])
        self.assertIn("system", [e["path"] for e in self.ci.check({**self.SEED, "system": "gurps"})])
        no_cal = {k: v for k, v in self.SEED.items() if k != "calendar"}
        self.assertIn("calendar", [e["path"] for e in self.ci.check(no_cal)])   # forced engine needs a calendar

    def test_d20_seed_header(self):
        out = self.ci.build({**copy.deepcopy(self.SEED), "system": "d20", "ruleset": "2024", "flags": {"display": "none"},
                             "calendar": None})
        self.assertTrue(out["ok"], out)
        state = (self.root / "campaigns" / "braidtown" / "state.md").read_text(encoding="utf-8")
        self.assertIn("**Ruleset:** 2024  **System:** d20", state)
        self.assertEqual(paths.campaign_ruleset("braidtown"), "2024")


if __name__ == "__main__":
    unittest.main()
