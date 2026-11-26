#!/usr/bin/env python3
"""mod_seasons.py — the seasons module (data/modules/seasons.json): the season the campaign calendar is in, and what
happens when it turns.

The season comes from calendar.json's month: a World Kit's `climate.seasons` (name + months) when it has one, else
the module's four spread evenly over the calendar's months. Any action that moves the calendar is checked after it
runs; when the season differs from the one on record it turns: the script rolls a happening from that season's
table and every character gains tokens."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mechanics  # noqa: E402
import modules  # noqa: E402
import paths  # noqa: E402
import turn  # noqa: E402
import world_db as wdb  # noqa: E402


def season_of(cal: dict, climate: dict) -> "str | None":
    """The season name for a calendar dict (None without a calendar)."""
    if not cal:
        return None
    month = int(cal.get("month", 1) or 1)
    for s in (climate or {}).get("seasons") or []:
        if month in (s.get("months") or []):
            return str(s.get("name"))
    names = modules.load("seasons")["numbers"]["names"]
    months = len(cal.get("months") or []) or 12
    return names[min(len(names) - 1, (month % months) * len(names) // months)]   # the last month and the first two: winter


def _turn(ctx, cal: dict) -> "dict | None":
    """Compare the calendar's season with the one on record; turn it if they differ. Returns what happened."""
    import scheduler
    world = scheduler.World(ctx.campaign, ctx.db)
    name = season_of(cal, (world.json("worldkit.json") or {}).get("climate") or {})
    rec = wdb.get(ctx.db, "season", "party")
    if not name or (rec and rec["name"] == name):
        return None
    mod = modules.load("seasons")
    table = mod["tables"].get(name.casefold())
    if table is None:                             # a kit's own season name: the default season in the same place
        table = mod["tables"][season_of({k: v for k, v in cal.items()}, {})]
    happening = mechanics.roll_table(ctx, table, f"season-{name}")["result"]
    import table as tbl
    pcs = list(tbl.pcs(ctx.campaign))
    modules.ensure(ctx, "seasons", pcs)
    gained = []
    if rec:                                       # the first season on record is where play starts: no tokens yet
        for pc in pcs:
            mechanics._pool(ctx, {"action": "pool", "owner": pc, "id": "tokens",
                                  "gain": int(mod["numbers"]["tokens_per_season"]), "why": f"{name} begins"})
            gained.append(pc)
    log = ((rec or {}).get("log") or [])[-11:] + [{"name": name, "happening": happening, "turn": ctx.turn_id}]
    new = {"name": name, "happening": happening, "since": cal.get("day"), "log": log}
    wdb.put(ctx.db, "season", "party", new)
    return {"season": name, "happening": happening, "tokens_to": gained, "was": (rec or {}).get("name")}


def _events(turned: dict) -> list:
    if not turned.get("was"):                     # the first season on record is where play starts: nothing turned
        return [{"type": "season", "recipient": "dm", "text": f"Play starts in {turned['season']}: {turned['happening']}"}]
    return [{"type": "season", "recipient": "party", "text": f"The season turns: {turned['season']}."},
            {"type": "season", "recipient": "dm", "text": f"This season: {turned['happening']}"}]


@turn.handler("season")
@modules.requires("seasons")
def _season(ctx, intent: dict) -> dict:
    """season — the campaign's season and its happening (module seasons).

    {"action": "season"}   the season the calendar is in now; if it differs from the one on record it turns here
    It also turns by itself after any action that moves the calendar (wait, travel). A turn rolls a happening from
    that season's table and gives every character 1 token (pool `tokens`, our default)."""
    import scheduler
    turned = _turn(ctx, scheduler.World(ctx.campaign, ctx.db).json("calendar.json") or {})
    rec = wdb.get(ctx.db, "season", "party")
    if not rec:
        return mechanics.error("no calendar: the season comes from calendar.json (calendar.py init)")
    data = {"season": rec["name"], "happening": rec["happening"], "turned": bool(turned)}
    return mechanics.done(data, refresh="clocks", visible_events=_events(turned) if turned else [])


def _after(ctx, intent: dict, out: dict) -> None:
    """After an action that moved the calendar: turn the season if it changed."""
    writes = out.get("writes") or {}
    if "calendar.json" not in writes or intent.get("action") == "season":
        return
    if paths.campaign_system(ctx.campaign) == "d20" or "seasons" not in modules.enabled(ctx.campaign):
        return
    try:
        cal = json.loads(writes["calendar.json"])
    except (TypeError, ValueError):
        return
    turned = _turn(ctx, cal)
    if turned:
        out.setdefault("data", {})["season"] = turned
        out["visible_events"] = (out.get("visible_events") or []) + _events(turned)
        out["refresh"] = out.get("refresh") or "clocks"


turn.AFTER_ACTION.append(_after)
