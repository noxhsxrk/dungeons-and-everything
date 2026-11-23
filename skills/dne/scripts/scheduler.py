#!/usr/bin/env python3
"""
scheduler.py — the world moves by in-world time, and what was set in motion arrives when it is due.

`advance(world, until)` is the one way time passes in an engine campaign. It takes the events that
are due, in order, applies each one's effect, and moves the clock, timed effects and faction weeks
with it. Nothing else may add minutes to calendar.json (use `correct` to fix a wrong date).

    scheduler.py -c <campaign> list                       # what is queued, due first
    scheduler.py -c <campaign> advance --minutes N | --days N [--batch 200]
    scheduler.py -c <campaign> correct --minutes ±N       # the date was wrong: move the clock, run nothing

Engine actions (turn.py resolve):
    {"action": "wait", "minutes": 90}                     let time pass
    {"action": "schedule", "in_minutes": 240, "text": "The toll captain's rider reaches the mill.",
     "audience": "dm", "cause": "bribed the clerk", "event_id": "rider-reaches-mill"}

AN EVENT  event_id (stable: scheduling the same id twice is one event), due_minute, priority,
          trigger, preconditions, cause_id, effect, audience, status pending | applied | cancelled.
TRIGGERS  {"at": minute} (the default); {"enter": "<place>"} fires when the party arrives there;
          {"when": {"thing": [kind, id], "path": "status", "equals": "open"}} fires when that becomes true.
ORDER     By due minute, then higher priority first, then event_id. Events due in the same minute
          read `world.at_start(kind, id)`: the state as it was when that minute began, so two things
          that happen at once do not see each other's result.
BATCHES   At most `batch` events per call. If more are due the clock stops at the last one applied
          and `remaining` says how many are left: call again. Nothing due is ever skipped.
RANDOM    Each event draws from its own generator (campaign seed + event_id), so crossing 70 days
          in one call or in 70 gives the same world.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import paths  # noqa: E402
import world_db as wdb  # noqa: E402

sys.modules.setdefault("scheduler", sys.modules[__name__])   # run as a script, `import scheduler` is still this module

WEEK = 7 * 1440
EFFECTS: dict = {}       # effect type -> fn(world, event_row, effect) -> list of visible events (or None)


def effect(name: str):
    def register(fn):
        EFFECTS[name] = fn
        return fn
    return register


class World:
    """The campaign as one action sees it: the store, plus files read once and written back only if changed."""

    def __init__(self, campaign: str, db):
        self.campaign, self.db = campaign, db
        self.camp = paths.find_campaign(campaign)
        self._json: dict = {}
        self._dirty: set = set()
        self._start: "dict | None" = None
        self.expired: list = []

    def json(self, rel: str, default=None):
        if rel not in self._json:
            try:
                self._json[rel] = json.loads((self.camp / rel).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self._json[rel] = default if default is not None else {}
        return self._json[rel]

    def touch(self, rel: str) -> None:
        self._dirty.add(rel)

    def writes(self) -> dict:
        return {rel: json.dumps(self._json[rel], indent=2, ensure_ascii=False) for rel in sorted(self._dirty)}

    # the clock
    @property
    def minute(self) -> "int | None":
        cal = self.json("calendar.json")
        return _minutes_of(cal) if cal else None

    def move_clock(self, minutes: int) -> None:
        if minutes <= 0 or not self.json("calendar.json"):
            return
        _calendar_module()._advance_minutes(self.json("calendar.json"), minutes)
        self.touch("calendar.json")
        tracker = self.json("tracker.json")
        if tracker:
            import tracker as tracker_mod
            for key, ent in tracker.items():
                if not key.startswith("_") and isinstance(ent, dict) and ent.get("effects"):
                    expired = tracker_mod._run_down(ent, minutes)
                    for e in expired:
                        if e.get("concentration") and (ent.get("concentration") or "").lower() == str(e.get("name", "")).lower():
                            ent["concentration"] = None
                    if expired:
                        self.expired += [(ent.get("name", key), e.get("name")) for e in expired]
                    self.touch("tracker.json")

    # things
    def get(self, kind: str, id: str):
        return wdb.get(self.db, kind, id)

    def put(self, kind: str, id: str, data: dict) -> None:
        wdb.put(self.db, kind, id, data)

    def all(self, kind: str) -> dict:
        return wdb.all_of(self.db, kind)

    def at_start(self, kind: str, id: str):
        """The record as it was when the current minute began (for effects that happen at the same moment)."""
        if self._start is None:
            return self.get(kind, id)
        return self._start.get((kind, id))

    def _freeze(self) -> None:
        self._start = {(r["kind"], r["id"]): json.loads(r["data"]) for r in self.db.execute("SELECT * FROM things")}


def _calendar_module():
    """scripts/calendar.py shadows the standard library's calendar: load it by path."""
    import importlib.util
    cached = sys.modules.get("dne_calendar")
    if cached:
        return cached
    spec = importlib.util.spec_from_file_location("dne_calendar", HERE / "calendar.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["dne_calendar"] = mod
    spec.loader.exec_module(mod)
    return mod


def _minutes_of(cal: dict) -> int:
    from datetime import datetime
    year, month, day = int(cal.get("year", 1)), int(cal.get("month", 1)), int(cal.get("day", 1))
    if cal.get("gregorian"):
        days = datetime(year, month, day).toordinal()
    else:
        per_year = max(1, len(cal.get("months") or [])) * int(cal.get("month_length", 30))
        days = year * per_year + (month - 1) * int(cal.get("month_length", 30)) + day - 1
    return days * 1440 + int(cal.get("hour", 0)) * 60 + int(cal.get("minute", 0))


# ── the queue ─────────────────────────────────────────────────────────────────

def schedule(db, event_id: str, due_minute: "int | None", effect: dict, *, priority: int = 0,
             trigger: "dict | None" = None, preconditions: "list | None" = None, cause_id: str = "",
             audience: str = "dm", note: str = "") -> bool:
    """Queue an event. The id is its identity: the same id again changes nothing. True if it was new."""
    cur = db.execute(
        "INSERT OR IGNORE INTO events (event_id, due_minute, priority, trigger, preconditions, cause_id, effect, "
        "audience, status, note) VALUES (?,?,?,?,?,?,?,?,'pending',?)",
        (event_id, due_minute, priority, json.dumps(trigger or {"at": due_minute}, ensure_ascii=False),
         json.dumps(preconditions or [], ensure_ascii=False), cause_id,
         json.dumps(effect, ensure_ascii=False, sort_keys=True), audience, note))
    return cur.rowcount == 1


def cancel(db, event_id: str, reason: str) -> None:
    db.execute("UPDATE events SET status='cancelled', note=? WHERE event_id=? AND status='pending'", (reason, event_id))


def _holds(world: World, cond: dict) -> bool:
    """One precondition or `when` trigger: {"thing": [kind, id], "path": "a.b", "equals": v} or {"event": id, "status": s}."""
    if "event" in cond:
        row = world.db.execute("SELECT status FROM events WHERE event_id=?", (cond["event"],)).fetchone()
        return bool(row) and row["status"] == cond.get("status", "applied")
    if "thing" in cond:
        value = world.get(*cond["thing"])
        for part in str(cond.get("path", "")).split("."):
            if part:
                value = value.get(part) if isinstance(value, dict) else None
        if "equals" in cond:
            return value == cond["equals"]
        if "not" in cond:
            return value != cond["not"]
        return bool(value)
    return True


def _apply(world: World, row, visible: list) -> None:
    eff = json.loads(row["effect"])
    failed = [c for c in json.loads(row["preconditions"] or "[]") if not _holds(world, c)]
    if failed:                                    # the reason stays on the event: why it never happened is on record
        world.db.execute("UPDATE events SET status='cancelled', note=?, applied_minute=? WHERE event_id=?",
                         ("precondition no longer true: " + json.dumps(failed[0], ensure_ascii=False),
                          world.minute, row["event_id"]))
        return
    fn = EFFECTS.get(eff.get("type", "note"))
    out = fn(world, row, eff) if fn else None
    world.db.execute("UPDATE events SET status='applied', applied_minute=? WHERE event_id=?", (world.minute, row["event_id"]))
    for item in out or []:
        visible.append({"event_id": row["event_id"], "cause_id": row["cause_id"],
                        "recipient": item.get("recipient", row["audience"]), **item})


def fire(world: World, kind: str, value: str = "") -> list:
    """Apply the events waiting on something other than time: the party entering `value`, or a state that changed."""
    visible, rows = [], world.db.execute(
        "SELECT * FROM events WHERE status='pending' AND due_minute IS NULL ORDER BY priority DESC, event_id").fetchall()
    for row in rows:
        trig = json.loads(row["trigger"] or "{}")
        if kind == "enter" and str(trig.get("enter", "")).casefold() == value.casefold() and value:
            _apply(world, row, visible)
        elif kind == "when" and "when" in trig and _holds(world, trig["when"]):
            _apply(world, row, visible)
    return visible


def ensure_recurring(world: World) -> None:
    """Queue the world's own rhythm: the next faction week, if factions are tracked and none is queued."""
    data = world.json("factions.json")
    if not data or not data.get("factions") or world.minute is None:
        return
    if world.db.execute("SELECT 1 FROM events WHERE status='pending' AND event_id LIKE 'faction-week-%'").fetchone():
        return
    week = int(data.get("turn", 0)) + 1
    base = data.get("last_turn")
    due = (base if base is not None else world.minute) + WEEK
    schedule(world.db, f"faction-week-{week}", due, {"type": "faction_week", "week": week}, priority=-10)


def advance(world: World, until: int, batch: int = 200) -> dict:
    """Move the world to minute `until`, applying what comes due on the way. See the module docstring for the rules."""
    start = world.minute
    if start is None:
        return {"from": None, "to": None, "applied": [], "visible_events": [], "remaining": 0, "elapsed_minutes": 0,
                "note": "no calendar: run calendar.py init to give this world a clock"}
    world.expired = []
    ensure_recurring(world)
    visible, applied, stopped = [], [], False
    while len(applied) < batch:
        row = world.db.execute(
            "SELECT * FROM events WHERE status='pending' AND due_minute IS NOT NULL AND due_minute<=? "
            "ORDER BY due_minute, priority DESC, event_id LIMIT 1", (until,)).fetchone()
        if not row:
            break
        if row["due_minute"] > world.minute:
            world.move_clock(row["due_minute"] - world.minute)
        world._freeze()                           # everything due this minute reads the state the minute began with
        same = world.db.execute(
            "SELECT * FROM events WHERE status='pending' AND due_minute IS NOT NULL AND due_minute<=? "
            "ORDER BY priority DESC, event_id", (world.minute,)).fetchall()
        for due in same:
            if len(applied) >= batch:
                stopped = True
                break
            before = len(visible)
            _apply(world, due, visible)
            applied.append(due["event_id"])
            visible += fire(world, "when")
            if any(v.get("interrupt") for v in visible[before:]):
                stopped = True                    # someone has to decide: time stops here
                break
        world._start = None
        if stopped:
            break
    remaining = world.db.execute(
        "SELECT COUNT(*) AS n FROM events WHERE status='pending' AND due_minute IS NOT NULL AND due_minute<=?",
        (until,)).fetchone()["n"]
    interrupted = any(v.get("interrupt") for v in visible)
    if not remaining and not interrupted and until > world.minute:
        world.move_clock(until - world.minute)    # the rest of the stretch is quiet
    for who, name in world.expired:
        visible.append({"type": "effect_expired", "recipient": "party", "text": f"{who}: {name} ran out"})
    return {"from": start, "to": world.minute, "elapsed_minutes": world.minute - start, "applied": applied,
            "visible_events": visible, "remaining": remaining, "interrupted": interrupted}


# ── effects every world has ───────────────────────────────────────────────────

@effect("note")
def _note(world: World, row, eff: dict):
    """Something the GM set in motion comes due: surface it so it is narrated through what the party can perceive."""
    return [{"type": eff.get("kind", "consequence"), "text": eff.get("text", ""), "interrupt": bool(eff.get("interrupt"))}]


@effect("set")
def _set(world: World, row, eff: dict):
    """Change one record: {"type": "set", "thing": [kind, id], "data": {...}} merges `data` into it."""
    kind, id = eff["thing"]
    record = world.get(kind, id) or {}
    record.update(eff.get("data") or {})
    world.put(kind, id, record)
    return [{"type": "changed", "text": eff["text"]}] if eff.get("text") else None


@effect("faction_week")
def _faction_week(world: World, row, eff: dict):
    """One off-screen week for every faction, then the next week is queued. Seeded by the event, so it does not
    matter how the time was crossed."""
    import faction
    data = world.json("factions.json")
    if not data or not data.get("factions"):
        return None
    r = wdb.rng(world.db, row["event_id"])
    data["turn"] = int(data.get("turn", 0)) + 1
    lines = [faction.act(name, data, r) for name in sorted(data["factions"])]
    data["last_turn"] = row["due_minute"]
    log = data.setdefault("log", [])
    log.extend(f"- {line}" for line in lines)
    del log[:-60]
    world.touch("factions.json")
    schedule(world.db, f"faction-week-{data['turn'] + 1}", row["due_minute"] + WEEK,
             {"type": "faction_week", "week": data["turn"] + 1}, priority=-10)
    return [{"type": "faction_move", "recipient": "dm", "text": line} for line in lines]


def correct(world: World, minutes: int) -> dict:
    """The date was wrong. Move the clock by `minutes` (either way) and run nothing: every queued event and the
    faction week keep their distance from now. This is not time passing, and not an undo."""
    cal = world.json("calendar.json")
    if not cal:
        return {"error": "no calendar"}
    before = world.minute
    _calendar_module()._advance_minutes(cal, minutes) if minutes >= 0 else _rewind(cal, -minutes)
    world.touch("calendar.json")
    world.db.execute("UPDATE events SET due_minute = due_minute + ? WHERE status='pending' AND due_minute IS NOT NULL", (minutes,))
    data = world.json("factions.json")
    if data and data.get("last_turn") is not None:
        data["last_turn"] += minutes
        world.touch("factions.json")
    log = world.get("clock", "corrections") or {"log": []}
    log["log"].append({"from": before, "to": world.minute})
    world.put("clock", "corrections", log)
    return {"from": before, "to": world.minute, "corrected_by": minutes}


def _rewind(cal: dict, minutes: int) -> None:
    from datetime import datetime, timedelta
    if cal.get("gregorian"):
        v = datetime(cal["year"], cal["month"], cal["day"], cal.get("hour", 0), cal.get("minute", 0)) - timedelta(minutes=minutes)
        cal.update(year=v.year, month=v.month, day=v.day, hour=v.hour, minute=v.minute)
        return
    month_len, months = int(cal.get("month_length", 30)), max(1, len(cal.get("months") or []) or 12)
    total = ((cal.get("year", 1) * months + cal.get("month", 1) - 1) * month_len + cal.get("day", 1) - 1) * 1440 \
        + cal.get("hour", 0) * 60 + cal.get("minute", 0) - minutes
    days, rest = divmod(total, 1440)
    ym, day = divmod(days, month_len)
    year, month = divmod(ym, months)
    cal.update(year=year, month=month + 1, day=day + 1, hour=rest // 60, minute=rest % 60)


def run(campaign: str, minutes: int = 0, batch: int = 200, fix: "int | None" = None) -> dict:
    """Outside a turn (the CLI, tests): pass time or correct the clock, with the same crash safety as an action."""
    with wdb.writer(campaign) as db:
        world = World(campaign, db)
        out = correct(world, fix) if fix is not None else advance(world, (world.minute or 0) + minutes, batch)
        wdb.stage_writes(db, wdb.next_id(db, "sched_seq", "sched"), world.writes())
    wdb.apply_staged(campaign)
    return out


def _register() -> None:
    import turn

    @turn.handler("wait")
    def _wait(ctx, intent: dict) -> dict:
        """wait — let in-world time pass: {"action": "wait", "minutes": 90} (or "hours" / "days").

        Whatever comes due on the way happens, in order. If something needs the party to decide, time stops
        there and the result says how much really passed."""
        minutes = int(intent.get("minutes", 0)) + 60 * int(intent.get("hours", 0)) + 1440 * int(intent.get("days", 0))
        world = World(ctx.campaign, ctx.db)
        out = advance(world, (world.minute or 0) + minutes, int(intent.get("batch", 200)))
        return {"status": "done", "elapsed_minutes": out["elapsed_minutes"], "writes": world.writes(),
                "visible_events": out["visible_events"], "data": {k: out[k] for k in ("from", "to", "applied", "remaining", "interrupted")}}

    @turn.handler("schedule")
    def _schedule(ctx, intent: dict) -> dict:
        """schedule — set a consequence in motion.

        {"action": "schedule", "in_minutes": 240, "text": "The rider reaches the mill.", "cause": "bribed the clerk",
         "audience": "dm" | "party" | "<PC>", "event_id": "rider-reaches-mill", "interrupt": false,
         "enter": "<place>"  (instead of a time: when the party arrives there),
         "unless": [{"thing": ["bridge", "millbridge"], "path": "status", "equals": "closed"}]}
        It happens when its time comes (or the party enters), unless a precondition has stopped being true."""
        world = World(ctx.campaign, ctx.db)
        eid = str(intent.get("event_id") or f"ev-{ctx.action_id}")
        if intent.get("enter"):
            due, trig = None, {"enter": intent["enter"]}
        elif intent.get("when"):
            due, trig = None, {"when": intent["when"]}
        else:
            due = int(intent["at_minute"]) if "at_minute" in intent else (world.minute or 0) + int(intent.get("in_minutes", 0))
            trig = {"at": due}
        conditions = list(intent.get("if") or [])
        for cond in intent.get("unless") or []:   # "unless X equals v" is the precondition "X is not v"
            cond = dict(cond)
            if "equals" in cond:
                cond["not"] = cond.pop("equals")
            conditions.append(cond)
        new = schedule(ctx.db, eid, due, {"type": intent.get("effect", "note"), "text": intent.get("text", ""),
                                          "interrupt": bool(intent.get("interrupt")), **(intent.get("data") or {})},
                       priority=int(intent.get("priority", 0)), trigger=trig, preconditions=conditions,
                       cause_id=str(intent.get("cause", "")), audience=str(intent.get("audience", "dm")))
        return {"status": "done", "elapsed_minutes": 0, "data": {"event_id": eid, "due_minute": due, "new": new}}


try:
    _register()
except Exception:
    pass


def main() -> int:
    p = argparse.ArgumentParser(description="In-world time and the consequence queue.")
    p.add_argument("-c", "--campaign", required=True)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    a = sub.add_parser("advance")
    a.add_argument("--minutes", type=int, default=0)
    a.add_argument("--days", type=int, default=0)
    a.add_argument("--batch", type=int, default=200)
    c = sub.add_parser("correct")
    c.add_argument("--minutes", type=int, required=True)
    args = p.parse_args()
    if not wdb.enabled(args.campaign):
        print("world_engine is not on for this campaign (Session Flags).")
        return 0
    import turn  # noqa: F401  (loads every engine module, so their effects are registered)
    if args.cmd == "list":
        with wdb.reader(args.campaign) as db:
            rows = db.execute("SELECT * FROM events WHERE status='pending' ORDER BY due_minute IS NULL, due_minute, "
                              "priority DESC, event_id").fetchall() if db else []
        for r in rows:
            print(f"{r['event_id']:<28} due {r['due_minute']}  {r['trigger']}  {json.loads(r['effect']).get('text', r['effect'])[:70]}")
        print(f"{len(rows)} pending.")
        return 0
    out = run(args.campaign, args.minutes + 1440 * getattr(args, "days", 0), getattr(args, "batch", 200),
              fix=args.minutes if args.cmd == "correct" else None)
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
