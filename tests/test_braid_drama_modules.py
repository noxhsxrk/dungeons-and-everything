"""Braid PR 5, the drama, heist, war and everyday modules: strings, emotions, labels, position_effect, heat,
engagement, usage_die, vows, contest, seasons, mooks, gm_budget, war_layer.

Acceptance (plan §5 PR 5): a scripted heist game (core + position_effect + heat) plays one whole job, and a scripted
romance game (core + strings) plays one whole arc, through engine turns, with nothing 5e touched or printed."""
from __future__ import annotations

import contextlib
import io
import json
import pathlib
import re
import shlex
import sys
import unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _engine_case import EngineCase  # noqa: E402
from test_braid_seam import stamp  # noqa: E402
from test_braid_rules import MIRA, THEO, SEED, BraidCampaign, leaks, no_5e  # noqa: E402

import turn  # noqa: E402,F401  (the engine first)
import modules  # noqa: E402
import story_gen  # noqa: E402

PR5 = ("strings", "emotions", "labels", "position_effect", "heat", "engagement", "usage_die", "vows", "contest",
       "seasons", "mooks", "gm_budget", "war_layer")
#: Names from the games these mechanics were learned from: never in a module (plan §6). Case-sensitive like PR 4's.
TRADE = [r"Monsterhearts", r"Masks", r"Blades", r"Band of Blades", r"Forged in the Dark", r"Wanderhome", r"Ironsworn",
         r"Black Hack", r"\bFate\b", r"Savage Worlds", r"Burning Wheel", r"Mouse Guard", r"Feng Shui", r"Duskvol",
         r"Doskvol", r"Thirsty Sword", r"Danger", r"Freak", r"Savior", r"Superior", r"Mundane", r"Legion",
         r"Gang Trouble", r"Usual Suspects", r"Unquiet Dead", r"Turn Someone On", r"Shut Someone Down", r"Influence",
         r"Iron Vow", r"Duel of Wits", r"Disposition", r"Keeper", r"Trophy"]
FLAGS = "- display: none\n- roll_mode: {}\n- world_engine: on\n- modules: {}\n"


class Module(EngineCase):
    """An old-world campaign stamped core, with the modules named in MODULES switched on."""
    MODULES = ""
    ROLL = "players"

    def setUp(self):
        super().setUp()
        self.flags(FLAGS.format(self.ROLL, self.MODULES))
        stamp(self.camp, "core")

    def turn_with(self, text, *intents, answers=()):
        r = self.do(text, *intents)
        for a in answers:
            self.assertEqual(r["status"], "waiting_for_player", r)
            r = self.turn.answer("oldworld", r["next_input"]["request_id"], a)
        self.turn.finish("oldworld", "ok")
        return r

    def one(self, intent, answers=(), i=-1):
        return self.data(self.turn_with(intent["action"], intent, answers=answers), i)

    def system(self, system):
        state = self.camp / "state.md"
        text = state.read_text(encoding="utf-8")
        state.write_text(re.sub(r"\*\*System:\*\* \w+", f"**System:** {system}", text), encoding="utf-8")


class Format(unittest.TestCase):
    def test_every_pr5_module_exists_keeps_the_format_and_no_trade_names(self):
        known = modules.catalog()
        for mid in PR5:
            with self.subTest(mid):
                self.assertIn(mid, known)
                self.assertEqual(modules.validate(mid), [])
                for path in sorted(modules.DIR.glob(f"{mid}.*")):
                    text = path.read_text(encoding="utf-8")
                    self.assertEqual([t for t in TRADE if re.search(t, text)], [], path.name)
                script = known[mid].get("script")
                if script:
                    text = (modules.HERE / f"{script}.py").read_text(encoding="utf-8")
                    self.assertEqual([t for t in TRADE if re.search(t, text)], [], script)

    def test_requires_and_the_whole_set_together(self):
        self.assertEqual(modules.problems(["engagement"])[0], ["engagement requires position_effect: switch it on too"])
        self.assertEqual(modules.problems(["engagement", "position_effect", "heat"]), ([], []))


# ── position and effect ───────────────────────────────────────────────────────

