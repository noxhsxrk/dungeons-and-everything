"""World plan section 6, the Replay and Integration tiers. A recorded log played into a copy of the
starting save gives the same game state with no model and no real messages; the chat entry and the
display's entry lead to the same time, resources and messages."""
from __future__ import annotations

import json
import pathlib
import shutil
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _engine_case import EngineCase  # noqa: E402

SHEET = "# Mira\n- **Class:** Medic | **Level:** 3\n- **XP:** 1150 / 2700\n- **HP:** 9 / 20\n- **Hit Dice:** 3d8 (remaining: 3)\n\n## Equipment & Inventory\n**Currency:** 3 gp\n"


class ReplayTests(EngineCase):
    def setUp(self):
        super().setUp()
        (self.camp / "characters" / "mira.md").write_text(SHEET, encoding="utf-8")
        import world_migrate
        world_migrate.set_flag("oldworld", "survival", "on")
        with self.wdb.writer("oldworld"):                              # the store exists (with its seed) before the copy
            pass
        shutil.copytree(self.camp, self.root / "campaigns" / "copy")   # the snapshot a replay starts from

    def play(self):
        self.do("setup", {"action": "market", "at": "Market", "stock": {"flour": 4}, "base": {"flour": 5}, "target": {"flour": 20},
                          "cash": 100, "eats": {"flour": 1}},
                {"action": "upkeep", "stores": {"food": 30}, "per_day": {"food": 2}},
                {"action": "schedule", "in_minutes": 300, "text": "a rider waves you down", "event_id": "rider", "interrupt": True})
        self.turn.finish("oldworld", "Ready.")
        out = self.do("[Mira]: we go to market", {"action": "travel", "to": "Market"})
        self.turn.answer("oldworld", out["next_input"]["request_id"], "continue")
        self.turn.finish("oldworld", "You arrive.")
        self.do("[Mira]: flour, a roll and a night's sleep",
                {"actor": "Mira", "action": "buy", "item": "flour", "qty": 2, "at": "Market"},
                {"actor": "Mira", "action": "roll", "spec": "1d20+5", "dc": 13, "label": "Haggle"},
                {"action": "rest", "type": "long", "resting": ["Mira"]})
        self.turn.finish("oldworld", "Morning.")
        self.do("a week goes by", {"action": "wait", "days": 8})

    def test_a_recorded_log_replays_to_the_same_state(self):
        self.play()
        log = json.loads(json.dumps(self.turn.export_log("oldworld")))   # as it would come back from a file
        self.assertEqual(len(log), 4)
        self.assertEqual(log[1]["answers"][0]["value"], "continue")
        self.assertNotIn("dice", json.dumps(log))                        # no results in the log: they are reproduced
        sent_before = (self.root / "out.jsonl").read_text(encoding="utf-8")
        out = self.turn.replay("copy", log)
        self.assertEqual(out["state_hash"], self.wdb.state_hash("oldworld"))
        self.assertEqual((self.root / "campaigns" / "copy" / "characters" / "mira.md").read_bytes(),
                         (self.camp / "characters" / "mira.md").read_bytes())
        self.assertEqual(self.thing("market", "market", "copy"), self.thing("market", "market"))
        with self.wdb.reader("copy") as a, self.wdb.reader("oldworld") as b:
            rolls = lambda db: [tuple(r) for r in db.execute("SELECT action_id, key, result FROM rolls ORDER BY action_id, key")]  # noqa: E731
            self.assertEqual(rolls(a), rolls(b))                         # the same dice, never rolled by a model
        self.assertTrue(sent_before)                                     # (the original did talk to its table)

    def test_chat_and_display_entries_agree(self):
        shutil.copytree(self.camp, self.root / "campaigns" / "viadisplay")
        intents = [{"action": "wait", "hours": 3}, {"actor": "Mira", "action": "roll", "spec": "1d20+5", "dc": 13}]
        self.turn.begin("oldworld", "[Mira]: we wait, then I listen at the door")          # typed in chat
        chat = self.turn.resolve("oldworld", intents)
        queue = self.rt / ".input_queue"
        queue.write_text("[Mira]: we wait, then I listen at the door", encoding="utf-8")    # sent from a phone
        self.turn.receive("viadisplay", queue.read_text(encoding="utf-8"), str(queue))
        shown = self.turn.resolve("viadisplay", intents)
        self.assertEqual(chat["elapsed_minutes"], shown["elapsed_minutes"])
        self.assertEqual(self.read_json("calendar.json"),
                         json.loads((self.root / "campaigns" / "viadisplay" / "calendar.json").read_text(encoding="utf-8")))
        self.assertEqual(chat["results"][1]["data"], shown["results"][1]["data"])           # the same roll either way
        self.assertEqual(self.wdb.state_hash("oldworld", ("events", "things", "rolls")),
                         self.wdb.state_hash("viadisplay", ("events", "things", "rolls")))


if __name__ == "__main__":
    unittest.main()
