#!/usr/bin/env python3
"""
mechanics.py — Braid's building blocks as engine actions: track, pool, condition, bond, progress, table_roll.

Every module (composure, panic, doom, strings, vows, seasons, loop, realm, …) is built from these, never from a
second way to roll: a character's check is always `roll` (turn.py) graded by resolve.py. Records live in world.db
`things` (kinds track, pool, condition, bond, progress, step_up), so they persist, undo with the turn, and a resent
intent applies once (the turn runner keys an action by its intent). Engine campaigns only (world_engine: on, which
Braid campaigns always have); the actions work under any system.

Shared ids: a track or pool is (owner, id). The same id is the same track whatever module named it: the stress a
push marks is the stress panic reads. Numbers here (track 0-6, bond 0-5, usage die 1-2 steps down, progress ranks)
are our defaults, adjustable.

What a `roll` check reads from here (turn._check, core): conditions on the actor ({"approach": …}), {"push": true}
(+1, marks 1 stress), {"help": "<name>"} (+1 when that character has a bond with the actor). A token spent after the
roll ({"action": "pool", "id": "tokens", "step_up": true}) moves the result one step up through resolve().
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import paths  # noqa: E402
import turn  # noqa: E402
import world_db as wdb  # noqa: E402

TABLES = HERE.parent / "data" / "tables"
#: Braid's numbers (SKILL-core.md): harm and stress tracks, approaches, threats, XP.
BRAID = json.loads((HERE.parent / "data" / "braid.json").read_text(encoding="utf-8"))
DIE_STEPS = ("d12", "d10", "d8", "d6", "d4")      # a usage die rolls 1-2: one step down; on a d4 it is gone
CADENCES = ("scene", "session", "rest", "day")
#: Progress ranks: quarter-boxes marked per `mark` (a box is 4, the track 10 boxes = 40).
RANKS = {"easy": 12, "tough": 8, "hard": 4, "extreme": 2, "epic": 1}
#: A progress roll in story mode: the oracle's likelihood for 0..10 boxes.
PROGRESS_ODDS = ("no-way", "no-way", "unlikely", "unlikely", "50/50", "50/50", "likely", "likely",
                 "sure-thing", "sure-thing", "sure-thing")
LOG_KEEP = 20


def key_of(*parts) -> str:
    return "/".join(str(p).strip().casefold() for p in parts)


def done(data: dict, **extra) -> dict:
    return {"status": "done", "elapsed_minutes": 0, "data": data, **extra}


def error(msg: str) -> dict:
    return done({"error": msg})


def log_entry(rec: dict, entry: dict) -> None:
    rec["log"] = (rec.get("log") or [])[-(LOG_KEEP - 1):] + [entry]


# ── tables ────────────────────────────────────────────────────────────────────

def load_table(table) -> list:
    """A table's entries: an inline list, or data/tables/<name>.json (a JSON list, or {"entries": [...]})."""
    if isinstance(table, list):
        return [str(e) for e in table]
    name = str(table)
    if not re.fullmatch(r"[a-z0-9_-]+", name):
        raise ValueError(f"table name {name!r}: lower-case letters, digits, - and _ only")
    data = json.loads((TABLES / f"{name}.json").read_text(encoding="utf-8"))
    return [str(e) for e in (data if isinstance(data, list) else data.get("entries") or [])]


def roll_table(ctx, table, key: str) -> dict:
    """One entry, rolled once for this action under `key` (a retry or a replay reads the same entry)."""
    entries = load_table(table)
    if not entries:
        raise ValueError("the table is empty")
    n = ctx.roll(key, len(entries))[0]
    return {"table": table if isinstance(table, str) else "inline", "roll": n, "result": entries[n - 1]}


@turn.handler("table_roll")
def _table_roll(ctx, intent: dict) -> dict:
    """table_roll — the script rolls a table, so nobody opens one by hand.

    {"action": "table_roll", "table": "panic"}                       data/tables/panic.json
    {"action": "table_roll", "table": ["the lights fail", "a door slams", "someone screams"], "why": "the house stirs"}
    One entry, rolled once: resending it returns the same entry. Name a different `why` to roll the same table again
    in one turn."""
    try:
        return done({**roll_table(ctx, intent.get("table"), "table"), "why": str(intent.get("why", ""))})
    except (OSError, ValueError) as exc:
        return error(f"table_roll: {exc}")


