"""Autorun must not stall: the wait loop announces itself, the Stop hook blocks a turn
that ends without it, and the display's Status panel explains and retries."""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "skills" / "dne" / "scripts"
DISPLAY = ROOT / "skills" / "dne" / "display"
sys.path.insert(0, str(SCRIPTS))


class _Env(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)
        self.rt = self.root / "rt"
        self.rt.mkdir()
        camp = self.root / "campaigns" / "eden"
        camp.mkdir(parents=True)
        (camp / "state.md").write_text("# Campaign: eden\n## Session Flags\n- autorun: true\n- autorun_interval: 60\n",
                                       encoding="utf-8")
        (self.rt / ".campaign").write_text("eden", encoding="utf-8")
        self._saved = {k: os.environ.get(k) for k in ("DNE_CAMPAIGN_ROOT", "DNE_RUNTIME_DIR")}
        os.environ["DNE_CAMPAIGN_ROOT"] = str(self.root)
        os.environ["DNE_RUNTIME_DIR"] = str(self.rt)

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self._tmp.cleanup()

    def write_waiter(self, pid, since=None):
        import time
        (self.rt / ".autorun-waiter.json").write_text(
            json.dumps({"pid": pid, "since": since or time.time(), "session": "x"}), encoding="utf-8")


class WaiterTests(_Env):
    def test_live_dead_and_stale_waiters(self):
        import paths
        self.assertIsNone(paths.autorun_waiter())
        self.write_waiter(os.getpid())
        self.assertIsNotNone(paths.autorun_waiter())
        self.write_waiter(os.getpid(), since=1)                    # older than 4 hours
        self.assertIsNone(paths.autorun_waiter())
        if os.name != "nt":
            dead = subprocess.Popen([sys.executable, "-c", "pass"]); dead.wait()
            self.write_waiter(dead.pid)
            self.assertIsNone(paths.autorun_waiter())

    def test_autorun_wait_registers_and_cleans_up(self):
        (self.rt / ".input_queue").write_text("[Mira]: opens the door", encoding="utf-8")
        r = subprocess.run([sys.executable, str(DISPLAY / "autorun_wait.py")], capture_output=True,
                           encoding="utf-8", env={**os.environ, "DNE_DISPLAY_HOST": "127.0.0.1:9"}, timeout=60)
        self.assertIn("[Mira]: opens the door", r.stdout)
        self.assertFalse((self.rt / ".autorun-waiter.json").exists())


class StopHookTests(_Env):
    def setUp(self):
        super().setUp()
        spec = importlib.util.spec_from_file_location("ac_never_stop", SCRIPTS / "autosave_checkpoint.py")
        self.ac = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.ac)

    def test_blocks_when_autorun_has_no_waiter(self):
        with mock.patch.object(self.ac, "display_up", return_value=True):
            reason = self.ac.autorun_stall_reason({}, "eden", wait_s=0)
        self.assertIn("autorun_wait.py", reason)
        self.assertIn("--tutor", reason)

    def test_no_block_with_a_waiter_or_display_down_or_second_stop(self):
        self.write_waiter(os.getpid())
        with mock.patch.object(self.ac, "display_up", return_value=True):
            self.assertIsNone(self.ac.autorun_stall_reason({}, "eden", wait_s=0))
        (self.rt / ".autorun-waiter.json").unlink()
        with mock.patch.object(self.ac, "display_up", return_value=False):
            self.assertIsNone(self.ac.autorun_stall_reason({}, "eden", wait_s=0))
        with mock.patch.object(self.ac, "display_up", return_value=True):
            self.assertIsNone(self.ac.autorun_stall_reason({"stop_hook_active": True}, "eden", wait_s=0))

    def test_autorun_off_never_blocks(self):
        (self.root / "campaigns" / "eden" / "state.md").write_text("## Session Flags\n- autorun: false\n", encoding="utf-8")
        with mock.patch.object(self.ac, "display_up", return_value=True):
            self.assertIsNone(self.ac.autorun_stall_reason({}, "eden", wait_s=0))


class DoctorEndpointTests(_Env):
    def setUp(self):
        super().setUp()
        sys.path.insert(0, str(DISPLAY))
        spec = importlib.util.spec_from_file_location("dne_display_doctor", DISPLAY / "dne-display-app.py")
        self.app = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.app)
        self.app.CAMP_FILE = str(self.rt / ".campaign")
        self.app.QUEUE_FILE = str(self.rt / ".input_queue")
        self.client = self.app.app.test_client()

    def checks(self, j):
        return {c["id"]: c for c in j["checks"]}

    def test_reports_gm_not_listening_and_resends(self):
        with self.app._staged_lock:
            self.app._staged["Mira"] = {"text": "opens the door", "ready": False, "timestamp": 0}
        j = self.client.get("/doctor").get_json()
        self.assertEqual(j["campaign"], "eden")
        self.assertTrue(j["autorun"])
        self.assertFalse(self.checks(j)["gm"]["ok"])
        self.assertIn("continue autorun", self.checks(j)["gm"]["hint"])
        r = self.client.post("/doctor/retry").get_json()
        self.assertEqual(r["resent"], 1)
        self.assertIn("[Mira]: opens the door", (self.rt / ".input_queue").read_text(encoding="utf-8"))
        self.assertTrue(r["queue_pending"])

    def test_listening_when_waiter_alive(self):
        self.write_waiter(os.getpid())
        j = self.client.get("/doctor").get_json()
        self.assertTrue(j["gm_listening"])
        self.assertTrue(self.checks(j)["gm"]["ok"])
