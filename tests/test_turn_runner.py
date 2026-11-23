"""World plan PR 2: the turn runner. A repeated input does not roll again, a crashed turn resumes,
a message reaches the table once, and chat mode waits on nothing."""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import unittest

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
SCRIPTS = ROOT / "skills" / "dne" / "scripts"
DISPLAY = ROOT / "skills" / "dne" / "display"
sys.path.insert(0, str(HERE))
import _old_campaign  # noqa: E402


class _Engine(unittest.TestCase):
    FLAGS = "- autorun: false\n- display: none\n- roll_mode: players\n- world_engine: on\n"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)
        self.rt = self.root / "rt"
        self.rt.mkdir()
        self.camp = _old_campaign.make(self.root)
        self.flags(self.FLAGS)
        (self.rt / ".campaign").write_text("oldworld", encoding="utf-8")
        self.outbox = self.root / "outbox.jsonl"
        self.env = {**os.environ, "DNE_CAMPAIGN_ROOT": str(self.root), "DNE_RUNTIME_DIR": str(self.rt),
                    "DNE_DISPLAY_HOST": "127.0.0.1:9", "DNE_OUTBOX_LOG": str(self.outbox)}
        self.env.pop("DNE_CRASH_AT", None)

    def tearDown(self):
        self._tmp.cleanup()

    def flags(self, block):
        state = self.camp / "state.md"
        text = state.read_text(encoding="utf-8").split("## Session Flags")[0]
        state.write_text(text + "## Session Flags\n" + block, encoding="utf-8")

    def turn(self, *args, crash=None, stdin=None, ok=True):
        env = {**self.env, **({"DNE_CRASH_AT": crash} if crash else {})}
        r = subprocess.run([sys.executable, str(SCRIPTS / "turn.py"), "-c", "oldworld", *args], input=stdin,
                           capture_output=True, encoding="utf-8", env=env, timeout=60)
        if crash:
            self.assertEqual(r.returncode, 77, r.stdout + r.stderr)      # the process died where we asked
            return None
        if ok:
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return json.loads(r.stdout)

    def sent(self):
        if not self.outbox.exists():
            return []
        return [json.loads(l) for l in self.outbox.read_text(encoding="utf-8").splitlines()]

    ROLL = json.dumps([{"actor": "Mira", "action": "roll", "spec": "1d20+5", "dc": 13, "label": "Stealth"}])


