#!/usr/bin/env python3
"""
upkeep.py — what a party uses up as time passes, and the season and weather it travels in.

Off unless the table turns it on: `survival: on` in Session Flags. A campaign that never did keeps
playing by the rules it knows; nothing here runs.

  upkeep  "party" → {stores: {food: 12, water: 12, coin: 500}, per_day: {food: 2, water: 2, coin: 20},
                     warn_days: 2, carry: {limit: 300, load: 240}, minutes: <in-world minutes counted>,
                     used: {…}, warned: {…}}

Engine actions (turn.py help <name>):
  upkeep      choose what this campaign tracks, how much there is and how fast it goes
  supply      add to a store (bought, found, foraged)
  use         spend from a store by hand (ammunition, a repair kit)
  conditions  the season, the light and today's weather, and what they change

WHAT TO TRACK is the table's choice and should fit the genre: water in a desert, fuel and ammunition on a
ruined highway, wages for a hired crew, nothing at all in a city intrigue. Anything with a daily rate works
(`coin` at 20 a day is a payroll). Things spent by the piece (`ammo`) have no rate: spend them with `use`.

THE MATHS is exact however time is crossed: it is done in whole numbers, a day at a time. The moment a
store will fall to `warn_days` of supply, and the moment it will run out, are queued as events that stop a
journey or a rest, so the players choose what to do while there is still something to choose.
A plain conversation takes no time and produces no upkeep at all.

CLIMATE comes from worldkit.json:
  "climate": {"seasons": [{"name": "winter", "months": [12, 1, 2], "travel": 1.5, "light_hours": 8,
                           "supplies": {"fuel": 2}, "weather": [["clear", 3], ["snow", 2]]}],
              "weather": {"snow": {"travel": 1.5, "sight_feet": 60}, "fog": {"sight_feet": 30}}}
A season's `travel` and the day's weather lengthen journeys, `sight_feet` limits how far anyone sees in a
fight, and `supplies` multiplies what is used. The day's weather is rolled once per in-world day.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import journey  # noqa: E402
import paths  # noqa: E402
import scheduler  # noqa: E402
import skirmish  # noqa: E402
import turn  # noqa: E402
import world_db as wdb  # noqa: E402


def on(campaign: str) -> bool:
    return paths.session_flag(campaign, "survival", "off") == "on"


def _world(ctx):
    return scheduler.World(ctx.campaign, ctx.db)


# ── climate ───────────────────────────────────────────────────────────────────

def conditions(world) -> dict:
    """{season, light, weather, travel, sight_feet, supplies}: what the calendar and the world kit say about now."""
    climate = (world.json("worldkit.json") or {}).get("climate") or {}
    cal = world.json("calendar.json") or {}
    out = {"season": None, "light": None, "weather": None, "travel": 1.0, "sight_feet": None, "supplies": {}, "why": []}
    month, hour = int(cal.get("month", 0) or 0), int(cal.get("hour", 12) or 12)
    season = next((s for s in climate.get("seasons") or [] if month in (s.get("months") or [])), None)
    if not season:
        return out
    out["season"] = season.get("name")
    if season.get("travel", 1.0) != 1.0:
        out["travel"] *= float(season["travel"])
        out["why"].append(f"{season.get('name')} roads ×{season['travel']}")
    out["supplies"] = dict(season.get("supplies") or {})
    hours = float(season.get("light_hours", 12))
    out["light"] = "day" if 12 - hours / 2 <= hour < 12 + hours / 2 else "night"
    table = season.get("weather") or []
    if table and world.minute is not None:
        r = wdb.rng(world.db, f"weather-{world.minute // 1440}")       # one roll per in-world day, the same on every read
        pick = r.uniform(0, sum(w for _n, w in table))
        for name, weight in table:
            pick -= weight
            if pick <= 0:
                out["weather"] = name
                break
        effect = (climate.get("weather") or {}).get(out["weather"]) or {}
        if effect.get("travel", 1.0) != 1.0:
            out["travel"] *= float(effect["travel"])
            out["why"].append(f"{out['weather']} ×{effect['travel']}")
        if effect.get("sight_feet"):
            out["sight_feet"] = int(effect["sight_feet"])
    if out["light"] == "night" and climate.get("night_sight_feet"):
        out["sight_feet"] = min(out["sight_feet"] or 10 ** 6, int(climate["night_sight_feet"]))
    return out


def _travel_factor(world) -> tuple:
    c = conditions(world)
    factor, why = c["travel"], list(c["why"])
    if on(world.campaign):
        carry = (world.get("upkeep", "party") or {}).get("carry") or {}
        if carry.get("limit") and carry.get("load", 0) > carry["limit"]:
            factor *= 1.5
            why.append("overloaded ×1.5")
    return factor, ", ".join(why)


journey.TIME_FACTORS.append(_travel_factor)
skirmish.SIGHT_LIMITS.append(lambda world: conditions(world)["sight_feet"])


# ── stores ────────────────────────────────────────────────────────────────────

def _rate(world, record: dict, item: str) -> float:
    """Units of `item` used per day now, the season's multiplier included."""
    return float((record.get("per_day") or {}).get(item, 0)) * float(conditions(world)["supplies"].get(item, 1))


