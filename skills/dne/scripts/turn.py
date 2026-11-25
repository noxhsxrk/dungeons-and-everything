#!/usr/bin/env python3
"""
turn.py — the turn runner of the world engine (see world_db.py for the store and the contract).

One turn: BEGIN (the table's input is stored, once) → RESOLVE (intents become actions; the engine
applies their effects or stops to wait for a player) → ANSWER (a roll or a decision arrives, the
turn continues where it stopped) → FINISH (the narration goes out, once). STATUS and RESUME pick
up a turn that a crash, a new session or a context compaction interrupted.

    turn.py -c <campaign> begin  --text "<what the table said>" [--input-id ID]
    turn.py -c <campaign> resolve --intents '[{"actor": "Mira", "action": "roll", "approach": "wits"}]'   (5e: "spec": "1d20+5", "dc": 13)
    turn.py -c <campaign> answer --request req-4-1 --value 14
    turn.py -c <campaign> status | resume
    turn.py -c <campaign> finish  < narration.txt
    turn.py -c <campaign> help [action]
    turn.py -c <campaign> log > turns.json        # what was played, without the dice
    turn.py -c <copy> replay --log turns.json     # play it again on a copy taken at the start: same state

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

    {"action": "ask"}  →  the in-world time, the open requests and the revision.
    A table that agreed thinking takes time sets `ooc_minutes: N` in Session Flags: each `ask` then lets N in-world
    minutes pass, and whatever comes due in them happens."""
    spent, extra = int(ctx.flag("ooc_minutes", "0") or 0), {}
    if spent > 0:
        import scheduler
        world = scheduler.World(ctx.campaign, ctx.db)
        if world.minute is not None:
            out = scheduler.advance(world, world.minute + spent)
            extra = {"elapsed_minutes": out["elapsed_minutes"], "writes": world.writes(), "visible_events": out["visible_events"]}
    minute = wdb.now_minute(ctx.campaign) if not extra else scheduler.World(ctx.campaign, ctx.db).minute + extra["elapsed_minutes"]
    when = None
    if minute is not None:
        when = f"day {minute // 1440}, {minute % 1440 // 60:02d}:{minute % 60:02d}"
    return {"status": "done", "elapsed_minutes": 0, "data": {"in_world_time": when, "minute": minute}, **extra}