# ── tracks ────────────────────────────────────────────────────────────────────

def _new_track(owner: str, tid: str, braid: bool = False) -> dict:
    """A fresh track at its minimum. Under Braid, `harm` and `stress` start with the rules' size and thresholds."""
    rule = BRAID["tracks"].get(tid.casefold(), {}) if braid else {}
    return {"owner": owner, "id": tid, "min": rule.get("min", 0), "max": rule.get("max", 6), "value": rule.get("min", 0),
            "thresholds": json.loads(json.dumps(rule.get("thresholds", []))), "log": []}


def _braid(ctx) -> bool:
    return paths.campaign_system(ctx.campaign) != "d20"


def _sync_conditions(ctx, rec: dict) -> None:
    """A threshold with a `condition` holds it while the track is at or past `at` (dir up) and drops it below."""
    for t in rec.get("thresholds") or []:
        cond = t.get("condition")
        if not cond:
            continue
        key = key_of(rec["owner"], cond["name"])
        down = t.get("dir") == "down"
        on = rec["value"] <= int(t["at"]) if down else rec["value"] >= int(t["at"])
        if on and wdb.get(ctx.db, "condition", key) is None:
            wdb.put(ctx.db, "condition", key, {"owner": rec["owner"], "name": cond["name"], "mod": int(cond.get("mod", 0)),
                                                "approaches": list(cond.get("approaches") or []), "clears": "",
                                                "note": f"{rec['id']} {'≤' if down else '≥'} {t['at']}"})
        elif not on and wdb.get(ctx.db, "condition", key) is not None:
            wdb.delete(ctx.db, "condition", key)


def _crossed(ctx, rec: dict, before: int) -> list:
    """Thresholds this change crossed: up = from below `at` to `at` or more; down = from above to `at` or less.
    Staying beyond fires nothing; coming back and crossing again fires again."""
    out, after = [], rec["value"]
    for t in rec.get("thresholds") or []:
        at, down = int(t["at"]), t.get("dir") == "down"
        if (before > at >= after) if down else (before < at <= after):
            hit = {"at": at, "dir": "down" if down else "up", "note": str(t.get("note", ""))}
            if t.get("table"):
                try:
                    hit.update(roll_table(ctx, t["table"], f"{key_of(rec['owner'], rec['id'])}@{at}{hit['dir']}"))
                except (OSError, ValueError) as exc:
                    hit["error"] = f"table: {exc}"
            out.append(hit)
    return out


def change_track(ctx, owner: str, tid: str, *, mark: int = 0, set_to=None, why: str = "", define: "dict | None" = None) -> dict:
    """Change one track (created with defaults if new) and store it. Returns the record plus `crossed`."""
    key = key_of(owner, tid)
    rec = wdb.get(ctx.db, "track", key)
    new = rec is None
    shaped = any(k in (define or {}) for k in ("min", "max", "thresholds"))
    rec = rec or _new_track(owner, tid, _braid(ctx) and not shaped)   # an enemy's `max` is its own track, no PC thresholds
    for field in ("min", "max"):
        if field in (define or {}):
            rec[field] = int(define[field])
    if "thresholds" in (define or {}):
        rec["thresholds"] = [{"at": int(t["at"]), "dir": "down" if t.get("dir") == "down" else "up",
                              **({"note": str(t["note"])} if t.get("note") else {}),
                              **({"table": t["table"]} if t.get("table") else {}),
                              **({"condition": dict(t["condition"])} if isinstance(t.get("condition"), dict) else {})}
                             for t in define["thresholds"]]
    before = rec["value"]
    if set_to is not None:
        rec["value"] = int(set_to)
    rec["value"] = max(rec["min"], min(rec["max"], rec["value"] + int(mark)))
    # a track's starting value (set or defined when it is created) crosses nothing; a first mark from the minimum does
    crossed = [] if new and (shaped or set_to is not None) else _crossed(ctx, rec, before)
    _sync_conditions(ctx, rec)
    if rec["value"] != before or crossed:
        log_entry(rec, {"from": before, "to": rec["value"], "why": why, "turn": ctx.turn_id,
                   **({"crossed": [c["at"] for c in crossed]} if crossed else {})})
    wdb.put(ctx.db, "track", key, rec)
    return {**{k: v for k, v in rec.items() if k != "log"}, "crossed": crossed}


