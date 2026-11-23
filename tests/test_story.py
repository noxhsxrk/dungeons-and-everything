"""Storytelling tools: a guard against the GM's own habits, sparks the GM may drop, pacing, NPCs who
want something, and the engine's flashback, bargain, place rule and clock. Plus what the display
gained for them: handout cards, a voice per NPC, progress clocks."""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _engine_case import DISPLAY, ROOT, EngineCase  # noqa: E402


class StoryTests(EngineCase):
    FLAGS = "- display: none\n- roll_mode: players\n"          # an ordinary campaign: no world engine

    def setUp(self):
        super().setUp()
        import gm_guide
        import story
        self.story, self.guide = story, gm_guide
        (self.camp / "npcs-full.md").write_text(
            "# NPCs\n\n## Bren\n- **Aliases:** เบรน, the miller\n- **Voice:** Fenrir | gruff, says \"mark me\"\n- **HP:** 9 | **AC:** 11\n"
            "- **Demeanor:** tired | **Motivation:** keep his daughter safe | **Secret:** owes the Tollmen\n"
            "- **Current goal:** get home before dark\n", encoding="utf-8")

    def feed(self, *texts):
        (self.rt / "text_log.json").write_text(json.dumps(
            [{"text": t, "_camp": "oldworld"} for t in texts], ensure_ascii=False), encoding="utf-8")

    def note(self, text="[Mira]: I look around", count=True):
        return "\n".join(self.guide.turn_notes("oldworld", count=count, text=text))

    # ── style guard ───────────────────────────────────────────────────────

    def test_it_notices_feelings_told_and_a_turn_that_ends_by_asking(self):
        self.feed("The cart rolls in from the east road, loaded high.",
                  "Your sister's shoes are by the door. Your heart pounds; hope you thought was dead flares up. "
                  "Will you push the door open or not? What do you do?")
        notes = " | ".join(self.story.guard("oldworld"))
        self.assertIn("told the player what their character feels", notes)
        self.assertIn("ended by asking what they do", notes)
        self.flags(self.FLAGS + "- turn_end: options\n")                 # a table that asked for options is left alone
        self.assertNotIn("ended by asking", " | ".join(self.story.guard("oldworld")))

    def test_it_leaves_a_plain_ending_alone(self):
        self.feed("The cart rolls in from the east road, loaded high.",
                  "Your sister's shoes are by the door. The left one still has the red lace.\nInside, someone is chopping spring onions.")
        self.assertEqual(self.story.guard("oldworld"), [])

    def test_repeated_openings_and_phrases_in_thai_and_english(self):
        self.feed("กลิ่นโอโซนลอยอบอวลไปทั่วห้อง ดวงตาของเธอหรี่ลงอย่างช้าๆ เมื่อมองมาที่คุณ ยานลำเลียงหุ้มเกราะจอดอยู่ด้านนอก",
                  "กลิ่นเลือดเก่าโชยมาจากห้องใต้ดิน ดวงตาของเธอหรี่ลงอย่างช้าๆ ก่อนจะหันหนี ยานลำเลียงหุ้มเกราะติดเครื่อง",
                  "กลิ่นฝนลอยเข้ามาทางหน้าต่าง ดวงตาของเธอหรี่ลงอย่างช้าๆ อีกครั้ง ยานลำเลียงหุ้มเกราะเคลื่อนออกไป",
                  "ดวงตาของเธอหรี่ลงอย่างช้าๆ ขณะที่ยานลำเลียงหุ้มเกราะหายไปในหมอก",
                  "The smell of old blood hangs here. Silence settles over the room like dust.")
        (self.rt / "text_log.json").write_text(json.dumps(
            json.loads((self.rt / "text_log.json").read_text(encoding="utf-8"))
            + [{"player": "Mira", "text": "Mira: ผมวิ่งตามยานลำเลียงหุ้มเกราะไป"}], ensure_ascii=False), encoding="utf-8")
        notes = " | ".join(self.story.guard("oldworld"))
        self.assertIn("opened with a smell", notes)
        self.assertIn("wording that came back in 4 or more", notes)
        self.assertIn("ดวงตาของเธอหรี่ลงอย่างช้าๆ", notes)                 # the whole habit, not a fragment of it
        self.assertNotIn("ยานลำเลียง", notes)                            # what the players are chasing is the scene, not a tic

    def test_the_worlds_own_banned_phrases(self):
        (self.camp / "worldkit.json").write_text(json.dumps({"narrative_dna": {"taboo_cliches": ["smell of ozone"]}}), encoding="utf-8")
        self.feed("The door opens on the workshop.", "A smell of ozone fills the lab as the relay clicks.")
        self.assertIn("\"smell of ozone\"", " | ".join(self.story.guard("oldworld")))

    def test_the_note_carries_the_style_warning_and_can_be_switched_off(self):
        self.feed("Rain drums on the roof of the mill.", "You feel a chill of fear. What do you do?")
        self.assertIn("STYLE: ", self.note())
        self.flags(self.FLAGS + "- style_guard: off\n")
        self.assertNotIn("STYLE: ", self.note())

    # ── NPC wants, sparks, pacing ─────────────────────────────────────────

    def test_an_npc_named_in_the_input_brings_what_they_want(self):
        note = self.note("[Mira]: ผมถามเบรนว่าเมื่อคืนใครข้ามสะพาน")
        self.assertIn("Bren is in this (goal: get home before dark; drive: keep his daughter safe)", note)
        self.assertIn("what does Bren want from the person in front of them right now", note)
        self.assertNotIn("Bren is in this", self.note("[Mira]: I look at the river"))

    def test_a_spark_comes_now_and_then_and_may_be_dropped(self):
        notes = [self.note() for _ in range(12)]
        sparks = [n for n in notes if "SPARK (an offer, not an order)" in n]
        self.assertGreaterEqual(len(sparks), 2)
        self.assertLessEqual(len(sparks), 3)                              # not every turn
        self.assertIn("drop this and follow that", sparks[0])
        self.assertEqual(self.story.spark("oldworld", 7), self.story.spark("oldworld", 7))   # reproducible
        self.flags(self.FLAGS + "- sparks: off\n")
        self.assertFalse(any("SPARK" in self.note() for _ in range(8)))

    def test_the_display_tools_come_round_with_their_exact_commands(self):
        self.flags(self.FLAGS.replace("display: none", "display: local") + "- sparks: off\n")
        notes = [self.note() for _ in range(20)]
        tips = [line for n in notes for line in n.splitlines() if line.startswith("TABLE TOOL: ")]
        self.assertEqual(len(tips), 5)                                    # one in four turns
        joined = " ".join(tips)
        for needle in ("--tone tension|combat", "--handout letter|news", "--clock ", "--to \"<PC>\"", "campfire"):
            self.assertIn(needle, joined)
        self.assertIn(str(DISPLAY / "send.py"), joined)                   # a real path, not a placeholder
        self.flags(self.FLAGS + "- sparks: off\n")                        # no display: nothing to show them on
        self.assertFalse(any("TABLE TOOL" in self.note() for _ in range(8)))

    def test_previewing_the_note_does_not_use_up_a_spark(self):
        before = self.story.load("oldworld")
        self.note(count=False)
        self.assertEqual(self.story.load("oldworld"), before)

    def test_three_scenes_of_one_tone_ask_for_another(self):
        self.flags(self.FLAGS + "- sparks: off\n")
        for tone in ("tension", "tension"):
            self.story.note_tone("oldworld", tone)
        self.assertNotIn("PACING", self.note())
        self.story.note_tone("oldworld", "tension")
        self.assertIn("PACING: the last three scenes were all tension. Make the next one relief or humour", self.note())

    def test_the_storyteller_and_a_campfire_question(self):
        self.flags(self.FLAGS + "- storyteller: noir\n- sparks: off\n")
        self.assertIn("This table's storyteller: Noir mystery", self.note())
        (self.camp / "characters" / "mira.md").write_text(
            "# Mira\n- **Class:** Medic\n\n## Bonds\n- I promised the miller's daughter I would come back.\n", encoding="utf-8")
        import random
        asked = self.story.campfire("oldworld", random.Random(1))
        self.assertIn("Mira", asked)
        self.assertIn("I promised the miller's daughter I would come back.", asked)

    # ── the display ───────────────────────────────────────────────────────

    def app(self):
        sys.path.insert(0, str(DISPLAY))
        spec = importlib.util.spec_from_file_location("dne_display_story", DISPLAY / "dne-display-app.py")
        app = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(app)
        app.CLOCKS_FILE = str(self.rt / "clocks.json")
        return app

    def test_a_handout_keeps_its_kind_and_a_line_keeps_its_voice(self):
        app = self.app()
        client, before = app.app.test_client(), len(app._text_log)
        client.post("/chunk", json={"text": "Meet me at the ford. Burn this.\n", "handout": {"type": "letter", "title": "Unsigned"}})
        client.post("/chunk", json={"text": "Not a real kind.\n", "handout": {"type": "hologram"}})
        client.post("/chunk", json={"text": "Mark me, the bridge is shut.\n", "npc": "Bren", "voice": "Fenrir"})
        client.post("/chunk", json={"text": "Hm.\n", "npc": "Bren", "voice": "NotAVoice"})
        new = list(app._text_log)[before:]
        self.assertEqual(new[0]["handout"], {"type": "letter", "title": "Unsigned"})
        self.assertNotIn("handout", new[1])                               # an unknown kind is plain narration
        if app._tts is not None:
            self.assertEqual(new[2].get("voice"), "Fenrir")
        self.assertNotIn("voice", new[3])

    def test_send_py_finds_the_voice_on_the_npcs_record(self):
        sys.path.insert(0, str(DISPLAY))
        spec = importlib.util.spec_from_file_location("dne_send_voice", DISPLAY / "send.py")
        send = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(send)
        (self.rt / ".campaign").write_text("oldworld", encoding="utf-8")
        self.assertEqual(send._npc_voice("the miller"), "Fenrir")         # by alias
        self.assertEqual(send._npc_voice("Nobody"), "")

    def test_progress_clocks_are_set_ticked_and_removed(self):
        app = self.app()
        client = app.app.test_client()
        client.post("/clocks", json={"set": {"name": "The alarm", "filled": 3, "size": 6}})
        client.post("/clocks", json={"set": {"name": "Trust", "filled": 9, "size": 4}})
        self.assertEqual(client.get("/clocks").get_json(), [{"name": "The alarm", "size": 6, "filled": 3},
                                                             {"name": "Trust", "size": 4, "filled": 4}])   # clamped to its size
        client.post("/clocks", json={"set": {"name": "The alarm", "filled": 4, "size": 6}})
        client.post("/clocks", json={"remove": "Trust"})
        self.assertEqual(client.get("/clocks").get_json(), [{"name": "The alarm", "size": 6, "filled": 4}])

    def test_the_page_renders_handouts_and_clocks(self):
        html = (ROOT / "skills" / "dne" / "display" / "templates" / "index.html").read_text(encoding="utf-8")
        for needle in ("function renderHandoutBlock", "function renderClocks", 'id="clocks"', ".handout.terminal",
                       "payload.handout", "item.handout", "blockEl.dataset.voice"):
            self.assertIn(needle, html)


