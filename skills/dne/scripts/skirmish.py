#!/usr/bin/env python3
"""
skirmish.py — fights that use where everyone stands, and end when the point of the scene is settled.

Works on the tactical grid (battlemap.json) or, for a scene told in words, on ZONES the GM names
("platform", "stairs", "street") with which zones touch and which can see each other.

  fight      "current" → {objective, end_when, sides, zones, props, round_triggers, round, status, outcome}
  combatant  "<name>"  → {side, resist, immune, vulnerable, needs_sight, reach, range, con_mod, morale,
                          orders, concentrating, used: {round, action, bonus, reaction}, resources}

Engine actions (turn.py help <name>):
  fight      open a fight: what it is for, what ends it, the ground, props and what happens on which round
  combatant  who is in it and what they can do
  advise     what an enemy can sensibly do now, from what it can see and reach and what it was told to do
  move       move someone; says who gets a reaction to it and waits for a player whose reaction it is
  spend      use an action, bonus action, reaction or a limited resource (refused if already used)
  damage     apply damage through resistance, immunity and vulnerability to HP, concentration and morale
  area       who is inside a blast, cone or line
  prop       use something in the scenery (once, unless it says otherwise)
  round      the next round: budgets reset, the round's trigger fires

SIGHT   A wall between two creatures blocks line of sight; so does a zone that cannot see the other.
        An ability marked needs_sight cannot pick a target its user cannot see.
COVER   One cover square (or a creature) on the line: half cover, +2 AC. Two or more: three-quarters, +5.
        `cover_rule: off` in Session Flags turns it off.
REACTION One per creature per round. Leaving a hostile creature's reach gives it a chance to use it.
THE END A fight is over when its `end_when` is true, whatever HP is left on either side.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import journey  # noqa: E402
import paths  # noqa: E402
import scheduler  # noqa: E402
import turn  # noqa: E402

MAP = "battlemap.json"
SIGHT_LIMITS: list = []   # fn(world) -> feet or None: fog, darkness … how far anyone can see at all


def _world(ctx):
    return scheduler.World(ctx.campaign, ctx.db)


def _map(world) -> dict:
    data = world.json(MAP)
    if isinstance(data, dict):
        data.setdefault("tokens", [])
        data.setdefault("terrain", {})
    return data


def token(world, name: str) -> "dict | None":
    low = str(name).strip().casefold()
    return next((t for t in _map(world).get("tokens", []) if str(t.get("name", "")).casefold() == low), None)


def _fight(world) -> dict:
    return world.get("fight", "current") or {}


# ── geometry: grid or zones ───────────────────────────────────────────────────

def cells_between(a: tuple, b: tuple) -> list:
    """The squares a straight line from a to b passes through, ends excluded (Bresenham)."""
    (x0, y0), (x1, y1) = a, b
    dx, dy, sx, sy = abs(x1 - x0), -abs(y1 - y0), (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
    err, out = dx + dy, []
    while (x0, y0) != (x1, y1):
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x0 += sx
        if e2 <= dx:
            err += dx
            y0 += sy
        if (x0, y0) != (x1, y1):
            out.append((x0, y0))
    return out


def _zone_of(t: dict) -> "str | None":
    return t.get("zone")


def _zone_hops(fight: dict, a: str, b: str) -> int:
    zones, seen, frontier, hops = fight.get("zones") or {}, {a}, [a], 0
    while frontier:
        if b in frontier:
            return hops
        frontier = [n for z in frontier for n in (zones.get(z, {}).get("next") or []) if n not in seen and not seen.add(n)]
        hops += 1
    return 99


def distance(world, a: dict, b: dict) -> int:
    """Feet between two tokens. Zones: same zone 5 ft, 30 ft per zone crossed."""
    if _zone_of(a) or _zone_of(b):
        return 5 if _zone_of(a) == _zone_of(b) else 30 * _zone_hops(_fight(world), _zone_of(a), _zone_of(b))
    return 5 * max(abs(a["x"] - b["x"]), abs(a["y"] - b["y"]))


def sees(world, a: dict, b: dict) -> bool:
    """Whether `a` has line of sight to `b`: no wall on the line (grid), or the zone can see the other (zones)."""
    if b.get("hidden"):
        return False
    limits = [f for f in (limit(world) for limit in SIGHT_LIMITS) if f]
    if limits and "name" in a and "name" in b and distance(world, a, b) > min(limits):
        return False
    if _zone_of(a) or _zone_of(b):
        za, zb = _zone_of(a), _zone_of(b)
        return za == zb or zb in ((_fight(world).get("zones") or {}).get(za, {}).get("sees") or [])
    terrain = _map(world).get("terrain", {})
    return not any(terrain.get(f"{x},{y}") == "wall" for x, y in cells_between((a["x"], a["y"]), (b["x"], b["y"])))


def cover(world, a: dict, b: dict) -> tuple:
    """(AC bonus, name) of the cover `b` has from `a`."""
    if paths.session_flag(world.campaign, "cover_rule", "standard") == "off":
        return 0, "none"
    if _zone_of(a) or _zone_of(b):
        return ((2, "half") if b.get("cover") else (0, "none"))
    data = _map(world)
    line = set(cells_between((a["x"], a["y"]), (b["x"], b["y"])))
    blockers = sum(1 for x, y in line if data.get("terrain", {}).get(f"{x},{y}") == "cover")
    blockers += sum(1 for t in data.get("tokens", []) if (t.get("x"), t.get("y")) in line and t.get("kind") != "obj")
    return (5, "three-quarters") if blockers >= 2 else (2, "half") if blockers == 1 else (0, "none")


def _side(world, name: str) -> str:
    rec = world.get("combatant", name) or {}
    t = token(world, name) or {}
    return rec.get("side") or ("party" if t.get("kind") == "pc" else "enemy" if t.get("kind") == "enemy" else "other")


def _hp(t: dict) -> "tuple | None":
    m = re.fullmatch(r"\s*(-?\d+)\s*/\s*(\d+)\s*", str(t.get("hp", "")))
    return (int(m.group(1)), int(m.group(2))) if m else None


def _budget(world, name: str) -> dict:
    rec = world.get("combatant", name) or {}
    rnd = int(_fight(world).get("round", 1))
    used = rec.get("used") or {}
    if used.get("round") != rnd:
        used = {"round": rnd}
    rec["used"] = used
    return rec


# ── the end of a fight ────────────────────────────────────────────────────────

def _met(world, cond: dict) -> bool:
    if "token" in cond:
        t = token(world, cond["token"])
        if cond.get("gone"):
            return t is None
        if t is None:
            return False
        if "zone" in cond:
            return _zone_of(t) == cond["zone"]
        if "at" in cond:
            return [t.get("x"), t.get("y")] in [list(c) for c in cond["at"]]
        if "down" in cond:
            hp = _hp(t)
            return bool(hp) and hp[0] <= 0
    if "all_down" in cond:
        side = [t for t in _map(world).get("tokens", []) if _side(world, t["name"]) == cond["all_down"]]
        return bool(side) and all((_hp(t) or (1, 1))[0] <= 0 for t in side)
    if "round" in cond:
        return int(_fight(world).get("round", 1)) > int(cond["round"])
    if "thing" in cond:
        return scheduler._holds(world, cond)
    return False


def check_end(world) -> list:
    """Close the fight if what it was for is settled. Returns the notice, or nothing."""
    fight = _fight(world)
    if not fight or fight.get("status") != "running":
        return []
    for cond in fight.get("end_when") or []:
        if _met(world, cond):
            fight.update(status="ended", outcome=cond.get("outcome", "objective settled"), ended_round=fight.get("round", 1))
            world.put("fight", "current", fight)
            standing = [t["name"] for t in _map(world).get("tokens", [])
                        if _side(world, t["name"]) == "enemy" and (_hp(t) or (1, 1))[0] > 0]
            return [{"type": "fight_over", "recipient": "party",
                     "text": f"The fight is over: {fight['outcome']}."
                             + (f" Still standing: {', '.join(standing)} (they do not have to be beaten)." if standing else "")}]
    return []


# ── actions ───────────────────────────────────────────────────────────────────

@turn.handler("fight")
def _fight_action(ctx, intent: dict) -> dict:
    """fight — open a fight and say what it is for.

    {"action": "fight", "objective": "get the witness off the platform",
     "end_when": [{"token": "Witness", "at": [[11, 5]], "outcome": "the witness is on the train"},
                  {"token": "Witness", "down": true, "outcome": "the witness is lost"},
                  {"all_down": "enemy", "outcome": "the platform is clear"}],
     "zones": {"platform": {"next": ["stairs"], "sees": ["stairs"]}, "stairs": {"next": ["platform", "street"], "sees": ["platform"]},
               "street": {"next": ["stairs"], "sees": []}},
     "props": [{"name": "chandelier", "effect": "falls on whoever stands under it: 2d6, prone"}],
     "round_triggers": {"2": "the fire reaches the exit", "3": "a second squad comes up the stairs"}}
    `end_when` conditions: {"token": T, "at": [[x, y]]} | {"token": T, "zone": Z} | {"token": T, "down": true} |
    {"token": T, "gone": true} | {"all_down": "<side>"} | {"round": N}. The first that is true ends the fight, with
    whatever HP is left. Use `zones` instead of the grid for a fight told in words."""
    world = _world(ctx)
    fight = {"objective": str(intent.get("objective", "")), "end_when": intent.get("end_when") or [{"all_down": "enemy"}],
             "zones": intent.get("zones") or {}, "props": [{**p, "used": False} for p in intent.get("props") or []],
             "round_triggers": {str(k): v for k, v in (intent.get("round_triggers") or {}).items()},
             "round": 1, "status": "running", "outcome": ""}
    world.put("fight", "current", fight)
    return {"status": "done", "elapsed_minutes": 0, "data": fight}


@turn.handler("combatant")
def _combatant(ctx, intent: dict) -> dict:
    """combatant — someone in the fight, where they are and what they can do.

    {"action": "combatant", "name": "Guard", "side": "enemy", "kind": "enemy", "x": 9, "y": 5, "hp": "18/18",
     "reach": 5, "range": 60, "needs_sight": true, "resist": ["fire"], "immune": [], "vulnerable": ["cold"],
     "con_mod": 1, "morale": 7, "orders": "block the stairs", "concentrating": "Hold Person",
     "resources": {"Second Wind": 1}}
    Use "zone": "platform" instead of x and y in a fight told in words. `needs_sight` says its attacks need a target
    it can see. `orders` is what it was told to do: `advise` weighs it against the fight's objective."""
    world = _world(ctx)
    name = str(intent.get("name", ""))
    rec = world.get("combatant", name) or {}
    for key in ("side", "reach", "range", "needs_sight", "resist", "immune", "vulnerable", "con_mod", "morale", "orders",
                "concentrating", "resources"):
        if key in intent:
            rec[key] = intent[key]
    world.put("combatant", name, rec)
    if any(k in intent for k in ("x", "y", "zone", "hp", "kind", "hidden", "cover")):
        data = _map(world)
        if not data:
            data.update({"width": 12, "height": 10, "title": "Encounter", "terrain": {}, "tokens": []})
        t = token(world, name)
        if t is None:
            t = {"name": name, "kind": intent.get("kind", "enemy")}
            data["tokens"].append(t)
        t.update({k: intent[k] for k in ("x", "y", "zone", "hp", "kind", "hidden", "cover") if k in intent})
        world.touch(MAP)
    return {"status": "done", "elapsed_minutes": 0, "writes": world.writes(), "refresh": "battlemap",
            "data": {"name": name, **rec, "token": token(world, name)}, "visible_events": check_end(world)}