@turn.handler("track")
def _track(ctx, intent: dict) -> dict:
    """track — a numbered track on a character (or "party"): stress, harm, composure, doom, supply, …

    {"action": "track", "owner": "Mira", "id": "resolve", "min": 0, "max": 10, "set": 10,
     "thresholds": [{"at": 3, "dir": "down", "note": "a lasting fear", "table": "fears"}, {"at": 0, "dir": "down"}]}
    (a module's own track, such as composure, comes from `modules apply`: do not define it by hand)
    {"action": "track", "owner": "Mira", "id": "stress", "mark": 2, "why": "the thing in the cellar"}   (mark -1 heals)
    {"action": "track", "owner": "Mira", "id": "stress"}          read it; {"remove": true} drops it
    New tracks run 0-6 unless min/max say otherwise. Same owner + id = the same track, whichever module uses it.
    A threshold fires when a change crosses it (dir up: reaches `at` from below; down: from above), once per
    crossing: the reply's `crossed` carries its note and, if it names a table (data/tables/<name>.json or an inline
    list), the entry the script rolled. Narrate that. Sending the same intent again in a turn applies it once; to
    mark twice in one turn give each a different `why`."""
    owner, tid = str(intent.get("owner") or "party").strip(), str(intent.get("id", "")).strip()
    if not tid:
        return error("track needs an id (stress, harm, composure, …)")
    if intent.get("remove"):
        wdb.delete(ctx.db, "track", key_of(owner, tid))
        return done({"removed": f"{owner} {tid}"}, refresh="clocks")
    try:
        rec = change_track(ctx, owner, tid, mark=int(intent.get("mark", 0)), set_to=intent.get("set"),
                           why=str(intent.get("why", "")), define=intent)
    except (KeyError, TypeError, ValueError) as exc:
        return error(f"track: {exc}")
    events = [{"type": "track", "recipient": "party", "text": f"{owner} {tid}: {rec['value']}/{rec['max']}"}]
    events += [{"type": "threshold", "recipient": "dm",
                "text": f"{owner} {tid} crossed {c['at']}: " + "; ".join(x for x in (c["note"], c.get("result", "")) if x)}
               for c in rec["crossed"]]
    return done(rec, refresh="clocks", visible_events=events)


# ── pools (points, usage dice) ────────────────────────────────────────────────

def _last_check(ctx, actor: str, of: "str | None") -> "tuple[str, dict] | tuple[None, None]":
    """The latest graded Braid check (a `roll` or a progress roll) by `actor`, or the action named `of`."""
    rows = ctx.db.execute("SELECT a.action_id, a.result FROM actions a JOIN turns t ON a.turn_id = t.turn_id "
                          "WHERE a.status = 'done' ORDER BY t.seq DESC, a.seq DESC LIMIT 200").fetchall()
    for r in rows:
        data = (json.loads(r["result"] or "{}").get("data") or {})
        if of and r["action_id"] != of:
            continue
        if data.get("spec") and data.get("degree") and (of or str(data.get("actor", "")).casefold() == actor.casefold()):
            return r["action_id"], data
        if not of and data.get("degree") and "check" not in data and \
                str(data.get("actor") or data.get("by") or "").casefold() == actor.casefold():
            return None, None        # their latest check was a judge, flashback or bargain: its outcome is already settled
    return None, None


def _step_up(ctx, rec: dict, intent: dict) -> dict:
    """Spend from this pool to move the actor's last check one step up the ladder, through resolve()."""
    import paths
    import resolve as checks
    actor = str(intent.get("actor") or rec["owner"])
    aid, data = _last_check(ctx, actor, intent.get("of"))
    if not aid:
        return error(f"no graded check by {actor} to step up (a `roll` check or a progress roll, System core or story)")
    cost = int(intent.get("spend", 1))
    if rec["value"] < cost:
        return error(f"{rec['owner']} has {rec['value']} {rec['id']}: not enough to spend {cost}")
    before = wdb.get(ctx.db, "step_up", aid) or {"steps": 0, "degree": data["degree"]}
    if before["degree"] == checks.LADDER[-1]:
        return error(f"{actor}'s {data.get('label') or 'check'} is already a critical success")
    steps = before["steps"] + 1
    graded = checks.resolve(paths.campaign_system(ctx.campaign), data["spec"], None, data["dice"], step_up=steps,
                            likelihood=str(data.get("likelihood") or "50/50"), chaos=int(data.get("chaos", checks.oracle.CHAOS_DEFAULT)))
    rec["value"] -= cost
    log_entry(rec, {"spent": cost, "why": f"step up {aid}", "turn": ctx.turn_id})
    wdb.put(ctx.db, "pool", key_of(rec["owner"], rec["id"]), rec)
    wdb.put(ctx.db, "step_up", aid, {"steps": steps, "degree": graded["degree"]})
    return done({"owner": rec["owner"], "id": rec["id"], "value": rec["value"], "check": aid, "actor": actor,
                  "was": data["degree"], "degree": graded["degree"], "passed": graded["passed"]},
                 refresh="clocks", visible_events=[{"type": "roll", "recipient": "party",
                                                    "text": f"{actor} spends {cost} {rec['id'].removesuffix('s') if cost == 1 else rec['id']}: {graded['degree']}"}])


