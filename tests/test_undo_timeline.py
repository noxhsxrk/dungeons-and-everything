"""PR 1 of the world plan: undo covers companions, old snapshots still open, and nothing from an undone
timeline can change the current one."""
from __future__ import annotations

import importlib.util
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


class _Env(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)
        self.rt = self.root / "rt"
        self.rt.mkdir()
        self.camp = _old_campaign.make(self.root)
        self._saved = {k: os.environ.get(k) for k in ("DNE_CAMPAIGN_ROOT", "DNE_RUNTIME_DIR", "DNE_DISPLAY_HOST")}
        os.environ.update(DNE_CAMPAIGN_ROOT=str(self.root), DNE_RUNTIME_DIR=str(self.rt), DNE_DISPLAY_HOST="127.0.0.1:9")

    def tearDown(self):
        for k, v in self._saved.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        self._tmp.cleanup()

    def snap(self, *args, ok=True):
        r = subprocess.run([sys.executable, str(SCRIPTS / "turn_snapshot.py"), "-c", "oldworld", *args],
                           capture_output=True, encoding="utf-8", timeout=60)
        if ok:
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r

    def meta_path(self, redo=False):
        return sorted((self.camp / (".redo-snapshots" if redo else ".snapshots")).glob("turn_*"))[-1] / "meta.json"

    def epoch(self):
        try:
            return json.loads((self.rt / "timeline.json").read_text(encoding="utf-8"))["epoch"]
        except OSError:
            return 0


class CompanionSnapshotTests(_Env):
    def test_a_companion_made_after_the_snapshot_is_undone_and_redone_with_its_memory(self):
        bren = self.camp / "companions" / "Bren.md"
        self.snap("save", "--label", "before the bridge")
        bren.write_text(bren.read_text(encoding="utf-8") + "- Day 4: they lied to me about the toll.\n", encoding="utf-8")
        (self.camp / "companions" / "Sela.md").write_text("# Sela\n- **Status:** active\n", encoding="utf-8")
        (self.camp / "companions" / "portraits").mkdir()
        (self.camp / "companions" / "portraits" / "sela.txt").write_text("sketch", encoding="utf-8")

        out = self.snap("undo", "--no-display").stdout
        self.assertFalse((self.camp / "companions" / "Sela.md").exists())            # created after: gone
        self.assertFalse((self.camp / "companions" / "portraits" / "sela.txt").exists())
        self.assertNotIn("Day 4", bren.read_text(encoding="utf-8"))                  # the journal a briefing is built from
        self.assertIn("companions/Sela.md", out)
        self.assertIn("Companions (restored with this turn): Bren.md", out)
        self.assertIn("stop each one and start it again from its sheet", out)

        self.snap("redo", "--no-display")
        self.assertTrue((self.camp / "companions" / "Sela.md").exists())
        self.assertEqual((self.camp / "companions" / "portraits" / "sela.txt").read_text(encoding="utf-8"), "sketch")
        self.assertIn("Day 4", bren.read_text(encoding="utf-8"))

    def test_redo_is_refused_when_a_companion_changed_after_the_undo(self):
        self.snap("save")
        (self.camp / "state.md").write_text("changed", encoding="utf-8")
        self.snap("undo", "--no-display")
        (self.camp / "companions" / "Bren.md").write_text("# Bren\nplay continued\n", encoding="utf-8")
        r = self.snap("redo", "--no-display", ok=False)
        self.assertEqual(r.returncode, 1)
        self.assertIn("changed since the undo", r.stderr)

    def test_snapshots_from_before_companions_were_tracked_leave_the_sheets_alone(self):
        for drop in (("tracked", "tracked_dirs", "dirs", "fingerprint_scope"),      # before "tracked" existed
                     ("tracked_dirs", "dirs", "fingerprint_scope")):                 # 1.6.4: tracked, no folders
            with self.subTest(drop=drop):
                self.snap("save")
                meta_path = self.meta_path()
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                for key in drop:
                    meta.pop(key, None)
                meta_path.write_text(json.dumps(meta), encoding="utf-8")
                import shutil
                shutil.rmtree(meta_path.parent / "campaign" / "companions")          # such a snapshot held no sheets
                (self.camp / "companions" / "Sela.md").write_text("# Sela\n", encoding="utf-8")
                (self.camp / "state.md").write_text("later", encoding="utf-8")
                out = self.snap("undo", "--no-display").stdout
                self.assertIn("Find out who is taxing the bridge", (self.camp / "state.md").read_text(encoding="utf-8"))
                self.assertTrue((self.camp / "companions" / "Sela.md").exists())     # the table's sheets are kept
                self.assertTrue((self.camp / "companions" / "Bren.md").exists())
                self.assertTrue((self.camp / "calendar.json").exists() and (self.camp / "factions.json").exists())
                self.assertIn("left as they are: this snapshot predates companion tracking", out)

    def test_a_redo_frame_from_an_older_version_still_compares_like_with_like(self):
        import turn_snapshot
        self.snap("save")
        (self.camp / "state.md").write_text("changed", encoding="utf-8")
        self.snap("undo", "--no-display")
        meta_path = self.meta_path(redo=True)
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta.pop("fingerprint_scope")                                                # made before folders were hashed
        meta["state_after_undo"] = turn_snapshot._fingerprint(self.camp, 1)
        meta_path.write_text(json.dumps(meta), encoding="utf-8")
        self.snap("redo", "--no-display")
        self.assertEqual((self.camp / "state.md").read_text(encoding="utf-8"), "changed")

    def test_the_displays_stats_and_feed_are_restored(self):
        (self.rt / "stats.json").write_text('{"players": [{"name": "Mira", "xp": {"current": 1150}}]}', encoding="utf-8")
        (self.rt / "text_log.json").write_text('[{"text": "before"}]', encoding="utf-8")
        self.snap("save")
        (self.rt / "stats.json").write_text('{"players": [{"name": "Mira", "xp": {"current": 2000}}]}', encoding="utf-8")
        (self.rt / "text_log.json").write_text('[{"text": "before"}, {"text": "the undone turn"}]', encoding="utf-8")
        self.snap("undo", "--no-display")
        self.assertIn("1150", (self.rt / "stats.json").read_text(encoding="utf-8"))
        self.assertNotIn("the undone turn", (self.rt / "text_log.json").read_text(encoding="utf-8"))