class PositionEffect(Module):
    MODULES = "position_effect"

    def act(self, die, **extra):
        intent = {"action": "position", "actor": "Mira", "spec": "2d6+0", "label": f"try {die}", **extra}
        return self.one(intent, answers=[die])

    def test_the_ladder_read_through_position_and_effect(self):
        cases = [  # (position, effect, total) -> (harm_if_hurt, ticks)
            ("controlled", "standard", "3", 2, 0), ("controlled", "standard", "5", 1, 0), ("controlled", "limited", "8", 0, 1),
            ("risky", "standard", "5", 2, 0), ("risky", "standard", "8", 1, 2), ("risky", "great", "10", 0, 3),
            ("desperate", "great", "12", 0, 4), ("desperate", "standard", "8", 2, 2), ("desperate", "limited", "2", 4, 0)]
        tables = modules.load("position_effect")["tables"]
        for position, effect, die, harm, ticks in cases:
            with self.subTest((position, effect, die)):
                d = self.act(die, position=position, effect=effect)
                r = d["reading"]
                self.assertEqual((r["harm_if_hurt"], r["ticks"]), (harm, ticks))
                self.assertIn(r["consequence"], tables[position])
                self.assertNotIn("spec", d)

    def test_a_clock_is_ticked_and_the_position_carries(self):
        self.turn_with("clock", {"action": "clock", "name": "The vault", "size": 4})
        self.assertEqual(self.one({"action": "position"})["position"], "risky")             # the default
        self.one({"action": "position", "set": "desperate", "why": "the alarm"})
        d = self.act("10", clock="The vault")                                                # success, standard
        self.assertEqual((d["reading"]["position"], d["clock"]["filled"]), ("desperate", 2))
        d = self.act("12", clock="The vault", effect="limited")                               # critical: 1 + 1
        self.assertEqual((d["clock"]["filled"], d["clock"]["full"]), (4, True))
        self.assertEqual(self.act("5", clock="The vault")["reading"]["ticks"], 0)
        self.assertIn("one of", self.one({"action": "position", "set": "doomed"})["error"])

    def test_sheet_approach_push_and_help_still_apply(self):
        self.turn_with("cond", {"action": "condition", "owner": "Mira", "name": "Shaken", "mod": -1})
        r = self.do("act", {"action": "position", "actor": "Mira", "spec": "2d6+1", "push": True, "label": "jump"})
        self.assertIn("2d6+1", r["next_input"]["question"])                                   # +1 -1 +1
        self.turn.answer("oldworld", r["next_input"]["request_id"], "9")
        self.turn.finish("oldworld", "ok")
        self.assertEqual(self.thing("track", "mira/stress")["value"], 1)

    def test_refused_when_off(self):
        self.flags(FLAGS.format("players", "heat"))
        self.assertIn("not switched on", self.one({"action": "position"})["error"])


class Engagement(Module):
    MODULES = "position_effect, engagement"

    def test_factors_and_the_starting_position(self):
        r = self.do("go", {"action": "engagement", "actor": "Mira", "plan": "stealth", "detail": "the laundry chute",
                           "bold": True, "weakness": True, "interfere": True, "other": 1})
        self.assertIn("2d6+2", r["next_input"]["question"])
        d = self.data(self.turn.answer("oldworld", r["next_input"]["request_id"], "5"))      # 7: at a cost
        self.turn.finish("oldworld", "ok")
        self.assertEqual((d["position"], d["factors"]), ("risky", ["bold", "weakness", "interfere"]))
        self.assertEqual(self.one({"action": "position"})["position"], "risky")
        for die, where in (("2", "desperate"), ("10", "controlled"), ("12", "controlled")):
            d = self.one({"action": "engagement", "actor": "Mira", "plan": "social", "detail": "the cousin",
                          "why": die}, answers=[die])
            self.assertEqual(d["position"], where)
        self.assertTrue(d["past_first_obstacle"])

    def test_bad_plans_are_refused_and_position_effect_is_required(self):
        self.assertIn("plan: one of", self.one({"action": "engagement", "plan": "magic", "detail": "x"})["error"])
        self.assertIn("needs its detail", self.one({"action": "engagement", "plan": "assault"})["error"])
        self.flags(FLAGS.format("players", "engagement"))
        self.assertIn("position_effect", self.one({"action": "engagement", "plan": "assault", "detail": "x"})["error"])


# ── heat ──────────────────────────────────────────────────────────────────────

class Heat(Module):
    MODULES = "heat"
    ROLL = "auto"

    def test_job_heat_overflows_into_wanted(self):
        d = self.one({"action": "crew_heat", "job": "loud", "high_profile": True, "killing": True})   # 4 + 1 + 2
        self.assertEqual((d["crew_heat"], d["wanted"]), (7, 0))
        d = self.one({"action": "crew_heat", "job": "contained", "hostile_turf": True})               # 7 + 3 = 10
        self.assertEqual((d["crew_heat"], d["wanted"], d["wanted_up"]), (1, 1, 1))
        d = self.one({"action": "crew_heat", "add": -5, "why": "laid low"})
        self.assertEqual((d["crew_heat"], d["wanted"]), (0, 1))
        self.assertIn("job: one of", self.one({"action": "crew_heat", "job": "noisy"})["error"])
        self.assertIsNotNone(self.thing("track", "party/wanted"))

    def test_entanglement_dice_and_column(self):
        tables = modules.load("heat")["tables"]
        d = self.one({"action": "crew_heat", "entangle": True})                                  # wanted 0: two, lower
        self.assertEqual((len(d["dice"]), d["result"], d["column"]), (2, min(d["dice"]), "entangle_low"))
        self.assertIn(d["entanglement"], tables["entangle_low"])
        self.one({"action": "crew_heat", "add": 15, "why": "a wild night"})                     # 15: wanted 1, heat 6
        d = self.one({"action": "crew_heat", "entangle": True, "why": "again"})
        self.assertEqual((len(d["dice"]), d["result"], d["column"]), (1, d["dice"][0], "entangle_high"))
        row = 0 if d["result"] <= 3 else 1 if d["result"] <= 5 else 2
        self.assertEqual(d["entanglement"], tables["entangle_high"][row])


# ── strings and emotions ──────────────────────────────────────────────────────

