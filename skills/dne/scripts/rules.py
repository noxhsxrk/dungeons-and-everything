#!/usr/bin/env python3
"""
rules.py — a campaign declares its own kinds of work, and the engine runs them on the one clock.

A world says what can be done in it (`rule`), who can do it (`agent`), and what there is to do it with
(`store`). A `task` is one piece of that work under way. Everything is built from what the engine can check:
conditions are the scheduler's own (`{"thing": [kind, id], "path": "a.b", "equals" | "not" | "at_least" |
"at_most": v}` or `{"event": id, "status": s}`), costs and gains are counts in stores, effects are the
scheduler's `set`. No code per campaign.

Records:
  rule   "<id>"  {label, actor: {skill, min} | {right}, requires: [cond], cost: {store: {item: n}}, minutes,
                  gives: {store: {item: n}}, sets: [{thing: [kind, id], data: {…}}], cancel_if: [cond]}
  agent  "<name>" {skills: {skill: level}, rights: [..], busy: task id | null}
  store  "<id>"  {items: {item: n}, reserved: {task id: {item: n}}}
  task   "<id>"  {rule, actor, status: waiting | started | blocked | done | cancelled, why, since, ends,
                  caused_by, log: [{minute, status, why}]}

A task's life: asked for → `blocked` while a condition, the actor or the materials are missing (it is looked at
again whenever the world changes) → `started`: the cost is *reserved* in its stores and an end event is queued →
at the end its conditions are checked again: `done` (cost used, gains added, sets applied) or `blocked` (the
reservation is kept; it finishes when the condition is back) → `cancelled` at any point when a `cancel_if` holds,
which gives the reservation back. Each change is logged with its reason and the event or task that caused it.

Order and loops: tasks are looked at in id order; a change one task makes can unblock or cancel another in the
same minute (the cause is recorded), but in one look at the world no task changes status more than LOOP_LIMIT
times: past that it is left `blocked` with the reason "stopped a loop", for the GM to look at.

Engine actions:
  {"action": "rule", "id": "smelt", "label": "smelt iron", "actor": {"skill": "smith", "min": 1},
   "requires": [{"thing": ["store", "forge"], "path": "items.ore", "at_least": 2}],
   "cost": {"forge": {"ore": 2, "coal": 1}}, "minutes": 480, "gives": {"forge": {"iron": 1}},
   "cancel_if": [{"thing": ["route", "ford|millbridge"], "path": "access", "equals": "closed"}]}
  {"action": "agent", "name": "Bren", "skills": {"smith": 2}, "rights": ["guild"]}
  {"action": "store", "id": "forge", "items": {"ore": 4, "coal": 2}}            (adds; negative takes away)
  {"action": "task", "rule": "smelt", "actor": "Bren", "id": "smelt-1"}         (or "cancel": "smelt-1")
  {"action": "tasks"}                                                            (what is under way, and why)
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import scheduler  # noqa: E402
import turn  # noqa: E402

sys.modules.setdefault("rules", sys.modules[__name__])

LOOP_LIMIT = 4
OPEN = ("waiting", "blocked", "started")


def _free(store: dict, item: str) -> int:
    held = sum(int(r.get(item, 0)) for r in (store.get("reserved") or {}).values())
    return int((store.get("items") or {}).get(item, 0)) - held


def _short(world, cost: dict, task_id: str = "") -> list:
    """What is missing to reserve `cost` (what the task itself already holds counts as there)."""
    out = []
    for sid, items in sorted((cost or {}).items()):
        store = world.get("store", sid) or {}
        mine = (store.get("reserved") or {}).get(task_id, {})
        for item, n in sorted(items.items()):
            have = _free(store, item) + int(mine.get(item, 0))
            if have < int(n):
                out.append(f"{sid} has {have} {item} free of {n}")
    return out


def _who_cannot(world, rule: dict, actor: str, task_id: str) -> "str | None":
    need = rule.get("actor") or {}
    if not need:
        return None
    a = world.get("agent", actor)
    if not a:
        return f"{actor} is not an agent of this world"
    if a.get("busy") and a["busy"] != task_id:
        return f"{actor} is busy with {a['busy']}"
    if need.get("skill") and int((a.get("skills") or {}).get(need["skill"], 0)) < int(need.get("min", 1)):
        return f"{actor} has {need['skill']} {int((a.get('skills') or {}).get(need['skill'], 0))}, needs {need.get('min', 1)}"
    if need.get("right") and need["right"] not in (a.get("rights") or []):
        return f"{actor} lacks the right {need['right']!r}"
    return None


def _log(task: dict, minute, status: str, why: str, cause: str = "") -> None:
    task["status"], task["why"] = status, why
    task.setdefault("log", []).append({"minute": minute, "status": status, "why": why, **({"cause": cause} if cause else {})})


def _reserve(world, tid: str, cost: dict) -> None:
    for sid, items in (cost or {}).items():
        store = world.get("store", sid) or {"items": {}}
        store.setdefault("reserved", {})[tid] = {k: int(v) for k, v in items.items()}
        world.put("store", sid, store)


def _release(world, tid: str, cost: dict, use: bool) -> None:
    """Give a reservation back, or use it up."""
    for sid in (cost or {}):
        store = world.get("store", sid) or {"items": {}}
        held = (store.get("reserved") or {}).pop(tid, {})
        if use:
            for item, n in held.items():
                store.setdefault("items", {})[item] = int(store["items"].get(item, 0)) - int(n)
        world.put("store", sid, store)


def _gain(world, gives: dict) -> None:
    for sid, items in (gives or {}).items():
        store = world.get("store", sid) or {"items": {}}
        for item, n in items.items():
            store.setdefault("items", {})[item] = int(store["items"].get(item, 0)) + int(n)
        world.put("store", sid, store)


def _step(world, tid: str, task: dict, cause: str, moves: dict) -> bool:
    """Look at one task once. True if its status changed."""
    rule = world.get("rule", task["rule"]) or {}
    minute = world.minute
    if moves.get(tid, 0) >= LOOP_LIMIT:
        if task["why"] != "stopped a loop":
            _log(task, minute, "blocked", "stopped a loop", cause)
            world.put("task", tid, task)
        return False
    before = task["status"]
    if any(scheduler._holds(world, c) for c in rule.get("cancel_if") or []):
        if task["status"] == "started":
            _release(world, tid, rule.get("cost"), use=False)
            scheduler.cancel(world.db, f"task-end-{tid}", "the task was cancelled")
        _free_actor(world, task)
        hit = next(c for c in rule["cancel_if"] if scheduler._holds(world, c))
        _log(task, minute, "cancelled", f"cancel_if holds: {_say(hit)}", cause)
    elif task["status"] in ("waiting", "blocked") and not task.get("ended"):
        why = _missing(world, rule, task, tid)
        if why:
            if task["status"] != "blocked" or task["why"] != why:
                _log(task, minute, "blocked", why, cause)
        else:
            _reserve(world, tid, rule.get("cost"))
            a = world.get("agent", task["actor"])
            if a is not None and rule.get("actor"):
                a["busy"] = tid
                world.put("agent", task["actor"], a)
            task["ends"] = minute + int(rule.get("minutes", 0))
            scheduler.schedule(world.db, f"task-end-{tid}", task["ends"], {"type": "task_end", "id": tid},
                               cause_id=tid, priority=2)
            _log(task, minute, "started", f"{task['actor']} began; materials reserved", cause)
    elif task["status"] == "blocked" and task.get("ended"):          # finished its time, waiting on a condition
        broken = [c for c in rule.get("requires") or [] if not scheduler._holds(world, c)]
        if not broken:
            _complete(world, tid, task, rule, cause)
    changed = task["status"] != before
    if changed:
        moves[tid] = moves.get(tid, 0) + 1
    world.put("task", tid, task)
    return changed


def _missing(world, rule: dict, task: dict, tid: str) -> "str | None":
    broken = [c for c in rule.get("requires") or [] if not scheduler._holds(world, c)]
    if broken:
        return f"needs {_say(broken[0])}"
    who = _who_cannot(world, rule, task["actor"], tid)
    if who:
        return who
    short = _short(world, rule.get("cost"), tid)
    return ("short: " + "; ".join(short)) if short else None


def _say(cond: dict) -> str:
    if "event" in cond:
        return f"event {cond['event']} {cond.get('status', 'applied')}"
    test = next((f"{k} {cond[k]}" for k in ("equals", "not", "at_least", "at_most") if k in cond), "to be set")
    return f"{'/'.join(map(str, cond.get('thing', [])))}{'.' + cond['path'] if cond.get('path') else ''} {test}"


def _free_actor(world, task: dict) -> None:
    a = world.get("agent", task.get("actor", ""))
    if a and a.get("busy") == task.get("id"):
        a["busy"] = None
        world.put("agent", task["actor"], a)


def _complete(world, tid: str, task: dict, rule: dict, cause: str) -> None:
    _release(world, tid, rule.get("cost"), use=True)
    _gain(world, rule.get("gives"))
    for s in rule.get("sets") or []:
        kind, id_ = s["thing"]
        rec = world.get(kind, id_) or {}
        rec.update(s.get("data") or {})
        world.put(kind, id_, rec)
    _free_actor(world, task)
    _log(task, world.minute, "done", f"{rule.get('label', task['rule'])} finished", cause)


def settle(world, cause: str = "") -> list:
    """Look at every open task until nothing more changes (each task at most LOOP_LIMIT times this minute)."""
    moves: dict = {}
    out = []
    for _round in range(LOOP_LIMIT + 1):
        changed = False
        for tid, task in sorted(world.all("task").items()):
            if task["status"] in OPEN:
                task.setdefault("id", tid)
                was = task["status"]
                if _step(world, tid, task, cause, moves):
                    changed = True
                    out.append({"type": "task", "recipient": "dm", "task": tid, "status": task["status"],
                                "text": f"{task.get('label') or task['rule']} ({tid}, {task['actor']}): {was} → {task['status']}: {task['why']}"})
                    cause = cause or f"task:{tid}"
        if not changed:
            break
    return out


@scheduler.effect("task_end")
def _task_end(world, row, eff):
    """A task's time is up: done if its conditions still hold, else it waits for them, holding its materials."""
    tid = eff["id"]
    task = world.get("task", tid)
    if not task or task["status"] != "started":
        return None
    rule = world.get("rule", task["rule"]) or {}
    task["ended"] = True
    broken = [c for c in rule.get("requires") or [] if not scheduler._holds(world, c)]
    if broken:
        _log(task, world.minute, "blocked", f"time is up but it needs {_say(broken[0])}; materials held", row["event_id"])
    else:
        _complete(world, tid, task, rule, row["event_id"])
    world.put("task", tid, task)
    return [{"type": "task", "recipient": "dm", "task": tid, "status": task["status"],
             "text": f"{rule.get('label', task['rule'])} ({tid}, {task['actor']}): {task['status']}: {task['why']}"}] \
        + settle(world, f"task:{tid}")                # what this one finishing makes possible, with it as the cause


