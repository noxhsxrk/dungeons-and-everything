"""Braid PR 6, the modules we designed ourselves: loop, roles, realm, status_window, memories.

Acceptance (plan §5 PR 6): after three loops the state is back to the seed everywhere the players did not carry
something across, and the world replays the same day each time; the seal of a secret deal matches the roles revealed
at the end, and a deal changed after sealing is caught."""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import sqlite3
import sys
import unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _engine_case import EngineCase  # noqa: E402
from test_braid_seam import stamp  # noqa: E402

import turn  # noqa: E402,F401  (the engine first)
import modules  # noqa: E402

PR6 = ("loop", "roles", "realm", "status_window", "memories")
FLAGS = "- display: none\n- roll_mode: {}\n- world_engine: on\n- modules: {}\n"
#: Published games the research for these modules looked at: none of their names belongs in a module.
TRADE = [r"TimeWatch", r"Chronal", r"Thousand Year Old Vampire", r"Hitler", r"Battlestar", r"Paranoia",
         r"Dungeon Crawler", r"Log Horizon", r"Wushu", r"Risus", r"Weapons of the Gods", r"Feng Shui", r"Groundhog",
         r"Continuum", r"Microscope", r"Ironsworn", r"Mythic"]
#: What a reset leaves alone (loop.md): the loop's own record and tracks, minds, secrets, and the runner's books.
CARRY_KINDS = {"loop", "memory", "roles", "status_seen", "achievement", "turn_record", "mention", "step_up"}
CARRY_TRACKS = {"party/loop_break", "party/loop_fatigue"}
WORLD_FILES = ("calendar.json", "tracker.json", "world-map.json", "factions.json")


class Pr6(EngineCase):
    MODULES, ROLL, SYSTEM = ", ".join(PR6), "auto", "core"

    def setUp(self):
        self.FLAGS = FLAGS.format(self.ROLL, self.MODULES)
        super().setUp()
        stamp(self.camp, self.SYSTEM)

    def turn_with(self, text, *intents, answers=()):
        r = self.do(text, *intents)
        for a in answers:
            self.assertEqual(r["status"], "waiting_for_player", r)
            r = self.turn.answer("oldworld", r["next_input"]["request_id"], a)
        self.turn.finish("oldworld", "ok")
        return r

    def one(self, intent, answers=()):
        return self.data(self.turn_with(intent["action"], intent, answers=answers))

    def outbox(self) -> list:
        path = self.root / "out.jsonl"
        return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


class Refusals(Pr6):
    def test_each_action_needs_braid_and_its_module(self):
        intents = [{"action": "loop"}, {"action": "roles"}, {"action": "realm", "actor": "Mira"},
                   {"action": "status", "show": "Mira"}, {"action": "memories", "owner": "Mira"}]
        self.flags(FLAGS.format("auto", "composure"))
        for it in intents:
            self.assertIn("not switched on", self.one(it)["error"], it)
        stamp_back = (self.camp / "state.md").read_text(encoding="utf-8").replace("  **System:** core", "")
        (self.camp / "state.md").write_text(stamp_back, encoding="utf-8")
        self.flags(FLAGS.format("auto", ", ".join(PR6)))
        for it in intents:
            self.assertIn("Braid module", self.one(it)["error"], it)

    def test_no_trade_names(self):
        files = [p for m in PR6 for p in (modules.DIR / f"{m}.json", modules.DIR / f"{m}.md")]
        files += [modules.HERE / f"mod_{m}.py" for m in PR6]
        for path in files:
            text = path.read_text(encoding="utf-8")
            self.assertEqual([t for t in TRADE if re.search(t, text)], [], path.name)


# ── loop ──────────────────────────────────────────────────────────────────────