class Strings(Module):
    MODULES = "strings, emotions"

    def test_gain_spend_and_the_one_roll_modifier(self):
        self.assertIn("no string", self.one({"action": "string", "by": "Mira", "on": "Theo", "spend": "plus"})["error"])
        d = self.one({"action": "string", "by": "Mira", "on": "Theo", "gain": 2, "why": "she saw him cry"})
        self.assertEqual(d["strings"], {"mira": 2})
        self.one({"action": "string", "by": "Mira", "on": "Theo", "spend": "plus"})
        self.assertEqual(self.thing("condition", "mira/mira's hold on theo")["mod"], 1)
        self.turn_with("goal", {"action": "progress", "owner": "Mira", "name": "Win him back", "rank": "easy"})
        self.one({"action": "progress", "owner": "Mira", "name": "Win him back", "roll": True}, answers=["7"])
        self.assertIsNotNone(self.thing("condition", "mira/mira's hold on theo"))             # not counted there
        r = self.do("roll", {"action": "roll", "actor": "Mira", "spec": "2d6+0", "label": "talk to him"})
        self.assertIn("2d6+1", r["next_input"]["question"])
        d = self.data(self.turn.answer("oldworld", r["next_input"]["request_id"], "8"))
        self.turn.finish("oldworld", "ok")
        self.assertEqual(d["used"], ["Mira's hold on Theo"])
        self.assertIsNone(self.thing("condition", "mira/mira's hold on theo"))                # one roll only
        self.one({"action": "string", "by": "Mira", "on": "Theo", "spend": "minus"})
        r = self.do("roll", {"action": "roll", "actor": "Theo", "spec": "2d6+1"})
        self.assertIn("— 2d6 (", r["next_input"]["question"])
        self.turn.answer("oldworld", r["next_input"]["request_id"], "8")
        self.turn.finish("oldworld", "ok")
        self.assertIsNone(self.thing("condition", "theo/mira's hold on theo"))
        self.assertEqual(self.thing("bond", "mira|theo")["points"], {"mira": 0})

    def test_tempt_pays_xp_only_if_they_go_along_and_emotion_spend(self):
        self.one({"action": "string", "by": "Mira", "on": "Theo", "gain": 3})
        self.assertIn("needs the offer", self.one({"action": "string", "by": "Mira", "on": "Theo", "spend": "tempt"})["error"])
        self.one({"action": "string", "by": "Mira", "on": "Theo", "spend": "tempt", "offer": "run away with me"})
        d = self.one({"action": "string", "on": "Theo", "accept": True})
        self.assertEqual(d["xp"], 1)
        self.assertIn('xp "Theo" --mark 1', d["xp_command"])
        self.assertIn("no open temptation", self.one({"action": "string", "on": "Theo", "accept": True, "why": "2"})["error"])
        self.one({"action": "string", "by": "Mira", "on": "Theo", "spend": "tempt", "offer": "lie for me"})
        self.assertNotIn("xp", self.one({"action": "string", "on": "Theo", "accept": False}))
        d = self.one({"action": "string", "by": "Mira", "on": "Theo", "spend": "emotion", "emotion": "insecure"})
        self.assertEqual(d["condition"]["approaches"], ["finesse"])
        self.assertEqual(self.thing("bond", "mira|theo")["points"], {"mira": 0})

    def test_only_the_check_that_counted_it_uses_it_up(self):
        import mod_strings
        self.assertEqual(mod_strings._edges({"rolled": {"edges": ["A +1"]}, "x": [{"edges": ["B -1"]}]}), ["A +1", "B -1"])
        self.one({"action": "string", "by": "Mira", "on": "Theo", "gain": 2})
        self.one({"action": "string", "by": "Mira", "on": "Theo", "spend": "plus"})
        self.one({"action": "roll", "actor": "Theo", "spec": "2d6+0"}, answers=["8"])          # someone else's roll
        self.assertIsNotNone(self.thing("condition", "mira/mira's hold on theo"))

    def test_story_mode_has_no_plus_or_minus(self):
        self.system("story")
        self.one({"action": "string", "by": "Mira", "on": "Theo", "gain": 1})
        self.assertIn("token", self.one({"action": "string", "by": "Mira", "on": "Theo", "spend": "plus"})["error"])

    def test_emotion_spend_needs_the_emotions_module(self):
        self.flags(FLAGS.format("players", "strings"))
        self.one({"action": "string", "by": "Mira", "on": "Theo", "gain": 1})
        d = self.one({"action": "string", "by": "Mira", "on": "Theo", "spend": "emotion", "emotion": "afraid"})
        self.assertIn("emotions module", d["error"])


class Emotions(Module):
    MODULES = "emotions"

    def test_an_emotion_costs_one_approach_until_acted_on(self):
        d = self.one({"action": "emotion", "owner": "Theo", "name": "Guilty", "why": "he lied"})
        self.assertEqual((d["mod"], d["approaches"]), (-1, ["wits"]))
        self.assertIn("confess", d["note"])
        r = self.do("think", {"action": "roll", "actor": "Theo", "spec": "2d6+1", "approach": "wits"})
        self.assertIn("— 2d6 (", r["next_input"]["question"])
        self.turn.answer("oldworld", r["next_input"]["request_id"], "8")
        self.turn.finish("oldworld", "ok")
        r = self.do("lift", {"action": "roll", "actor": "Theo", "spec": "2d6+1", "approach": "force"})
        self.assertIn("2d6+1", r["next_input"]["question"])
        self.turn.answer("oldworld", r["next_input"]["request_id"], "8")
        self.turn.finish("oldworld", "ok")
        self.assertEqual([e["name"] for e in self.one({"action": "emotion", "owner": "Theo"})["emotions"]], ["Guilty"])
        self.assertTrue(self.one({"action": "emotion", "owner": "Theo", "name": "guilty", "act": True})["cleared"])
        self.assertIsNone(self.thing("condition", "theo/guilty"))
        self.assertIn("one of", self.one({"action": "emotion", "owner": "Theo", "name": "smug"})["error"])


