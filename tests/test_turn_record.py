"""Living World plan PR 2: a change to the world and its record are one command. `finish` notes which actions
and events the narration stands on, rewrites the engine's own block in state.md (and nothing else) before the
narration is sent, survives a crash between the two, and an undo takes the store, the queue and the block back
together."""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _engine_case import SCRIPTS, EngineCase  # noqa: E402

CLOSE = {"action": "route", "between": ["Millbridge", "The Ford"], "access": "closed", "reason": "the Tollmen hold it"}
RIDER = {"action": "schedule", "in_minutes": 600, "text": "The rider reaches the mill.", "event_id": "rider"}


class TurnRecordTests(EngineCase):
    def state(self) -> str:
        return (self.camp / "state.md").read_text(encoding="utf-8")

    def block(self) -> str:
        text = self.state()
        a, b = text.find("<!-- unrolled:world -->"), text.find("<!-- /unrolled:world -->")
        return text[a:b] if a != -1 else ""

    def cli(self, *args, crash=None):
        env = {**os.environ, **({"DNE_CRASH_AT": crash} if crash else {})}
        env.pop("DNE_CRASH_AT", None) if not crash else None
        r = subprocess.run([sys.executable, str(SCRIPTS / "turn.py"), "-c", "oldworld", *args],
                           capture_output=True, encoding="utf-8", env=env, timeout=60)
        if crash:
            self.assertEqual(r.returncode, 77, r.stdout + r.stderr)
            return None
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def sent(self):
        out = self.root / "out.jsonl"
        return [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines()] if out.exists() else []

    def test_finish_records_what_the_narration_stands_on_and_writes_only_its_block(self):
        mine = self.state().replace("## Pinned Facts", "## Pinned Facts\n- The GM's own line stays.", 1) \
            if "## Pinned Facts" in self.state() else self.state() + "\nThe GM's own line stays.\n"
        (self.camp / "state.md").write_text(mine, encoding="utf-8")
        self.do("[Mira]: the Tollmen shut the road and send a rider", CLOSE, RIDER)
        done = self.turn.finish("oldworld", "The barrier drops across the road.")
        rec = done["committed"]
        self.assertEqual([a["action"] for a in rec["actions"]], ["route", "schedule"])
        block = self.block()
        self.assertIn("ford|millbridge closed (the Tollmen hold it)", block)
        self.assertIn("The rider reaches the mill. (rider)", block)
        self.assertIn(f"{done['turn_id']}: route, schedule", block)
        self.assertIn("The GM's own line stays.", self.state())
        self.assertEqual(self.thing("turn_record", done["turn_id"]), rec)
        # A GM edit inside the block is replaced at the next finish; the rest of the file is left alone.
        (self.camp / "state.md").write_text(self.state().replace("closed (the Tollmen hold it)", "open"), encoding="utf-8")
        self.do("an hour", {"action": "wait", "hours": 1})
        self.turn.finish("oldworld", "An hour.")
        self.assertIn("closed (the Tollmen hold it)", self.block())
        self.assertEqual(self.state().count("<!-- unrolled:world -->"), 1)

    def test_a_turn_with_no_engine_action_closes_and_writes_nothing(self):
        before = self.state()
        self.turn.begin("oldworld", "[Mira]: I look around")
        out = self.turn.finish("oldworld", "Dust and silence.")
        self.assertEqual(out["status"], "finished")
        self.assertIsNone(out["committed"])
        self.assertEqual(self.state(), before)

    def test_finishing_twice_changes_nothing_more(self):
        self.do("[Mira]: shut it", CLOSE)
        done = self.turn.finish("oldworld", "Shut.")
        first, n = self.state(), len(self.sent())
        again = self.turn.finish("oldworld", "Shut.", turn_id=done["turn_id"])
        self.assertTrue(again.get("duplicate"))
        self.assertEqual(self.state(), first)
        self.assertEqual(len(self.sent()), n)

    def test_a_crash_between_the_record_and_the_file_is_finished_by_the_next_reader(self):
        self.cli("begin", "--text", "[Mira]: shut it")
        self.cli("resolve", "--intents", json.dumps([CLOSE]))
        self.cli("finish", "--narration", "The barrier drops.", crash="after_commit_before_apply")
        self.assertEqual(self.block(), "")                     # the store has the record, the file not yet
        self.assertEqual(self.sent(), [])
        self.cli("resume")                                     # any reader completes the file, then the send goes out
        self.assertIn("closed (the Tollmen hold it)", self.block())
        self.assertEqual([m.get("body") or m.get("text") for m in self.sent()].count("The barrier drops."), 1)
        self.cli("resume")
        self.assertEqual(len(self.sent()), 1)

    def test_a_change_survives_a_new_agent_and_undo_takes_it_all_back(self):
        self.do("[Mira]: we wait", {"action": "wait", "hours": 1})
        self.turn.finish("oldworld", "Waiting.")
        before_block = self.block()
        self.do("[Mira]: shut it and send the rider", CLOSE, RIDER)
        self.turn.finish("oldworld", "Shut.")
        self.assertEqual(self.cli("status")["status"], "idle")              # a fresh process: nothing left open
        self.assertEqual(self.thing("route", "ford|millbridge")["access"], "closed")
        self.assertEqual(self.event("rider")["status"], "pending")
        r = subprocess.run([sys.executable, str(SCRIPTS / "turn_snapshot.py"), "-c", "oldworld", "undo", "--no-display"],
                           capture_output=True, encoding="utf-8", env=os.environ.copy(), timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIsNone(self.thing("route", "ford|millbridge"))
        self.assertIsNone(self.event("rider"))
        self.assertEqual(self.block(), before_block)