scheduler.AFTER_CHANGE.append(lambda world: settle(world, getattr(world, "cause", "")))


# ── actions ───────────────────────────────────────────────────────────────────

def _done(data: dict, visible: "list | None" = None, world=None) -> dict:
    out = {"status": "done", "elapsed_minutes": 0, "data": data, "visible_events": visible or []}
    if world is not None:
        out["writes"] = world.writes()
    return out


@turn.handler("rule")
def _rule(ctx, intent: dict) -> dict:
    """rule — a kind of work this world has. See `rules.py`'s docstring for every field.

    {"action": "rule", "id": "smelt", "label": "smelt iron", "actor": {"skill": "smith", "min": 1},
     "requires": [{"thing": ["store", "forge"], "path": "items.ore", "at_least": 2}],
     "cost": {"forge": {"ore": 2, "coal": 1}}, "minutes": 480, "gives": {"forge": {"iron": 1}},
     "sets": [{"thing": ["route", "a|b"], "data": {"access": "open"}}], "cancel_if": [ … ]}"""
    rid = str(intent.get("id", "")).strip()
    if not rid:
        return _done({"error": "a rule needs an id"})
    rule = {k: intent[k] for k in ("label", "actor", "requires", "cost", "minutes", "gives", "sets", "cancel_if") if k in intent}
    for field in ("requires", "cancel_if"):
        for i, c in enumerate(rule.get(field) or []):
            if not isinstance(c, dict) or not ("thing" in c or "event" in c):
                return _done({"error": f"{field}[{i}]: a condition is {{thing: [kind, id], path, equals|not|at_least|at_most}} or {{event, status}}"})
    for field in ("cost", "gives"):
        for sid, items in (rule.get(field) or {}).items():
            if not isinstance(items, dict) or not all(isinstance(n, int) and n >= 0 for n in items.values()):
                return _done({"error": f"{field}.{sid}: whole numbers of items, e.g. {{\"ore\": 2}}"})
    if not isinstance(rule.get("minutes", 0), int) or rule.get("minutes", 0) < 0:
        return _done({"error": "minutes: a whole number, 0 or more"})
    world = scheduler.World(ctx.campaign, ctx.db)
    world.put("rule", rid, rule)
    return _done({"rule": rid, **rule})