class StoryEngineTests(EngineCase):
    FLAGS = EngineCase.FLAGS.replace("roll_mode: auto", "roll_mode: players")

    def test_a_flashback_is_told_when_it_is_needed(self):
        asked = self.do("[Mira]: actually, last night I swapped the cellar key",
                        {"actor": "Mira", "action": "flashback", "claim": "I swapped the cellar key with the gardener's.",
                         "cost": "a Hero Point", "roll": {"spec": "1d20+4", "dc": 13, "label": "Sleight of Hand"}})
        self.assertEqual(asked["next_input"]["expected"], "Mira")
        done = self.data(self.turn.answer("oldworld", asked["next_input"]["request_id"], 12))
        self.assertTrue(done["worked"])
        self.assertEqual(done["cost"], "a Hero Point")
        self.turn.finish("oldworld", "The key turns.")
        asked = self.do("[Mira]: and I bribed the cook", {"actor": "Mira", "action": "flashback", "claim": "I bribed the cook.",
                                                          "roll": {"spec": "1d20+4", "dc": 13}})
        failed = self.data(self.turn.answer("oldworld", asked["next_input"]["request_id"], 3))
        self.assertFalse(failed["worked"])
        self.assertIn("let that be the new problem", failed["note"])

    def test_a_bargain_is_offered_before_the_roll_and_its_price_is_certain(self):
        offer = {"actor": "Mira", "action": "bargain", "offer": "the guard will remember your face",
                 "roll": {"spec": "1d20+5", "dc": 15, "label": "Deception"}}
        asked = self.do("[Mira]: I lie to the guard", offer)
        self.assertEqual(asked["next_input"]["kind"], "decision")         # the choice comes first
        self.assertIn("the guard will remember your face", asked["next_input"]["question"])
        rolling = self.turn.answer("oldworld", asked["next_input"]["request_id"], "accept")
        self.assertIn("Roll twice and send the higher", rolling["next_input"]["question"])
        done = self.data(self.turn.answer("oldworld", rolling["next_input"]["request_id"], 17))
        self.assertTrue(done["accepted"] and done["passed"] and done["advantage"])
        self.assertEqual(done["price"], "the guard will remember your face")         # paid even on a success
        self.turn.finish("oldworld", "He waves you through, and looks twice.")
        asked = self.do("[Mira]: again, another guard", offer)
        plain = self.turn.answer("oldworld", asked["next_input"]["request_id"], "refuse")
        self.assertNotIn("Roll twice", plain["next_input"]["question"])
        self.assertIsNone(self.data(self.turn.answer("oldworld", plain["next_input"]["request_id"], 17))["price"])

    def test_a_place_keeps_its_strange_rule_and_every_ruling(self):
        self.do("the storeroom", {"action": "scene", "place": "the storeroom", "present": []},
                {"action": "place_rule", "place": "the storeroom",
                 "rule": "Every object returns to where it was one minute ago; people stay.",
                 "scope": "inside the door frame", "shown_by": "the maid sets a cup down; a minute later it is in her hand"},
                {"action": "place_rule", "place": "the storeroom", "ruling": "Held in a hand counts as that hand's place."})
        import gm_guide
        note = "\n".join(gm_guide.turn_notes("oldworld", count=False, text="[Theo]: I put the key in Mira's hand and wait"))
        self.assertIn("THIS PLACE HAS A RULE: Every object returns to where it was one minute ago", note)
        self.assertIn("Rulings so far: Held in a hand counts as that hand's place.", note)
        self.do("somewhere else", {"action": "scene", "place": "the yard", "present": []})
        self.assertNotIn("THIS PLACE HAS A RULE", "\n".join(gm_guide.turn_notes("oldworld", count=False, text="[Theo]: I wait")))

    def test_a_clock_fills_and_says_so(self):
        self.do("the alarm", {"action": "clock", "name": "The alarm", "size": 4, "filled": 2})
        out = self.do("a door slams", {"action": "clock", "name": "The alarm", "tick": 1, "why": "a door slammed"})
        self.assertFalse(self.data(out)["full"])
        out = self.do("a shout", {"action": "clock", "name": "The alarm", "tick": 3})
        self.assertTrue(self.data(out)["full"])
        self.assertEqual(self.data(out)["filled"], 4)                     # never past its size
        self.assertIn("it is full", out["visible_events"][0]["text"])
        import story
        self.assertEqual(story.clocks("oldworld"), [{"name": "The alarm", "filled": 4, "size": 4}])


if __name__ == "__main__":
    unittest.main()