# ── labels, vows, mooks, the GM's budget ──────────────────────────────────────

class Labels(Module):
    MODULES = "labels, emotions"

    def setUp(self):
        super().setUp()
        self.turn_with("apply", {"action": "modules", "apply": True})
        self.one({"action": "identity", "owner": "Mira",
                  "set": {"fierce": 2, "uncanny": 1, "guardian": 1, "proud": 0, "grounded": -1}})

    def test_a_shift_moves_two_together_and_the_edge_becomes_an_emotion(self):
        d = self.one({"action": "identity", "owner": "Mira", "up": "guardian", "down": "fierce", "by": "Coach Reyes",
                      "why": "you protect people"})
        self.assertEqual((d["labels"]["guardian"], d["labels"]["fierce"], d["edge"]), (2, 1, []))
        for n in range(1, 3):
            d = self.one({"action": "identity", "owner": "Mira", "up": "uncanny", "down": "grounded", "why": f"{n}"})
        self.assertEqual((d["labels"]["uncanny"], d["labels"]["grounded"], d["edge"]), (3, -2, ["grounded"]))
        d = self.one({"action": "identity", "owner": "Mira", "up": "uncanny", "down": "proud", "why": "again"})
        self.assertEqual((d["labels"]["uncanny"], d["labels"]["proud"], d["edge"]), (3, -1, ["uncanny"]))
        self.assertEqual(self.thing("condition", "mira/insecure")["approaches"], ["finesse"])
        r = self.do("roll", {"action": "identity", "owner": "Mira", "roll": "uncanny"})
        self.assertIn("2d6+2", r["next_input"]["question"])                                    # 3, insecure -1
        self.turn.answer("oldworld", r["next_input"]["request_id"], "7")
        self.turn.finish("oldworld", "ok")
        self.assertIn("send both", self.one({"action": "identity", "owner": "Mira", "up": "proud"})["error"])
        self.assertIn("labels:", self.one({"action": "identity", "owner": "Mira", "roll": "danger"})["error"])

    def test_a_roll_with_a_label_is_the_usual_check(self):
        r = self.do("roll", {"action": "identity", "owner": "Mira", "roll": "fierce", "label": "hold the line"})
        self.assertIn("2d6+2", r["next_input"]["question"])
        d = self.data(self.turn.answer("oldworld", r["next_input"]["request_id"], "8"))
        self.turn.finish("oldworld", "ok")
        self.assertEqual((d["total"], d["with_label"], d["spec"]), (10, "fierce", "2d6+2"))   # a token may step it up


class Vows(Module):
    MODULES = "vows"

    def vow(self, **extra):
        return self.one({"action": "vow", "owner": "Mira", "name": "Get my brother out", **extra})

    def test_swear_mark_and_keep_it_for_xp(self):
        self.assertIn("swear it", self.vow(mark=1)["error"])
        self.assertIn("swear it", self.vow(rank="easy", forsake=True)["error"])
        self.vow(rank="hard", why="at the gate")
        for n in range(6):
            d = self.vow(mark=1, why=f"step {n}")
        self.assertEqual(d["boxes"], 6)
        r = self.do("fulfil", {"action": "vow", "owner": "Mira", "name": "Get my brother out", "fulfil": True})
        self.assertIn("2d6+1", r["next_input"]["question"])                                    # 6 boxes: +1
        d = self.data(self.turn.answer("oldworld", r["next_input"]["request_id"], "9"))
        self.turn.finish("oldworld", "ok")
        self.assertEqual((d["degree"], d["kept"], d["xp"]), ("success", True, 3))
        self.assertIn('xp "Mira" --mark 3', d["xp_command"])
        self.assertNotIn("spec", d)
        self.assertIsNone(self.thing("progress", "mira/get my brother out"))

    def test_a_miss_loses_two_boxes_a_cost_one_xp_and_forsaking_marks_stress(self):
        self.vow(rank="tough")
        self.vow(mark=2)                                                                       # 4 boxes: +0
        d = self.data(self.turn_with("f", {"action": "vow", "owner": "Mira", "name": "Get my brother out",
                                           "fulfil": True}, answers=["5"]))
        self.assertEqual((d["kept"], d["boxes_now"]), (False, 2))
        d = self.data(self.turn_with("f2", {"action": "vow", "owner": "Mira", "name": "Get my brother out",
                                            "fulfil": True, "why": "2"}, answers=["9"]))       # 9 - 1 = 8: a cost
        self.assertEqual((d["degree"], d["xp"]), ("success at a cost", 1))
        self.vow(rank="epic", why="again")
        d = self.vow(forsake=True)
        self.assertEqual((d["forsaken"], d["stress"]), (True, 3))
        self.assertEqual(self.thing("track", "mira/stress")["value"], 3)


