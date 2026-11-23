#!/usr/bin/env python3
"""
journey.py — rests and journeys that the world can interrupt (engine actions `rest` and `travel`).

Both take in-world time through the scheduler. If something comes due on the way that the party has
to answer (an event queued with "interrupt": true, a closed road), time stops at that minute, the
turn waits for the players' decision, and the rest of the plan is worked out again from where they
are. Nothing is granted or spent ahead of time: a rest gives its benefit only when it is complete,
and a journey marks a place visited only when the party is standing in it.

    {"action": "rest", "type": "long", "resting": ["Mira", "Theo"], "watch": ["Bren"]}
    {"action": "rest", "type": "short", "resting": ["Mira"], "hit_dice": {"Mira": 2}, "heal": {"Mira": 9}}
    {"action": "travel", "to": "Market", "mode": "foot"}

Decisions are answered with `turn.py answer --request <id> --value <choice>`:
    rest    continue | restart | stop        travel    continue | back | stop
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import paths  # noqa: E402
import scheduler  # noqa: E402
import turn  # noqa: E402

REST_MINUTES = {"short": 60, "long": 480}
TIME_FACTORS: list = []   # fn(world) -> (factor, why): season, weather, an overloaded pack … slow a journey down


def _decide(st: dict, question: str, options: list, expected: str = "party", **extra) -> dict:
    """Stop here and ask. The key is numbered, so each interruption of the same action is its own question."""
    st["asked"] = st.get("asked", 0) + 1
    st["waiting"] = f"d{st['asked']}"
    return {"status": "waiting_for_player",
            "requests": [{"key": st["waiting"], "kind": "decision", "expected": expected,
                          "text": f"{question} ({' / '.join(options)})"}], **extra}


def _answer(ctx, st: dict) -> "str | None":
    key = st.pop("waiting", None)
    if not key or key not in ctx.answers:
        return None
    return str(ctx.answers[key]["value"]).strip().lower()


def _interruptions(visible: list) -> str:
    return "; ".join(v.get("text", "") for v in visible if v.get("interrupt")) or "something needs your attention"


# ── rest ──────────────────────────────────────────────────────────────────────

def _pc_sheets(world, names) -> dict:
    sheets = {}
    folder = world.camp / "characters"
    for sheet in sorted(folder.glob("*.md")) if folder.is_dir() else []:
        text = sheet.read_text(encoding="utf-8")
        title = text.splitlines()[0].lstrip("# ").strip() if text.strip() else sheet.stem
        if names is None or any(n.casefold() in (title.casefold(), sheet.stem.casefold(), title.split()[0].casefold())
                                for n in names):
            sheets[f"characters/{sheet.name}"] = (title, text)
    return sheets


def _grant_rest(world, st: dict, rest_type: str, writes: dict) -> list:
    """The benefit of a finished rest, once, for those who really rested. Rules come from economy and tracker."""
    import economy
    import tracker as tracker_mod
    ruleset = paths.campaign_ruleset(world.campaign)
    gained = []
    for rel, (title, text) in _pc_sheets(world, st.get("resting")).items():
        new_text, changes = economy._apply_rest_to_sheet(
            text, rest_type, hit_dice_spent=int((st.get("hit_dice") or {}).get(title, 0)),
            heal=int((st.get("heal") or {}).get(title, 0)), ruleset=ruleset)
        if new_text != text:
            writes[rel] = new_text
        gained.append({"character": title, "changes": changes})
    if rest_type == "long":
        state = world.json("tracker.json")
        resting = {n.casefold() for n in st.get("resting") or []}
        watch = {n.casefold() for n in st.get("watch") or []}
        for key, ent in (state or {}).items():
            if key.startswith("_") or not isinstance(ent, dict):
                continue
            name = str(ent.get("name", key)).casefold()
            if st.get("resting") is not None and name not in resting | watch:
                continue                          # not part of this rest
            if ent.get("concentration") and name not in watch:      # sleeping ends it; someone on watch is awake
                spell = ent["concentration"]
                ent["concentration"] = None
                ent["effects"] = [e for e in ent.get("effects", [])
                                  if not (e.get("concentration") and str(e.get("name", "")).lower() == spell.lower())]
                world.touch("tracker.json")
            if ent.get("exhaustion", 0) > 0 and not tracker_mod._is_dead(ent) and not tracker_mod._is_down(ent, world.campaign):
                ent["exhaustion"] -= 1
                world.touch("tracker.json")
    return gained


@turn.handler("rest")
def _rest(ctx, intent: dict) -> dict:
    """rest — a short (1 hour) or long (8 hours) rest that can be interrupted.

    {"action": "rest", "type": "long", "resting": ["Mira", "Theo"], "watch": ["Bren"],
     "hit_dice": {"Mira": 2}, "heal": {"Mira": 9}}      (hit_dice / heal: a short rest's spent dice and their total)
    `resting` defaults to every PC. Someone on `watch` still rests but stays awake (keeps concentration).
    Time passes through the world clock, once. If something interrupts, the turn waits:
      continue — it was brief; the rest goes on for the time that was left
      restart  — it was strenuous (a fight, an hour on your feet); the rest begins again
      stop     — get up. 2014: no benefit. 2024: a long rest of an hour or more still counts as a short one.
    The benefit (HP, Hit Dice, slots, exhaustion) is applied only when the rest is complete."""
    world = scheduler.World(ctx.campaign, ctx.db)
    kind = "long" if str(intent.get("type", "long")).lower().startswith("l") else "short"
    st = world.get("rest", ctx.action_id) or {
        "type": kind, "need": REST_MINUTES[kind], "done": 0, "start_minute": world.minute,
        "resting": intent.get("resting"), "watch": intent.get("watch") or [],
        "hit_dice": intent.get("hit_dice") or {}, "heal": intent.get("heal") or {}, "log": []}
    visible, writes, elapsed = [], {}, 0
    choice = _answer(ctx, st)
    ruleset = paths.campaign_ruleset(ctx.campaign)
    if choice == "restart":
        st["done"] = 0
        st["log"].append({"minute": world.minute, "restart": True})
    elif choice == "stop":
        granted = []
        if ruleset == "2024" and st["type"] == "long" and st["done"] >= 60:
            granted = _grant_rest(world, {**st, "hit_dice": {}, "heal": {}}, "short", writes)
        st["status"] = "abandoned"
        world.put("rest", ctx.action_id, st)
        return {"status": "done", "elapsed_minutes": 0, "writes": {**world.writes(), **writes},
                "data": {"rest": "abandoned", "rested_minutes": st["done"], "benefit": granted,
                         "ruleset": ruleset, "start_minute": st["start_minute"]},
                "visible_events": [{"type": "rest", "recipient": "party",
                                    "text": "The rest is broken off." + ("" if granted else " No one gains its benefit.")}]}
    while st["done"] < st["need"]:
        out = scheduler.advance(world, world.minute + st["need"] - st["done"])
        st["done"] += out["elapsed_minutes"]
        elapsed += out["elapsed_minutes"]
        visible += out["visible_events"]
        if out["interrupted"]:
            st["log"].append({"minute": world.minute, "interrupted_by": _interruptions(out["visible_events"])})
            world.put("rest", ctx.action_id, st)
            ask = _decide(st, f"The rest is interrupted after {st['done'] // 60}h{st['done'] % 60:02d}: "
                              f"{_interruptions(out['visible_events'])}", ["continue", "restart", "stop"])
            world.put("rest", ctx.action_id, st)
            return {**ask, "elapsed_minutes": elapsed, "writes": world.writes(), "visible_events": visible,
                    "pending": ["adjudicate_interruption", "resolve_remaining_rest"],
                    "data": {"rested_minutes": st["done"], "remaining_minutes": st["need"] - st["done"]}}
        if not out["remaining"] and out["elapsed_minutes"] == 0:
            break                                 # no clock: nothing more can pass
    gained = _grant_rest(world, st, st["type"], writes)
    st["status"] = "complete"
    world.put("rest", ctx.action_id, st)
    visible.append({"type": "rest", "recipient": "party", "text": f"The {st['type']} rest is complete."})
    campfire = None
    if ctx.flag("campfire", "on") != "off":       # a rest is when characters talk: one question from their own sheets
        try:
            import story
            import world_db
            campfire = story.campfire(ctx.campaign, world_db.rng(ctx.db, f"campfire-{ctx.action_id}"))
        except Exception:
            campfire = None
    return {"status": "done", "elapsed_minutes": elapsed, "writes": {**world.writes(), **writes}, "visible_events": visible,
            "data": {"rest": "complete", "benefit": gained, "ruleset": ruleset, "start_minute": st["start_minute"],
                     "interruptions": st["log"], "campfire": campfire}}


# ── travel ────────────────────────────────────────────────────────────────────

def plan_route(world, to_name: str, mode: str = "foot", from_key: "str | None" = None) -> list:
    """The legs from where the party is to `to_name`: [{a, b, a_name, b_name, miles, minutes}]. Changes nothing."""
    import world_map
    data = world.json("world-map.json", {"places": {}, "edges": [], "party_location": None})
    src, dst = place_key(data, from_key or data.get("party_location") or ""), place_key(data, to_name)
    if not src or not dst:
        raise ValueError(f"no route: unknown place ({from_key or data.get('party_location') or 'party location not set'} → {to_name})")
    route = _shortest(data, src, dst, mode, world)
    legs, slow, why = [], 1.0, []
    for factor in TIME_FACTORS:
        f, reason = factor(world)
        if f != 1.0:
            slow *= f
            why.append(reason)
    for a, b, miles, mult in route:
        speed = world_map.TRAVEL_SPEED_MPD.get(mode, 24.0)
        leg = {"a": a, "b": b, "a_name": data["places"][a]["name"], "b_name": data["places"][b]["name"],
               "miles": miles, "minutes": max(1, round(miles * mult * slow / speed * 1440))}
        if why:
            leg["slowed_by"] = why
        legs.append(leg)
    return legs


def place_key(data: dict, ref: str) -> "str | None":
    """The map key of a place given its key, its name or a slug of its name."""
    import world_map
    if not ref:
        return None
    places = data.get("places", {})
    if ref in places:
        return ref
    low = ref.strip().casefold()
    for key, place in places.items():
        if low in (key.casefold(), str(place.get("name", "")).casefold(), world_map._slug(str(place.get("name", ""))).casefold()):
            return key
    return None


def _shortest(data: dict, src: str, dst: str, mode: str, world) -> list:
    """Dijkstra over the map's edges by travel time; an off-road straight line when no road connects them."""
    import heapq
    import world_map
    adj: dict = {}
    for e in data.get("edges", []):
        for a, b in ((e["a"], e["b"]), (e["b"], e["a"])):
            biome = data["places"].get(b, {}).get("biome", "plains")
            mult = 1.0 if e.get("road", True) else world_map.BIOME_COST.get(biome, 1.2)
            adj.setdefault(a, []).append((b, float(e["miles"]), mult))
    queue, best = [(0.0, src, [])], {}
    while queue:
        cost, cur, path = heapq.heappop(queue)
        if cur == dst:
            return path
        if cur in best:
            continue
        best[cur] = cost
        for nxt, miles, mult in adj.get(cur, []):
            heapq.heappush(queue, (cost + miles * mult, nxt, path + [(cur, nxt, miles, mult)]))
    a, b = data["places"][src], data["places"][dst]
    mult = max(world_map.BIOME_COST.get(a.get("biome"), 1.0), world_map.BIOME_COST.get(b.get("biome"), 1.0))
    return [(src, dst, round(world_map._dist_miles(a, b), 1), mult)]


def route_block(world, a: str, b: str) -> "str | None":
    """Why the party cannot use the stretch between `a` and `b` right now, or None if it is open to them."""
    data = world.json("world-map.json", {"edges": []})
    for e in data.get("edges", []):
        if {e["a"], e["b"]} == {a, b} and e.get("closed"):
            return str(e.get("closed_reason") or "the way is closed")
    record = world.get("route", "|".join(sorted((a, b))))
    if record and record.get("access") == "closed":
        return str(record.get("reason") or f"closed by {record.get('owner', 'someone')}")
    return None


def route_toll(world, a: str, b: str) -> "str | None":
    """What is asked of travellers on the stretch between `a` and `b`, if someone takes a toll there."""
    record = world.get("route", "|".join(sorted((a, b))))
    if record and record.get("access") == "toll":
        return f"{record.get('owner') or 'someone'} asks a toll" + (f" of {record['toll']}" if record.get("toll") else "")
    return None


def _arrive(world, key: str) -> list:
    data = world.json("world-map.json")
    place = data["places"].get(key, {})
    data["party_location"] = key
    place["visited"], place["hidden"] = True, False
    data.pop("party_en_route", None)
    world.touch("world-map.json")
    return scheduler.fire(world, "enter", place.get("name", key))


@turn.handler("travel")
def _travel(ctx, intent: dict) -> dict:
    """travel — go to a place on the campaign map, one stretch at a time.

    {"action": "travel", "to": "Market", "mode": "foot" | "wagon" | "horse" | "ship"}
    The route is worked out leg by leg. A leg that is closed stops the party before it; an event that comes due
    on the road stops them at that minute. Either way the turn waits for a decision:
      continue — go on (the remaining route is worked out again from where they are)
      back     — return to the last place they stood in
      stop     — stay where they are, on the road
    A place counts as reached, and is marked visited, only when the party arrives in it."""
    world = scheduler.World(ctx.campaign, ctx.db)
    mode = str(intent.get("mode", "foot"))
    st = world.get("journey", ctx.action_id)
    visible, elapsed = [], 0
    if st is None:
        try:
            legs = plan_route(world, str(intent["to"]), mode)
        except (ValueError, KeyError) as exc:
            return {"status": "done", "elapsed_minutes": 0, "data": {"error": str(exc)}}
        st = {"to": legs[-1]["b"], "mode": mode, "legs": legs, "i": 0, "progress": 0, "start_minute": world.minute, "log": []}
    choice = _answer(ctx, st)
    data = world.json("world-map.json")
    if choice == "stop":
        st["status"] = "stopped"
        world.put("journey", ctx.action_id, st)
        return {"status": "done", "elapsed_minutes": 0, "writes": world.writes(),
                "data": {"journey": "stopped", "position": data.get("party_en_route") or data.get("party_location")},
                "visible_events": [{"type": "travel", "recipient": "party", "text": "You stop where you are."}]}
    if choice == "back" and st["i"] < len(st["legs"]):
        leg = st["legs"][st["i"]]
        st["legs"] = [{"a": leg["b"], "b": leg["a"], "a_name": leg["b_name"], "b_name": leg["a_name"],
                       "miles": leg["miles"], "minutes": max(1, st["progress"]), "returning": True}]
        st["i"], st["progress"], st["to"] = 0, 0, leg["a"]
    elif choice == "continue" and st["i"] < len(st["legs"]):     # the plan from here, on the map as it is now
        leg = st["legs"][st["i"]]
        try:
            onward = plan_route(world, data["places"][st["to"]]["name"], mode, from_key=leg["b"]) if leg["b"] != st["to"] else []
        except ValueError:
            onward = st["legs"][st["i"] + 1:]
        st["legs"] = st["legs"][:st["i"] + 1] + onward
        st["passed_block"] = True                 # they chose to go on past whatever stopped them
    while st["i"] < len(st["legs"]):
        leg = st["legs"][st["i"]]
        fresh = st["progress"] == 0 and not leg.get("returning")
        block = route_block(world, leg["a"], leg["b"]) if fresh else None
        toll = route_toll(world, leg["a"], leg["b"]) if fresh and not block else None
        if (block or toll) and not st.pop("passed_block", False):
            st["log"].append({"minute": world.minute, "blocked": [leg["a"], leg["b"]], "reason": block or toll})
            ask = _decide(st, f"The way from {leg['a_name']} toward {leg['b_name']} is closed: {block}" if block else
                          f"On the way from {leg['a_name']} toward {leg['b_name']}, {toll}", ["continue", "back", "stop"])
            world.put("journey", ctx.action_id, st)
            return {**ask, "elapsed_minutes": elapsed, "writes": world.writes(), "visible_events": visible,
                    "pending": ["adjudicate_closed_route", "resolve_remaining_journey"],
                    "data": {"at": leg["a_name"], "blocked_leg": [leg["a_name"], leg["b_name"]]}}
        st.pop("passed_block", None)
        data["party_en_route"] = {"from": leg["a"], "to": leg["b"], "eta_minute": world.minute + leg["minutes"] - st["progress"]}
        world.touch("world-map.json")
        out = scheduler.advance(world, world.minute + leg["minutes"] - st["progress"])
        st["progress"] += out["elapsed_minutes"]
        elapsed += out["elapsed_minutes"]
        visible += out["visible_events"]
        if out["interrupted"]:
            st["log"].append({"minute": world.minute, "interrupted_by": _interruptions(out["visible_events"])})
            ask = _decide(st, f"On the road from {leg['a_name']} toward {leg['b_name']}: {_interruptions(out['visible_events'])}",
                          ["continue", "back", "stop"])
            world.put("journey", ctx.action_id, st)
            return {**ask, "elapsed_minutes": elapsed, "writes": world.writes(), "visible_events": visible,
                    "pending": ["adjudicate_interruption", "resolve_remaining_journey"],
                    "data": {"between": [leg["a_name"], leg["b_name"]], "minutes_into_leg": st["progress"]}}
        if st["progress"] < leg["minutes"]:
            if out["remaining"]:
                continue                          # a batch limit: more is due on this stretch
            break                                 # no clock to move
        visible += _arrive(world, leg["b"])
        visible.append({"type": "arrival", "recipient": "party", "text": f"You reach {leg['b_name']}."})
        st["i"], st["progress"] = st["i"] + 1, 0
        if any(v.get("interrupt") for v in visible[-3:]) and st["i"] < len(st["legs"]):
            ask = _decide(st, f"In {leg['b_name']}: {_interruptions(visible)}", ["continue", "back", "stop"])
            world.put("journey", ctx.action_id, st)
            return {**ask, "elapsed_minutes": elapsed, "writes": world.writes(), "visible_events": visible,
                    "data": {"at": leg["b_name"]}}
    st["status"] = "arrived"
    world.put("journey", ctx.action_id, st)
    here = data["places"].get(data.get("party_location") or "", {}).get("name")
    return {"status": "done", "elapsed_minutes": elapsed, "writes": world.writes(), "visible_events": visible,
            "data": {"journey": "arrived", "at": here, "start_minute": st["start_minute"], "stops": st["log"]}}
