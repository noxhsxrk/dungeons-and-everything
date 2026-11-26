#!/usr/bin/env python3
"""mod_loop.py — the loop module (data/modules/loop.json, rules in .md): one day that plays again.

`start` copies the world as it stands (the store's events and records, and the world files) into the loop's record:
that copy is the seed. `reset` puts the seed back, so the scheduler replays the same day (each event rolls from the
campaign seed and its own id, so it comes out the same). What carries over: the loop's own record (knowledge and
anchors), its two tracks (loop_break, loop_fatigue), and records that are not the world (memories, roles, the
status window, achievements, the turn runner's bookkeeping). Character sheets (prose) are the GM's to rewind."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mechanics  # noqa: E402
import modules  # noqa: E402
import paths  # noqa: E402
import turn  # noqa: E402

#: Records a reset never rewinds: the loop itself, the minds and secrets that ride along, the turn runner's books.
CARRY_KINDS = ("loop", "memory", "roles", "status_seen", "achievement", "turn_record", "mention", "step_up")
CARRY_TRACKS = ("party/loop_break", "party/loop_fatigue")
#: World files the day is made of (state.md is the GM's prose and the engine block it rewrites at every finish).
FILES = ("calendar.json", "tracker.json", "world-map.json", "factions.json")


def carried(kind: str, id: str, extra=()) -> bool:
    """`extra`: track, pool or progress ids the GM chose to carry at `start` ("carry": ["realm", "tokens"])."""
    return kind in CARRY_KINDS or (kind == "track" and id in CARRY_TRACKS) or \
        (kind in ("track", "pool", "progress") and id.rsplit("/", 1)[-1] in extra)


def capture(ctx, extra=()) -> dict:
    """The seed: every event row, every record that is world, and the world files as they are now."""
    db, camp = ctx.db, paths.find_campaign(ctx.campaign)
    events = [dict(r) for r in db.execute("SELECT * FROM events ORDER BY event_id")]
    things = [[r["kind"], r["id"], r["data"]] for r in db.execute("SELECT kind, id, data FROM things ORDER BY kind, id")
              if not carried(r["kind"], r["id"], extra)]
    files = {rel: (camp / rel).read_text(encoding="utf-8") for rel in FILES if (camp / rel).is_file()}
    return {"events": events, "things": things, "files": files}


def restore(ctx, seed: dict, extra=()) -> dict:
    """Put the seed back in the store; returns the files to write back (handlers never write files themselves)."""
    db = ctx.db
    db.execute("DELETE FROM events")
    for row in seed["events"]:
        cols = list(row)
        db.execute(f"INSERT INTO events ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", [row[c] for c in cols])
    for r in db.execute("SELECT kind, id FROM things").fetchall():
        if not carried(r["kind"], r["id"], extra):
            db.execute("DELETE FROM things WHERE kind=? AND id=?", (r["kind"], r["id"]))
    db.executemany("INSERT INTO things VALUES (?, ?, ?)", [tuple(t) for t in seed["things"]])
    # shortcut: a world file made during the loop (absent from the seed) stays; none of FILES is new mid-story
    return dict(seed["files"])


def _record(ctx) -> dict:
    import world_db as wdb
    return wdb.get(ctx.db, "loop", "party") or {"loop": 0, "seed": None, "knowledge": [], "anchors": []}


def _view(rec: dict, **extra) -> dict:
    return {"loop": rec["loop"], "started": rec["seed"] is not None, "knowledge": rec["knowledge"],
            "anchors": rec["anchors"], **extra}


@turn.handler("loop")
@modules.requires("loop")
def _loop(ctx, intent: dict) -> dict:
    """loop — the day that plays again (module loop).

    {"action": "loop", "start": true}             the seed: the world as it stands now is the morning every loop
                                                  wakes to ("restart": true takes a new seed later)
        "carry": ["realm", "tokens"] on start/restart: those track, pool or vow ids (any owner) also carry
    {"action": "loop", "reset": true, "why": "Mira fell from the tower"}   back to the seed: events, records and
        world files rewind; knowledge, anchors, loop_break and loop_fatigue stay. Each reset marks 1 fatigue; every
        3rd fatigue (default) the script crosses out one knowledge entry it picks. Refused once loop_break is full.
    {"action": "loop", "learn": "Ada rings the bell at nine"}   knowledge that carries ("forget": "<text>" drops one)
    {"action": "loop", "anchor": "the silver key"}    an item that carries (3 at most, default; "drop": "<name>")
    {"action": "loop"}                            read it
    Escape progress: {"action": "track", "owner": "party", "id": "loop_break", "mark": 1, "why": "learned why"}."""
    import world_db as wdb
    nums = modules.load("loop")["numbers"]
    modules.ensure(ctx, "loop", [])
    rec, events = _record(ctx), []
    if intent.get("start") or intent.get("restart"):
        if rec["seed"] is not None and not intent.get("restart"):
            return mechanics.error("the loop already has its seed: send \"restart\": true to take a new one")
        rec["carry"] = sorted({str(c).strip().casefold() for c in intent.get("carry") or [] if str(c).strip()})
        rec["seed"] = capture(ctx, rec["carry"])
        rec["loop"] = max(rec["loop"], 1)
        events.append({"type": "loop", "recipient": "party", "text": f"The day is set. Loop {rec['loop']} begins."})
    elif intent.get("reset"):
        if rec["seed"] is None:
            return mechanics.error("no seed yet: send {\"action\": \"loop\", \"start\": true} at the loop's first morning")
        brk = wdb.get(ctx.db, "track", "party/loop_break")
        if brk and brk["value"] >= brk["max"]:
            return mechanics.error("the loop is broken (loop_break is full): tomorrow comes, nothing resets")
        writes = restore(ctx, rec["seed"], rec.get("carry") or ())
        rec["loop"] += 1
        fat = mechanics.change_track(ctx, "party", "loop_fatigue", mark=int(nums["fatigue_per_loop"]),
                                     why=str(intent.get("why") or "the day began again"))
        forgot = None
        if rec["knowledge"] and fat["value"] % int(nums["forget_every"]) == 0:
            forgot = rec["knowledge"].pop(ctx.roll("forget", len(rec["knowledge"]))[0] - 1)
        wdb.put(ctx.db, "loop", "party", rec)
        events.append({"type": "loop", "recipient": "party",
                       "text": f"The day begins again: loop {rec['loop']}. Fatigue {fat['value']}/{fat['max']}."
                               + (f" Forgotten: {forgot}." if forgot else "")})
        return mechanics.done(_view(rec, fatigue=fat["value"], forgot=forgot, carried=rec["anchors"],
                                     carried_tracks=rec.get("carry") or []),
                               writes=writes, refresh="clocks", visible_events=events)
    for field, have, cap in (("learn", "knowledge", None), ("anchor", "anchors", int(nums["anchors"]))):
        text = str(intent.get(field) or "").strip()
        if text and text not in rec[have]:
            if cap is not None and len(rec[have]) >= cap:
                return mechanics.error(f"{cap} anchors at most (default): drop one first ({', '.join(rec[have])})")
            rec[have].append(text)
    for field, have in (("forget", "knowledge"), ("drop", "anchors")):
        text = str(intent.get(field) or "").strip()
        if text:
            if text not in rec[have]:
                return mechanics.error(f"{field}: {text!r} is not in {have}")
            rec[have].remove(text)
    wdb.put(ctx.db, "loop", "party", rec)
    return mechanics.done(_view(rec), visible_events=events)