class Mooks(Module):
    MODULES = "mooks"

    def test_mooks_drop_in_one_hit_and_deal_less_as_they_drop(self):
        d = self.one({"action": "foe", "name": "Dock thugs", "threat": 1, "count": 6})
        self.assertEqual((d["kind"], d["boxes"], d["deals"]), ("mooks", 6, 2))               # threat 1 + 2: deals 2
        d = self.one({"action": "foe", "name": "Dock thugs", "hit": 3, "why": "a big swing"})
        self.assertEqual((d["left"], d["deals"]), (3, 1))                                       # 3 harm, 3 down
        d = self.one({"action": "foe", "name": "Dock thugs", "hit": 2})
        self.assertEqual((d["left"], d["deals"]), (1, 1))
        d = self.one({"action": "foe", "name": "Lone sentry", "threat": 4, "count": 1, "mook": True})
        self.assertEqual((d["kind"], d["boxes"]), ("mooks", 1))                                 # nameless: one hit
        for n in range(1):
            d = self.one({"action": "foe", "name": "Dock thugs", "hit": 1, "why": f"{n}"})
        self.assertEqual((d["down"], d["deals"]), (True, 0))

    def test_named_foes_take_several(self):
        d = self.one({"action": "foe", "name": "Captain Hale", "threat": 1})
        self.assertEqual((d["kind"], d["boxes"]), ("named", 2))                                 # at least 2
        d = self.one({"action": "foe", "name": "The Warden", "threat": 5})
        self.assertEqual((d["boxes"], d["deals"]), (6, 3))
        d = self.one({"action": "foe", "name": "The Warden", "hit": 2})
        self.assertEqual((d["harm"], d["left"], d["down"]), (2, 4, False))
        self.assertIn("threat first", self.one({"action": "foe", "name": "Nobody", "hit": 1})["error"])
        self.assertEqual(self.thing("track", "the warden/harm")["thresholds"], [])              # no PC thresholds


class GmBudget(Module):
    MODULES = "gm_budget"

    def test_spends_are_counted_refused_when_short_and_refilled(self):
        d = self.one({"action": "complicate", "what": "the relief guard comes early", "cost": 2})
        self.assertEqual((d["left"], d["seq"]), (1, 1))
        d = self.one({"action": "complicate", "what": "the bridge is out", "cost": 2})
        self.assertIn("budget is short", d["error"])
        self.one({"action": "complicate", "what": "a dog barks", "cost": 1})
        d = self.one({"action": "complicate"})
        self.assertEqual((d["left"], [s["what"] for s in d["spent"]]), (0, ["the relief guard comes early", "a dog barks"]))
        self.assertTrue(all(s["turn"] for s in d["spent"]))
        self.turn_with("new session", {"action": "pool", "refill": "session"})
        self.assertEqual(self.one({"action": "complicate"})["left"], 3)


# ── usage dice, contests, seasons, the war layer ──────────────────────────────

class UsageDie(Module):
    MODULES = "usage_die"
    ROLL = "auto"

    def test_stock_and_step_down_until_gone(self):
        d = self.one({"action": "upkeep", "dice": {"torches": "d4"}})
        self.assertEqual(d["dice"], {"torches": "d4"})
        seen = []
        for n in range(60):
            d = self.one({"action": "use", "item": "torches", "why": f"{n}"})
            if "error" in d:
                break
            seen.append(d)
            self.assertEqual(d["gone"], d["rolled"] <= 2)
            if d["gone"]:
                self.assertIsNone(d["die"])
        self.assertTrue(seen[-1]["gone"])
        self.assertIn("no usage die left", d["error"])
        self.assertIn("sizes", self.one({"action": "upkeep", "dice": {"fuel": "d7"}})["error"])
        self.assertIn("of their own", self.one({"action": "upkeep", "dice": {"fuel": "d6"}, "stores": {"food": 3}})["error"])

    def test_off_and_5e_keep_the_old_supplies(self):
        self.flags(FLAGS.format("auto", "heat"))
        self.assertIn("not switched on", self.one({"action": "upkeep", "dice": {"torches": "d8"}})["error"])
        self.system("d20")
        self.assertIn("survival is off", self.one({"action": "use", "item": "torches"})["error"])
        self.assertIn("survival is off", self.one({"action": "upkeep", "dice": {"torches": "d8"}})["error"])