def _cadence(ctx, cadence: str) -> dict:
    """A new scene / session / rest / day: refill the pools and clear the conditions that run on it."""
    refilled, cleared = [], []
    for key, rec in wdb.all_of(ctx.db, "pool").items():
        if rec.get("cadence") == cadence and rec["value"] != rec["max"]:
            rec["value"] = rec["max"]
            log_entry(rec, {"refill": cadence, "turn": ctx.turn_id})
            wdb.put(ctx.db, "pool", key, rec)
            refilled.append(f"{rec['owner']} {rec['id']}")
    for key, rec in wdb.all_of(ctx.db, "condition").items():
        if rec.get("clears") == cadence:
            wdb.delete(ctx.db, "condition", key)
            cleared.append(f"{rec['owner']}: {rec['name']}")
    return done({"cadence": cadence, "refilled": refilled, "cleared": cleared}, refresh="clocks")


@turn.handler("pool")
def _pool(ctx, intent: dict) -> dict:
    """pool — points to spend that come back on a rhythm (tokens, luck, focus), or a usage die (torches, ammo, fuel).

    {"action": "pool", "owner": "Mira", "id": "tokens", "max": 3, "set": 3, "cadence": "session"}   define
    {"action": "pool", "owner": "Mira", "id": "tokens", "gain": 1}     {"spend": 1, "why": "…"}   (refused if short)
    {"action": "pool", "owner": "Mira", "id": "tokens", "step_up": true}   spend 1 (or `spend`) to move Mira's last
        check one step up the ladder (failure → success at a cost …), through resolve(); `of: <action_id>` names it
    {"action": "pool", "refill": "scene"}       a new scene|session|rest|day: refills every pool with that cadence
        and clears every condition that `clears` on it
    {"action": "pool", "owner": "party", "id": "torches", "die": "d8"}   a usage die (d12 d10 d8 d6 d4)
    {"action": "pool", "owner": "party", "id": "torches", "use": true}   the script rolls it: 1-2 steps it down one
        size; a 1-2 on a d4 and it is gone (set a new `die` to restock)
    No op reads the pool. Sending the same intent again in a turn applies it once; spend twice with different `why`."""
    if isinstance(intent.get("refill"), str) and not intent.get("id"):
        if intent["refill"] not in CADENCES:
            return error(f"refill: one of {', '.join(CADENCES)}")
        return _cadence(ctx, intent["refill"])
    owner, pid = str(intent.get("owner") or "party").strip(), str(intent.get("id", "")).strip()
    if not pid:
        return error("pool needs an id (tokens, luck, torches, …)")
    key = key_of(owner, pid)
    if intent.get("remove"):
        wdb.delete(ctx.db, "pool", key)
        return done({"removed": f"{owner} {pid}"}, refresh="clocks")
    rec = wdb.get(ctx.db, "pool", key) or {"owner": owner, "id": pid, "value": 0, "max": 3, "cadence": None,
                                           "die": None, "log": []}
    if intent.get("cadence") not in (None, *CADENCES):
        return error(f"cadence: one of {', '.join(CADENCES)}")
    if intent.get("die") is not None and intent["die"] not in DIE_STEPS:
        return error(f"die: one of {', '.join(DIE_STEPS)}")
    for field in ("max", "cadence", "die"):
        if field in intent:
            rec[field] = int(intent[field]) if field == "max" else intent[field]
    if intent.get("die"):
        rec["gone"] = False
    if intent.get("step_up"):
        return _step_up(ctx, rec, intent)
    data = {}
    if intent.get("use"):
        if not rec.get("die"):
            return error(f"{owner} {pid} has no usage die left")
        was = rec["die"]
        n = ctx.roll("use", int(was[1:]))[0]
        if n <= 2:
            i = DIE_STEPS.index(was) + 1
            rec["die"] = DIE_STEPS[i] if i < len(DIE_STEPS) else None
        rec["gone"] = rec["die"] is None
        data = {"rolled": n, "was": was}
        log_entry(rec, {"use": was, "rolled": n, "turn": ctx.turn_id})
    if "set" in intent:
        rec["value"] = int(intent["set"])
    if intent.get("gain"):
        rec["value"] += int(intent["gain"])
    if intent.get("spend"):
        cost = int(intent["spend"])
        if rec["value"] < cost:
            return error(f"{owner} has {rec['value']} {pid}: not enough to spend {cost}")
        rec["value"] -= cost
        log_entry(rec, {"spent": cost, "why": str(intent.get("why", "")), "turn": ctx.turn_id})
    rec["value"] = max(0, min(rec["max"], rec["value"]))
    wdb.put(ctx.db, "pool", key, rec)
    shown = rec["die"] or ("gone" if rec.get("gone") else f"{rec['value']}/{rec['max']}")
    return done({**{k: v for k, v in rec.items() if k != "log"}, **data}, refresh="clocks",
                 visible_events=[{"type": "pool", "recipient": "party", "text": f"{owner} {pid}: {shown}"}])


