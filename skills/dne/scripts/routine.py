#!/usr/bin/env python3
"""
routine.py — NPCs who are somewhere and have plans, and factions that decide from what they know.

  npcpos       "<NPC>" → {place, since}                              where they are now
  schedule     "<NPC>" → {blocks: [{from, to, place, activity}], exceptions: [{day, place, activity}]}
  appointment  "<id>"  → {npc, place, at_minute, purpose, otherwise, on_meet, status, note}
  decision     "<faction>|<week>" → {choice, because, by}            what a faction chose that week, and why

Engine actions (turn.py help <name>):
  npc_schedule   give an NPC a structured day (their prose Schedule stays until you do)
  appointment    an NPC will be at a place at a time, for a purpose
  where          where an NPC is at a given minute, and why
  faction_brief  everything one faction knows and has: the only input for planning its move
  faction_intent submit a faction's move for the coming week; the engine checks it is possible

An NPC cannot be in two places: an appointment they could not reach from the one before is refused.
They set out in time to arrive. They plan the road by what THEY know (their own beliefs and what is
common knowledge where they stand): knowing a stretch is shut, they follow their `otherwise` plan or
stay; not knowing, they walk into it and turn back. Arriving, they meet who is there: news is
passed on and relationships change as the appointment's `on_meet` says.

A faction's week is chosen by rules that read only that faction's beliefs and stats (rest, defend,
negotiate, postpone, or carry on), or by an intent submitted for it. Either way the choice and its
reasons are stored, and a replay reuses them.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import journey  # noqa: E402
import knowledge  # noqa: E402
import scheduler  # noqa: E402
import trade  # noqa: E402
import turn  # noqa: E402

CHOICES = ("advance", "attack", "rest", "defend", "negotiate", "postpone")


def _world(ctx):
    return scheduler.World(ctx.campaign, ctx.db)


def _map(world) -> dict:
    return world.json("world-map.json", {"places": {}, "edges": [], "party_location": None})


def _pname(world, key) -> str:
    return _map(world).get("places", {}).get(key, {}).get("name", key or "nowhere known")


# ── where an NPC is ───────────────────────────────────────────────────────────

def _hhmm(text: str) -> int:
    h, _, m = str(text).partition(":")
    return int(h) * 60 + int(m or 0)


def where(world, npc: str, minute: "int | None" = None) -> dict:
    """{place, activity, why} for `npc` at `minute` (now by default): an appointment in progress, else an
    exception for that day, else their schedule block, else where they were last known to be."""
    minute = world.minute if minute is None else minute
    for aid, a in sorted(world.all("appointment").items()):
        if a["npc"] != npc or a["status"] not in ("planned", "travelling", "kept"):
            continue
        if a.get("departs") is not None and a["departs"] <= minute < a["at_minute"] and a["status"] != "kept":
            return {"place": None, "between": [a.get("from"), a["place"]], "activity": f"on the way to {_pname(world, a['place'])}",
                    "why": f"appointment {aid}"}
        if a["at_minute"] <= minute < a["at_minute"] + int(a.get("stays_minutes", 120)) and a["status"] in ("kept", "planned", "travelling"):
            return {"place": a["place"], "activity": a.get("purpose", ""), "why": f"appointment {aid}"}
    sched = world.get("schedule", npc) or {}
    day, clock = minute // 1440, minute % 1440
    for ex in sched.get("exceptions") or []:
        if int(ex.get("day", -1)) == day:
            return {"place": ex.get("place"), "activity": ex.get("activity", ""), "why": "schedule exception"}
    for block in sched.get("blocks") or []:
        start, end = _hhmm(block["from"]), _hhmm(block["to"])
        inside = start <= clock < end if start <= end else (clock >= start or clock < end)
        if inside:
            return {"place": block.get("place"), "activity": block.get("activity", ""), "why": "schedule"}
    pos = world.get("npcpos", npc)
    return {"place": (pos or {}).get("place"), "activity": "", "why": "last known place" if pos else "unknown"}


def _knows_closed(world, npc: str, here: "str | None") -> set:
    """Stretches this NPC believes are shut: their own beliefs and the common knowledge where they stand,
    the most recently learned word on each stretch winning."""
    latest: dict = {}
    for holder in (f"npc:{npc}", f"place:{here}"):
        for b in knowledge.known_to(world, holder):
            fact = str(b["fact"])
            if fact.startswith("route:") and (fact not in latest or (b.get("learned_at") or 0) > (latest[fact].get("learned_at") or 0)):
                latest[fact] = b
    return {fact[len("route:"):] for fact, b in latest.items() if str(b["claim"]).startswith("closed")}


def _npc_route(world, src: str, dst: str, avoid: set, mode: str = "foot") -> "list | None":
    data = _map(world)
    edges = [e for e in data.get("edges", []) if trade.route_id(e["a"], e["b"]) not in avoid]
    if src == dst:
        return []
    path = journey._shortest({**data, "edges": edges}, src, dst, mode, world)
    real = {trade.route_id(e["a"], e["b"]) for e in edges}
    return path if all(trade.route_id(a, b) in real for a, b, _m, _x in path) else None


def _minutes(path: list, mode: str = "foot") -> int:
    import world_map
    return sum(max(1, round(miles * mult / world_map.TRAVEL_SPEED_MPD.get(mode, 24.0) * 1440)) for _a, _b, miles, mult in path)


# ── appointments ──────────────────────────────────────────────────────────────

@scheduler.effect("npc_depart")
def _npc_depart(world, row, eff):
    """Time to leave for an appointment: they go if they know of a way, otherwise they change their plan."""
    aid = eff["id"]
    a = world.get("appointment", aid)
    if not a or a["status"] != "planned":
        return None
    npc, here = a["npc"], a.get("from")
    seen = "party" if _map(world).get("party_location") == here else "dm"
    cost = dict(a.get("cost") or {})
    payer = cost.pop("payer", None)
    if payer and cost:                            # the trip costs something: paid when they set out, or not made
        data = world.json("factions.json")
        f = (data.get("factions") or {}).get(payer)
        short = [f"{stat} {f.get(stat, 0) if f else 0} of {n}" for stat, n in sorted(cost.items())
                 if not f or int(f.get(stat, 0)) < int(n)]
        if short:
            other = a.get("otherwise") or {}
            a.update(status="changed", note=f"{payer} could not pay for it: " + ", ".join(short))
            world.put("appointment", aid, a)
            return [{"type": "npc_changed_plan", "recipient": seen, "npc": npc,
                     "text": f"{npc} does not go to {_pname(world, a['place'])}: {payer} cannot pay for it ({', '.join(short)}). "
                             + (f"Instead: {other.get('purpose') or other.get('place')}." if other else "They stay.")}]
        for stat, n in cost.items():
            f[stat] = int(f.get(stat, 0)) - int(n)
        world.touch("factions.json")
        a["paid"] = {"payer": payer, **cost}
    known_shut = _knows_closed(world, npc, here)
    path = _npc_route(world, here, a["place"], known_shut, a.get("mode", "foot"))
    if path is None:                              # they know there is no way through: no point setting out
        other = a.get("otherwise") or {}
        a.update(status="changed", note=f"knew the road was closed ({', '.join(sorted(known_shut))})")
        world.put("appointment", aid, a)
        if other.get("place"):
            world.put("npcpos", npc, {"place": journey.place_key(_map(world), other["place"]) or other["place"],
                                      "since": world.minute})
        return [{"type": "npc_changed_plan", "recipient": seen, "npc": npc,
                 "text": f"{npc} does not leave for {_pname(world, a['place'])}: the way is known to be closed. "
                         + (f"Instead: {other.get('purpose') or other.get('place')}." if other else "They stay.")}]
    for x, y, _miles, _mult in path:              # the road as it really is, which they may not know
        block = journey.route_block(world, x, y)
        if block:
            a.update(status="missed", note=f"turned back at {_pname(world, x)}: {block}")
            world.put("appointment", aid, a)
            knowledge.learn(world, f"npc:{npc}", f"route:{trade.route_id(x, y)}", f"closed: {block}", "saw it", 1.0)
            world.put("npcpos", npc, {"place": here, "since": world.minute})
            return [{"type": "npc_turned_back", "recipient": seen, "npc": npc,
                     "text": f"{npc} sets out for {_pname(world, a['place'])} and is turned back: {block}."}]
    a["status"] = "travelling"
    world.put("appointment", aid, a)
    scheduler.schedule(world.db, f"npc-arrive-{aid}", a["at_minute"], {"type": "npc_arrive", "id": aid})
    return [{"type": "npc_left", "recipient": seen, "npc": npc, "text": f"{npc} leaves {_pname(world, here)}."}]


@scheduler.effect("npc_arrive")
def _npc_arrive(world, row, eff):
    """They are there, on time. Whoever else is there, they meet."""
    aid = eff["id"]
    a = world.get("appointment", aid)
    if not a or a["status"] not in ("travelling", "planned"):
        return None
    npc, place = a["npc"], a["place"]
    a["status"] = "kept"
    world.put("appointment", aid, a)
    world.put("npcpos", npc, {"place": place, "since": world.minute})
    seen = "party" if _map(world).get("party_location") == place else "dm"
    out = [{"type": "npc_arrived", "recipient": seen, "npc": npc, "place": place,
            "text": f"{npc} is at {_pname(world, place)}" + (f": {a['purpose']}" if a.get("purpose") else "") + "."}]
    meet = a.get("on_meet") or {}
    with_ = meet.get("with")
    there = with_ and (where(world, with_).get("place") == place)
    if with_ and there:
        for fact in meet.get("tell") or []:       # what they came to say
            told = world.get("belief", f"npc:{npc}|{fact}") or world.get("fact", fact)
            if told:
                knowledge.learn(world, f"npc:{with_}", fact, told.get("claim") or told.get("text", ""), f"told by {npc}", 0.8)
        if meet.get("relation"):
            world.put("relation", f"{npc}|{with_}", {"type": meet["relation"], "since": world.minute, "from": aid})
            graph = world.json("graph.json")
            if isinstance(graph.get("edges"), list) and isinstance(graph.get("nodes"), list):
                import campaign_graph
                src, dst = campaign_graph._resolve_node(graph, npc), campaign_graph._resolve_node(graph, with_)
                if src and dst:
                    graph["edges"].append({"id": campaign_graph._next_edge_id(graph["edges"]), "from": src, "to": dst,
                                           "type": meet["relation"], "since_session": None, "until_session": None,
                                           "note": f"met at {_pname(world, place)} (appointment {aid})"})
                    world.touch("graph.json")
        out.append({"type": "meeting", "recipient": seen, "place": place,
                    "text": f"{npc} and {with_} meet at {_pname(world, place)}"
                            + (f"; {with_} now knows: {', '.join(meet.get('tell') or [])}" if meet.get("tell") else "")
                            + (f"; they are now {meet['relation']}" if meet.get("relation") else "") + "."})
    elif with_:
        out.append({"type": "meeting_missed", "recipient": seen, "place": place,
                    "text": f"{npc} waits at {_pname(world, place)}; {with_} is not there."})
    return out


def _conflict(world, npc: str, place: str, at_minute: int, mode: str) -> "str | None":
    """Why `npc` cannot be at `place` at that minute, given where their other appointments put them."""
    for aid, other in sorted(world.all("appointment").items()):
        if other["npc"] != npc or other["status"] not in ("planned", "travelling", "kept"):
            continue
        first, second = sorted(((other["at_minute"], other["place"]), (at_minute, place)))
        path = _npc_route(world, first[1], second[1], set(), mode)
        need = _minutes(path, mode) if path else (0 if first[1] == second[1] else 10 ** 9)
        if second[0] - first[0] < need:
            return (f"{npc} is due at {_pname(world, other['place'])} (appointment {aid}) and "
                    f"{_pname(world, first[1])} to {_pname(world, second[1])} takes {need // 60}h{need % 60:02d}: "
                    f"only {(second[0] - first[0]) // 60}h{(second[0] - first[0]) % 60:02d} between the two")
    return None


@turn.handler("appointment")
def _appointment(ctx, intent: dict) -> dict:
    """appointment — an NPC will be somewhere at a set time.

    {"action": "appointment", "id": "wheelwright-market", "npc": "Bren", "place": "Market", "in_minutes": 1500,
     "purpose": "sell cartwheels", "from": "Millbridge", "mode": "foot",
     "otherwise": {"place": "Millbridge", "purpose": "mend the mill wheel instead"},
     "on_meet": {"with": "Rina Saelim", "tell": ["mill-fire"], "relation": "owes"},
     "cost": {"payer": "Millers' Guild", "wealth": 1}}
    `cost` is paid from the payer faction's stats when they set out; if it cannot pay, they follow `otherwise`.
    They leave in time to arrive. Refused if another appointment makes it impossible to get there. If they know
    the road is closed they follow `otherwise`; if they do not know, they set out and are turned back."""
    world = _world(ctx)
    npc = str(intent.get("npc", ""))
    data = _map(world)
    place = journey.place_key(data, str(intent.get("place", "")))
    if not npc or not place:
        return {"status": "done", "elapsed_minutes": 0, "data": {"error": "an appointment needs an npc and a place on the map"}}
    at = int(intent["at_minute"]) if "at_minute" in intent else world.minute + int(intent.get("in_minutes", 0))
    mode = str(intent.get("mode", "foot"))
    start = journey.place_key(data, str(intent.get("from") or "")) or where(world, npc).get("place") or place
    clash = _conflict(world, npc, place, at, mode)
    path = _npc_route(world, start, place, set(), mode)
    need = _minutes(path, mode) if path else 0
    if not clash and at - need < world.minute:
        clash = f"{npc} cannot reach {_pname(world, place)} from {_pname(world, start)} in time: it takes {need // 60}h{need % 60:02d}"
    if clash:
        return {"status": "done", "elapsed_minutes": 0, "data": {"made": False, "error": clash}}
    aid = str(intent.get("id") or f"appt-{ctx.action_id}")
    record = {"npc": npc, "place": place, "from": start, "at_minute": at, "departs": at - need, "mode": mode,
              "purpose": str(intent.get("purpose", "")), "otherwise": intent.get("otherwise"), "on_meet": intent.get("on_meet"),
              "cost": intent.get("cost"), "stays_minutes": int(intent.get("stays_minutes", 120)), "status": "planned", "note": ""}
    world.put("appointment", aid, record)
    if world.get("npcpos", npc) is None:
        world.put("npcpos", npc, {"place": start, "since": world.minute})
    scheduler.schedule(ctx.db, f"npc-depart-{aid}", at - need, {"type": "npc_depart", "id": aid}, priority=1)
    return {"status": "done", "elapsed_minutes": 0, "data": {"made": True, "appointment": aid, "departs_minute": at - need, **record}}


@turn.handler("npc_schedule")
def _npc_schedule(ctx, intent: dict) -> dict:
    """npc_schedule — give an NPC a structured day. Their prose Schedule in npcs-full.md stays as it is until you do.

    {"action": "npc_schedule", "npc": "Bren", "blocks": [{"from": "06:00", "to": "18:00", "place": "Millbridge",
     "activity": "at the mill"}, {"from": "18:00", "to": "06:00", "place": "Millbridge", "activity": "home"}],
     "exceptions": [{"day": 739755, "place": "Market", "activity": "market day"}]}
    `day` is the absolute in-world day (minute ÷ 1440). An appointment overrides the schedule while it lasts."""
    world = _world(ctx)
    npc = str(intent.get("npc", ""))
    data = _map(world)
    fix = lambda items: [{**i, "place": journey.place_key(data, str(i.get("place", ""))) or i.get("place")} for i in items or []]  # noqa: E731
    record = {"blocks": fix(intent.get("blocks")), "exceptions": fix(intent.get("exceptions")), "confirmed": True}
    world.put("schedule", npc, record)
    return {"status": "done", "elapsed_minutes": 0, "data": {"npc": npc, **record, "now": where(world, npc)}}


@turn.handler("where")
def _where(ctx, intent: dict) -> dict:
    """where — where an NPC is: {"action": "where", "npc": "Bren"} (add "in_minutes" or "at_minute" for another time)."""
    world = _world(ctx)
    minute = int(intent["at_minute"]) if "at_minute" in intent else world.minute + int(intent.get("in_minutes", 0))
    found = where(world, str(intent.get("npc", "")), minute)
    return {"status": "done", "elapsed_minutes": 0,
            "data": {"npc": intent.get("npc"), "minute": minute, **found, "place_name": _pname(world, found.get("place"))}}


# ── factions that decide ──────────────────────────────────────────────────────

def brief(world, name: str) -> dict:
    """All one faction has to go on: its own numbers and what it has heard. Nothing the GM knows that it does not."""
    data = world.json("factions.json")
    f = (data.get("factions") or {}).get(name)
    if f is None:
        return {"error": f"no faction {name!r}"}
    beliefs = knowledge.known_to(world, f"faction:{name}")
    return {"faction": name,
            "stats": {k: f.get(k) for k in ("force", "wealth", "influence", "stability", "goal", "progress", "clock", "rivals", "holds")},
            "knows": [{"fact": b["fact"], "claim": b["claim"], "source": b["source"], "confidence": b["confidence"]} for b in beliefs],
            "truces": sorted(k.split("|", 1)[1] for k, t in world.all("truce").items()
                             if k.startswith(f"{name}|") and t.get("until", 0) > (world.minute or 0)),
            "may_choose": list(CHOICES)}


def legal(world, name: str, intent: dict) -> "str | None":
    """Why a faction cannot make this move, or None if it can. It may only act on what it knows and has."""
    data = world.json("factions.json")
    factions = data.get("factions") or {}
    f = factions.get(name)
    if f is None:
        return f"no faction {name!r}"
    choice = intent.get("choice")
    if choice not in CHOICES:
        return f"unknown choice {choice!r} (one of {', '.join(CHOICES)})"
    known = {b["fact"] for b in knowledge.known_to(world, f"faction:{name}")}
    for fact in intent.get("because") or []:
        if fact not in known:
            return f"{name} has not heard of {fact!r}: it cannot be a reason for them"
    if choice in ("attack", "negotiate"):
        target = intent.get("target")
        if target not in factions:
            return f"no faction {target!r} to {choice} with"
        if target not in (f.get("rivals") or []) and not any(target in str(b) for b in known):
            return f"{name} has no dealings with {target} and has heard nothing of them"
        truce = world.get("truce", f"{name}|{target}")
        if choice == "attack" and truce and truce["until"] > (world.minute or 0):
            return f"{name} has a truce with {target}"
    if choice == "advance" and f.get("progress", 0) >= f.get("clock", 1):
        return f"{name}'s goal is complete: it needs a new one"
    for stat, need in (f.get("goal_cost") or {}).items():
        if choice == "advance" and f.get(stat, 0) < need:
            return f"{name} lacks {stat} {need} for its goal: postpone or rest"
    return None


def decide(world, name: str, week: int) -> "dict | None":
    """This week's move by rule, from the faction's own brief. None means: nothing special, act as factions do."""
    data = world.json("factions.json")
    f = data["factions"][name]
    import faction as faction_mod
    info = brief(world, name)
    threats = [b for b in info["knows"] if any(h in str(b["claim"]) or h in str(b["fact"]) for h in (f.get("holds") or []))
               and any(w in str(b["claim"]).lower() for w in ("attack", "seize", "raid", "march", "take", "threat"))]
    if f["stability"] * 2 <= faction_mod.max_stability(f):
        return {"choice": "rest", "because": [], "why": "too weak to do anything else"}
    if threats:
        return {"choice": "defend", "because": [t["fact"] for t in threats], "why": "it has heard its ground is threatened"}
    for rival in f.get("rivals") or []:
        r = data["factions"].get(rival)
        heard = [b["fact"] for b in info["knows"] if rival in str(b["claim"]) or rival in str(b["fact"])]
        if r and heard and r.get("force", 0) > f.get("force", 0) and rival not in info["truces"]:
            return {"choice": "negotiate", "target": rival, "because": heard, "why": f"it has heard {rival} is stronger"}
    for stat, need in (f.get("goal_cost") or {}).items():
        if f.get(stat, 0) < need and f.get("progress", 0) < f.get("clock", 1):
            return {"choice": "postpone", "because": [], "why": f"it lacks {stat} {need} for its goal"}
    return None


def _carry_out(world, name: str, d: dict, rng) -> str:
    import faction as faction_mod
    data = world.json("factions.json")
    f = data["factions"][name]
    choice = d["choice"]
    if choice == "rest":
        return faction_mod._recover(name, f)
    if choice == "defend":
        f["stability"] = min(faction_mod.max_stability(f), f["stability"] + 1)
        world.put("guard", name, {"holds": f.get("holds") or [], "since": world.minute, "because": d.get("because")})
        return f"{name} pulls its people back to hold what it has (Stability → {f['stability']})"
    if choice == "negotiate":
        target = d["target"]
        until = (world.minute or 0) + 4 * scheduler.WEEK
        world.put("truce", f"{name}|{target}", {"until": until, "because": d.get("because")})
        world.put("truce", f"{target}|{name}", {"until": until, "because": d.get("because")})
        return f"{name} sends envoys to {target}: a truce for four weeks"
    if choice == "postpone":
        return f"{name} puts its plan off: {d.get('why', 'not the time')}"
    if choice == "attack":
        return faction_mod.act(name, data, rng, "attack", d["target"])
    return faction_mod.act(name, data, rng, "advance")


_inner_week = scheduler.EFFECTS["faction_week"]


@scheduler.effect("faction_week")
def _faction_week(world, row, eff):
    """A week for every faction: a stored decision is replayed, else the rules decide from what the faction
    knows, else it acts as factions do. Then (trade.py) a finished goal may change the map."""
    import faction as faction_mod
    import world_db as wdb
    data = world.json("factions.json")
    if not data or not data.get("factions"):
        return None
    week = int(data.get("turn", 0)) + 1
    chosen = {}
    for name in sorted(data["factions"]):
        if not faction_mod._alive(data["factions"][name]):
            continue
        stored = world.get("decision", f"{name}|{week}")
        d = stored or decide(world, name, week)
        if d and not stored:
            d = {**d, "by": "rules"}
            world.put("decision", f"{name}|{week}", d)
        if d and not legal(world, name, d):
            chosen[name] = d
    if not chosen:
        return _inner_week(world, row, eff)
    r = wdb.rng(world.db, row["event_id"])
    data["turn"] = week
    lines = []
    for name in sorted(data["factions"]):
        truced = {k.split("|", 1)[1] for k, t in world.all("truce").items()
                  if k.startswith(f"{name}|") and t.get("until", 0) > (world.minute or 0)}
        f = data["factions"][name]
        if name in chosen:
            lines.append(_carry_out(world, name, chosen[name], r) + f" [{chosen[name].get('why') or chosen[name]['choice']}]")
        else:
            keep = f.get("rivals") or []
            f["rivals"] = [x for x in keep if x not in truced]     # no striking someone you have a truce with
            lines.append(faction_mod.act(name, data, r))
            f["rivals"] = keep
    data["last_turn"] = row["due_minute"]
    log = data.setdefault("log", [])
    log.extend(f"- {line}" for line in lines)
    del log[:-60]
    world.touch("factions.json")
    scheduler.schedule(world.db, f"faction-week-{week + 1}", row["due_minute"] + scheduler.WEEK,
                       {"type": "faction_week", "week": week + 1}, priority=-10)
    return [{"type": "faction_move", "recipient": "dm", "text": line} for line in lines] + trade.faction_outcomes(world)


@turn.handler("faction_brief")
def _faction_brief(ctx, intent: dict) -> dict:
    """faction_brief — what one faction knows and has: {"action": "faction_brief", "faction": "Tollmen"}.

    Plan that faction's move from this and nothing else (give exactly this to a subagent if you use one)."""
    return {"status": "done", "elapsed_minutes": 0, "data": brief(_world(ctx), str(intent.get("faction", "")))}