class TimelineTests(_Env):
    def test_undo_and_redo_each_start_a_new_timeline_and_drop_queued_input(self):
        self.snap("save")
        (self.camp / "state.md").write_text("changed", encoding="utf-8")
        (self.rt / ".input_queue").write_text("[Mira]: opens the door", encoding="utf-8")
        (self.rt / ".autorun-delivered").write_text("1", encoding="utf-8")
        self.snap("undo", "--dry-run")
        self.assertEqual(self.epoch(), 0)                                            # a preview changes nothing
        self.assertTrue((self.rt / ".input_queue").exists())
        out = self.snap("undo", "--no-display").stdout
        self.assertEqual(self.epoch(), 1)
        self.assertIn("Timeline 1", out)
        self.assertFalse((self.rt / ".input_queue").exists())
        self.assertFalse((self.rt / ".autorun-delivered").exists())
        self.snap("redo", "--no-display")
        self.assertEqual(self.epoch(), 2)                                            # never rewound by a restore


class LateMessageTests(_Env):
    """A message or roll written for turns that were undone must not reach the current story."""

    def setUp(self):
        super().setUp()
        sys.path.insert(0, str(DISPLAY))
        spec = importlib.util.spec_from_file_location("dne_display_timeline", DISPLAY / "dne-display-app.py")
        self.app = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.app)
        self.app.QUEUE_FILE = str(self.rt / ".input_queue")
        self.app.TIMELINE_FILE = str(self.rt / "timeline.json")
        self.app._staged.clear()
        self.client = self.app.app.test_client()

    def rewind(self):
        (self.rt / "timeline.json").write_text(json.dumps({"epoch": self.epoch() + 1}), encoding="utf-8")

    def stage(self, text="opens the door", ready=True):
        with self.app._staged_lock:
            self.app._staged["Mira"] = {"text": text, "ready": ready, "timestamp": 0, "epoch": self.app._timeline_epoch()}

    def test_an_action_staged_before_the_undo_never_reaches_the_gm(self):
        self.stage()
        self.rewind()                                                                # undo ran with --no-display
        self.app._check_auto_trigger()
        self.assertFalse((self.rt / ".input_queue").exists())
        self.assertEqual(self.app._staged, {})
        self.stage("listens at the door")                                            # sent on the new timeline
        self.app._check_auto_trigger()
        self.assertIn("listens at the door", (self.rt / ".input_queue").read_text(encoding="utf-8"))

    def test_a_roll_for_a_request_made_before_the_undo_is_refused(self):
        req = self.client.post("/dice-request", json={"character": "Mira", "spec": "1d20", "label": "Stealth"}).get_json()
        self.rewind()
        late = self.client.post("/player-input/dice", json={"character": "Mira", "spec": "1d20", "request_id": req["request_id"]})
        self.assertEqual(late.status_code, 409)
        self.assertEqual(late.get_json()["error"], "rewound")
        self.assertEqual(self.app._dice_pending, {})
        fresh = self.client.post("/dice-request", json={"character": "Mira", "spec": "1d20"}).get_json()
        ok = self.client.post("/player-input/dice", json={"character": "Mira", "spec": "1d20", "request_id": fresh["request_id"]})
        self.assertEqual(ok.status_code, 200)

    def test_a_page_on_an_old_timeline_is_refused_and_one_that_never_heard_of_timelines_is_not(self):
        self.rewind()
        old = self.client.post("/player-input", json={"character": "Mira", "text": "hi"}, headers={"X-DND-Timeline": "0"})
        self.assertEqual(old.status_code, 409)
        current = self.client.post("/player-input", json={"character": "Mira", "text": "hi"}, headers={"X-DND-Timeline": "1"})
        self.assertEqual(current.status_code, 204)
        unrefreshed = self.client.post("/player-input", json={"character": "Mira", "text": "hi"})
        self.assertEqual(unrefreshed.status_code, 204)

    def test_rollback_clears_what_was_queued_and_announces_the_timeline(self):
        self.stage(ready=False)
        self.client.post("/dice-request", json={"character": "Mira", "spec": "1d20"})
        self.rewind()
        self.assertEqual(self.client.post("/rollback", json={"campaign": "oldworld", "turn": 1}).status_code, 200)
        self.assertEqual(self.app._staged, {})
        self.assertEqual(self.app._dice_pending, {})


if __name__ == "__main__":
    unittest.main()
