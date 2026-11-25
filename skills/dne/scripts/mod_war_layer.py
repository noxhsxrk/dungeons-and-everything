#!/usr/bin/env python3
"""mod_war_layer.py — the war_layer module's engine action, `war` (data/modules/war_layer.json).

The army's four party tracks (time, pressure, morale, supply) and the steps that move them: time passing, the army
advancing (the script rolls dice equal to pressure), losses. A unit is a character with a rating and harm boxes;
its rolls are the usual Braid check."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mechanics  # noqa: E402
import modules  # noqa: E402
import paths  # noqa: E402
import turn  # noqa: E402
import world_db as wdb  # noqa: E402

TRACKS = ("war_time", "war_pressure", "morale", "supply")


def _tracks(ctx) -> dict:
    return {t: wdb.get(ctx.db, "track", mechanics._key("party", t))["value"] for t in TRACKS}


def _report(ctx, extra: dict, why: str = "") -> dict:
    now, nums = _tracks(ctx), modules.load("war_layer")["numbers"]
    actions = next(n for top, n in nums["actions_by_morale"] if now["morale"] <= top)
    events = [{"type": "track", "recipient": "party",
               "text": f"War: time {now['war_time']}/12, pressure {now['war_pressure']}, morale {now['morale']}, supply {now['supply']}"}]
    crossed = [c for c in extra.pop("crossed", [])]
    events += [{"type": "threshold", "recipient": "party", "text": c["note"]} for c in crossed]
    return mechanics._done({**now, "campaign_actions": actions, **extra, "crossed": crossed}, refresh="clocks",
                           visible_events=events if why else [])


def _unit(ctx, intent: dict) -> dict:
    nums = modules.load("war_layer")["numbers"]
    name = str(intent["unit"]).strip()
    unit = wdb.get(ctx.db, "unit", name.casefold())
    if intent.get("quality"):
        if intent["quality"] not in nums["quality"]:
            return mechanics._err(f"quality: one of {', '.join(nums['quality'])}")
        rating, boxes = nums["quality"][intent["quality"]]
        unit = {"name": name, "quality": intent["quality"], "rating": rating}
        wdb.put(ctx.db, "unit", name.casefold(), unit)
        rec = mechanics.change_track(ctx, name, "harm", set_to=0, why="mustered", define={"min": 0, "max": boxes, "thresholds": []})
        return mechanics._done({**unit, "harm": rec["value"], "boxes": rec["max"]}, refresh="clocks")
    if not unit:
        return mechanics._err(f"no unit {name!r}: muster it with a quality first")
    if intent.get("roll"):
        check = {"action": "roll", "actor": name, "spec": f"2d6{unit['rating']:+d}", "label": str(intent["roll"]),
                 **{k: intent[k] for k in ("push", "help") if k in intent}}
        return turn._check(ctx, check, paths.campaign_system(ctx.campaign))
    rec = mechanics.change_track(ctx, name, "harm", mark=int(intent.get("hit", 0)), why=str(intent.get("why") or "a hit"))
    data = {**unit, "harm": rec["value"], "boxes": rec["max"], "broken": rec["value"] >= rec["max"]}
    if data["broken"] and int(intent.get("hit", 0)) and not unit.get("broken"):
        unit["broken"] = True
        wdb.put(ctx.db, "unit", name.casefold(), unit)
        m = mechanics.change_track(ctx, "party", "morale", mark=int(nums["unit_broken_morale"]), why=f"{name} broke")
        data["crossed"] = m["crossed"]
    return mechanics._done(data, refresh="clocks", visible_events=[{"type": "unit", "recipient": "party",
                                                                    "text": f"{name}: {rec['value']}/{rec['max']} harm"
                                                                            + (" — broken" if data["broken"] else "")}])


@turn.handler("war")
def _war(ctx, intent: dict) -> dict:
    """war — the army between missions (module war_layer).

    {"action": "war", "pass": true}               time passes: time +1, pressure +1, supply -1 (none left: morale -2)
    {"action": "war", "advance": true}            the script rolls pressure d6s; time +1 (1-3), +2 (4-5), +3 (6),
                                                  +5 (two sixes); pressure back to 0
    {"action": "war", "losses": 2, "why": "…"}    morale -1 each; at 0 morale the rest are desertions
    {"action": "war", "unit": "Third Lantern", "quality": "trained"}   muster a unit (raw +0/1 box, trained +1/2,
                                                  veteran +2/3); "roll": "hold the bridge" rolls it; "hit": 1 harms it
    {"action": "war"}                             read the four tracks and how many campaign actions morale allows"""
    err = modules.need(ctx, "war_layer")
    if err:
        return mechanics._err(err)
    nums = modules.load("war_layer")["numbers"]
    modules.ensure(ctx, "war_layer", [])
    if intent.get("unit"):
        return _unit(ctx, intent)
    now, crossed, extra = _tracks(ctx), [], {}
    if intent.get("pass"):
        for t, d in nums["pass"].items():
            if t == "supply" and now["supply"] <= 0:
                crossed += mechanics.change_track(ctx, "party", "morale", mark=nums["hungry_morale"], why="no supply")["crossed"]
                extra["hungry"] = True
                continue
            crossed += mechanics.change_track(ctx, "party", t, mark=d, why="time passes")["crossed"]
        return _report(ctx, {**extra, "crossed": crossed}, "pass")
    if intent.get("advance"):
        dice = ctx.roll("advance", 6, now["war_pressure"]) if now["war_pressure"] else []
        top = max(dice) if dice else 0
        add = nums["advance_two_sixes"] if dice.count(6) >= 2 else \
            next((n for limit, n in nums["advance_time"] if top <= limit), 0) if dice else 0
        crossed += mechanics.change_track(ctx, "party", "war_time", mark=add, why="the army advances")["crossed"]
        mechanics.change_track(ctx, "party", "war_pressure", set_to=0, why="the army advances")
        return _report(ctx, {"dice": dice, "time_added": add, "crossed": crossed}, "advance")
    if intent.get("losses"):
        n = int(intent["losses"])
        lost = min(n, now["morale"])
        crossed += mechanics.change_track(ctx, "party", "morale", mark=lost * int(nums["loss_morale"]),
                                          why=str(intent.get("why") or f"{n} lost"))["crossed"]
        return _report(ctx, {"losses": n, "deserters": n - lost, "crossed": crossed}, "losses")
    return _report(ctx, {})