@turn.handler("advise")
def _advise(ctx, intent: dict) -> dict:
    """advise — what an enemy can sensibly do this turn: {"action": "advise", "enemy": "Guard"}.

    Lists the targets it can actually see and reach (an attack that needs sight never picks someone behind a wall),
    with distance and cover, and the moves its orders and the fight's objective suggest: hold a spot, block the way
    out, go for the one the party is protecting, or fetch help. You choose; this is only what is possible."""
    world = _world(ctx)
    name = str(intent.get("enemy", ""))
    me, rec, fight = token(world, name), world.get("combatant", name) or {}, _fight(world)
    if not me:
        return {"status": "done", "elapsed_minutes": 0, "data": {"error": f"{name} is not on the map"}}
    mine = _side(world, name)
    needs_sight = rec.get("needs_sight", True)
    reach = max(int(rec.get("reach", 5)), int(rec.get("range", 0)))
    targets, unseen = [], []
    for t in _map(world).get("tokens", []):
        if t["name"] == me["name"] or t.get("kind") == "obj" or _side(world, t["name"]) == mine:
            continue
        if (_hp(t) or (1, 1))[0] <= 0:
            continue
        visible = sees(world, me, t)
        if needs_sight and not visible:
            unseen.append(t["name"])
            continue
        dist = distance(world, me, t)
        ac_bonus, cov = cover(world, me, t) if visible else (0, "unseen")
        targets.append({"name": t["name"], "feet": dist, "in_range": dist <= reach, "sees": visible,
                        "cover": cov, "ac_bonus": ac_bonus, "hp": t.get("hp", "")})
    targets.sort(key=lambda t: (not t["in_range"], t["feet"]))
    options = []
    protected = [c.get("token") for c in fight.get("end_when") or [] if c.get("token") and ("at" in c or "zone" in c)]
    for who in protected:
        seen = next((t for t in targets if t["name"] == who), None)
        options.append(f"stop {who} getting away" + ("" if seen else f" (it cannot see {who} from here: move first)"))
    if rec.get("orders"):
        options.append(f"keep to its orders: {rec['orders']}")
    if targets and not any(t["in_range"] for t in targets):
        options.append(f"close with {targets[0]['name']} ({targets[0]['feet']} ft away)")
    hp = _hp(me)
    if hp and hp[0] * 2 <= hp[1]:
        options.append("fall back and fetch help (it is badly hurt: check its morale)")
    return {"status": "done", "elapsed_minutes": 0,
            "data": {"enemy": me["name"], "can_target": targets, "cannot_see": unseen, "options": options,
                     "reaction_left": not _budget(world, me["name"])["used"].get("reaction"),
                     "objective": fight.get("objective", "")}}


