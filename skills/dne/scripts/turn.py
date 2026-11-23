#!/usr/bin/env python3
"""
turn.py — the turn runner of the world engine (see world_db.py for the store and the contract).

One turn: BEGIN (the table's input is stored, once) → RESOLVE (intents become actions; the engine
applies their effects or stops to wait for a player) → ANSWER (a roll or a decision arrives, the
turn continues where it stopped) → FINISH (the narration goes out, once). STATUS and RESUME pick
up a turn that a crash, a new session or a context compaction interrupted.

    turn.py -c <campaign> begin  --text "<what the table said>" [--input-id ID]
    turn.py -c <campaign> resolve --intents '[{"actor": "Mira", "action": "roll", "spec": "1d20+5", "dc": 13}]'
    turn.py -c <campaign> answer --request req-4-1 --value 14
    turn.py -c <campaign> status | resume
    turn.py -c <campaign> finish  < narration.txt
    turn.py -c <campaign> help [action]

With a display, the scripts the GM already runs carry the lifecycle: autorun_wait.py and
check_input.py call `begin` when they hand over the players' input, and a plain send.py narration
closes the turn. In chat (`display: none`) the GM calls begin and finish; nothing waits on a
background process.

Only campaigns with `world_engine: on` use any of this.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import paths  # noqa: E402
import world_db as wdb  # noqa: E402

sys.modules.setdefault("turn", sys.modules[__name__])   # run as a script, `import turn` must still mean this module

SCHEMA_VERSION = 1
HANDLERS: dict = {}
AFTER_ACTION: list = []      # fn(ctx, intent, result): called in the same transaction once an action is done


def handler(name: str):
    """Register an engine action. The function's docstring is its on-demand manual (`turn.py help <name>`)."""
    def register(fn):
        HANDLERS[name] = fn
        return fn
    return register


class Ctx:
    """What a handler may use: the campaign, the store (inside the writer), and this action's rolls and answers."""

    def __init__(self, campaign: str, db, turn_id: str, action_id: str):
        self.campaign, self.db, self.turn_id, self.action_id = campaign, db, turn_id, action_id
        self.answers = {json.loads(r["question"]).get("key"): json.loads(r["answer"])
                        for r in db.execute("SELECT question, answer FROM requests WHERE action_id=? AND status='answered'",
                                            (action_id,))}

    def flag(self, key: str, default: str = "") -> str:
        return paths.session_flag(self.campaign, key, default)

    def roll(self, key: str, sides: int, count: int = 1) -> list:
        """Dice for this action, rolled once: a retry or a resume reads the stored result."""
        def make():
            r = wdb.rng(self.db, f"{self.action_id}:{key}")
            return {"dice": [r.randint(1, sides) for _ in range(count)]}
        dice = wdb.roll_once(self.db, self.action_id, key, make)["dice"]
        wdb.crash_point("after_roll")
        return dice


# ── the two adapters every table needs first ──────────────────────────────────

@handler("ask")
def _ask(ctx: Ctx, intent: dict) -> dict:
    """ask — an out-of-game question ("what time is it?", "where are we?"). No in-world time passes.

    {"action": "ask"}  →  the in-world time, the open requests and the revision."""
    minute = wdb.now_minute(ctx.campaign)
    when = None
    if minute is not None:
        when = f"day {minute // 1440}, {minute % 1440 // 60:02d}:{minute % 60:02d}"
    return {"status": "done", "elapsed_minutes": 0, "data": {"in_world_time": when, "minute": minute}}