@handler("roll")
def _roll(ctx: Ctx, intent: dict) -> dict:
    """roll — one roll for one character.

    Braid: {"actor": "Mira", "action": "roll", "approach": "finesse", "label": "slip past the guard"}
    5e:    {"actor": "Mira", "action": "roll", "spec": "1d20+5", "dc": 13, "label": "Stealth"}
    With roll_mode: players the turn waits for that player's dice (5e: the d20 before bonuses; Braid: both d6 added);
    with roll_mode: auto the engine rolls. Either way the roll happens once: sending the turn
    again, or resuming after a crash, returns the same result.
    Braid (System: core): a check is {"spec": "2d6+1"} with no DC, graded on the five-step ladder; any other spec is
    a plain roll (damage, a table). Story mode: {"likelihood": "likely"} (or a dc) asks the oracle instead of dice.
    Braid core also reads "approach" (conditions on the actor apply; with no spec the check is 2d6 + that approach
    from the actor's sheet), "push": true (+1, marks 1 stress) and "help": "<name>" (+1 if that character has a
    bond with the actor). judge, flashback, bargain and search read the same three, in the intent or its `roll`. Afterwards a token steps the result up:
    {"action": "pool", "owner": "Mira", "id": "tokens", "step_up": true} (see mechanics.py)."""
    import dice
    import resolve as checks
    system = paths.campaign_system(ctx.campaign)
    if system != "d20":
        num, sides, *_ = dice.parse_notation(str(intent.get("spec") or checks.CORE_DICE))
        # A DC, or a d20, means the GM meant a 5e check: Braid has neither. Other dice (damage, a table) roll as written.
        err = checks.spec_error(system, intent.get("spec")) if intent.get("dc") is not None or sides == 20 else None
        if err:
            return {"status": "done", "elapsed_minutes": 0, "data": {"error": err}}
        # Story never asks for dice: a check (no spec, an approach, a likelihood, a dc or a d20) asks the oracle.
        is_check = (num, sides) == (2, 6) if system == "core" else (
            intent.get("dc") is not None or bool(intent.get("likelihood")) or bool(intent.get("approach"))
            or not intent.get("spec") or sides == 20)
        if is_check:
            return _check(ctx, intent, system)
    num, sides, mod, *_ = dice.parse_notation(str(intent.get("spec", "1d20")))
    actor = str(intent.get("actor") or "Party")
    if system != "story" and ctx.flag("roll_mode", "players") == "players" and "roll" not in ctx.answers:
        label = intent.get("label") or "a roll"
        dc = f" (DC {intent['dc']})" if intent.get("dc") is not None and ctx.flag("show_dc", "on") == "on" else ""
        return {"status": "waiting_for_player",
                "requests": [{"key": "roll", "kind": "roll", "expected": actor,
                              "text": f"{actor}: roll {label} — {intent.get('spec', '1d20')}{dc}",
                              **({"dice": f"{num}d{sides}"} if system != "d20" else {})}]}
    if "roll" in ctx.answers:
        raw = [int(ctx.answers["roll"]["value"])]
    else:
        raw = ctx.roll("roll", sides, num)
    total = sum(raw) + mod
    data = {"actor": actor, "dice": raw, "modifier": mod, "total": total, "label": intent.get("label", "")}
    if intent.get("dc") is not None:
        graded = checks.resolve(system, intent.get("spec", "1d20"), intent["dc"], raw)
        data["dc"] = int(intent["dc"])
        data["degree"] = graded["degree"] if (num, sides) == (1, 20) else None
        data["passed"] = graded["passed"]
    return {"status": "done", "elapsed_minutes": 0, "data": data,
            "visible_events": [{"type": "roll", "recipient": "party",
                                "text": f"{actor} rolls {data['label'] or intent.get('spec', '')}: {total}"}]}


def _check(ctx: Ctx, intent: dict, system: str) -> dict:
    """A Braid check through `roll`: 2d6 + modifier (core) or the oracle (story), graded by resolve.py."""
    import resolve as checks
    spec, actor = intent.get("spec"), str(intent.get("actor") or "Party")
    edge = {"mod": 0, "notes": [], "push": False}
    if intent.get("action") == "roll":            # sheet approach, conditions, a push, help (mechanics.edged); a progress roll has none
        import mechanics
        edge = mechanics.edged(ctx, intent, system, actor, spec)
        if edge.get("error"):
            return {"status": "done", "elapsed_minutes": 0, "data": {"error": edge["error"]}}
        spec = edge["spec"]
    spec = spec or checks.CORE_DICE
    label = intent.get("label") or "a roll"
    if system == "core" and ctx.flag("roll_mode", "players") == "players" and "roll" not in ctx.answers:
        return {"status": "waiting_for_player",
                "requests": [{"key": "roll", "kind": "roll", "expected": actor, "dice": checks.CORE_DICE,
                              "text": f"{actor}: roll {label} — {checks.shown(system, spec)}"}]}
    num, sides, mod = checks.dice_for(system, spec)
    rolled = [int(ctx.answers["roll"]["value"])] if "roll" in ctx.answers else ctx.roll("roll", sides, num)
    likelihood, chaos = str(intent.get("likelihood") or _odds(ctx, intent, actor, system)), checks.chaos(ctx.campaign, system)
    graded = checks.resolve(system, spec, None, rolled, likelihood=likelihood, chaos=chaos)
    data = {"actor": actor, "dice": rolled, "modifier": mod, "total": graded["total"], "label": intent.get("label", ""),
            "degree": graded["degree"], "passed": graded["passed"], "spec": spec}   # spec: a token can step it up later
    if system == "story":
        import oracle
        data.update(likelihood=likelihood, chaos=chaos, answer=oracle.verdict(rolled[0], likelihood, chaos))
    if edge["notes"]:
        data["edges"] = edge["notes"]
    if edge["push"]:
        data["stress_crossed"] = mechanics.push(ctx, actor)
    said = f"{graded['total']}, {graded['degree']}" if system == "core" else f"the oracle says {graded['degree']}"
    return {"status": "done", "elapsed_minutes": 0, "data": data,
            "visible_events": [{"type": "roll", "recipient": "party", "text": f"{actor} rolls {label}: {said}"}]}