# ── conditions ────────────────────────────────────────────────────────────────

def conditions_on(db, actor: str, approach) -> list:
    """The conditions that change `actor`'s roll with `approach` (a condition with no approaches applies to all)."""
    out = []
    for rec in wdb.all_of(db, "condition").values():
        listed = [a.casefold() for a in rec.get("approaches") or []]
        if rec["owner"].casefold() == actor.casefold() and rec.get("mod") and \
                (not listed or str(approach or "").casefold() in listed):
            out.append(rec)
    return out


@turn.handler("condition")
def _condition(ctx, intent: dict) -> dict:
    """condition — a named state on a character that changes their rolls until it clears (Shaken, Bleeding, Wanted).

    {"action": "condition", "owner": "Mira", "name": "Shaken", "mod": -1, "approaches": ["heart", "wits"],
     "clears": "scene", "note": "saw the body"}
    {"action": "condition", "owner": "Mira", "name": "Shaken", "clear": true}
    {"action": "condition", "owner": "Mira"}          list Mira's conditions
    `mod` applies to Mira's `roll` checks with a listed `approach` (no approaches = every roll). `clears`: scene,
    session, rest or day go when `{"action": "pool", "refill": "<that>"}` runs; anything else ("treated by a
    healer") is cleared by hand. Not the weather (`conditions`)."""
    owner, name = str(intent.get("owner") or "").strip(), str(intent.get("name", "")).strip()
    if not owner:
        return error("condition needs an owner")
    if not name:
        mine = [r for r in wdb.all_of(ctx.db, "condition").values() if r["owner"].casefold() == owner.casefold()]
        return done({"owner": owner, "conditions": mine})
    key = key_of(owner, name)
    if intent.get("clear"):
        had = wdb.get(ctx.db, "condition", key)
        wdb.delete(ctx.db, "condition", key)
        return done({"owner": owner, "name": name, "cleared": had is not None})
    rec = wdb.get(ctx.db, "condition", key) or {"owner": owner, "name": name, "mod": 0, "approaches": [],
                                                "clears": "", "note": ""}
    try:
        for field, cast in (("mod", int), ("approaches", lambda v: [v] if isinstance(v, str) else [str(a) for a in v]), ("clears", str), ("note", str)):
            if field in intent:
                rec[field] = cast(intent[field])
    except (TypeError, ValueError) as exc:
        return error(f"condition: {exc}")
    wdb.put(ctx.db, "condition", key, rec)
    return done(rec, visible_events=[{"type": "condition", "recipient": "party", "text": f"{owner} is {name}"}])


# ── bonds ─────────────────────────────────────────────────────────────────────

def bond_of(db, a: str, b: str) -> "dict | None":
    return wdb.get(db, "bond", "|".join(sorted((a.strip().casefold(), b.strip().casefold()))))