def _reactors(world, mover: dict, start: tuple, end: tuple) -> list:
    """Hostile creatures whose reach `mover` leaves, that can see it and still have their reaction."""
    out, mine = [], _side(world, mover["name"])
    for t in _map(world).get("tokens", []):
        if t["name"] == mover["name"] or t.get("kind") == "obj" or _side(world, t["name"]) == mine:
            continue
        if (_hp(t) or (1, 1))[0] <= 0 or _zone_of(t) or t.get("x") is None:
            continue
        reach = int((world.get("combatant", t["name"]) or {}).get("reach", 5)) // 5
        was = max(abs(t["x"] - start[0]), abs(t["y"] - start[1])) <= reach
        still = max(abs(t["x"] - end[0]), abs(t["y"] - end[1])) <= reach
        if was and not still and not _budget(world, t["name"])["used"].get("reaction") and sees(world, t, {**mover, "x": start[0], "y": start[1]}):
            out.append(t["name"])
    return out


@turn.handler("move")
def _move(ctx, intent: dict) -> dict:
    """move — move someone on the map: {"actor": "Guard", "action": "move", "to": [4, 5], "speed": 30}
    (or "to": "stairs" in a fight with zones; "disengage": true to provoke nobody).

    The path respects walls and difficult ground and is refused if it costs more than `speed`. Leaving a hostile
    creature's reach gives that creature a reaction, if it has one left this round and can see the mover. When that
    creature is a player's, the turn waits and asks them; an enemy's reaction is yours to use with `spend`."""
    import battlemap
    world = _world(ctx)
    name = str(intent.get("actor", ""))
    t = token(world, name)
    if not t:
        return {"status": "done", "elapsed_minutes": 0, "data": {"error": f"{name} is not on the map"}}
    st = world.get("moving", ctx.action_id)
    if st is None:
        to = intent.get("to")
        if isinstance(to, str):
            st = {"from_zone": _zone_of(t), "to_zone": to, "ask": [], "feet": 30 * _zone_hops(_fight(world), _zone_of(t), to)}
        else:
            data = _map(world)
            try:
                feet, path = battlemap.find_path(data, t["x"], t["y"], int(to[0]), int(to[1]))
            except (ValueError, KeyError, TypeError) as exc:
                return {"status": "done", "elapsed_minutes": 0, "data": {"moved": False, "error": str(exc)}}
            speed = int(intent.get("speed", 0))
            if speed and feet > speed:
                return {"status": "done", "elapsed_minutes": 0,
                        "data": {"moved": False, "error": f"that is {feet} ft; {name} has {speed} ft of movement"}}
            react = [] if intent.get("disengage") else _reactors(world, t, (t["x"], t["y"]), (int(to[0]), int(to[1])))
            st = {"from": [t["x"], t["y"]], "to": [int(to[0]), int(to[1])], "feet": feet, "provokes": react,
                  "ask": [r for r in react if (token(world, r) or {}).get("kind") == "pc"], "reactions": []}
    for who in list(st.get("ask") or []):
        key = f"react-{who}"
        if key in ctx.answers:
            took = str(ctx.answers[key]["value"]).strip().lower().startswith(("y", "a", "ใ"))
            if took:
                rec = _budget(world, who)
                rec["used"]["reaction"] = True
                world.put("combatant", who, rec)
            st["reactions"].append({"who": who, "used": took})
            st["ask"].remove(who)
        else:
            world.put("moving", ctx.action_id, st)
            return {"status": "waiting_for_player",
                    "requests": [{"key": key, "kind": "decision", "expected": who,
                                  "text": f"{who}: {name} is leaving your reach. Use your reaction to strike? (yes / no)"}],
                    "data": {"moving": name, "provokes": st["provokes"]}}
    if "to_zone" in st:
        t["zone"] = st["to_zone"]
    else:
        t["x"], t["y"] = st["to"]
    world.touch(MAP)
    world.put("moving", ctx.action_id, st)
    return {"status": "done", "elapsed_minutes": 0, "writes": world.writes(), "refresh": "battlemap",
            "visible_events": check_end(world),
            "data": {"moved": True, "actor": name, "feet": st.get("feet"), "now": {k: t.get(k) for k in ("x", "y", "zone")},
                     "provokes": st.get("provokes", []), "reactions": st.get("reactions", []),
                     "enemy_reactions_available": [r for r in st.get("provokes", [])
                                                   if (token(world, r) or {}).get("kind") != "pc"]}}


