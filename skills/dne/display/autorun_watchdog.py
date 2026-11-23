#!/usr/bin/env python3
"""Autorun watchdog: wakes the GM when the game has stalled.

Start it once as a background task, next to autorun_wait.py. It prints nothing while the game
runs. It exits, which makes the host wake the GM, when a player action has waited STALL seconds
with no autorun_wait.py running: the GM ended a turn without relaunching the wait loop (a
declined or blocked reply, an error). Claude Code also has the Stop hook for this; hosts without
hooks (Antigravity and others) have only this script.

Prints the stall notice to stdout, or nothing when a newer watchdog took over or after 4 hours.
"""
import json
import os
import sys
import time

DISPLAY_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(DISPLAY_DIR, "..", "scripts"))
import paths  # noqa: E402
import autosave_checkpoint as ac  # noqa: E402

STALL = float(os.environ.get("DNE_AUTORUN_STALL_S", "90"))
POLL = min(3.0, max(0.2, STALL / 4))


def stalled_for(started: float) -> float:
    """Seconds the oldest unanswered player action has waited with no wait loop (0 = all is well).

    Unanswered = still in the queue, or handed to the GM with no wait loop launched since.
    Markers older than this watchdog count from its start, so a leftover one can't fire at once.
    """
    if paths.autorun_waiter():
        return 0.0
    times = []
    for name in (".input_queue", ".autorun-delivered"):
        try:
            times.append((paths.runtime_dir() / name).stat().st_mtime)
        except OSError:
            pass
    return time.time() - max(min(times), started) if times else 0.0


def main() -> int:
    reg = paths.runtime_dir() / paths.AUTORUN_WATCHDOG
    started = time.time()
    reg.write_text(json.dumps({"pid": os.getpid(), "since": started}), encoding="utf-8")

    def mine() -> bool:
        try:
            return json.loads(reg.read_text(encoding="utf-8")).get("pid") == os.getpid()
        except (OSError, ValueError, AttributeError):
            return False

    try:
        while time.time() - started < 4 * 3600 and mine():
            time.sleep(POLL)
            if stalled_for(started) < STALL:
                continue
            campaign = ac.active_campaign()
            reason = campaign and ac.autorun_stall_reason({}, campaign, wait_s=0)  # autorun on + display up
            if reason:
                # The notice can reach the GM late (after a long turn that did relaunch): don't stack loops.
                print(f"AUTORUN STALLED: {reason} If you already relaunched the wait loop since, leave it "
                      f"running. Either way start this watchdog again as a background task: "
                      f"python3 \"{os.path.abspath(__file__)}\"")
                return 0
    finally:
        if mine():
            try:
                reg.unlink()
            except OSError:
                pass
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