@turn.handler("bond")
def _bond(ctx, intent: dict) -> dict:
    """bond — what ties two characters (PC or NPC): a shared value 0-5 and points each side holds on the other.

    {"action": "bond", "a": "Mira", "b": "Theo", "set": 2, "note": "grew up on the same street"}
    {"action": "bond", "a": "Mira", "b": "Theo", "mark": 1, "why": "he took the blame for her"}
    {"action": "bond", "a": "Mira", "b": "Theo", "gain": 1}     Mira gains a point on Theo; {"spend": 1} uses one
    {"action": "bond", "a": "Mira", "b": "Theo"}                read it
    A bond of 1 or more lets one help the other: {"action": "roll", …, "help": "Theo"} is +1, and Theo shares what goes
    wrong. Points are what drama modules spend (a hold on someone, a favour owed). Refused if short."""
    a, b = str(intent.get("a", "")).strip(), str(intent.get("b", "")).strip()
    if not a or not b or a.casefold() == b.casefold():
        return error("bond needs two different characters, a and b")
    key = "|".join(sorted((a.casefold(), b.casefold())))
    rec = wdb.get(ctx.db, "bond", key) or {"between": sorted((a, b), key=str.casefold), "value": 0, "max": 5,
                                           "points": {}, "note": "", "log": []}
    if "max" in intent:
        rec["max"] = int(intent["max"])
    if "note" in intent:
        rec["note"] = str(intent["note"])
    before = rec["value"]
    if "set" in intent:
        rec["value"] = int(intent["set"])
    rec["value"] = max(0, min(rec["max"], rec["value"] + int(intent.get("mark", 0))))
    held = int(rec["points"].get(a.casefold(), 0))
    if intent.get("spend"):
        if held < int(intent["spend"]):
            return error(f"{a} holds {held} on {b}: not enough to spend {intent['spend']}")
        held -= int(intent["spend"])
    held += int(intent.get("gain", 0))
    rec["points"][a.casefold()] = max(0, held)
    if rec["value"] != before or intent.get("spend") or intent.get("gain"):
        log_entry(rec, {"by": a, "from": before, "to": rec["value"], "gain": intent.get("gain"), "spend": intent.get("spend"),
                   "why": str(intent.get("why", "")), "turn": ctx.turn_id})
    wdb.put(ctx.db, "bond", key, rec)
    return done({k: v for k, v in rec.items() if k != "log"})


# ── progress ──────────────────────────────────────────────────────────────────

def progress_spec(boxes: int) -> str:
    """A progress roll is an ordinary Braid check whose modifier is the progress: 0-1 boxes -2 … 10 boxes +3."""
    return f"2d6{boxes // 2 - 2:+d}"


@turn.handler("progress")
def _progress(ctx, intent: dict) -> dict:
    """progress — a 10-box track toward a long goal (a vow, a journey, a case, a cultivation stage).

    {"action": "progress", "owner": "party", "name": "Find the heir", "rank": "tough"}
    {"action": "progress", "owner": "party", "name": "Find the heir", "mark": 1, "why": "the ledger"}
    {"action": "progress", "owner": "party", "name": "Find the heir", "roll": true, "actor": "Mira"}
    Rank sets how much one mark fills: easy 3 boxes, tough 2, hard 1, extreme half a box, epic a quarter. The roll
    is the usual check through resolve(), the boxes as its modifier (0-1 boxes -2, 2-3 -1, 4-5 +0, 6-7 +1, 8-9 +2,
    10 +3); in story mode the boxes set the oracle's odds. Any result can be stepped up with a token. Not under 5e.
    {"remove": true} drops it. The same intent sent again in a turn applies once."""
    import paths
    owner, name = str(intent.get("owner") or "party").strip(), str(intent.get("name", "")).strip()
    if not name:
        return error("progress needs a name")
    key = key_of(owner, name)
    if intent.get("remove"):
        wdb.delete(ctx.db, "progress", key)
        return done({"removed": f"{owner} {name}"}, refresh="clocks")
    rec = wdb.get(ctx.db, "progress", key)
    if intent.get("roll"):                        # alone: the handler runs again when the player's dice arrive
        if not rec:
            return error(f"no progress track {name!r} for {owner}")
        system = paths.campaign_system(ctx.campaign)
        if system == "d20":
            return error("progress rolls are Braid checks (System: core or story)")
        boxes = rec["ticks"] // 4
        out = turn._check(ctx, {"actor": intent.get("actor") or owner, "spec": progress_spec(boxes),
                                "label": f"progress: {name}", "likelihood": PROGRESS_ODDS[boxes]}, system)
        if out.get("status") == "done" and "degree" in (out.get("data") or {}):
            out["data"].update(progress=name, boxes=boxes)
        return out
    rec = rec or {"owner": owner, "name": name, "rank": "tough", "ticks": 0, "log": []}
    if "rank" in intent:
        if intent["rank"] not in RANKS:
            return error(f"rank: one of {', '.join(RANKS)}")
        rec["rank"] = intent["rank"]
    if intent.get("mark"):
        before = rec["ticks"]
        rec["ticks"] = max(0, min(40, before + int(intent["mark"]) * RANKS[rec["rank"]]))
        log_entry(rec, {"from": before, "to": rec["ticks"], "why": str(intent.get("why", "")), "turn": ctx.turn_id})
    wdb.put(ctx.db, "progress", key, rec)
    boxes = rec["ticks"] // 4
    return done({**{k: v for k, v in rec.items() if k != "log"}, "boxes": boxes, "full": boxes >= 10},
                 refresh="clocks", visible_events=[{"type": "progress", "recipient": "party",
                                                    "text": f"{name}: {boxes}/10"}])