def _consume(world, minutes: int) -> None:
    """The clock moved: take what that time used. Exact for any slicing: used = floor(day-units accumulated)."""
    if not on(world.campaign):
        return
    record = world.get("upkeep", "party")
    if not record:
        return
    owed, used = record.setdefault("owed", {}), record.setdefault("used", {})
    for item in sorted(record.get("per_day") or {}):
        # whole numbers only: thousandths of a unit per day × minutes. 1 unit = 1440 × 1000.
        owed[item] = int(owed.get(item, 0)) + minutes * int(round(_rate(world, record, item) * 1000))
        due = owed[item] // 1_440_000 - int(used.get(item, 0))
        if due > 0:
            have = float(record["stores"].get(item, 0))
            record["stores"][item] = max(0, have - due)
            used[item] = int(used.get(item, 0)) + due
    record["minutes"] = int(record.get("minutes", 0)) + minutes
    world.put("upkeep", "party", record)


scheduler.CLOCK_HOOKS.append(_consume)


def _schedule_warnings(world, record: dict) -> None:
    """Queue the moments each store hits `warn_days` of supply and runs out. Re-queued whenever stores change."""
    version = record["version"] = int(record.get("version", 0)) + 1
    world.db.execute("UPDATE events SET status='cancelled', note='stores changed' WHERE status='pending' AND event_id LIKE 'upkeep-%'")
    now = world.minute
    if now is None:
        return
    for item in sorted(record.get("per_day") or {}):
        rate = _rate(world, record, item)
        have = float(record["stores"].get(item, 0))
        if rate <= 0:
            continue
        frac = (int(record.get("owed", {}).get(item, 0)) % 1_440_000) / 1_440_000   # part of the next unit already used up
        for level, days in (("low", float(record.get("warn_days", 2))), ("out", 0.0)):
            units_until = have - days * rate                                   # units that may still be used before then
            if units_until <= 0 and level == "low":
                continue
            minutes = max(1, int((units_until - frac) / rate * 1440)) if units_until > 0 else 1
            scheduler.schedule(world.db, f"upkeep-{item}-{level}-{version}", now + minutes,
                               {"type": "upkeep_signal", "item": item, "level": level}, priority=3, audience="party")


@scheduler.effect("upkeep_signal")
def _signal(world, row, eff):
    """A store is nearly gone, or gone. The journey or rest in progress stops so the players can decide."""
    record = world.get("upkeep", "party")
    if not record:
        return None
    item, have = eff["item"], float(record["stores"].get(eff["item"], 0))
    rate = _rate(world, record, item)
    days = have / rate if rate else 0
    if eff["level"] == "low":
        text = f"Supplies: {item} for about {days:.1f} more days ({have:g} left, {rate:g} a day)."
    else:
        text = f"The {item} has run out."
        record.setdefault("out_since", {})[item] = world.minute
        world.put("upkeep", "party", record)
    return [{"type": f"upkeep_{eff['level']}", "recipient": "party", "interrupt": True, "item": item, "text": text}]


@turn.handler("upkeep")
def _upkeep(ctx, intent: dict) -> dict:
    """upkeep — what this campaign tracks as time passes (needs `survival: on` in Session Flags).

    {"action": "upkeep", "stores": {"food": 12, "water": 12, "coin": 500, "ammo": 40},
     "per_day": {"food": 2, "water": 2, "coin": 20}, "warn_days": 2, "carry": {"limit": 300, "load": 240}}
    Track only what makes for decisions in this world. A store with a daily rate goes down as in-world time passes
    (rest, travel, wait); the players are stopped and told when it reaches `warn_days` of supply and again when it
    is gone. A store with no rate (ammo) is spent with `use`. A load over `carry.limit` slows every journey by half.
    Braid with the usage_die module: {"action": "upkeep", "dice": {"torches": "d8", "fuel": "d10"}} stocks usage
    dice (party pools), with or without `survival`; `use` on one of them rolls it (1-2: a size down, then gone)."""
    if "dice" in intent and paths.campaign_system(ctx.campaign) != "d20":
        return _usage_dice(ctx, intent["dice"])
    if not on(ctx.campaign):
        return {"status": "done", "elapsed_minutes": 0,
                "data": {"error": "survival is off for this campaign: add `- survival: on` to Session Flags to track supplies"}}
    world = _world(ctx)
    record = world.get("upkeep", "party") or {"stores": {}, "per_day": {}, "warn_days": 2, "carry": {}, "owed": {}, "used": {}, "minutes": 0}
    for field in ("stores", "per_day", "carry"):
        record[field].update(intent.get(field) or {})
    if "warn_days" in intent:
        record["warn_days"] = float(intent["warn_days"])
    _schedule_warnings(world, record)
    world.put("upkeep", "party", record)
    return {"status": "done", "elapsed_minutes": 0, "data": _report(world, record)}