@handler("roll")
def _roll(ctx: Ctx, intent: dict) -> dict:
    """roll — one roll for one character.

    {"actor": "Mira", "action": "roll", "spec": "1d20+5", "dc": 13, "label": "Stealth"}
    With roll_mode: players the turn waits for that player's d20 (the number before bonuses);
    with roll_mode: auto the engine rolls. Either way the roll happens once: sending the turn
    again, or resuming after a crash, returns the same result."""
    import dice
    num, sides, mod, *_ = dice.parse_notation(str(intent.get("spec", "1d20")))
    actor = str(intent.get("actor") or "Party")
    if ctx.flag("roll_mode", "players") == "players" and "roll" not in ctx.answers:
        label = intent.get("label") or "a roll"
        dc = f" (DC {intent['dc']})" if intent.get("dc") is not None and ctx.flag("show_dc", "on") == "on" else ""
        return {"status": "waiting_for_player",
                "requests": [{"key": "roll", "kind": "roll", "expected": actor,
                              "text": f"{actor}: roll {label} — {intent.get('spec', '1d20')}{dc}"}]}
    if "roll" in ctx.answers:
        raw = [int(ctx.answers["roll"]["value"])]
    else:
        raw = ctx.roll("roll", sides, num)
    total = sum(raw) + mod
    data = {"actor": actor, "dice": raw, "modifier": mod, "total": total, "label": intent.get("label", "")}
    if intent.get("dc") is not None:
        data["dc"] = int(intent["dc"])
        data["degree"] = dice.degree(raw[0], total, int(intent["dc"])) if (num, sides) == (1, 20) else None
        data["passed"] = total >= int(intent["dc"])
    return {"status": "done", "elapsed_minutes": 0, "data": data,
            "visible_events": [{"type": "roll", "recipient": "party",
                                "text": f"{actor} rolls {data['label'] or intent.get('spec', '')}: {total}"}]}


# ── store helpers ─────────────────────────────────────────────────────────────

def _epoch() -> int:
    import turn_snapshot
    return turn_snapshot.timeline_epoch()


def _open_turn(db):
    return db.execute("SELECT * FROM turns WHERE status='open' ORDER BY seq DESC LIMIT 1").fetchone()


def _open_requests(db, turn_id: "str | None" = None) -> list:
    sql = "SELECT * FROM requests WHERE status='open'" + (" AND turn_id=?" if turn_id else "") + " ORDER BY request_id"
    return [{"request_id": r["request_id"], "kind": r["kind"], "expected": r["expected"],
             "question": json.loads(r["question"]).get("text", ""), "action_id": r["action_id"]}
            for r in db.execute(sql, (turn_id,) if turn_id else ())]


def _turn_view(db, turn, **extra) -> dict:
    """The answer every command gives: where the turn stands and what it waits for."""
    acts = db.execute("SELECT action_id, status FROM actions WHERE turn_id=? ORDER BY seq", (turn["turn_id"],)).fetchall()
    waiting = _open_requests(db, turn["turn_id"])
    out = {"schema_version": SCHEMA_VERSION, "turn_id": turn["turn_id"], "revision": wdb.revision(db),
           "status": "waiting_for_player" if waiting else turn["status"],
           "completed": [a["action_id"] for a in acts if a["status"] == "done"],
           "pending": [a["action_id"] for a in acts if a["status"] in ("pending", "waiting", "applying")],
           "next_input": ({"kind": waiting[0]["kind"], "request_id": waiting[0]["request_id"],
                           "expected": waiting[0]["expected"], "question": waiting[0]["question"]} if waiting else None),
           "waiting": waiting}
    out.update(extra)
    return out


def _queue(db, turn_id: str, message_id: str, body: str, audience: str = "party", kind: str = "narration") -> None:
    db.execute("INSERT OR IGNORE INTO outbox (message_id, turn_id, audience, kind, body, status) VALUES (?,?,?,?,?,'pending')",
               (message_id, turn_id, audience, kind, body))


def deliver(campaign: str) -> list:
    """Send every message still pending, in order. A message keeps its id on a retry, so the display shows it once."""
    with wdb.reader(campaign) as db:
        rows = db.execute("SELECT * FROM outbox WHERE status='pending' ORDER BY rowid").fetchall() if db else []
    sent = []
    for row in rows:
        ok = _send(campaign, row["message_id"], row["body"], row["audience"], row["kind"])
        with wdb.writer(campaign) as db:
            db.execute("UPDATE outbox SET attempts=attempts+1, status=? WHERE message_id=?",
                       ("sent" if ok else "pending", row["message_id"]))
        if ok:
            wdb.crash_point("after_send_before_ack")
            sent.append({"message_id": row["message_id"], "audience": row["audience"], "kind": row["kind"],
                         "body": row["body"]})
    return sent