# ── what a `roll` check reads ─────────────────────────────────────────────────

def edged(ctx, intent: dict, system: str, actor: str, spec) -> dict:
    """The one step every Braid check (roll, judge, flashback, bargain, search) takes before its dice: the actor's
    conditions, a push, help, a sheet label ("use_label": +1) and a dangerous foe ("against": threat 4-5 is -1), read
    from the intent or its `roll` dict. With no spec, a core check takes 2d6 + the approach on the actor's sheet. Returns {"spec", "mod", "notes", "push"} or
    {"error"}. A d20 check is returned untouched."""
    if system == "d20":
        return {"spec": spec, "mod": 0, "notes": [], "push": False}
    roll = intent.get("roll") if isinstance(intent.get("roll"), dict) else {}
    asked = {k: roll.get(k, intent.get(k)) for k in ("approach", "push", "help", "use_label", "against")}
    import resolve as checks
    if system == "core" and not spec and asked["approach"]:
        import sheet
        base = sheet.approach(ctx.campaign, actor, asked["approach"])
        if base is None:
            return {"error": f"no approach {asked['approach']!r} on {actor}'s sheet: send a spec (\"2d6+1\") or "
                             f"one of {', '.join(BRAID['approaches'])}"}
        spec = f"{checks.CORE_DICE}{base:+d}"
    edge = _modifiers(ctx, asked, system, actor)
    if edge.get("error"):
        return edge
    if edge["mod"] and system == "core":
        spec = f"{checks.CORE_DICE}{checks.dice_for(system, spec)[2] + edge['mod']:+d}"
    return {**edge, "spec": spec, "push": bool(asked["push"])}