class Contest(Module):
    MODULES = "contest"

    def sub(self, *argv):
        import subprocess
        return subprocess.run([sys.executable, str(modules.HERE / "subsystem.py"), "-c", "oldworld", *argv],
                              capture_output=True, text=True, encoding="utf-8")

    def test_race_to_three(self):
        self.assertEqual(self.sub("start", "Bake-off", "--race", "3", "--sides", "Mira,The baker").returncode, 0)
        self.assertIn("Mira 2 · The baker 0", self.sub("check", "Bake-off", "--side", "Mira", "--total", "12").stdout)
        out = self.sub("check", "Bake-off", "--side", "mira", "--total", "5").stdout
        self.assertIn("Mira 2 · The baker 1", out)
        out = self.sub("check", "Bake-off", "--side", "Mira", "--total", "8").stdout
        self.assertIn("WON BY Mira", out)
        self.assertIn("GM sets the price", out)
        self.assertNotEqual(self.sub("check", "Bake-off", "--side", "Mira", "--total", "8").returncode, 0)

    def test_countdown_and_the_concession(self):
        self.sub("start", "The hearing", "--countdown", "4", "--sides", "Theo,The prosecutor")
        self.assertIn("--side: one of", self.sub("check", "The hearing", "--total", "8").stderr)
        self.assertIn("Theo 3/4 · The prosecutor 3/4", self.sub("check", "The hearing", "--side", "Theo", "--total", "8").stdout)
        self.sub("check", "The hearing", "--side", "Theo", "--total", "10")                    # prosecutor 1
        out = self.sub("check", "The hearing", "--side", "Theo", "--total", "11").stdout       # prosecutor 0
        self.assertIn("WON BY Theo · concession owed: small", out)
        self.sub("start", "Chase", "--goal", "2")
        self.assertIn("not a contest", self.sub("check", "Chase", "--side", "Theo", "--total", "8").stderr)

    def test_a_cost_that_wins_costs_nothing(self):
        self.sub("start", "Duel", "--countdown", "2", "--sides", "Mira,Ash")
        self.sub("check", "Duel", "--side", "Mira", "--total", "7")                            # 1 / 1
        out = self.sub("check", "Duel", "--side", "Ash", "--total", "8").stdout                  # Ash wins at a cost
        self.assertIn("Mira 0/2 · Ash 1/2", out)
        self.assertIn("WON BY Ash · concession owed: a real one", out)

    def test_gated_and_old_challenges_unchanged(self):
        self.assertIn("two different sides", self.sub("start", "X", "--race", "3", "--sides", "Mira").stderr)
        self.flags(FLAGS.format("players", "heat"))
        self.assertIn("not switched on", self.sub("start", "X", "--race", "3", "--sides", "A,B").stderr)
        self.system("d20")
        self.assertIn("Braid module", self.sub("start", "X", "--race", "3", "--sides", "A,B").stderr)
        self.assertEqual(self.sub("start", "Chase", "--goal", "2").stdout.strip(), "Chase: 0/2")


class Seasons(Module):
    MODULES = "seasons"
    ROLL = "auto"

    def test_the_season_turns_by_itself_as_time_passes(self):
        d = self.one({"action": "season"})                                                    # May: spring
        self.assertEqual((d["season"], d["turned"]), ("spring", True))
        self.assertIn(d["happening"], modules.load("seasons")["tables"]["spring"])
        self.assertEqual(self.thing("pool", "mira/tokens")["value"], 1)                       # the start: no gain
        r = self.turn_with("a month", {"action": "wait", "minutes": 30 * 1440})               # June: summer
        d = self.data(r)
        self.assertEqual(d["season"]["season"], "summer")
        self.assertIn(d["season"]["happening"], modules.load("seasons")["tables"]["summer"])
        self.assertEqual(self.thing("pool", "mira/tokens")["value"], 2)
        r = self.turn_with("a day", {"action": "wait", "minutes": 1440})
        self.assertNotIn("season", self.data(r))
        self.assertEqual(self.one({"action": "season", "why": "read"})["turned"], False)

    def test_a_kit_climate_names_the_seasons(self):
        (self.camp / "worldkit.json").write_text(json.dumps({"climate": {"seasons": [
            {"name": "dry", "months": [4, 5, 6, 7, 8, 9]}, {"name": "rains", "months": [10, 11, 12, 1, 2, 3]}]}}),
            encoding="utf-8")
        d = self.one({"action": "season"})
        self.assertEqual(d["season"], "dry")
        self.assertIn(d["happening"], modules.load("seasons")["tables"]["spring"])            # May's default table

    def test_off_nothing_turns(self):
        self.flags(FLAGS.format("auto", "heat"))
        r = self.turn_with("a month", {"action": "wait", "minutes": 30 * 1440})
        self.assertNotIn("season", self.data(r))
        self.assertIsNone(self.thing("season", "party"))


class WarLayer(Module):
    MODULES = "war_layer"
    ROLL = "auto"

    def test_time_pressure_supply_and_morale(self):
        d = self.one({"action": "war"})
        self.assertEqual((d["war_time"], d["war_pressure"], d["morale"], d["supply"], d["campaign_actions"]), (0, 0, 8, 3, 2))
        for n in range(4):
            d = self.one({"action": "war", "pass": True, "why": f"{n}"})
        self.assertEqual((d["war_time"], d["war_pressure"], d["supply"], d["morale"], d["hungry"]), (4, 4, 0, 6, True))
        d = self.one({"action": "war", "advance": True})
        self.assertEqual((len(d["dice"]), d["war_pressure"]), (4, 0))
        top = max(d["dice"])
        self.assertEqual(d["time_added"], 5 if d["dice"].count(6) >= 2 else 1 if top <= 3 else 2 if top <= 5 else 3)
        self.assertEqual(d["war_time"], 4 + d["time_added"])
        d = self.one({"action": "war", "losses": 4, "why": "the ford"})
        self.assertEqual((d["morale"], d["campaign_actions"]), (2, 0))
        self.assertEqual([c["at"] for c in d["crossed"]], [3])
        d = self.one({"action": "war", "losses": 5, "why": "the rout"})
        self.assertEqual((d["morale"], d["deserters"]), (0, 3))

    def test_a_unit_is_a_character(self):
        d = self.one({"action": "war", "unit": "Third Lantern", "quality": "trained"})
        self.assertEqual((d["rating"], d["boxes"]), (1, 2))
        d = self.one({"action": "war", "unit": "Third Lantern", "roll": "hold the bridge"})
        self.assertEqual((d["actor"], d["modifier"]), ("Third Lantern", 1))
        self.one({"action": "war", "unit": "Third Lantern", "hit": 1})
        d = self.one({"action": "war", "unit": "Third Lantern", "hit": 1, "why": "again"})
        self.assertTrue(d["broken"])
        self.assertEqual(self.thing("track", "party/morale")["value"], 7)
        self.assertIn("quality: one of", self.one({"action": "war", "unit": "X", "quality": "elite"})["error"])