@turn.handler("spend")
def _spend(ctx, intent: dict) -> dict:
    """spend — use up part of a creature's turn or a limited resource.

    {"actor": "Mira", "action": "spend", "use": "reaction"}      use: action | bonus | reaction | <a resource name>
    Refused if it was already used this round (one action, one bonus action, one reaction) or none is left."""
    world = _world(ctx)
    name, use = str(intent.get("actor", "")), str(intent.get("use", "action"))
    rec = _budget(world, name)
    if use in ("action", "bonus", "reaction"):
        if rec["used"].get(use):
            return {"status": "done", "elapsed_minutes": 0,
                    "data": {"spent": False, "error": f"{name} has already used their {use} this round"}}
        rec["used"][use] = True
    else:
        left = int((rec.get("resources") or {}).get(use, 0))
        if left <= 0:
            return {"status": "done", "elapsed_minutes": 0, "data": {"spent": False, "error": f"{name} has no {use} left"}}
        rec["resources"][use] = left - 1
    world.put("combatant", name, rec)
    return {"status": "done", "elapsed_minutes": 0, "data": {"spent": True, "actor": name, "use": use,
                                                             "left": rec.get("resources", {}).get(use) if use not in rec["used"] else None}}


def reduce(amount: int, kind: str, rec: dict) -> tuple:
    """(damage after resistance, immunity and vulnerability, why). Resistance halves (rounded down) before
    vulnerability doubles, as both rulesets apply them."""
    kind = str(kind or "").lower()
    if kind in [str(x).lower() for x in rec.get("immune") or []]:
        return 0, f"immune to {kind}"
    out, why = int(amount), []
    if kind in [str(x).lower() for x in rec.get("resist") or []]:
        out, _ = out // 2, why.append(f"resists {kind} (half)")
    if kind in [str(x).lower() for x in rec.get("vulnerable") or []]:
        out, _ = out * 2, why.append(f"vulnerable to {kind} (double)")
    return out, "; ".join(why) or "full"


