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

    def test_autorun_wait_flags_a_reply_that_never_reached_the_display(self):
        import http.server
        import threading
        state = {"last_narration_at": None}

        class Doctor(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                body = json.dumps(state).encode()
                self.send_response(200)
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        srv = http.server.HTTPServer(("127.0.0.1", 0), Doctor)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        env = {**os.environ, "DNE_DISPLAY_HOST": f"127.0.0.1:{srv.server_port}"}
        run = lambda: subprocess.run([sys.executable, str(DISPLAY / "autorun_wait.py")], capture_output=True,
                                     encoding="utf-8", env=env, timeout=60).stdout
        queue, delivered = self.rt / ".input_queue", self.rt / ".autorun-delivered"
        queue.write_text("[Mira]: opens the door", encoding="utf-8")
        self.assertIn("[Mira]", run())
        self.assertTrue(delivered.exists())
        out = run()                                   # no narration since: warn and return at once
        self.assertIn("NOT ON THE DISPLAY", out)
        self.assertFalse(delivered.exists())          # warns once only
        queue.write_text("[Mira]: listens", encoding="utf-8")
        run()
        state["last_narration_at"] = 9e12             # the GM narrated
        queue.write_text("[Mira]: steps in", encoding="utf-8")
        self.assertTrue(run().startswith("[Mira]: steps in\n[[GM note"))

    def test_autorun_wait_tells_the_gm_to_come_back_and_to_start_the_watchdog(self):
        env = {**os.environ, "DNE_DISPLAY_HOST": "127.0.0.1:9"}
        run = lambda: subprocess.run([sys.executable, str(DISPLAY / "autorun_wait.py")], capture_output=True,
                                     encoding="utf-8", env=env, timeout=60).stdout
        (self.rt / ".input_queue").write_text("[Mira]: opens the door", encoding="utf-8")
        out = run()
        self.assertIn("autorun_wait.py running again", out)
        self.assertIn("autorun_watchdog.py", out)
        (self.rt / ".autorun-watchdog.json").write_text(json.dumps({"pid": os.getpid(), "since": 9e12}), encoding="utf-8")
        (self.rt / ".input_queue").write_text("[Mira]: listens", encoding="utf-8")
        out = run()
        self.assertIn("autorun_wait.py running again", out)
        self.assertNotIn("autorun_watchdog.py", out)


class WatchdogTests(_Env):
    """Hosts without a Stop hook: a background task that exits (waking the GM) when the game stalls."""

    def setUp(self):
        super().setUp()
        (self.rt / "active-campaign.json").write_text(json.dumps({"name": "eden"}), encoding="utf-8")
        import http.server
        import threading

        class Health(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"ok")

            def log_message(self, *a):
                pass

        srv = http.server.HTTPServer(("127.0.0.1", 0), Health)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        self.env = {**os.environ, "DNE_DISPLAY_HOST": f"127.0.0.1:{srv.server_port}", "DNE_AUTORUN_STALL_S": "1"}

    def start(self):
        p = subprocess.Popen([sys.executable, str(DISPLAY / "autorun_watchdog.py")], stdout=subprocess.PIPE,
                             encoding="utf-8", env=self.env)
        self.addCleanup(p.kill)
        return p

    def test_wakes_the_gm_when_an_action_got_no_wait_loop(self):
        (self.rt / ".autorun-delivered").write_text("1", encoding="utf-8")   # handed out, GM never came back
        out, _ = self.start().communicate(timeout=30)
        self.assertIn("AUTORUN STALLED", out)
        self.assertIn("autorun_wait.py", out)
        self.assertIn("autorun_watchdog.py", out)
        self.assertFalse((self.rt / ".autorun-watchdog.json").exists())

    def test_silent_while_the_gm_listens_or_no_action_waits_and_yields_to_a_newer_one(self):
        import time
        p = self.start()                        # nothing queued, nothing delivered: the GM drives in chat
        time.sleep(2.5)
        self.assertIsNone(p.poll())
        self.write_waiter(os.getpid())          # the wait loop is running
        (self.rt / ".input_queue").write_text("[Mira]: waits", encoding="utf-8")
        time.sleep(2.5)
        self.assertIsNone(p.poll())
        (self.rt / ".autorun-watchdog.json").write_text(json.dumps({"pid": 1, "since": 1}), encoding="utf-8")
        out, _ = p.communicate(timeout=30)      # a newer watchdog registered: leave without waking anyone
        self.assertEqual(out, "")
        self.assertTrue((self.rt / ".autorun-watchdog.json").exists())


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
