#!/usr/bin/env python3
"""Pure-python autorun wait — TCC-safe replacement for autorun-wait.sh.

macOS TCC blocks shell-level file creation in ~/Documents, but python file
writes are permitted. autorun-wait.sh fails on its `echo > .autorun-session`
redirect; this script does the identical job (session-invalidation, countdown
broadcast, input-queue poll, /queue/consumed POST) using python I/O only.

Prints the queued player action(s) to stdout, or nothing on timeout (9 min).
"""
import os
import sys
import ssl
import time
import json
import secrets
import subprocess
import urllib.request
_DISPLAY_HOST = os.environ.get("DNE_DISPLAY_HOST", "localhost:5001")  # tests point this away from a live display
if hasattr(sys.stdout, "reconfigure"):   # player actions come in any script; a cp1252 console would refuse them
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DISPLAY_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(DISPLAY_DIR, "..", "scripts"))
PUSH = os.path.join(DISPLAY_DIR, "push_stats.py")

try:
    from paths import runtime_dir, find_campaign
    RT = str(runtime_dir())
except Exception:
    RT = os.path.join(os.environ.get("DNE_CAMPAIGN_ROOT", os.path.expanduser("~/.dne")), ".runtime")
os.makedirs(RT, exist_ok=True)

QFILE = os.path.join(RT, ".input_queue")
SESSION_FILE = os.path.join(RT, ".autorun-session")

# Invalidate any previous wait loop by writing a new session id (python write — TCC-ok)
my_session = secrets.token_hex(8)
with open(SESSION_FILE, "w", encoding="utf-8") as f:
    f.write(my_session)

SCHEME_FILE = os.path.join(DISPLAY_DIR, ".scheme")
SCHEME = open(SCHEME_FILE, encoding="utf-8").read().strip() if os.path.exists(SCHEME_FILE) else "http"
CTX = None
if SCHEME == "https":
    CTX = ssl.create_default_context()
    CTX.check_hostname = False
    CTX.verify_mode = ssl.CERT_NONE

# Backstop: the actions handed out last time got no narration on the display (the GM answered
# only in its chat). Say so at once, once, instead of waiting for the next action.
DELIVERED_FILE = os.path.join(RT, ".autorun-delivered")
try:
    delivered = float(open(DELIVERED_FILE, encoding="utf-8").read())
    os.unlink(DELIVERED_FILE)
    with urllib.request.urlopen(f"{SCHEME}://{_DISPLAY_HOST}/doctor", timeout=2, context=CTX) as r:
        doc = json.load(r)
    missed = "last_narration_at" in doc and (doc["last_narration_at"] or 0) < delivered  # older servers lack it
except Exception:
    missed = False
if missed:
    sys.stdout.write("NOT ON THE DISPLAY: your reply to the last player actions never reached the display "
                     "(no send.py since they arrived), so the players have not seen it. Send that narration "
                     "now with send.py, then run autorun_wait.py again. No new player actions yet.\n")
    sys.exit(0)

# Resolve autorun interval from the active campaign's state.md (default 60s)
interval = 60
camp = ""
try:
    import re
    camp = open(os.path.join(RT, ".campaign"), encoding="utf-8").read().strip()
    txt = (find_campaign(camp) / "state.md").read_text(encoding="utf-8", errors="replace")
    m = re.search(r"autorun_interval:\s*(\d+)", txt)
    if m:
        interval = int(m.group(1))
except Exception:
    pass

# Tell the display (Status panel) and the Stop hook that the GM is listening.
WAITER_FILE = os.path.join(RT, ".autorun-waiter.json")
with open(WAITER_FILE, "w", encoding="utf-8") as f:
    json.dump({"pid": os.getpid(), "since": time.time(), "session": my_session}, f)

subprocess.run([sys.executable, PUSH, "--autorun-waiting", "true", "--autorun-cycle", str(interval)],
               capture_output=True)

# Poll loop — exit when queue appears, session changes, or timeout passes (4 hours)
content = ""
turn_view = None
try:
    for _ in range(48000):  # 0.3s * 48000 = 4 hours
        if os.path.exists(QFILE):
            try:
                content = open(QFILE, encoding="utf-8").read()
                try:                      # world engine: the input is stored before the queue file goes
                    import turn
                    turn_view = turn.receive(camp, content, QFILE)
                except Exception:
                    turn_view = None
                os.unlink(QFILE)
            except Exception:
                content = ""
            break
        try:
            if open(SESSION_FILE, encoding="utf-8").read().strip() != my_session:
                break
        except Exception:
            break
        time.sleep(0.3)
finally:
    try:
        with open(WAITER_FILE, encoding="utf-8") as f:
            mine = json.load(f).get("session") == my_session
        if mine:   # unlink after closing: Windows can't delete an open file
            os.unlink(WAITER_FILE)
    except Exception:
        pass

# Clean up our session file if it's still ours
try:
    if open(SESSION_FILE, encoding="utf-8").read().strip() == my_session:
        os.unlink(SESSION_FILE)
except Exception:
    pass

subprocess.run([sys.executable, PUSH, "--autorun-waiting", "false"], capture_output=True)

# Clear the display queue indicator on success
if content:
    with open(DELIVERED_FILE, "w", encoding="utf-8") as f:
        f.write(str(time.time()))
    try:
        token = open(os.path.join(RT, ".token"), encoding="utf-8").read().strip()
        req = urllib.request.Request(f"{SCHEME}://{_DISPLAY_HOST}/queue/consumed",
                                     data=b"", method="POST",
                                     headers={"X-DND-Token": token})
        urllib.request.urlopen(req, timeout=1, context=CTX)
    except Exception:
        pass

# The GM reads this output every turn, so the rule that keeps the game alive travels with it.
if content:
    note = ("[[GM note, not a player action: end this turn with your reply on the display (send.py; if you "
            "decline the action or your reply was blocked, one short line with send.py --tutor and move the "
            "scene on) and with autorun_wait.py running again in the background.")
    try:
        from paths import autorun_waiter, AUTORUN_WATCHDOG
        if not autorun_waiter(AUTORUN_WATCHDOG):
            note += (f' The autorun watchdog is not running: also start `python3 "{os.path.join(DISPLAY_DIR, "autorun_watchdog.py")}"`'
                     " as a second background task now. It wakes you if the game stalls.")
    except Exception:
        pass
    try:   # what else this turn needs: engine for fights, XP that isn't on the sheet, a save that is due
        import gm_guide
        note += "".join("\n- " + line for line in gm_guide.turn_notes(camp, text=content, turn=turn_view))
    except Exception:
        pass
    content = content.rstrip("\n") + "\n" + note + "]]\n"

sys.stdout.write(content)