def _odds(ctx: Ctx, intent: dict, actor: str, system: str) -> str:
    """Story mode with no likelihood: the approach on the sheet sets the odds (+2 or more likely, -1 or less unlikely)."""
    if system != "story" or not intent.get("approach"):
        return "50/50"
    import sheet
    base = sheet.approach(ctx.campaign, actor, intent["approach"]) or 0
    return "likely" if base >= 2 else "unlikely" if base <= -1 else "50/50"


def _dice_range(dice_spec: str) -> "tuple[int, int]":
    """The lowest and highest sum a player can send for `dice_spec` ("2d6" → 2..12)."""
    import dice
    num, sides, *_ = dice.parse_notation(dice_spec)
    return num, num * sides


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
    if resumed and view.get("waiting") and paths.campaign_system(campaign) != "d20":
        view["note"] = (f"this input joined {turn_id}, which still waits for: "
                        + "; ".join(w["question"] or w["request_id"] for w in view["waiting"])
                        + ". Answer it (`turn.py answer`) before anything new happens.")
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
            body = json.dumps({k: v for k, v in intent.items() if k != "action_id"}, ensure_ascii=False, sort_keys=True)
            nth = repeats[body] = repeats.get(body, 0) + 1
            action_id = intent.get("action_id") or f"{turn_id}-{hashlib.sha256(body.encode()).hexdigest()[:6]}-{nth}"
            db.execute("INSERT OR IGNORE INTO actions VALUES (?,?,?,?,?,?)",
                       (action_id, turn_id, i, body, "pending", ""))
    return _run(campaign, turn_id)