class Loop(Pr6):
    MODULES = "loop, memories"

    def print_world(self) -> str:
        """Everything a reset rewinds: every event row, every record not carried, the world files."""
        db = sqlite3.connect(str(self.camp / "world.db"))
        try:
            events = db.execute("SELECT * FROM events ORDER BY event_id").fetchall()
            things = [r for r in db.execute("SELECT kind, id, data FROM things ORDER BY kind, id")
                      if r[0] not in CARRY_KINDS and not (r[0] == "track" and r[1] in CARRY_TRACKS)]
        finally:
            db.close()
        files = [(f, (self.camp / f).read_text(encoding="utf-8") if (self.camp / f).exists() else None) for f in WORLD_FILES]
        return hashlib.sha256(json.dumps([events, things, files], default=str).encode()).hexdigest()

    def seeded_day(self) -> tuple:
        """What the world did by itself during the day: the seeded events' outcome and the files it wrote."""
        db = sqlite3.connect(str(self.camp / "world.db"))
        try:
            rows = db.execute("SELECT event_id, status, applied_minute FROM events WHERE event_id IN "
                              "('bell', 'faction-week-1', 'ferry') ORDER BY event_id").fetchall()
        finally:
            db.close()
        return rows, self.read_json("calendar.json"), self.read_json("factions.json")

    def test_three_loops_come_back_to_the_seed_and_replay_the_same_day(self):
        self.turn_with("the day before", {"action": "schedule", "in_minutes": 120, "text": "The bell rings",
                                          "event_id": "bell", "audience": "party"},
                       {"action": "schedule", "in_minutes": 600, "text": "The ferry leaves", "event_id": "ferry"},
                       {"action": "track", "owner": "Mira", "id": "harm", "mark": 1, "why": "an old cut"},
                       {"action": "wait", "minutes": 1})
        d = self.one({"action": "loop", "start": True})
        self.assertEqual((d["loop"], d["started"]), (1, True))
        self.assertIn("error", self.one({"action": "loop", "start": True}))   # the seed is taken once
        seed = self.print_world()
        self.assertIsNotNone(self.event("faction-week-1"))                     # the world's own rhythm is in the seed
        days = []
        meddling = [
            [{"action": "track", "owner": "Mira", "id": "harm", "mark": 2, "why": "fell"},
             {"action": "schedule", "in_minutes": 30, "text": "Mira's trap springs", "event_id": "trap"},
             {"action": "loop", "learn": "Ada rings the bell"}, {"action": "loop", "learn": "the ferryman lies"},
             {"action": "loop", "anchor": "the silver key"}],
            [{"action": "condition", "owner": "Mira", "name": "Shaken", "mod": -1},
             {"action": "pool", "owner": "Mira", "id": "tokens", "max": 3, "set": 2},
             {"action": "memories", "owner": "Mira", "keep": "the bell's third note is wrong"}],
            [{"action": "track", "owner": "party", "id": "loop_break", "mark": 3, "why": "found the clockwork"},
             {"action": "track", "owner": "Mira", "id": "harm", "set": 0},
             {"action": "schedule", "in_minutes": 5, "text": "the ferry is burned", "event_id": "ferry-burned"}],
        ]
        for n, touch in enumerate(meddling, 1):
            self.turn_with(f"loop {n}", *touch)
            self.turn_with("the day goes by", {"action": "wait", "minutes": 8 * 1440})
            self.assertNotEqual(self.print_world(), seed, n)                    # the day really moved
            days.append(self.seeded_day())
            self.assertEqual(self.event("bell")["status"], "applied")
            d = self.one({"action": "loop", "reset": True, "why": f"midnight {n}"})
            self.assertEqual(d["loop"], n + 1)
            self.assertEqual(self.print_world(), seed, f"after reset {n}")       # back to the seed, exactly
            self.assertEqual(self.event("bell")["status"], "pending")
        self.assertEqual(days[0], days[1])                                      # the same day, three times
        self.assertEqual(days[1], days[2])
        self.assertEqual(days[0][0][1][1], "applied")                           # faction week ran by itself
        # carried: anchors, loop_break, fatigue, memories; knowledge minus one the third fatigue took
        loop = self.thing("loop", "party")
        self.assertEqual(loop["anchors"], ["the silver key"])
        self.assertEqual(d["fatigue"], 3)
        self.assertEqual(len(loop["knowledge"]), 1)
        self.assertIn(d["forgot"], ["Ada rings the bell", "the ferryman lies"])
        self.assertEqual(self.thing("track", "party/loop_break")["value"], 3)
        self.assertEqual(self.thing("memory", "mira")["held"], ["the bell's third note is wrong"])
        self.assertEqual(self.thing("track", "mira/harm")["value"], 1)          # the seed's old cut, not loop 3's 0
        self.assertIsNone(self.thing("condition", "mira/shaken"))

    def test_reset_needs_a_seed_and_a_broken_loop_stays_broken(self):
        self.assertIn("no seed", self.one({"action": "loop", "reset": True})["error"])
        self.one({"action": "loop", "start": True})
        self.one({"action": "track", "owner": "party", "id": "loop_break", "mark": 10})
        self.assertIn("broken", self.one({"action": "loop", "reset": True})["error"])

    def test_anchors_are_few(self):
        for item in ("a", "b", "c"):
            self.one({"action": "loop", "anchor": item})
        self.assertIn("3 anchors", self.one({"action": "loop", "anchor": "d"})["error"])
        self.assertEqual(self.one({"action": "loop", "drop": "b"})["anchors"], ["a", "c"])