@turn.handler("agent")
def _agent(ctx, intent: dict) -> dict:
    """agent — someone who can do this world's work: {"action": "agent", "name": "Bren", "skills": {"smith": 2},
    "rights": ["guild"]}. Fields merge into what is already known about them."""
    name = str(intent.get("name", "")).strip()
    if not name:
        return _done({"error": "an agent needs a name"})
    world = scheduler.World(ctx.campaign, ctx.db)
    a = world.get("agent", name) or {"skills": {}, "rights": [], "busy": None}
    a["skills"].update(intent.get("skills") or {})
    a["rights"] = sorted(set(a.get("rights") or []) | set(intent.get("rights") or []))
    world.put("agent", name, a)
    return _done({"agent": name, **a}, settle(world, f"agent:{name}"), world)


@turn.handler("store")
def _store(ctx, intent: dict) -> dict:
    """store — what there is to work with: {"action": "store", "id": "forge", "items": {"ore": 4, "coal": 2}}.
    Adds (a negative number takes away, never below what tasks have reserved)."""
    sid = str(intent.get("id", "")).strip()
    if not sid:
        return _done({"error": "a store needs an id"})
    world = scheduler.World(ctx.campaign, ctx.db)
    store = world.get("store", sid) or {"items": {}, "reserved": {}}
    for item, n in (intent.get("items") or {}).items():
        new = int(store["items"].get(item, 0)) + int(n)
        held = sum(int(r.get(item, 0)) for r in (store.get("reserved") or {}).values())
        if new < max(0, held):
            return _done({"error": f"{sid} cannot go below {held} {item}: that much is reserved by work under way"})
        store["items"][item] = new
    world.put("store", sid, store)
    return _done({"store": sid, **store}, settle(world, f"store:{sid}") + scheduler.fire(world, "when"), world)


