#!/usr/bin/env python3
"""
autosave_checkpoint.py — behind-the-scenes continuity checkpoint for long sessions.

Designed to run as a Claude Code **Stop hook** (install with
`install_autosave_hook.py`). It fires after every DM turn and does two things:

  1. **Deterministic snapshot** (every turn): copies the active campaign's
     `state.md` to a recovery file under the runtime dir and verifies the
     display's `session_tail.json` is healthy. Pure file I/O — no model needed.

  2. **Cadence checkpoint** (every Nth turn): emits a Stop-hook `block`
     decision whose `reason` instructs the DM to do a silent micro-save
     (Live State Flags + new graph edges + session tail) *before* yielding the
     turn — so a context compaction can never cost more than a few turns of
     continuity. Keyed on turn count because the model cannot see its own
     context-usage percentage.

The hook is a no-op (exit 0, no output) when:
  - this agent session never started the game (no `/dne` command or dne skill
    call in its transcript — e.g. a coding session while a campaign marker is
    left over from an earlier game),
  - no campaign is active (no runtime marker — e.g. a non-D&D Claude session),
  - the active campaign has `autosave: off` in `state.md → ## Session Flags`,
  - `stop_hook_active` is set (we are already inside a continuation — never
    block twice, which would loop).

Stdin (Stop-hook JSON, when run as a hook):
  {"session_id": "...", "stop_hook_active": false, "hook_event_name": "Stop", ...}

Manual usage (for testing / forcing a snapshot):
  python3 autosave_checkpoint.py --campaign <name> [--snapshot-only]
  python3 autosave_checkpoint.py --status   # print active campaign + turn count
"""

import sys
import os
import json
import argparse
import shutil

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths  # noqa: E402

DEFAULT_EVERY_N = 10          # cadence checkpoint every N turns
ACTIVE_MARKER = "active-campaign.json"   # written by /dne load, under runtime_dir()

CHECKPOINT_REASON = (
    "Continuity autosave checkpoint (turn cadence reached). Before finishing, "
    "silently update state.md → ## Live State Flags (cover, faction stances, "
    "NPC dispositions), append any new relationships to the campaign graph, and "
    "make sure the latest beats are captured in the session tail. Do not narrate "
    "this to the player and do not run a full /dne save (no session-log "
    "rewrite) — just flush the continuity anchors, then end your turn."
)


def _read_stdin_json():
    """Parse the Stop-hook JSON from stdin. Returns {} when absent/!tty/invalid."""
    if sys.stdin is None or sys.stdin.isatty():
        return {}
    try:
        raw = sys.stdin.read()
    except Exception:
        return {}
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return {}


#: Transcript JSON that only appears when this session really ran the game: the
#: /dne slash command as a user message, or a Skill tool call naming dne. Matched
#: with the JSON quotes unescaped, so a conversation that merely mentions /dne
#: (or code containing these strings) does not count.
_DNE_SIGNS = (b'":"<command-message>dne</command-message>',
              b'"name":"Skill","input":{"skill":"dne"',
              b'"name":"Skill","input":{"skill":"dne:')


def session_plays_dne(stdin_obj: dict) -> bool:
    """True when this session's transcript shows /dne was started.

    No transcript_path (another agent, manual run) → True, the old behaviour.
    Scans only bytes added since the last call; a positive answer is cached.
    """
    path = stdin_obj.get("transcript_path")
    if not path or not os.path.isfile(path):
        return True
    key = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(stdin_obj.get("session_id") or path))[-80:]
    cache = paths.runtime_dir() / f"autosave-session-{key}.json"
    try:
        seen = json.loads(cache.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        seen = {"plays": False, "offset": 0}
    if seen.get("plays"):
        return True
    overlap = max(len(s) for s in _DNE_SIGNS)
    start = max(0, int(seen.get("offset", 0)) - overlap)
    try:
        with open(path, "rb") as f:
            f.seek(start)
            chunk = f.read()
    except OSError:
        return True
    plays = any(s in chunk for s in _DNE_SIGNS)
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"plays": plays, "offset": start + len(chunk)}), encoding="utf-8")
    except OSError:
        pass
    return plays