@turn.handler("faction_intent")
def _faction_intent(ctx, intent: dict) -> dict:
    """faction_intent — a faction's move for its next week, decided by you or a subagent from its brief.

    {"action": "faction_intent", "faction": "Tollmen", "choice": "negotiate", "target": "Millers' Guild",
     "because": ["mill-fire"], "why": "they cannot hold the bridge and fight the guild"}
    choice: advance | attack | rest | defend | negotiate | postpone. The engine refuses a move the faction could not
    make (a reason it has not heard of, a target it does not know, a goal it cannot pay for). An accepted move is
    stored and carried out when the faction's week comes; a replay uses the stored move."""
    world = _world(ctx)
    name = str(intent.get("faction", ""))
    problem = legal(world, name, intent)
    if problem:
        return {"status": "done", "elapsed_minutes": 0, "data": {"accepted": False, "error": problem}}
    week = int(world.json("factions.json").get("turn", 0)) + 1
    d = {k: intent[k] for k in ("choice", "target", "because", "why") if k in intent}
    d["by"] = str(intent.get("by", "gm"))
    world.put("decision", f"{name}|{week}", d)
    return {"status": "done", "elapsed_minutes": 0, "data": {"accepted": True, "faction": name, "week": week, **d}}


# A route's state is news like any other: both ends know at once, everyone else has to hear of it.
_inner_route = turn.HANDLERS["route"]


@turn.handler("route")
def _route(ctx, intent: dict) -> dict:
    out = _inner_route(ctx, intent)
    rid = (out.get("data") or {}).get("route")
    if rid and "access" in intent:
        world = _world(ctx)
        claim = f"{intent['access']}: {intent.get('reason') or (out['data']['now'].get('owner') or '')}".strip(": ")
        world.put("fact", f"route:{rid}", {"text": claim, "place": rid.split("|")[0], "minute": world.minute,
                                           "witnesses": [f"place:{p}" for p in rid.split("|")]})
        for end in rid.split("|"):
            knowledge.learn(world, f"place:{end}", f"route:{rid}", claim, "they can see it", 1.0)
    return out


_route.__doc__ = _inner_route.__doc__