@turn.handler("task")
def _task(ctx, intent: dict) -> dict:
    """task — put someone to work: {"action": "task", "rule": "smelt", "actor": "Bren", "id": "smelt-1"}.

    It starts at once if it can, or waits, blocked, and starts by itself when what it lacks turns up.
    {"action": "task", "cancel": "smelt-1", "why": "…"} stops it and gives its materials back."""
    world = scheduler.World(ctx.campaign, ctx.db)
    if intent.get("cancel"):
        tid = str(intent["cancel"])
        task = world.get("task", tid)
        if not task or task["status"] not in OPEN:
            return _done({"error": f"no task {tid} under way"})
        if task["status"] == "started":
            _release(world, tid, (world.get("rule", task["rule"]) or {}).get("cost"), use=False)
            scheduler.cancel(ctx.db, f"task-end-{tid}", "the task was cancelled")
        _free_actor(world, task)
        _log(task, world.minute, "cancelled", str(intent.get("why") or "called off"), ctx.action_id)
        world.put("task", tid, task)
        return _done({"task": tid, **task}, settle(world, f"task:{tid}"), world)
    rule = world.get("rule", str(intent.get("rule", "")))
    if not rule:
        return _done({"error": f"no rule {intent.get('rule')!r}: declare it with the rule action"})
    tid = str(intent.get("id") or f"task-{ctx.action_id}")
    if world.get("task", tid):
        return _done({"error": f"task {tid} already exists"})
    task = {"id": tid, "rule": intent["rule"], "actor": str(intent.get("actor", "")), "label": rule.get("label", ""),
            "status": "waiting", "why": "asked for", "since": world.minute, "caused_by": ctx.action_id, "log": []}
    world.put("task", tid, task)
    visible = settle(world, ctx.action_id)
    return _done({"task": tid, **world.get("task", tid)}, visible + scheduler.fire(world, "when"), world)


@turn.handler("tasks")
def _tasks(ctx, intent: dict) -> dict:
    """tasks — what work is under way or waiting, and why: {"action": "tasks"} (add "all": true for finished ones)."""
    world = scheduler.World(ctx.campaign, ctx.db)
    rows = {tid: {k: t.get(k) for k in ("rule", "actor", "status", "why", "ends", "log")}
            for tid, t in sorted(world.all("task").items()) if intent.get("all") or t["status"] in OPEN}
    return _done({"tasks": rows, "stores": world.all("store")})