def _modifiers(ctx, intent: dict, system: str, actor: str) -> dict:
    """The modifier conditions, a push and help add to `actor`'s check ({"mod", "notes"} or {"error"}). Reads only:
    the push's stress is marked by `push()` once the roll is done (the handler runs again when a player's dice come)."""
    if system == "story":
        if intent.get("push") or intent.get("help") or intent.get("use_label"):
            return {"error": "story mode has no modifiers to push, help or add a label with: spend a token afterwards to "
                             "step the answer up ({\"action\": \"pool\", \"id\": \"tokens\", \"step_up\": true})"}
        return {"mod": 0, "notes": []}
    mod, notes = 0, []
    for c in conditions_on(ctx.db, actor, intent.get("approach")):
        mod += int(c["mod"])
        notes.append(f"{c['name']} {int(c['mod']):+d}")
    if intent.get("push"):
        st = wdb.get(ctx.db, "track", key_of(actor, "stress")) or _new_track(actor, "stress", True)
        if st["value"] >= st["max"]:
            return {"error": f"{actor}'s stress is full ({st['value']}/{st['max']}): no push left"}
        mod += 1
        notes.append("pushed +1 (1 stress)")
    helper = str(intent.get("help") or "").strip()
    if helper:
        b = bond_of(ctx.db, helper, actor)
        if not b or b["value"] < 1:
            return {"error": f"{helper} has no bond with {actor}: help needs one ({{\"action\": \"bond\", …}})"}
        mod += 1
        notes.append(f"{helper} helps +1 (and shares what goes wrong)")
    wanted = str(intent.get("use_label") or "").strip()
    if wanted:                                   # one label per roll, and only one the sheet holds
        import sheet
        try:
            have = sheet.parse(sheet.find(ctx.campaign, actor).read_text(encoding="utf-8"))["labels"]
        except (OSError, ValueError, LookupError):
            have = []
        name = next((x.split(":")[0].strip() for x in have
                     if wanted.casefold() in (x.casefold(), x.split(":")[0].strip().casefold())), None)
        if name is None:
            return {"error": f"no label {wanted!r} on {actor}'s sheet" + (f": one of {', '.join(x.split(':')[0].strip() for x in have)}" if have else "")}
        mod += 1
        notes.append(f"label {name} +1")
    foe_name = str(intent.get("against") or "").strip()
    if foe_name:
        foe = wdb.get(ctx.db, "foe", foe_name.casefold())
        if not foe:
            return {"error": f"no foe {foe_name!r} on record (bring it in with the `foe` action, or fold its -1 into the spec)"}
        if int(foe["threat"]) >= 4:
            mod -= 1
            notes.append(f"against {foe['name']} (threat {foe['threat']}) -1")
    return {"mod": mod, "notes": notes}


def push(ctx, actor: str) -> list:
    """Mark the 1 stress a push costs; returns the thresholds it crossed."""
    return change_track(ctx, actor, "stress", mark=1, why="pushed a roll")["crossed"]


# ── read side: the display panel and the state.md line ────────────────────────

def _row(name: str, value: int, lo: int, hi: int) -> dict:
    """One display segment row: the panel shows 2-12 segments, so a longer track is scaled to 10 with its number."""
    span = max(1, hi - lo)
    if span <= 12:
        return {"name": name[:60], "filled": value - lo, "size": max(2, span)}
    return {"name": f"{name} {value}/{hi}"[:60], "filled": round((value - lo) * 10 / span), "size": 10}


def board(campaign: str) -> list:
    """Tracks, pools and progress as clock rows [{name, filled, size}] for the display's clock panel."""
    with wdb.reader(campaign) as db:
        if db is None:
            return []
        tracks, pools, prog = wdb.all_of(db, "track"), wdb.all_of(db, "pool"), wdb.all_of(db, "progress")
    rows = [_row(f"{t['owner']} {t['id']}", t["value"], t["min"], t["max"]) for t in tracks.values()]
    for p in pools.values():
        if p.get("die") or p.get("gone"):
            left = len(DIE_STEPS) - DIE_STEPS.index(p["die"]) if p.get("die") else 0
            rows.append({"name": f"{p['owner']} {p['id']} {p['die'] or 'gone'}"[:60], "filled": left, "size": len(DIE_STEPS)})
        else:
            rows.append(_row(f"{p['owner']} {p['id']}", p["value"], 0, p["max"]))
    rows += [{"name": f"{g['name']} ({g['rank']})"[:60], "filled": g["ticks"] // 4, "size": 10} for g in prog.values()]
    return rows


def summary(db) -> str:
    """One state.md line with every track, pool, condition, bond and progress; empty when there are none."""
    bits = [f"{t['owner']} {t['id']} {t['value']}/{t['max']}" for t in wdb.all_of(db, "track").values()]
    bits += [f"{p['owner']} {p['id']} " + (p["die"] if p.get("die") else f"{p['value']}/{p['max']}")
             for p in wdb.all_of(db, "pool").values()]
    bits += [f"{c['owner']} {c['name']}" + (f" {int(c['mod']):+d}" if c.get("mod") else "")
             + (f" (clears: {c['clears']})" if c.get("clears") else "") for c in wdb.all_of(db, "condition").values()]
    bits += [f"{' & '.join(b['between'])} bond {b['value']}" for b in wdb.all_of(db, "bond").values()]
    bits += [f"{g['name']} {g['ticks'] // 4}/10 boxes" for g in wdb.all_of(db, "progress").values()]
    return "- **Tracks and pools:** " + "; ".join(bits) if bits else ""