class StoryMode(Module):
    """Every module action that rolls asks the oracle in story mode, with odds from what the dice would have added."""
    MODULES = "position_effect, engagement, labels, vows, war_layer"

    def setUp(self):
        super().setUp()
        self.system("story")

    def test_each_rolling_action_asks_the_oracle(self):
        d = self.one({"action": "position", "actor": "Mira", "position": "desperate", "label": "leap"})
        self.assertEqual((d["likelihood"], d["reading"]["position"]), ("unlikely", "desperate"))
        d = self.one({"action": "engagement", "actor": "Mira", "plan": "social", "detail": "a cousin", "bold": True})
        self.assertEqual(d["likelihood"], "likely")
        self.assertIn(d["position"], ("controlled", "risky", "desperate"))
        self.turn_with("apply", {"action": "modules", "apply": True})
        self.one({"action": "identity", "owner": "Mira", "set": {"guardian": 3, "proud": -2}})
        self.assertEqual(self.one({"action": "identity", "owner": "Mira", "roll": "guardian"})["likelihood"], "sure-thing")
        self.assertEqual(self.one({"action": "identity", "owner": "Mira", "roll": "proud"})["likelihood"], "no-way")
        self.one({"action": "vow", "owner": "Mira", "name": "Home", "rank": "easy"})
        self.one({"action": "vow", "owner": "Mira", "name": "Home", "mark": 2})                 # 6 boxes
        d = self.one({"action": "vow", "owner": "Mira", "name": "Home", "fulfil": True})
        self.assertEqual(d["likelihood"], "likely")
        self.assertIn("kept", d)
        self.one({"action": "war", "unit": "Third Lantern", "quality": "veteran"})
        self.assertEqual(self.one({"action": "war", "unit": "Third Lantern", "roll": "hold"})["likelihood"], "sure-thing")


# ── the acceptance games ──────────────────────────────────────────────────────

class HeistJob(BraidCampaign):
    """One whole job, scripted: a core campaign with position_effect and heat, a job from the story generator, a clock
    on each defence ticked by position rolls the players roll, harm marked from the reading, the thing that goes
    wrong turning the position desperate, the getaway, and the heat and entanglement afterwards."""

    def test_one_job_from_the_first_obstacle_to_the_heat(self):
        with no_5e() as used:
            self.build(flags={**SEED["flags"], "modules": "position_effect, heat"})
            self.assertEqual(self.sheet(*MIRA), 0)
            self.assertEqual(self.sheet(*THEO), 0)
            self.assertEqual(story_gen.main(["-c", "braid", "skeleton", "--genre", "heist", "--seed", "1931"]), 0)
            skel = json.loads((self.root / "campaigns" / "braid" / "story-skeleton.json").read_text(encoding="utf-8"))
            plan = skel["threads"][0]["plan"]
            obstacles = plan["defences"] + [f"the getaway with {plan['target']}"]

            r = self.turn_with("the crew is in", {"action": "modules", "apply": True},
                               *[{"action": "clock", "name": o, "size": 4} for o in obstacles + ["The watch"]],
                               {"action": "position", "set": "risky", "why": "they are inside, unseen"})
            self.assertEqual(self.thing("track", "party/crew_heat")["value"], 0)

            # Each obstacle is worked by position rolls until its clock fills. The players' dice come in turn: a miss,
            # a cost, a clean hit. The GM makes a miss or a cost harm (exactly what the reading says) unless that would
            # take the character out; then it is a complication instead: the watch's clock ticks.
            dice, n, harm, trouble = ["3", "6", "9", "11"], 0, {"Mira Vale": 0, "Theo": 0}, 0
            for i, obstacle in enumerate(obstacles):
                if i == 1:                                                    # the thing that goes wrong
                    self.turn_with(f"[GM]: {plan['goes_wrong']}",
                                   {"action": "position", "set": "desperate", "why": plan["goes_wrong"]})
                while not (self.thing("clock", obstacle) or {}).get("filled", 0) >= 4:
                    actor = ["Mira Vale", "Theo"][n % 2]
                    self.assertLess(harm[actor], 4)                               # nobody taken out acts
                    r = self.turn_with(f"[{actor}]: I work on {obstacle}",
                                       {"action": "position", "actor": actor, "approach": "wits", "effect": "standard",
                                        "label": obstacle, "clock": obstacle}, answers=[dice[n % len(dice)]])
                    hurt = self.data(r)["reading"]["harm_if_hurt"]
                    n += 1
                    if hurt and harm[actor] + hurt < 4:
                        harm[actor] += hurt
                        self.turn_with("[GM]: it hurts", {"action": "track", "owner": actor, "id": "harm",
                                                          "mark": hurt, "why": obstacle})
                    elif hurt:
                        trouble += 1
                        self.turn_with("[GM]: the watch hears something", {"action": "clock", "name": "The watch",
                                                                           "tick": 1, "why": obstacle})
                    self.assertLess(n, 20)
            self.assertEqual(self.thing("position", "party")["position"], "desperate")
            self.assertGreater(sum(harm.values()), 0)
            self.assertGreater(trouble, 0)
            for actor, marked in harm.items():
                self.assertEqual((self.thing("track", f"{actor.casefold()}/harm") or {"value": 0})["value"], marked)

            r = self.turn_with("[GM]: the job is done; how loud was it?",
                               {"action": "crew_heat", "job": "loud", "high_profile": True})
            self.assertEqual(self.data(r)["crew_heat"], 5)
            r = self.turn_with("[GM]: a week later", {"action": "crew_heat", "entangle": True})
            d = self.data(r)
            self.assertEqual(d["column"], "entangle_mid")
            self.assertIn(d["entanglement"], modules.load("heat")["tables"]["entangle_mid"])
        self.assertEqual(used, [])
        self.assertEqual(leaks("\n".join(self.out)), [])