# ── roles ─────────────────────────────────────────────────────────────────────

class Roles(Pr6):
    MODULES = "roles"
    NAMES = ["Mira", "Vos", "Kell", "Ada"]

    def deal(self) -> tuple:
        r = self.turn_with("deal", {"action": "roles", "deal": self.NAMES, "roles": {"traitor": 1}})
        sent = self.outbox()
        seal = next(re.search(r"[0-9a-f]{64}", m["body"]).group(0) for m in sent if m["audience"] == "party"
                    and "Seal" in m["body"])
        return self.data(r), seal, sent

    def tamper(self, fn) -> None:
        db = sqlite3.connect(str(self.camp / "world.db"))
        try:
            rec = json.loads(db.execute("SELECT data FROM things WHERE kind='roles' AND id='deal'").fetchone()[0])
            fn(rec)
            db.execute("UPDATE things SET data=? WHERE kind='roles' AND id='deal'", (json.dumps(rec),))
            db.commit()
        finally:
            db.close()

    def test_the_seal_matches_the_roles_revealed_at_the_end(self):
        d, seal, sent = self.deal()
        self.assertEqual(d["seal"], seal)
        self.assertNotIn("deal", d)
        self.assertNotIn("traitor", json.dumps(d) + json.dumps([m for m in sent if m["audience"] == "party"]))
        mine = [m for m in sent if m["audience"] == "Mira"]                       # only the PC hears, privately
        self.assertEqual(len(mine), 1)
        self.assertEqual({m["audience"] for m in sent}, {"party", "Mira"})
        self.assertIn("error", self.one({"action": "roles", "deal": ["A", "B"]}))   # no second deal before the reveal
        out = self.one({"action": "roles", "reveal": True, "expect": seal})
        self.assertTrue(out["verified"], out)
        self.assertEqual(sorted(out["deal"].values()), ["loyal", "loyal", "loyal", "traitor"])
        self.assertEqual(sorted(out["deal"]), sorted(self.NAMES))
        body = json.dumps({"deal": out["deal"], "salt": out["salt"]}, sort_keys=True, separators=(",", ":"))
        self.assertEqual(hashlib.sha256(body.encode()).hexdigest(), seal)   # anyone can check it by hand
        self.assertIn(f"Your secret role: {out['deal']['Mira']}.", mine[0]["body"])

    def test_a_moved_traitor_is_caught(self):
        _, seal, _ = self.deal()

        def move(rec):
            names = sorted(rec["deal"])
            traitor = next(n for n in names if rec["deal"][n] == "traitor")
            other = next(n for n in names if n != traitor)
            rec["deal"][traitor], rec["deal"][other] = "loyal", "traitor"
        self.tamper(move)
        out = self.one({"action": "roles", "reveal": True})
        self.assertFalse(out["verified"])
        self.assertIn("stored seal", " ".join(out["problems"]))
        # moving it and re-sealing the record is still caught by what the table was sent and kept
        self.tamper(lambda rec: rec.update(seal=hashlib.sha256(json.dumps(
            {"deal": rec["deal"], "salt": rec["salt"]}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()))
        out = self.one({"action": "roles", "reveal": True, "expect": seal})
        self.assertFalse(out["verified"])
        self.assertEqual(len(out["problems"]), 2)

    def test_npcs_act_from_their_role_and_players_choose(self):
        self.deal()
        acts = modules.load("roles")["tables"]
        deal = self.one({"action": "roles", "reveal": True})["deal"]          # read it back for the check only
        for name in ("Vos", "Kell", "Ada"):
            got = self.one({"action": "roles", "act": name, "why": "the vote"})
            self.assertIn(got["act"], acts[f"{deal[name]}_acts"])
        self.assertIn("player character", self.one({"action": "roles", "act": "Mira"})["error"])
        self.assertIn("error", self.one({"action": "roles", "act": "Nobody"}))


# ── realm ─────────────────────────────────────────────────────────────────────

class Realm(Pr6):
    MODULES, ROLL = "realm", "players"

    def test_breakthrough_is_the_usual_check(self):
        names = modules.load("realm")["tables"]["realms"]
        d = self.one({"action": "realm", "actor": "Mira", "breakthrough": True, "spec": "2d6+0"}, answers=["8"])
        self.assertEqual((d["degree"], d["realm"], d["name"]), ("success at a cost", 1, names[1]))
        self.assertNotIn("spec", d)
        d = self.one({"action": "realm", "actor": "Mira", "breakthrough": True, "spec": "2d6+0"}, answers=["5"])
        self.assertEqual((d["realm"], d["deviation"]), (1, True))
        self.assertEqual(self.thing("condition", "mira/qi deviation")["mod"], -1)
        d = self.one({"action": "realm", "actor": "Mira", "breakthrough": True, "spec": "2d6+0"}, answers=["2"])
        self.assertEqual((d["degree"], d["harm"]), ("critical failure", 1))
        self.one({"action": "pool", "refill": "rest"})
        self.assertIsNone(self.thing("condition", "mira/qi deviation"))

    def test_tribulation_is_n_checks_in_a_row(self):
        self.one({"action": "track", "owner": "Mira", "id": "realm", "set": 2})
        r = self.do("breakthrough", {"action": "realm", "actor": "Mira", "breakthrough": True, "spec": "2d6+0"})
        self.assertIn("2d6-1", r["next_input"]["question"])                 # realm 3 is harder (-1)
        r = self.turn.answer("oldworld", r["next_input"]["request_id"], "10")
        self.turn.finish("oldworld", "ok")
        trib = self.data(r)["tribulation"]
        self.assertEqual((trib["waves"], self.data(r)["realm"]), (3, 2))
        self.assertIn("error", self.one({"action": "realm", "actor": "Mira", "wave": 2}))   # in order
        r, res = self.do("the sky opens", *[{"action": "realm", "actor": "Mira", "wave": n, "spec": "2d6+0"}
                                            for n in (1, 2, 3)]), []
        for die in ("9", "4", "10"):                                        # each wave asks for its own dice
            r = self.turn.answer("oldworld", r["next_input"]["request_id"], die)
            res.append(self.data(r, 0))
        self.turn.finish("oldworld", "ok")
        self.assertEqual([x["degree"] for x in res], ["success at a cost", "critical failure", "success at a cost"])
        self.assertEqual(res[-1]["survived"], True)
        self.assertEqual(self.thing("track", "mira/realm")["value"], 3)
        self.assertEqual(self.thing("track", "mira/harm")["value"], 2)        # one critical miss: 1 + 1
        self.assertIsNone(self.thing("tribulation", "mira"))

    def test_a_failed_tribulation_leaves_deviation_and_the_realm(self):
        self.one({"action": "track", "owner": "Mira", "id": "realm", "set": 2})
        self.one({"action": "realm", "actor": "Mira", "breakthrough": True, "spec": "2d6+0"}, answers=["11"])
        self.turn_with("waves", *[{"action": "realm", "actor": "Mira", "wave": n, "spec": "2d6+0"} for n in (1, 2, 3)],
                       answers=["5", "6", "12"])
        self.assertEqual(self.thing("track", "mira/realm")["value"], 2)
        self.assertIsNotNone(self.thing("condition", "mira/qi deviation"))


class RealmStory(Pr6):
    MODULES, SYSTEM = "realm", "story"

    def test_the_oracle_answers_a_breakthrough(self):
        seen = set()
        for n in range(40):                                     # 12 "likely" tries all passed ~3% of runs
            r = self.turn_with(f"try {n}", {"action": "track", "owner": "Mira", "id": "realm", "set": 0, "why": f"{n}"},
                               {"action": "realm", "actor": "Mira", "breakthrough": True, "why": f"try {n}"})
            d = self.data(r)
            self.assertEqual(d["likelihood"], "likely")
            self.assertEqual(d["realm"], 1 if d["passed"] else 0, d)
            seen.add(d["passed"])
        self.assertEqual(seen, {True, False})


# ── status window ─────────────────────────────────────────────────────────────

class StatusWindow(Pr6):
    MODULES = "status_window"

    def system_lines(self) -> list:
        return [line for m in self.outbox() if m["kind"] == "system" for line in m["body"].splitlines()]

    def test_messages_come_from_the_state(self):
        self.one({"action": "modules", "apply": True})                         # first look: nothing announced
        self.assertEqual(self.system_lines(), [])
        self.one({"action": "track", "owner": "Mira", "id": "harm", "mark": 1, "why": "a scratch"})
        self.assertEqual(self.system_lines(), ["[System] Mira — harm: new (1/4)"])
        self.one({"action": "track", "owner": "Mira", "id": "harm", "mark": 1, "why": "a blade"})
        lines = self.system_lines()
        harm = self.thing("track", "mira/harm")
        self.assertIn(f"[System] Mira — harm: 1/{harm['max']} → {harm['value']}/{harm['max']}", lines)
        self.assertIn("[System] Mira — Wounded: gained (-1)", lines)          # the threshold's condition
        self.one({"action": "track", "owner": "Mira", "id": "harm", "set": 0})
        self.assertIn("[System] Mira — Wounded: ended", self.system_lines())
        n = len(self.system_lines())
        self.one({"action": "status", "show": "Mira"})                         # a read changes nothing
        self.assertEqual(len([x for x in self.system_lines() if x.startswith("[System]")]), n)
        window = self.one({"action": "status", "show": "Mira"})["window"]
        self.assertIn("harm: 0/4", window)

    def test_achievements_once_and_loot_from_the_tables(self):
        a = self.one({"action": "status", "achievement": "Bridge Burner", "to": "Mira", "why": "no way back"})
        b = self.one({"action": "status", "achievement": "Bridge Burner", "to": "Mira"})
        self.assertEqual((a["new"], b["new"]), (True, False))
        self.assertEqual(sum("Bridge Burner" in x for x in self.system_lines()), 1)
        mod = modules.load("status_window")
        for box in ("bronze", "silver", "gold"):
            d = self.one({"action": "status", "loot": box, "to": "Mira"})
            caps, total = [], 0
            for n in mod["numbers"]["boxes"][box]:
                total += n
                caps.append(total)
            self.assertEqual(d["tier"], next(t for t, c in zip(mod["numbers"]["tiers"], caps) if d["d100"] <= c))
            self.assertIn(d["item"], mod["tables"][f"loot_{d['tier']}"])
        self.assertIn("error", self.one({"action": "status", "loot": "platinum", "to": "Mira"}))


class FirstCritical(Pr6):
    MODULES, ROLL = "status_window", "players"

    def test_the_first_critical_success_earns_one_achievement(self):
        self.one({"action": "roll", "actor": "Mira", "spec": "2d6+0", "label": "leap"}, answers=["12"])
        self.one({"action": "roll", "actor": "Mira", "spec": "2d6+0", "label": "leap again"}, answers=["12"])
        got = [x for x in self.system_lines() if "Achievement" in x]
        self.assertEqual(len(got), 1)
        self.assertTrue(any(t in got[0] for t in modules.load("status_window")["tables"]["first_critical_success"]))

    system_lines = StatusWindow.system_lines


# ── memories ──────────────────────────────────────────────────────────────────

class Memories(Pr6):
    MODULES = "memories"

    def test_a_full_mind_asks_which_memory_fades(self):
        for n in range(1, 6):
            self.one({"action": "memories", "owner": "Mira", "keep": f"m{n}"})
        r = self.do("a sixth", {"action": "memories", "owner": "Mira", "keep": "m6"})
        self.assertEqual(r["status"], "waiting_for_player")
        self.assertIn("2) m2", r["next_input"]["question"])
        self.assertEqual(self.thing("memory", "mira")["held"], ["m1", "m2", "m3", "m4", "m5"])   # nothing yet
        r = self.turn.answer("oldworld", r["next_input"]["request_id"], 2)
        self.turn.finish("oldworld", "ok")
        self.assertEqual(self.data(r)["forgotten"], ["m2"])
        self.assertEqual(self.thing("memory", "mira")["held"], ["m1", "m3", "m4", "m5", "m6"])
        d = self.one({"action": "memories", "owner": "Mira", "keep": "m7", "forget": "m1"})
        self.assertEqual(d["held"], ["m3", "m4", "m5", "m6", "m7"])

    def test_amnesia_and_a_shrinking_mind(self):
        for n in range(1, 5):
            self.one({"action": "memories", "owner": "Mira", "keep": f"m{n}"})
        d = self.one({"action": "memories", "owner": "Mira", "lose": True})
        self.assertEqual((len(d["held"]), len(d["forgotten"])), (3, 1))
        d = self.one({"action": "memories", "owner": "Mira", "slots": 2})
        self.assertEqual(len(d["held"]), 2)
        self.assertIn("error", self.one({"action": "memories", "owner": "Mira", "forget": 9}))


if __name__ == "__main__":
    unittest.main()
