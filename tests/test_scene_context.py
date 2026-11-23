"""World plan PR 3: the context a turn starts from. After a compaction the GM still knows who it is
waiting on, a secret told to one player stays with that player, and a Thai nickname finds the same
character as the full name."""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
SCRIPTS = ROOT / "skills" / "dne" / "scripts"
DISPLAY = ROOT / "skills" / "dne" / "display"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(SCRIPTS))
import _old_campaign  # noqa: E402


class SceneContextTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)
        self.rt = self.root / "rt"
        self.rt.mkdir()
        self.camp = _old_campaign.make(self.root)
        state = self.camp / "state.md"
        state.write_text(state.read_text(encoding="utf-8").split("## Session Flags")[0]
                         + "## Session Flags\n- display: none\n- roll_mode: players\n- world_engine: on\n", encoding="utf-8")
        (self.camp / "npcs.md").write_text(
            "# NPCs\n\n| Name | Role | Faction | Location | Attitude | Notes |\n|---|---|---|---|---|---|\n"
            "| Bren | miller | | Millbridge | friendly | |\n| Rina Saelim | inventor | | school | friendly | |\n", encoding="utf-8")
        (self.camp / "npcs-full.md").write_text(
            "# NPCs\n\n## Bren\n- **Aliases:** เบรน, the miller\n- **HP:** 9 | **AC:** 11\n\n"
            "## Rina Saelim\n- **Aliases:** รินะ, Rina\n- **HP:** 12 | **AC:** 12\n", encoding="utf-8")
        (self.camp / "characters" / "theo.md").write_text("# Theo\n- **Level:** 3\n", encoding="utf-8")
        (self.rt / ".campaign").write_text("oldworld", encoding="utf-8")
        self._saved = {k: os.environ.get(k) for k in ("DNE_CAMPAIGN_ROOT", "DNE_RUNTIME_DIR", "DNE_OUTBOX_LOG", "DNE_NOTE_BUDGET")}
        os.environ.update(DNE_CAMPAIGN_ROOT=str(self.root), DNE_RUNTIME_DIR=str(self.rt), DNE_OUTBOX_LOG=str(self.root / "out.jsonl"))
        os.environ.pop("DNE_NOTE_BUDGET", None)
        import scene_context
        import turn
        self.sc, self.turn = scene_context, turn

    def tearDown(self):
        for k, v in self._saved.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        self._tmp.cleanup()

    def feed(self, *entries):
        (self.rt / "text_log.json").write_text(json.dumps(list(entries), ensure_ascii=False), encoding="utf-8")

    def test_a_fresh_process_still_knows_who_the_turn_waits_on(self):
        self.turn.begin("oldworld", "[Mira]: I sneak past the guard")
        self.turn.resolve("oldworld", [{"actor": "Mira", "action": "roll", "spec": "1d20+5", "dc": 13, "label": "Stealth"}])
        out = subprocess.run([sys.executable, str(SCRIPTS / "scene_context.py"), "-c", "oldworld"],   # e.g. after a compaction
                             capture_output=True, encoding="utf-8", env=dict(os.environ), timeout=60).stdout
        self.assertIn("STILL WAITING: Mira: roll Stealth", out)
        self.assertIn("from Mira", out)

    def test_a_secret_told_to_one_player_stays_with_that_player(self):
        self.feed({"text": "The bridge is closed."},
                  {"text": "The clerk slips you a key.", "whisper": True, "whisper_to": ["Mira"]})
        mira = " ".join(self.sc.build("oldworld", audience="player:Mira")["recent"])
        theo = " ".join(self.sc.build("oldworld", audience="player:Theo")["recent"])
        bren = " ".join(self.sc.build("oldworld", audience="companion:Bren")["recent"])
        gm = " ".join(self.sc.build("oldworld", audience="dm")["recent"])
        self.assertIn("[told only to you] The clerk slips you a key.", mira)
        self.assertIn("The bridge is closed.", theo)
        self.assertNotIn("key", theo)                                    # not shortened, not hinted at: absent
        self.assertNotIn("key", bren)
        self.assertIn("[whisper to Mira]", gm)
        self.assertEqual(self.sc.build("oldworld", audience="player:Theo")["lore"], "")   # lore and graph are the GM's

    def test_a_thai_nickname_finds_the_same_character_as_the_full_name(self):
        by_nickname = self.sc.mentioned("oldworld", "ผมเดินไปหารินะที่ห้องชมรม")
        by_name = self.sc.mentioned("oldworld", "I look for Rina Saelim")
        self.assertEqual([e["id"] for e in by_nickname], ["npc:Rina Saelim"])
        self.assertEqual([e["id"] for e in by_nickname], [e["id"] for e in by_name])
        self.assertEqual(by_nickname[0]["source"], "npcs-full.md")       # points back at the record

    def test_him_again_means_the_one_just_named_and_asks_when_it_is_not_clear(self):
        self.turn.begin("oldworld", "[Mira]: I ask Bren about the toll")
        self.turn.finish("oldworld", "Bren shrugs.")
        view = self.turn.begin("oldworld", "[Mira]: ถามเขาอีกทีว่าใครเก็บค่าผ่านทาง")
        self.assertEqual(view["context"]["reference"]["means"], "Bren")
        self.turn.finish("oldworld", "Bren and Rina Saelim both look away.")
        unclear = self.turn.begin("oldworld", "[Mira]: I grab him by the collar")["context"]
        self.assertIn("Bren", unclear["reference"]["ask"])
        self.assertIn("Rina Saelim", unclear["reference"]["ask"])
        self.assertTrue(any("UNCLEAR WHO IS MEANT" in line for line in self.sc.render(unclear)))
        named = self.sc.build("oldworld", "[Mira]: I grab Bren by the collar")
        self.assertIsNone(named["reference"])                            # a name needs no guessing

    def test_the_scene_action_sets_where_and_who(self):
        self.turn.begin("oldworld", "[Mira]: we enter the market")
        self.turn.resolve("oldworld", [{"action": "scene", "place": "Millbridge market", "present": ["Bren"]}])
        view = self.sc.build("oldworld")
        self.assertEqual((view["place"], view["present"]), ("Millbridge market", ["Bren"]))
        self.assertIn("Scene: Millbridge market. Present: Bren.", self.sc.render(view))

    def test_what_binds_is_never_cut_for_space(self):
        (self.camp / "tracker.json").write_text(json.dumps(
            {"mira": {"name": "Mira", "conditions": ["poisoned"], "effects": [{"name": "Bless"}], "concentration": None}}),
            encoding="utf-8")
        self.feed(*[{"text": f"Event number {i} " + "x" * 150} for i in range(6)])
        self.turn.begin("oldworld", "[Mira]: I sneak")
        self.turn.resolve("oldworld", [{"actor": "Mira", "action": "roll", "spec": "1d20+5", "label": "Stealth"}])
        view = self.sc.build("oldworld", "Bren", budget=200)
        self.assertTrue(view["pending"])
        self.assertEqual(view["conditions"], ["Mira: poisoned, Bless"])
        self.assertIn("recent", view["cut"])

    def test_the_gm_note_keeps_what_is_due_under_a_small_budget(self):
        import gm_guide
        os.environ["DNE_NOTE_BUDGET"] = "300"
        self.turn.begin("oldworld", "[Mira]: I sneak", input_id="a")
        self.turn.resolve("oldworld", [{"actor": "Mira", "action": "roll", "spec": "1d20+5", "label": "Stealth"}])
        view = self.turn.begin("oldworld", "[Theo]: I wait", input_id="b")
        lines = gm_guide.turn_notes("oldworld", count=False, text="[Theo]: I wait", turn=view)
        joined = "\n".join(lines)
        self.assertIn("STILL WAITING: Mira: roll Stealth", joined)       # due: stays
        self.assertNotIn("Fights and rests run on the engine", joined)  # a standing rule: gone at this size
        self.assertRegex(joined, r"\(\d+ lower-priority lines? left out for length\.\)")
        self.assertLess(joined.index("STILL WAITING"), len(joined) // 2)


if __name__ == "__main__":
    unittest.main()