class TurnRunnerTests(_Engine):
    def test_off_by_default_creates_nothing_and_changes_no_output(self):
        self.flags("- autorun: false\n")
        self.assertEqual(self.turn("begin", "--text", "hello")["status"], "off")
        self.assertFalse((self.camp / "world.db").exists())
        self.assertFalse((self.camp / ".snapshots").exists())
        (self.rt / ".input_queue").write_text("[Mira]: opens the door", encoding="utf-8")
        out = subprocess.run([sys.executable, str(DISPLAY / "autorun_wait.py")], capture_output=True, encoding="utf-8",
                             env=self.env, timeout=60).stdout
        self.assertNotIn("World engine", out)
        self.assertFalse((self.camp / "world.db").exists())

    def test_a_turn_waits_for_the_players_roll_and_goes_on_from_the_answer(self):
        opened = self.turn("begin", "--text", "[Mira]: I sneak past the guard")
        self.assertEqual(opened["status"], "open")
        waiting = self.turn("resolve", "--intents", self.ROLL)
        self.assertEqual(waiting["status"], "waiting_for_player")
        self.assertEqual(waiting["next_input"]["kind"], "roll")
        self.assertEqual(waiting["next_input"]["expected"], "Mira")
        self.assertEqual(self.sent()[0]["kind"], "question")            # the question goes out before the turn ends
        self.assertIn("roll Stealth", self.sent()[0]["body"])
        blocked = self.turn("finish", "--narration", "She slips by.")
        self.assertFalse(blocked["finished"])                            # an owed roll cannot be narrated over
        done = self.turn("answer", "--request", waiting["next_input"]["request_id"], "--value", "14")
        self.assertEqual(done["results"][0]["data"]["total"], 19)
        self.assertEqual(done["results"][0]["data"]["degree"], "success")
        closed = self.turn("finish", "--narration", "She slips by.")
        self.assertTrue(closed["finished"])
        self.assertEqual(self.turn("status")["status"], "idle")

    def test_the_same_input_twice_is_one_turn_and_one_roll(self):
        self.flags(self.FLAGS.replace("players", "auto"))
        a = self.turn("begin", "--text", "[Mira]: I sneak", "--input-id", "press-1")
        b = self.turn("begin", "--text", "[Mira]: I sneak", "--input-id", "press-1")     # the player pressed send twice
        self.assertEqual(a["turn_id"], b["turn_id"])
        self.assertTrue(b["duplicate"])
        first = self.turn("resolve", "--intents", self.ROLL)
        again = self.turn("resolve", "--intents", self.ROLL)             # the GM ran the same resolve again
        self.assertEqual(first["results"][0]["data"]["dice"], again["results"][0]["data"]["dice"])
        self.assertEqual(len(again["completed"]), 1)                     # still one action, one roll

    def test_a_duplicate_answer_keeps_the_first(self):
        self.turn("begin", "--text", "[Mira]: I sneak")
        req = self.turn("resolve", "--intents", self.ROLL)["next_input"]["request_id"]
        self.turn("answer", "--request", req, "--value", "14")
        late = self.turn("answer", "--request", req, "--value", "20")    # sent again, or arrived late
        self.assertTrue(late["duplicate"])
        self.assertEqual(late["value"], 14)

    def test_the_players_number_arriving_as_the_next_message_answers_the_roll(self):
        self.turn("begin", "--text", "[Mira]: I sneak", "--input-id", "a")
        self.turn("resolve", "--intents", self.ROLL)
        view = self.turn("begin", "--text", "[Mira]: 14", "--input-id", "b")
        self.assertTrue(view["resumed"])
        self.assertEqual(view["answered"][0]["results"][0]["data"]["total"], 19)
        self.assertEqual(view["waiting"], [])

    def test_chat_mode_waits_on_no_background_process(self):
        self.env.pop("DNE_OUTBOX_LOG")                                   # the real path for display: none
        self.turn("begin", "--text", "what time is it?")
        self.turn("resolve", "--intents", '[{"action": "ask"}]')
        started = time.time()
        closed = self.turn("finish", "--narration", "Mid-morning.")
        self.assertTrue(closed["finished"])
        self.assertEqual(closed["sent"][0]["body"], "Mid-morning.")     # handed back for the GM to say in chat
        self.assertLess(time.time() - started, 20)
        self.assertEqual(self.turn("status")["status"], "idle")

    def test_an_out_of_game_question_takes_no_time(self):
        before = (self.camp / "calendar.json").read_text(encoding="utf-8")
        self.turn("begin", "--text", "what time is it?")
        out = self.turn("resolve", "--intents", '[{"action": "ask"}]')
        self.assertEqual(out["elapsed_minutes"], 0)
        self.assertEqual((self.camp / "calendar.json").read_text(encoding="utf-8"), before)

    def test_begin_takes_the_undo_point_and_undo_never_brings_back_an_open_turn(self):
        self.turn("begin", "--text", "[Mira]: first", "--input-id", "1")
        self.turn("finish", "--narration", "Done.")
        self.turn("begin", "--text", "[Mira]: I sneak", "--input-id", "2")
        self.turn("resolve", "--intents", self.ROLL)                     # open turn, open request
        r = subprocess.run([sys.executable, str(SCRIPTS / "turn_snapshot.py"), "-c", "oldworld", "undo", "--no-display"],
                           capture_output=True, encoding="utf-8", env=self.env, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        after = self.turn("status")
        self.assertEqual(after["status"], "idle")
        self.assertEqual(after["waiting"], [])


class RecoveryTests(_Engine):
    FLAGS = _Engine.FLAGS.replace("players", "auto")

    def test_crash_after_the_input_was_stored(self):
        self.turn("begin", "--text", "[Mira]: I sneak", "--input-id", "x", crash="after_input_stored")
        again = self.turn("begin", "--text", "[Mira]: I sneak", "--input-id", "x")
        self.assertTrue(again["duplicate"])                              # not a second turn

    def test_crash_after_the_roll_resumes_with_the_same_roll(self):
        self.turn("begin", "--text", "[Mira]: I sneak")
        self.turn("resolve", "--intents", self.ROLL, crash="after_roll")
        first = self.turn("resume")["results"][0]["data"]["dice"]
        again = self.turn("resolve", "--intents", self.ROLL)["results"][0]["data"]["dice"]
        self.assertEqual(first, again)                                   # one roll, whatever died in between

    def test_crash_after_commit_before_send_delivers_once_on_resume(self):
        self.turn("begin", "--text", "[Mira]: hello")
        self.turn("finish", "--narration", "The gate opens.", crash="after_commit_before_send")
        self.assertEqual(self.sent(), [])
        self.turn("resume")
        self.turn("resume")
        self.assertEqual([m["body"] for m in self.sent()], ["The gate opens."])

    def test_crash_after_send_before_ack_resends_under_the_same_id(self):
        self.turn("begin", "--text", "[Mira]: hello")
        self.turn("finish", "--narration", "The gate opens.", crash="after_send_before_ack")
        self.turn("resume")
        ids = [m["message_id"] for m in self.sent()]
        self.assertTrue(all(i == ids[0] for i in ids))                   # the display drops the repeat by this id

    def test_crash_mid_file_replace_is_finished_by_the_next_reader(self):
        sys.path.insert(0, str(SCRIPTS))
        code = ("import sys, os; sys.path.insert(0, %r); import world_db as w\n"
                "with w.writer('oldworld') as db:\n"
                "    w.stage_writes(db, 'a1', {'notes/a.txt': 'A', 'notes/b.txt': 'B'})\n"
                "w.apply_staged('oldworld')\n") % str(SCRIPTS)
        r = subprocess.run([sys.executable, "-c", code], env={**self.env, "DNE_CRASH_AT": "mid_file_replace"}, timeout=60)
        self.assertEqual(r.returncode, 77)
        self.assertFalse((self.camp / "notes" / "b.txt").exists())       # died with one file of two written
        status = self.turn("status")                                     # any reader finishes the job first
        self.assertEqual((self.camp / "notes" / "a.txt").read_text(encoding="utf-8"), "A")
        self.assertEqual((self.camp / "notes" / "b.txt").read_text(encoding="utf-8"), "B")
        self.assertEqual(status["revision"], 1)


class DisplayPathTests(_Engine):
    def test_the_wait_loop_stores_the_input_and_tells_the_gm_the_turn(self):
        (self.rt / ".input_queue").write_text("[Mira]: opens the door", encoding="utf-8")
        out = subprocess.run([sys.executable, str(DISPLAY / "autorun_wait.py")], capture_output=True, encoding="utf-8",
                             env=self.env, timeout=60).stdout
        self.assertIn("World engine: turn-1 is open", out)
        self.assertEqual(self.turn("status")["turn_id"], "turn-1")

    def test_the_display_shows_a_message_id_once(self):
        sys.path.insert(0, str(DISPLAY))
        saved = {k: os.environ.get(k) for k in ("DNE_CAMPAIGN_ROOT", "DNE_RUNTIME_DIR")}
        os.environ.update(DNE_CAMPAIGN_ROOT=str(self.root), DNE_RUNTIME_DIR=str(self.rt))
        self.addCleanup(lambda: [os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v) for k, v in saved.items()])
        spec = importlib.util.spec_from_file_location("dne_display_dedupe", DISPLAY / "dne-display-app.py")
        app = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(app)
        client = app.app.test_client()
        before = len(app._text_log)
        for _ in range(2):                                               # the outbox resent it after a crash
            self.assertEqual(client.post("/chunk", json={"text": "The gate opens.\n", "message_id": "turn-1-final#0"}).status_code, 204)
        client.post("/chunk", json={"text": "A horn sounds.\n", "message_id": "turn-2-final#0"})
        texts = [e.get("text", "") for e in list(app._text_log)[before:]]
        self.assertEqual(sum("The gate opens." in t for t in texts), 1)
        self.assertEqual(sum("A horn sounds." in t for t in texts), 1)


if __name__ == "__main__":
    unittest.main()