def _report(world, record: dict) -> dict:
    days = {}
    for item in sorted(record.get("stores") or {}):
        rate = _rate(world, record, item)
        days[item] = round(float(record["stores"][item]) / rate, 1) if rate else None
    carry = record.get("carry") or {}
    return {"stores": record["stores"], "per_day": record["per_day"], "days_left": days,
            "overloaded": bool(carry.get("limit") and carry.get("load", 0) > carry["limit"]), "conditions": conditions(world)}


def _change(ctx, intent: dict, sign: int) -> dict:
    if not on(ctx.campaign):
        return {"status": "done", "elapsed_minutes": 0, "data": {"error": "survival is off for this campaign"}}
    world = _world(ctx)
    record = world.get("upkeep", "party")
    item, qty = str(intent.get("item", "")), float(intent.get("qty", 1))
    if not record or item not in record["stores"]:
        return {"status": "done", "elapsed_minutes": 0, "data": {"error": f"{item or 'that'} is not tracked: set it with `upkeep`"}}
    have = float(record["stores"][item])
    if sign < 0 and have < qty:
        return {"status": "done", "elapsed_minutes": 0, "data": {"used": 0, "left": have, "error": f"only {have:g} {item} left"}}
    record["stores"][item] = have + sign * qty
    if "weight" in intent and record.get("carry"):
        record["carry"]["load"] = max(0, float(record["carry"].get("load", 0)) + sign * float(intent["weight"]))
    _schedule_warnings(world, record)
    world.put("upkeep", "party", record)
    return {"status": "done", "elapsed_minutes": 0,
            "data": {("added" if sign > 0 else "used"): qty, "item": item, "left": record["stores"][item], **_report(world, record)}}


@turn.handler("supply")
def _supply(ctx, intent: dict) -> dict:
    """supply — the party gains supplies: {"action": "supply", "item": "food", "qty": 6, "weight": 12}."""
    return _change(ctx, intent, +1)


@turn.handler("use")
def _use(ctx, intent: dict) -> dict:
    """use — spend supplies by hand: {"action": "use", "item": "ammo", "qty": 3}. Refused if there is not enough.
    A usage die (usage_die module, stocked with `upkeep` "dice") is rolled instead: {"action": "use", "item": "torches"}."""
    die = _usage_die(ctx, str(intent.get("item", "")))
    if die:
        import mechanics
        out = mechanics._pool(ctx, {"action": "pool", "owner": "party", "id": die["id"], "use": True})
        d = out["data"]
        if not d.get("error"):
            out["data"] = {"item": die["id"], "was": d["was"], "rolled": d["rolled"], "die": d["die"], "gone": d["gone"]}
            if d["gone"]:
                out["visible_events"] = [{"type": "upkeep_out", "recipient": "party", "item": die["id"],
                                          "text": f"The {die['id']} {'are' if die['id'].endswith('s') else 'is'} gone."}]
        return out
    return _change(ctx, intent, -1)


# ── usage dice (Braid, usage_die module) ──────────────────────────────────────

def _usage_die(ctx, item: str) -> "dict | None":
    """The party usage-die pool named `item`, in a Braid campaign with usage_die on; None otherwise (5e never)."""
    if not item or paths.campaign_system(ctx.campaign) == "d20":
        return None
    rec = wdb.get(ctx.db, "pool", f"party/{item.strip().casefold()}")
    if not rec or not (rec.get("die") or rec.get("gone")):
        return None
    import modules
    return rec if "usage_die" in modules.enabled(ctx.campaign) else None


def _usage_dice(ctx, dice: dict) -> dict:
    import mechanics
    import modules
    err = modules.need(ctx, "usage_die")
    if err:
        return {"status": "done", "elapsed_minutes": 0, "data": {"error": err}}
    if not isinstance(dice, dict) or not dice or any(d not in mechanics.DIE_STEPS for d in dice.values()):
        return {"status": "done", "elapsed_minutes": 0,
                "data": {"error": f"dice: {{item: size}}, sizes {', '.join(mechanics.DIE_STEPS)}"}}
    for item, size in dice.items():
        mechanics._pool(ctx, {"action": "pool", "owner": "party", "id": str(item).strip(), "die": size})
    return {"status": "done", "elapsed_minutes": 0, "refresh": "clocks", "data": {"dice": dict(dice)},
            "visible_events": [{"type": "upkeep", "recipient": "party",
                                "text": "Stocked: " + ", ".join(f"{k} {v}" for k, v in dice.items())}]}


@turn.handler("conditions")
def _conditions(ctx, intent: dict) -> dict:
    """conditions — the season, day or night, today's weather, and what they do: {"action": "conditions"}.

    Travel times, sight in a fight and the rate supplies go at already take them into account."""
    world = _world(ctx)
    data = conditions(world)
    if on(ctx.campaign) and world.get("upkeep", "party"):
        data["upkeep"] = _report(world, world.get("upkeep", "party"))
    return {"status": "done", "elapsed_minutes": 0, "data": data}