@turn.handler("damage")
def _damage(ctx, intent: dict) -> dict:
    """damage — hurt someone: {"action": "damage", "target": "Guard", "amount": 12, "type": "fire", "source": "Mira"}.

    The amount passes through the target's immunity, resistance and vulnerability, comes off its HP (the map token
    for a creature, the sheet for a player character), and the result says what follows: a concentration save (DC 10
    or half the damage, whichever is higher) if it is concentrating, a morale check when an enemy drops to half HP
    or below, and whether that ended the fight."""
    world = _world(ctx)
    name = str(intent.get("target", ""))
    rec, t = world.get("combatant", name) or {}, token(world, name)
    dealt, why = reduce(int(intent.get("amount", 0)), intent.get("type", ""), rec)
    writes, data = {}, {"target": name, "rolled": int(intent.get("amount", 0)), "dealt": dealt, "why": why}
    sheets = journey._pc_sheets(world, [name]) if (t or {}).get("kind") == "pc" or not t else {}
    if sheets:
        rel, (title, text) = next(iter(sheets.items()))
        m = re.search(r"(\*\*HP:\*\*\s*)(\d+)(\s*/\s*)(\d+)", text)
        if m:
            now = max(0, int(m.group(2)) - dealt)
            writes[rel] = text[:m.start(2)] + str(now) + text[m.end(2):]
            data.update(hp=f"{now}/{m.group(4)}", down=now == 0)
            if t is not None:
                t["hp"] = f"{now}/{m.group(4)}"
                world.touch(MAP)
    elif t is not None and _hp(t):
        cur, top = _hp(t)
        now = max(0, cur - dealt)
        t["hp"] = f"{now}/{top}"
        world.touch(MAP)
        data.update(hp=t["hp"], down=now == 0)
        if _side(world, name) == "enemy" and 0 < now * 2 <= top and cur * 2 > top:
            data["morale_check"] = f"{name} is at half HP or less: roll its morale (tracker.py enemy morale), score {rec.get('morale', 'default')}"
    else:
        data["error"] = f"no HP on record for {name}: nothing was taken off"
    if rec.get("concentrating") and dealt > 0:
        data["concentration_save"] = {"spell": rec["concentrating"], "dc": max(10, dealt // 2), "con_mod": rec.get("con_mod", 0)}
    trk = world.json("tracker.json") or {}
    held = trk.get(name.lower()) if isinstance(trk, dict) else None
    if isinstance(held, dict) and held.get("concentration") and dealt > 0 and "concentration_save" not in data:
        # A player character's concentration lives in tracker.json, not on the combatant record.
        if data.get("down"):
            import tracker as tracker_mod
            data["concentration_ends"] = tracker_mod.drop_concentration(trk, held)
            world.touch("tracker.json")
        else:
            data["concentration_save"] = {"spell": held["concentration"], "dc": max(10, dealt // 2)}
    return {"status": "done", "elapsed_minutes": 0, "writes": {**world.writes(), **writes}, "refresh": "battlemap",
            "data": data, "visible_events": check_end(world)}


def _in_cone(origin: tuple, toward: tuple, cells: int, at: tuple) -> bool:
    """A 5e cone on the grid: within `cells` along its axis, and no further off the axis than half the distance
    along it (it is as wide as it is long), measured between square centres with half a square of give."""
    dx, dy = toward[0] - origin[0], toward[1] - origin[1]
    norm = (dx * dx + dy * dy) ** 0.5
    if not norm:
        return False
    vx, vy = at[0] - origin[0], at[1] - origin[1]
    along = (vx * dx + vy * dy) / norm
    off = abs(vx * dy - vy * dx) / norm
    return 0 < along <= cells + 0.5 and off <= along / 2 + 0.5


@turn.handler("area")
def _area(ctx, intent: dict) -> dict:
    """area — who is caught in an area: {"action": "area", "shape": "sphere", "at": [6, 5], "feet": 20}
    (shape: sphere | cube | line with "to": [x, y] | cone from "at" toward "to"; or "zone": "platform" in a fight
    with zones).

    A sphere, cube or cone needs an unbroken line from its point of origin: a wall shelters whoever is behind it.
    A cone is as wide as it is far at every distance; its origin's own square is not in it."""
    world = _world(ctx)
    data, hit, sheltered = _map(world), [], []
    if intent.get("zone"):
        hit = [t["name"] for t in data.get("tokens", []) if _zone_of(t) == intent["zone"] and t.get("kind") != "obj"]
        return {"status": "done", "elapsed_minutes": 0, "data": {"inside": hit, "sheltered": []}}
    cx, cy = (int(v) for v in intent.get("at", [0, 0]))
    cells = int(intent.get("feet", 5)) // 5
    line = set(cells_between((cx, cy), tuple(int(v) for v in intent["to"])) + [tuple(int(v) for v in intent["to"])]) \
        if intent.get("shape") == "line" and intent.get("to") else None
    for t in data.get("tokens", []):
        if t.get("kind") == "obj" or t.get("x") is None:
            continue
        if line is not None:
            inside = (t["x"], t["y"]) in line
        elif intent.get("shape") == "cone" and intent.get("to"):
            inside = _in_cone((cx, cy), tuple(int(v) for v in intent["to"]), cells, (t["x"], t["y"]))
        else:
            inside = max(abs(t["x"] - cx), abs(t["y"] - cy)) <= cells
        if not inside:
            continue
        clear = sees(world, {"x": cx, "y": cy}, {**t, "hidden": False})
        (hit if clear or line is not None else sheltered).append(t["name"])
    return {"status": "done", "elapsed_minutes": 0, "data": {"inside": hit, "sheltered": sheltered}}


@turn.handler("prop")
def _prop(ctx, intent: dict) -> dict:
    """prop — someone uses a piece of the scenery: {"actor": "Mira", "action": "prop", "name": "chandelier"}.

    The reply is the prop's effect for you to apply. A prop works once unless it was set up with "reusable": true."""
    world = _world(ctx)
    fight = _fight(world)
    prop = next((p for p in fight.get("props") or [] if str(p.get("name", "")).casefold() == str(intent.get("name", "")).casefold()), None)
    if not prop:
        return {"status": "done", "elapsed_minutes": 0,
                "data": {"used": False, "error": "no such prop here", "props": [p["name"] for p in fight.get("props") or []]}}
    if prop.get("used") and not prop.get("reusable"):
        return {"status": "done", "elapsed_minutes": 0, "data": {"used": False, "error": f"the {prop['name']} has already been used"}}
    prop["used"] = True
    world.put("fight", "current", fight)
    return {"status": "done", "elapsed_minutes": 0,
            "data": {"used": True, "by": intent.get("actor"), "prop": prop["name"], "effect": prop.get("effect", "")},
            "visible_events": [{"type": "prop", "recipient": "party", "text": f"{intent.get('actor', 'Someone')} uses the {prop['name']}."}]}


@turn.handler("round")
def _round(ctx, intent: dict) -> dict:
    """round — the next round begins: {"action": "round"}.

    Everyone gets their action, bonus action and reaction back, and anything the fight was set up to do on this
    round happens (`round_triggers`)."""
    world = _world(ctx)
    fight = _fight(world)
    if not fight or fight.get("status") != "running":
        return {"status": "done", "elapsed_minutes": 0, "data": {"error": "no fight is running"}}
    fight["round"] = int(fight.get("round", 1)) + 1
    world.put("fight", "current", fight)
    visible = []
    trigger = (fight.get("round_triggers") or {}).get(str(fight["round"]))
    if trigger:
        visible.append({"type": "round_trigger", "recipient": "party", "text": f"Round {fight['round']}: {trigger}"})
    unused = [p["name"] for p in fight.get("props") or [] if not p.get("used")]
    return {"status": "done", "elapsed_minutes": 0, "visible_events": visible + check_end(world),
            "data": {"round": fight["round"], "trigger": trigger, "props_unused": unused, "objective": fight.get("objective")}}