def autorun_on(campaign: str) -> bool:
    """`autorun: true` in the campaign's state.md → ## Session Flags."""
    try:
        text = (paths.find_campaign(campaign) / "state.md").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    flags = _section(text, "## Session Flags") or ""
    for line in flags.splitlines():
        key, _, val = line.strip().lstrip("-").strip().partition(":")
        if key.strip().lower() == "autorun":
            return val.strip().lower() in ("true", "on", "yes")
    return False


def display_up() -> bool:
    """The display server answers /health (so players are actually waiting on it)."""
    import urllib.request
    import ssl
    host = os.environ.get("DNE_DISPLAY_HOST", "localhost:5001")
    scheme_file = paths.skill_root() / "display" / ".scheme"
    try:
        scheme = scheme_file.read_text(encoding="utf-8").strip() or "http"
    except OSError:
        scheme = "http"
    ctx = None
    if scheme == "https":
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(f"{scheme}://{host}/health", timeout=0.8, context=ctx) as r:
            return r.status == 200
    except Exception:
        return False


def autorun_stall_reason(stdin_obj: dict, campaign: str, wait_s: float = 2.0) -> "str | None":
    """Block ending the turn when autorun is on, the display is up and nothing waits for players.

    Gives a just-launched autorun_wait.py `wait_s` to register itself. Never blocks twice in a row
    (stop_hook_active), so a model that can't comply is not looped forever.
    """
    import time
    if stdin_obj.get("stop_hook_active") or not autorun_on(campaign) or not display_up():
        return None
    deadline = time.time() + wait_s
    while True:
        if paths.autorun_waiter():
            return None
        if time.time() >= deadline:
            break
        time.sleep(0.2)
    waiter = paths.skill_root() / "display" / "autorun_wait.py"
    return ("Autorun is on but nothing is waiting for the players' next action, so the game has stopped. "
            "Before ending this turn: if you declined or redirected a request, send one short line to the "
            "display with send.py --tutor (the players can't see this chat), continue the scene, and then "
            f"relaunch `python3 \"{waiter}\"` as a background task (SKILL.md → Autorun, step 3). "
            "An autorun turn never ends without the wait loop running.")


def active_campaign() -> str | None:
    """Return the name of the campaign marked active by the last /dne load."""
    marker = paths.runtime_dir() / ACTIVE_MARKER
    if not marker.exists():
        return None
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    name = data.get("name")
    return name if isinstance(name, str) and name.strip() else None


def autosave_enabled(campaign: str) -> bool:
    """Read the `autosave` flag from state.md → ## Session Flags. Default: on."""
    state = paths.find_campaign(campaign) / "state.md"
    if not state.exists():
        return False
    try:
        text = state.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    # Look only inside the Session Flags section so we don't match prose elsewhere.
    flags = _section(text, "## Session Flags")
    if flags is None:
        return True  # section absent (older campaign) — default on
    for line in flags.splitlines():
        low = line.lower()
        if "autosave" in low:
            if "off" in low or "false" in low or "disabled" in low:
                return False
            return True
    return True  # flag not written yet — default on


def _section(text: str, header: str) -> str | None:
    """Return the body of a `## `-level markdown section, or None if absent."""
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.strip() == header:
            start = i + 1
            break
    if start is None:
        return None
    body = []
    for line in lines[start:]:
        if line.startswith("## "):
            break
        body.append(line)
    return "\n".join(body)


def _counter_path(session_id: str | None, campaign: str) -> "paths.pathlib.Path":
    key = session_id or campaign or "default"
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in key)
    return paths.runtime_dir() / f"autosave-counter-{safe}.json"


def _load_counter(path) -> int:
    if not path.exists():
        return 0
    try:
        return int(json.loads(path.read_text(encoding="utf-8")).get("turns", 0))
    except (OSError, ValueError, TypeError):
        return 0