class RomanceArc(BraidCampaign):
    """One whole arc, scripted: a core campaign with strings, two characters made with sheet.py, the obstacles from
    the story generator, strings gained and spent (a rival's minus, a temptation taken for XP, a plus before the
    confession), and the bond the arc leaves behind."""

    def roll(self, text, intent, die):
        return self.data(self.turn_with(text, intent, answers=[die]))

    def test_one_arc_from_the_first_string_to_the_confession(self):
        import sheet
        with no_5e() as used:
            self.build(flags={**SEED["flags"], "modules": "strings"})
            self.assertEqual(self.sheet(*MIRA), 0)
            self.assertEqual(self.sheet(*THEO), 0)
            self.assertEqual(story_gen.main(["-c", "braid", "skeleton", "--genre", "romance", "--seed", "1931"]), 0)
            skel = json.loads((self.root / "campaigns" / "braid" / "story-skeleton.json").read_text(encoding="utf-8"))
            obstacles = skel["threads"][0]["obstacles"]
            rival = next(o["who"] for o in obstacles if o["src"] == "character")
            self.assertTrue(rival)

            # Scene 1: they meet again; each lets something slip, each gains a string on the other.
            self.turn_with("[GM]: the festival", {"action": "bond", "a": "Mira Vale", "b": "Theo", "set": 1,
                                                  "note": "a promise made as children"},
                           {"action": "string", "by": "Mira Vale", "on": "Theo", "gain": 1, "why": "he still keeps her letter"},
                           {"action": "string", "by": "Theo", "on": "Mira Vale", "gain": 1, "why": "she blushed"},
                           {"action": "string", "by": rival, "on": "Theo", "gain": 1, "why": "knows what he owes"})

            # Scene 2: the rival (the character obstacle) leans on Theo: -1 on his next roll, then it is gone.
            self.turn_with(f"[GM]: {obstacles[0]['text']}",
                           {"action": "string", "by": rival, "on": "Theo", "spend": "minus"})
            d = self.roll("[Theo]: I stand up to them", {"action": "roll", "actor": "Theo", "approach": "heart",
                                                         "label": "stand up to the rival"}, "6")
            self.assertEqual((d["total"], d["used"]), (7, [f"{rival}'s hold on Theo"]))  # 6 + Heart 2 - 1
            self.assertIsNone(self.thing("condition", f"theo/{rival.casefold()}'s hold on theo"))

            # Scene 3: Mira tempts Theo to leave with her before the trouble (the circumstance obstacle); he goes.
            r = self.turn_with(f"[Mira Vale]: {obstacles[1]['text']} - come away with me tonight",
                               {"action": "string", "by": "Mira Vale", "on": "Theo", "spend": "tempt",
                                "offer": "leave the city with her tonight"},
                               {"action": "string", "on": "Theo", "accept": True})
            cmd = shlex.split(self.data(r)["xp_command"])
            self.assertEqual(cmd[:3], ["sheet.py", "-c", "braid"])
            self.assertEqual(self.run_main(sheet, cmd[1:]), 0)
            self.assertEqual(sheet.parse(sheet.find("braid", "Theo").read_text(encoding="utf-8"))["xp"], 1)

            # Scene 4: the confession. Theo spends his string on Mira for +1; the bond grows with what happened.
            self.turn_with("[Theo]: I tell her", {"action": "string", "by": "Theo", "on": "Mira Vale", "spend": "plus"})
            d = self.roll("[Theo]: I tell her the truth", {"action": "roll", "actor": "Theo", "approach": "heart",
                                                           "label": "say it"}, "8")
            self.assertEqual((d["total"], d["degree"]), (11, "success"))                   # 8 + Heart 2 + 1
            r = self.turn_with("[GM]: the arc closes", {"action": "bond", "a": "Mira Vale", "b": "Theo", "mark": 2,
                                                        "why": "they said it out loud"})
            bond = self.thing("bond", "mira vale|theo")
            self.assertEqual((bond["value"], bond["points"]), (3, {"mira vale": 0, "theo": 0}))
            self.assertEqual(self.thing("bond", f"{rival.casefold()}|theo")["points"], {rival.casefold(): 0})
            self.assertEqual([c for c in self.conditions() if c["clears"] == "next roll"], [])
        self.assertEqual(used, [])
        self.assertEqual(leaks("\n".join(self.out)), [])

    def conditions(self):
        import world_db as wdb
        with wdb.reader("braid") as db:
            return list(wdb.all_of(db, "condition").values())


if __name__ == "__main__":
    unittest.main()