def _send(campaign: str, message_id: str, body: str, audience: str, kind: str) -> bool:
    """One delivery. DNE_OUTBOX_LOG (tests, replays) records it instead of reaching a display."""
    log = os.environ.get("DNE_OUTBOX_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as f:
            f.write(json.dumps({"message_id": message_id, "audience": audience, "kind": kind, "body": body},
                               ensure_ascii=False) + "\n")
        return True
    if paths.session_flag(campaign, "display", "none") == "none":
        return True                               # chat mode: the caller prints it; nothing runs in the background
    cmd = [sys.executable, str(HERE.parent / "display" / "send.py"), "--message-id", message_id]
    if kind == "question":
        cmd.append("--tutor")
    if audience not in ("party", ""):
        cmd += ["--to", audience]
    try:
        return subprocess.run(cmd, input=body.encode("utf-8"), capture_output=True, timeout=30).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


# ── begin ─────────────────────────────────────────────────────────────────────

def _answers_in(text: str) -> dict:
    """{'mira': 14} from lines like '[Mira]: 14': a number alone is a roll result."""
    found = {}
    for line in text.splitlines():
        m = re.match(r"\s*\[([^\]]+)\]\s*:\s*(\d{1,3})\s*$", line)
        if m:
            found[m.group(1).strip().casefold()] = int(m.group(2))
    return found


def begin(campaign: str, text: str, input_id: "str | None" = None, source: str = "chat") -> dict:
    """Store the table's input and open the turn for it. The same input_id always returns the same turn."""
    text = text.strip()
    with wdb.reader(campaign) as db:
        if db is not None:
            if input_id:
                seen = db.execute("SELECT turn_id FROM inputs WHERE input_id=?", (input_id,)).fetchone()
                if seen:
                    turn = db.execute("SELECT * FROM turns WHERE turn_id=?", (seen["turn_id"],)).fetchone()
                    return _turn_view(db, turn, duplicate=True)
            current = _open_turn(db)
            carries_on = bool(current and _open_requests(db, current["turn_id"]))
        else:
            carries_on = False
    if not carries_on:                            # a new turn: the undo point is taken before anything is written
        import turn_snapshot
        turn_snapshot.save_snapshot(campaign, label=text.splitlines()[0][:48] if text else "")
    with wdb.writer(campaign) as db:
        current = _open_turn(db)
        waiting = _open_requests(db, current["turn_id"]) if current else []
        if not input_id:
            n = db.execute("SELECT COUNT(*) AS n FROM inputs").fetchone()["n"]
            input_id = "in-" + hashlib.sha256(f"{n}:{text}".encode()).hexdigest()[:12]
        if current and waiting:                   # the table is answering: same turn, no new undo point
            db.execute("INSERT OR IGNORE INTO inputs VALUES (?,?,?,?,?)", (input_id, current["turn_id"], source, text, _wall()))
            turn_id, resumed = current["turn_id"], True
        else:
            if current:                           # the GM narrated without closing it: it is over
                db.execute("UPDATE turns SET status='finished' WHERE turn_id=?", (current["turn_id"],))
            turn_id = wdb.next_id(db, "turn_seq", "turn")
            db.execute("INSERT INTO turns VALUES (?,?,?,?,?,?,?)",
                       (turn_id, int(turn_id.split("-")[1]), "open", wdb.revision(db), wdb.now_minute(campaign), "", _wall()))
            db.execute("INSERT INTO inputs VALUES (?,?,?,?,?)", (input_id, turn_id, source, text, _wall()))
            resumed = False
    wdb.crash_point("after_input_stored")
    answered = []
    if resumed:
        given = _answers_in(text)
        for req in waiting:
            if req["kind"] == "roll" and req["expected"].casefold() in given:
                answered.append(answer(campaign, req["request_id"], given[req["expected"].casefold()], _view=False))
    with wdb.reader(campaign) as db:
        turn = db.execute("SELECT * FROM turns WHERE turn_id=?", (turn_id,)).fetchone()
        view = _turn_view(db, turn, input_id=input_id, resumed=resumed, answered=answered)
    try:                                          # what the GM needs to know to run this turn
        import scene_context
        view["context"] = scene_context.build(campaign, text)
        with wdb.writer(campaign) as db:          # after the context: "him" must not resolve to someone named just now
            scene_context.remember_mentions(db, text, campaign, int(turn_id.split("-")[1]))
    except Exception:
        pass
    return view


def receive(campaign: str, content: str, queue_file: str) -> "dict | None":
    """The display's queue file is about to be consumed: store its content first, then it may be deleted.

    The id comes from the file itself, so a wait loop that died between storing and deleting hands
    over the same input again and gets the same turn back. None when the engine is off.
    """
    if not campaign or not content.strip() or not wdb.enabled(campaign):
        return None
    try:
        stamp = os.stat(queue_file).st_mtime_ns
    except OSError:
        stamp = 0
    input_id = "q-" + hashlib.sha256(f"{stamp}:{content}".encode()).hexdigest()[:14]
    return begin(campaign, content, input_id=input_id, source="display")


def _wall() -> float:
    import time
    return time.time()


# ── resolve / answer ──────────────────────────────────────────────────────────

def resolve(campaign: str, intents: list, turn_id: "str | None" = None) -> dict:
    """Turn intents into actions and run them in order. The first one that needs a player stops the rest."""
    with wdb.writer(campaign) as db:
        turn = db.execute("SELECT * FROM turns WHERE turn_id=?", (turn_id,)).fetchone() if turn_id else _open_turn(db)
        if not turn or turn["status"] != "open":
            raise ValueError("no open turn: run `begin` first")
        turn_id = turn["turn_id"]
        base = db.execute("SELECT COUNT(*) AS n FROM actions WHERE turn_id=?", (turn_id,)).fetchone()["n"]
        repeats: dict = {}
        for i, intent in enumerate(intents, base + 1):
            if intent.get("action") not in HANDLERS:
                raise ValueError(f"unknown action {intent.get('action')!r}; `turn.py help` lists them")
            # The id comes from the intent itself: resolving the same list again is a retry, not new actions.
            # (Two identical intents in one list are two actions; a later identical one needs its own action_id.)
            body = json.dumps(intent, ensure_ascii=False, sort_keys=True)
            nth = repeats[body] = repeats.get(body, 0) + 1
            action_id = intent.get("action_id") or f"{turn_id}-{hashlib.sha256(body.encode()).hexdigest()[:6]}-{nth}"
            db.execute("INSERT OR IGNORE INTO actions VALUES (?,?,?,?,?,?)",
                       (action_id, turn_id, i, body, "pending", ""))
    return _run(campaign, turn_id)


def _run(campaign: str, turn_id: str) -> dict:
    """Run this turn's pending actions in order until one waits. Safe to call again at any point."""
    results, status = [], ""
    while True:
        with wdb.writer(campaign) as db:
            if _open_requests(db, turn_id):
                break
            act = db.execute("SELECT * FROM actions WHERE turn_id=? AND status IN ('pending','applying','waiting') "
                             "ORDER BY seq LIMIT 1", (turn_id,)).fetchone()
            if not act:
                break
            intent = json.loads(act["intent"])
            ctx = Ctx(campaign, db, turn_id, act["action_id"])
            out = HANDLERS[intent["action"]](ctx, intent) or {}
            status = out.get("status", "done")
            if status == "waiting_for_player":
                for req in out.get("requests") or []:
                    # named after its key: a second question from the same action is a new request, not the first again
                    request_id = f"req-{turn_id.split('-')[1]}-{act['seq']}-{req.get('key', 'choice')}"
                    db.execute("INSERT OR IGNORE INTO requests VALUES (?,?,?,?,?,?,?,?,?)",
                               (request_id, turn_id, act["action_id"], req.get("kind", "decision"), req.get("expected", "party"),
                                json.dumps({"key": req.get("key", "choice"), "text": req.get("text", "")}, ensure_ascii=False),
                                "open", "", _epoch()))
                    _queue(db, turn_id, request_id, req.get("text", ""), req.get("audience", "party"), "question")
                # Time that passed before the question still passed: its file changes are applied now.
                wdb.stage_writes(db, f"{act['action_id']}@{wdb.revision(db)}", out.get("writes"))
                out.pop("writes", None)
                db.execute("UPDATE actions SET status='waiting', result=? WHERE action_id=?",
                           (json.dumps(out, ensure_ascii=False), act["action_id"]))
            else:
                for hook in AFTER_ACTION:
                    hook(ctx, intent, out)
                # A handler may address someone alone: {"to": "<PC>", "text": "…"} goes out as a private message.
                for n, msg in enumerate(out.get("messages") or [], 1):
                    _queue(db, turn_id, f"{act['action_id']}-m{n}", str(msg.get("text", "")), str(msg.get("to", "party")),
                           str(msg.get("kind", "whisper")))
                staged_as = f"{act['action_id']}@{wdb.revision(db)}"
                wdb.stage_writes(db, staged_as, out.get("writes"))
                out.pop("writes", None)
                db.execute("UPDATE actions SET status='done', result=? WHERE action_id=?",
                           (json.dumps(out, ensure_ascii=False), act["action_id"]))
                if not db.execute("SELECT 1 FROM applies WHERE action_id=?", (staged_as,)).fetchone():
                    wdb.set_meta(db, "revision", wdb.revision(db) + 1)
            results.append({"action_id": act["action_id"], **out})
        wdb.apply_staged(campaign)
        if status == "waiting_for_player":
            break
    questions = deliver(campaign)
    with wdb.reader(campaign) as db:
        turn = db.execute("SELECT * FROM turns WHERE turn_id=?", (turn_id,)).fetchone()
        view = _turn_view(db, turn, results=results, sent=questions)
    if not results:                               # nothing new ran (a retry): report what the actions already gave
        results = view["results"] = [
            {"action_id": a["action_id"], **json.loads(a["result"])} for a in _done_actions(campaign, turn_id)]
    last = results[-1] if results else {}
    view["action_id"] = last.get("action_id")
    view["elapsed_minutes"] = sum(int(r.get("elapsed_minutes") or 0) for r in results)
    view["visible_events"] = [e for r in results for e in (r.get("visible_events") or [])]
    return view


def _done_actions(campaign: str, turn_id: str) -> list:
    with wdb.reader(campaign) as db:
        return db.execute("SELECT action_id, result FROM actions WHERE turn_id=? AND status='done' ORDER BY seq",
                          (turn_id,)).fetchall()


def answer(campaign: str, request_id: str, value, _view: bool = True) -> dict:
    """A player's roll or decision. The same request answered twice keeps the first answer."""
    with wdb.writer(campaign) as db:
        req = db.execute("SELECT * FROM requests WHERE request_id=?", (request_id,)).fetchone()
        if not req:
            raise ValueError(f"no request {request_id}")
        if req["status"] == "answered":
            first = json.loads(req["answer"])
            return {"request_id": request_id, "duplicate": True, "value": first["value"], "turn_id": req["turn_id"]}
        if req["epoch"] != _epoch():
            db.execute("UPDATE requests SET status='stale' WHERE request_id=?", (request_id,))
            return {"request_id": request_id, "stale": True,
                    "reason": "asked before an undo: that timeline is gone, ask again if you still need it"}
        if req["status"] != "open":
            return {"request_id": request_id, "stale": True, "reason": f"request is {req['status']}"}
        db.execute("UPDATE requests SET status='answered', answer=? WHERE request_id=?",
                   (json.dumps({"value": value}, ensure_ascii=False), request_id))
        db.execute("UPDATE actions SET status='pending' WHERE action_id=?", (req["action_id"],))
        turn_id = req["turn_id"]
    view = _run(campaign, turn_id)
    return view if _view else {"request_id": request_id, "value": value,
                               "results": view.get("results"), "status": view["status"]}


# ── status / resume / finish ──────────────────────────────────────────────────

def status(campaign: str) -> dict:
    """The turn in progress, if any, and what it is waiting for. Changes nothing."""
    with wdb.reader(campaign) as db:
        turn = _open_turn(db) if db is not None else None
        if not turn:
            return {"schema_version": SCHEMA_VERSION, "status": "idle", "turn_id": None, "waiting": [],
                    "revision": wdb.revision(db) if db is not None else 0}
        undelivered = db.execute("SELECT COUNT(*) AS n FROM outbox WHERE status='pending'").fetchone()["n"]
        return _turn_view(db, turn, undelivered=undelivered)


def resume(campaign: str) -> dict:
    """After a crash, a new session or a compaction: finish what was half done, resend what never arrived."""
    with wdb.writer(campaign):                    # opening the writer completes any half-replaced files
        pass
    with wdb.reader(campaign) as db:
        turn = _open_turn(db)
    if turn:
        view = _run(campaign, turn["turn_id"])    # also delivers the outbox
    else:
        view = {"schema_version": SCHEMA_VERSION, "status": "idle", "turn_id": None, "sent": deliver(campaign)}
    view["resumed"] = True
    return view


def finish(campaign: str, narration: str, turn_id: "str | None" = None, already_sent: bool = False) -> dict:
    """Close the turn with the GM's narration. Refused while an action still waits on a player."""
    with wdb.writer(campaign) as db:
        turn = db.execute("SELECT * FROM turns WHERE turn_id=?", (turn_id,)).fetchone() if turn_id else _open_turn(db)
        if not turn:
            return {"schema_version": SCHEMA_VERSION, "status": "idle", "turn_id": None,
                    "note": "no open turn: nothing to finish"}
        if turn["status"] == "finished":
            return _turn_view(db, turn, duplicate=True)
        waiting = _open_requests(db, turn["turn_id"])
        undone = db.execute("SELECT action_id FROM actions WHERE turn_id=? AND status IN ('pending','applying','waiting')",
                            (turn["turn_id"],)).fetchall()
        if waiting or undone:
            return _turn_view(db, turn, finished=False,
                              note="not finished: " + "; ".join(w["question"] or w["request_id"] for w in waiting)
                              if waiting else "not finished: actions still pending, run `resume`")
        if not already_sent and narration.strip():
            _queue(db, turn["turn_id"], f"{turn['turn_id']}-final", narration.strip())
        db.execute("UPDATE turns SET status='finished', narration=? WHERE turn_id=?", (narration.strip(), turn["turn_id"]))
        turn_id = turn["turn_id"]
        try:                                      # who the GM just talked about is who "she" means next turn
            import scene_context
            scene_context.remember_mentions(db, narration, campaign, turn["seq"])
        except Exception:
            pass
    wdb.crash_point("after_commit_before_send")
    sent = deliver(campaign)
    with wdb.reader(campaign) as db:
        turn = db.execute("SELECT * FROM turns WHERE turn_id=?", (turn_id,)).fetchone()
        return _turn_view(db, turn, finished=True, sent=sent)


def narration_sent(campaign: str, text: str) -> "dict | None":
    """send.py just put a plain narration on the display: that closes the open turn, if nothing waits."""
    if not wdb.enabled(campaign) or not wdb.db_path(campaign).exists():
        return None
    return finish(campaign, text, already_sent=True)


def stall_reason(campaign: str) -> "str | None":
    """For the Stop hook: a turn is open and nothing waits on a player, so the GM owes its narration."""
    if not wdb.enabled(campaign):
        return None
    view = status(campaign)
    if view.get("status") == "open":
        return (f"World engine: {view['turn_id']} is still open. Send its narration (send.py, or "
                f"`turn.py -c {campaign} finish`) before you stop.")
    return None


def main() -> int:
    p = argparse.ArgumentParser(description="World engine turn runner.")
    p.add_argument("-c", "--campaign", required=True)
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("begin")
    b.add_argument("--text", default=None)
    b.add_argument("--input-id")
    r = sub.add_parser("resolve")
    r.add_argument("--intents", required=True, help="JSON list, or - for stdin")
    r.add_argument("--turn")
    a = sub.add_parser("answer")
    a.add_argument("--request", required=True)
    a.add_argument("--value", required=True)
    sub.add_parser("status")
    sub.add_parser("resume")
    f = sub.add_parser("finish")
    f.add_argument("--narration", default=None)
    h = sub.add_parser("help")
    h.add_argument("action", nargs="?")
    args = p.parse_args()

    if args.cmd == "help":
        names = [args.action] if args.action else sorted(HANDLERS)
        for name in names:
            doc = (HANDLERS[name].__doc__ or name).strip() if name in HANDLERS else f"unknown action {name}"
            print(doc if args.action else doc.splitlines()[0])
        return 0
    if not wdb.enabled(args.campaign):
        print(json.dumps({"status": "off", "note": "world_engine is not on for this campaign (Session Flags)"}))
        return 0
    try:
        if args.cmd == "begin":
            out = begin(args.campaign, args.text if args.text is not None else sys.stdin.read(), args.input_id)
        elif args.cmd == "resolve":
            raw = sys.stdin.read() if args.intents == "-" else args.intents
            out = resolve(args.campaign, json.loads(raw), args.turn)
        elif args.cmd == "answer":
            value = int(args.value) if re.fullmatch(r"-?\d+", args.value) else args.value
            out = answer(args.campaign, args.request, value)
        elif args.cmd == "status":
            out = status(args.campaign)
        elif args.cmd == "resume":
            out = resume(args.campaign)
        else:
            out = finish(args.campaign, args.narration if args.narration is not None else sys.stdin.read())
    except (ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


def _load_modules() -> None:
    """Engine modules register their handlers on import (rest, travel, trade, …)."""
    for name in ("scene_context", "scheduler", "journey", "trade", "knowledge", "routine", "stakes", "table", "skirmish", "upkeep", "story"):
        try:
            __import__(name)
        except ImportError:
            pass


_load_modules()

if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