def _save_counter(path, turns: int, campaign: str) -> None:
    try:
        path.write_text(
            json.dumps({"turns": turns, "campaign": campaign}),
            encoding="utf-8",
        )
    except OSError:
        pass


def decide(stdin_obj: dict, prev_turns: int, every_n: int = DEFAULT_EVERY_N):
    """Pure cadence logic — separated from I/O so it is unit-testable.

    Returns (new_turns, block_reason_or_None).
      - If `stop_hook_active` is set, never block (avoid continuation loops) and
        leave the counter where it is.
      - Otherwise increment; when the new count is a multiple of every_n, emit a
        block reason and reset the counter to 0.
    """
    if stdin_obj.get("stop_hook_active"):
        return prev_turns, None
    turns = prev_turns + 1
    if every_n > 0 and turns % every_n == 0:
        return 0, CHECKPOINT_REASON
    return turns, None


def snapshot(campaign: str) -> None:
    """Deterministic durability: copy state.md to a recovery file. Best-effort."""
    camp_dir = paths.find_campaign(campaign)
    state = camp_dir / "state.md"
    if not state.exists():
        return
    dest = paths.runtime_dir() / f"{_safe(campaign)}.autocheckpoint.md"
    try:
        shutil.copy2(str(state), str(dest))
    except OSError:
        pass


def _safe(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in name)


def _emit_block(reason: str) -> None:
    """Print the Stop-hook decision JSON that tells Claude to continue."""
    print(json.dumps({"decision": "block", "reason": reason}))


def main() -> int:
    parser = argparse.ArgumentParser(description="Continuity autosave checkpoint.")
    parser.add_argument("--campaign", help="Override the active campaign (testing).")
    parser.add_argument("--snapshot-only", action="store_true",
                        help="Take the deterministic snapshot and exit; never block.")
    parser.add_argument("--status", action="store_true",
                        help="Print active campaign and current turn count.")
    parser.add_argument("--every", type=int, default=None,
                        help=f"Turns between cadence checkpoints (default {DEFAULT_EVERY_N}).")
    args = parser.parse_args()

    stdin_obj = {} if (args.campaign or args.status) else _read_stdin_json()
    campaign = args.campaign or active_campaign()

    if args.status:
        sid = stdin_obj.get("session_id")
        turns = _load_counter(_counter_path(sid, campaign or "")) if campaign else 0
        print(f"active_campaign: {campaign or '(none)'}")
        print(f"turns_since_checkpoint: {turns}")
        return 0

    # Guard: nothing to do when no campaign is active (non-D&D session, etc.),
    # or when this session never started the game (a stale marker from an old one).
    if not campaign:
        return 0
    if not args.campaign and not session_plays_dne(stdin_obj):
        return 0

    # The game must not stop: with autorun on, a turn may not end without the wait loop.
    if not args.campaign and not args.snapshot_only:
        stall = autorun_stall_reason(stdin_obj, campaign)
        if not stall and not stdin_obj.get("stop_hook_active"):
            try:                              # world engine: a turn is open and owes its narration
                import turn
                stall = turn.stall_reason(campaign)
            except Exception:
                stall = None
        if stall:
            _emit_block(stall)
            return 0
    if not autosave_enabled(campaign):
        return 0

    # Deterministic durability always runs.
    snapshot(campaign)

    if args.snapshot_only:
        return 0

    every_n = args.every if args.every is not None else _every_from_env()
    counter_file = _counter_path(stdin_obj.get("session_id"), campaign)
    prev = _load_counter(counter_file)
    new_turns, reason = decide(stdin_obj, prev, every_n)
    _save_counter(counter_file, new_turns, campaign)

    if reason:
        _emit_block(reason)
    return 0


def _every_from_env() -> int:
    raw = os.environ.get("DNE_AUTOSAVE_EVERY", "").strip()
    if raw.isdigit() and int(raw) > 0:
        return int(raw)
    return DEFAULT_EVERY_N


if __name__ == "__main__":
    sys.exit(main())