def _run(campaign: str, turn_id: str) -> dict:
    """Run this turn's pending actions in order until one waits. Safe to call again at any point."""
    results, status = [], ""
    braid = paths.campaign_system(campaign) != "d20"
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
            if braid and out.get("status", "done") == "done" and isinstance(out.get("data"), dict) and out["data"].get("error"):
                out["status"] = "refused"         # Braid: a refusal must not read as done (the action is still closed)
            status = out.get("status", "done")
            if status == "waiting_for_player":
                for req in out.get("requests") or []:
                    # named after its key: a second question from the same action is a new request, not the first again
                    request_id = f"req-{turn_id.split('-')[1]}-{act['seq']}-{req.get('key', 'choice')}"
                    db.execute("INSERT OR IGNORE INTO requests VALUES (?,?,?,?,?,?,?,?,?)",
                               (request_id, turn_id, act["action_id"], req.get("kind", "decision"), req.get("expected", "party"),
                                json.dumps({"key": req.get("key", "choice"), "text": req.get("text", ""),
                                            **({"dice": req["dice"]} if req.get("dice") else {})}, ensure_ascii=False),
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
        if out.get("refresh") == "clocks" and paths.session_flag(campaign, "display", "none") != "none":
            try:                                  # like the map: the clocks on the display are state, pushed whole
                import mechanics
                import story
                subprocess.run([sys.executable, str(HERE.parent / "display" / "push_stats.py"), "--clocks-json",
                                json.dumps(story.clocks(campaign) + mechanics.board(campaign), ensure_ascii=False)],
                               capture_output=True, timeout=15)
            except Exception:
                pass
        if out.get("refresh") == "battlemap" and paths.session_flag(campaign, "display", "none") != "none":
            try:                                  # the map on the display is state, not a message: pushing it twice is harmless
                import battlemap
                battlemap._push_display(battlemap._load(campaign))
            except Exception:
                pass
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
    refused = [{"action_id": r["action_id"], "error": r["data"]["error"]} for r in results if r.get("status") == "refused"]
    if refused:
        view["refused"] = refused
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
        dice_spec = json.loads(req["question"]).get("dice")
        if dice_spec:                             # a Braid roll: refuse a sum those dice cannot make, keep the question open
            lo, hi = _dice_range(dice_spec)
            if not str(value).strip().lstrip("-").isdigit() or not lo <= int(value) <= hi:
                return {"request_id": request_id, "status": "refused", "turn_id": req["turn_id"],
                        "error": f"{value!r} is not a {dice_spec} roll: send the dice added together, {lo} to {hi}"}
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
        record = _committed(db, turn["turn_id"])
        if record["actions"]:                      # the narration stands on these; the GM's prose is not checked
            wdb.put(db, "turn_record", turn["turn_id"], record)
            state = paths.find_campaign(campaign) / "state.md"
            if state.exists():
                text = state.read_text(encoding="utf-8")
                block = world_block(campaign, db, turn["turn_id"], record)
                new = with_block(text, block)
                if new != text:
                    wdb.stage_writes(db, f"{turn['turn_id']}-finish", {"state.md": new})
        if not already_sent and narration.strip():
            _queue(db, turn["turn_id"], f"{turn['turn_id']}-final", narration.strip())
        db.execute("UPDATE turns SET status='finished', narration=? WHERE turn_id=?", (narration.strip(), turn["turn_id"]))
        turn_id = turn["turn_id"]
        try:                                      # who the GM just talked about is who "she" means next turn
            import scene_context
            scene_context.remember_mentions(db, narration, campaign, turn["seq"])
        except Exception:
            pass
    wdb.crash_point("after_commit_before_apply")
    wdb.apply_staged(campaign)                    # the record is on disk before anyone reads the narration
    wdb.crash_point("after_commit_before_send")
    sent = deliver(campaign)
    with wdb.reader(campaign) as db:
        turn = db.execute("SELECT * FROM turns WHERE turn_id=?", (turn_id,)).fetchone()
        return _turn_view(db, turn, finished=True, sent=sent, committed=wdb.get(db, "turn_record", turn_id))


BLOCK = ("<!-- unrolled:world -->", "<!-- /unrolled:world -->")


def _committed(db, turn_id: str) -> dict:
    """What this turn changed, by id: its actions and the events they applied."""
    actions, events = [], []
    for a in db.execute("SELECT action_id, intent, status, result FROM actions WHERE turn_id=? ORDER BY seq", (turn_id,)):
        if a["status"] != "done":
            continue
        intent = json.loads(a["intent"] or "{}")
        res = json.loads(a["result"] or "{}")
        actions.append({"action_id": a["action_id"], "action": intent.get("action"), "actor": intent.get("actor")})
        for e in ((res.get("data") or {}).get("applied") or []) + [v.get("event_id") for v in res.get("visible_events") or []]:
            if e and e not in events:
                events.append(e)
    return {"actions": actions, "events": events}


def world_block(campaign: str, db, turn_id: str, record: dict) -> str:
    """The engine's part of state.md: what is true in world.db now, in a few lines the GM and any agent can read."""
    import scheduler
    camp = paths.find_campaign(campaign)
    lines = [BLOCK[0], "*Written by the Unrolled Engine from world.db when a turn finishes. Edits inside this block are "
                       "replaced: change the world with engine actions.*"]
    try:
        cal = json.loads((camp / "calendar.json").read_text(encoding="utf-8"))
        now = scheduler._minutes_of(cal)
        lines.append(f"- **In-world time:** {scheduler._calendar_module()._format_date(cal)}")
    except (OSError, ValueError):
        now = None
    due = [r for r in db.execute("SELECT event_id, due_minute, effect FROM events WHERE status='pending' "
                                 "AND due_minute IS NOT NULL ORDER BY due_minute, event_id LIMIT 300")
           if json.loads(r["effect"]).get("text")][:5]   # what someone set in motion, not the world's own rhythm
    if due:
        def when(m):
            if now is None:
                return f"minute {m}"
            h = max(0, m - now) // 60
            return f"in {h // 24}d {h % 24}h" if h >= 24 else f"in {h}h"
        lines.append("- **Coming up (GM only):** " + "; ".join(
            f"{when(r['due_minute'])}: {json.loads(r['effect'])['text']} ({r['event_id']})"
            for r in due))
    shut = [f"{k} {v.get('access')}" + (f" ({v['reason']})" if v.get("reason") else "")
            for k, v in sorted(wdb.all_of(db, "route").items()) if v.get("access") not in (None, "open")]
    if shut:
        lines.append("- **Roads:** " + "; ".join(shut))
    low = []
    for k, m in sorted(wdb.all_of(db, "market").items()):
        for item, n in sorted((m.get("stock") or {}).items()):
            want = int((m.get("target") or {}).get(item, 0))
            if int(n) <= 0 or (want and int(n) * 5 <= want):
                low.append(f"{k}: {item} {n}")
    if low:
        lines.append("- **Markets running low:** " + "; ".join(low))
    for k, s in sorted(wdb.all_of(db, "settlement").items()):
        down = [a["label"] for a in s.get("assets", {}).values() if a.get("status") != "running"]
        bits = [f"day {s.get('day', 0)}"] + ([f"down: {', '.join(down)}"] if down else []) \
            + ([f"rota: {', '.join(s['rota'])}"] if s.get("rota") else []) + ([f"pacts: {', '.join(s['pacts'])}"] if s.get("pacts") else [])
        lines.append(f"- **{s.get('name', k)}:** " + "; ".join(bits))
    import mechanics
    if mechanics.summary(db):
        lines.append(mechanics.summary(db))
    acts = ", ".join(a["action"] or "?" for a in record["actions"])
    lines.append(f"- **Last engine turn:** {turn_id}: {acts}" + (f"; events {', '.join(record['events'][:8])}" if record["events"] else ""))
    lines.append(BLOCK[1])
    return "\n".join(lines)


def with_block(text: str, block: str) -> str:
    """state.md with the engine's block replaced, or put at the top of ## World State; every other line kept."""
    start, end = text.find(BLOCK[0]), text.find(BLOCK[1])
    if start != -1 and end > start:
        return text[:start] + block + text[end + len(BLOCK[1]):]
    head = text.find("## World State\n")
    if head != -1:
        cut = head + len("## World State\n")
        return text[:cut] + block + "\n" + text[cut:]
    flags = text.find("## Session Flags")           # Session Flags stays the last section: tools append to it
    if flags != -1:
        return text[:flags] + "## World State\n" + block + "\n\n" + text[flags:]
    return text.rstrip("\n") + "\n\n## World State\n" + block + "\n"


def narration_sent(campaign: str, text: str) -> "dict | None":
    """send.py just put a plain narration on the display: that closes the open turn, if nothing waits."""
    if not wdb.enabled(campaign) or not wdb.db_path(campaign).exists():
        return None
    return finish(campaign, text, already_sent=True)


def export_log(campaign: str) -> list:
    """Everything needed to play this campaign's engine turns again: per turn its input, the intents that were
    resolved (in order), the players' answers and the narration. No dice: they come back from the campaign's seed."""
    with wdb.reader(campaign) as db:
        if db is None:
            return []
        log = []
        for t in db.execute("SELECT * FROM turns ORDER BY seq"):
            inputs = db.execute("SELECT * FROM inputs WHERE turn_id=? ORDER BY rowid", (t["turn_id"],)).fetchall()
            acts = db.execute("SELECT * FROM actions WHERE turn_id=? ORDER BY seq", (t["turn_id"],)).fetchall()
            answers = db.execute("SELECT request_id, answer FROM requests WHERE turn_id=? AND status='answered' ORDER BY rowid",
                                 (t["turn_id"],)).fetchall()
            log.append({"turn_id": t["turn_id"], "input_id": inputs[0]["input_id"] if inputs else None,
                        "text": inputs[0]["text"] if inputs else "", "source": inputs[0]["source"] if inputs else "chat",
                        "intents": [{**json.loads(a["intent"]), "action_id": a["action_id"]} for a in acts],
                        "answers": [{"request_id": r["request_id"], "value": json.loads(r["answer"])["value"]} for r in answers],
                        "narration": t["narration"], "finished": t["status"] == "finished"})
        return log


def replay(campaign: str, log: list) -> dict:
    """Play a recorded log into `campaign` (a copy taken at the snapshot the log starts from).

    No model is asked anything and nothing is sent to a display: deliveries go to DNE_OUTBOX_LOG or nowhere.
    Compare world_db.state_hash of the result with the original's."""
    saved = os.environ.get("DNE_OUTBOX_LOG")
    os.environ.setdefault("DNE_OUTBOX_LOG", os.devnull)
    try:
        for entry in log:
            begin(campaign, entry["text"], input_id=entry["input_id"], source=entry.get("source", "chat"))
            pending = list(entry["answers"])
            for intent in entry["intents"]:
                view = resolve(campaign, [intent])
                while view.get("waiting") and pending:           # answer in the order the table did
                    want = {w["request_id"] for w in view["waiting"]}
                    hit = next((a for a in pending if a["request_id"] in want), None)
                    if hit is None:
                        break
                    pending.remove(hit)
                    view = answer(campaign, hit["request_id"], hit["value"])
            if entry.get("finished"):
                finish(campaign, entry.get("narration", ""))
    finally:
        if saved is None:
            os.environ.pop("DNE_OUTBOX_LOG", None)
    return {"turns": len(log), "state_hash": wdb.state_hash(campaign)}


def metrics(campaign: str) -> dict:
    """Numbers for a playtest: how long the table waited, how often the runner was skipped, how much of the world's
    own movement there was to narrate."""
    with wdb.reader(campaign) as db:
        if db is None:
            return {"turns": 0}
        turns = db.execute("SELECT * FROM turns ORDER BY seq").fetchall()
        waits = []
        for t in turns:
            sent = db.execute("SELECT COUNT(*) AS n FROM outbox WHERE turn_id=? AND kind='narration'", (t["turn_id"],)).fetchone()["n"]
            acts = db.execute("SELECT COUNT(*) AS n FROM actions WHERE turn_id=?", (t["turn_id"],)).fetchone()["n"]
            waits.append({"turn_id": t["turn_id"], "actions": acts, "closed_by_the_runner": bool(t["narration"]) or sent > 0})
        applied = db.execute("SELECT COUNT(*) AS n FROM events WHERE status='applied'").fetchone()["n"]
        cancelled = db.execute("SELECT COUNT(*) AS n FROM events WHERE status='cancelled'").fetchone()["n"]
        asked = db.execute("SELECT COUNT(*) AS n FROM requests").fetchone()["n"]
        stale = db.execute("SELECT COUNT(*) AS n FROM requests WHERE status='stale'").fetchone()["n"]
    finished = [w for w in waits if w["closed_by_the_runner"]]
    return {"turns": len(turns), "turns_closed_through_the_runner": len(finished),
            "turns_the_gm_narrated_around_the_runner": len(turns) - len(finished),
            "turns_with_no_engine_action": sum(1 for w in waits if not w["actions"]),
            "background_events_applied": applied, "events_cancelled_with_a_reason": cancelled,
            "questions_put_to_players": asked, "questions_left_stale": stale}


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
    sub.add_parser("log")
    sub.add_parser("metrics")
    rp = sub.add_parser("replay")
    rp.add_argument("--log", required=True, help="a file written by `log`")
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
        elif args.cmd == "log":
            out = export_log(args.campaign)
        elif args.cmd == "metrics":
            out = metrics(args.campaign)
        elif args.cmd == "replay":
            out = replay(args.campaign, json.loads(Path(args.log).read_text(encoding="utf-8")))
        else:
            out = finish(args.campaign, args.narration if args.narration is not None else sys.stdin.read())
    except (ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


def _load_modules() -> None:
    """Engine modules register their handlers on import (rest, travel, trade, …)."""
    for name in ("scene_context", "scheduler", "journey", "trade", "knowledge", "routine", "stakes", "table", "skirmish", "upkeep", "story", "community", "rules", "mechanics", "modules"):
        try:
            __import__(name)
        except ImportError:
            pass


_load_modules()

if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
