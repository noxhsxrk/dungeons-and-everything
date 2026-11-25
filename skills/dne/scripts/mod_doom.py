#!/usr/bin/env python3
"""mod_doom.py — the doom module (data/modules/doom.json, rules in .md): a party track that every risk raises, and a
hidden die the script rolls against it. At or under doom, disaster: an entry from the module's table, doom back to a
floor that rises with each disaster. Nobody rolls for it but the script."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mechanics  # noqa: E402
import modules  # noqa: E402
import paths  # noqa: E402
import turn  # noqa: E402


def step(ctx, add: int, why: str) -> dict:
    """Raise doom by `add`, then roll the hidden die once for this action. Returns {doom, max, rolled, die, disaster}."""
    mod = modules.load("doom")
    nums = mod["numbers"]
    modules.ensure(ctx, "doom", [])
    rec = mechanics.change_track(ctx, "party", "doom", mark=add, why=why)
    rolled = ctx.roll("doom", int(nums["die"]))[0]
    out = {"doom": rec["value"], "max": rec["max"], "rolled": rolled, "die": f"d{nums['die']}", "disaster": None}
    if rolled <= rec["value"]:
        floor = min(rec["min"] + int(nums["floor_step"]), int(nums["floor_max"]))
        out["disaster"] = mechanics.roll_table(ctx, mod["tables"]["disasters"], "doom-disaster")["result"]
        after = mechanics.change_track(ctx, "party", "doom", set_to=floor, why=f"disaster: {out['disaster']}",
                                       define={"min": floor})
        out.update(doom=after["value"], floor=floor)
    return out


def _events(d: dict) -> list:
    ev = [{"type": "track", "recipient": "party", "text": f"Doom {d['doom']}/{d['max']}"}]
    if d["disaster"]:
        ev.append({"type": "threshold", "recipient": "dm", "text": f"DISASTER (doom die {d['rolled']}): {d['disaster']}"})
    return ev


@turn.handler("doom")
def _doom(ctx, intent: dict) -> dict:
    """doom — the party's doom track (module doom). Every Braid check already adds 1 and rolls by itself.

    {"action": "doom", "add": 1, "why": "they split up"}   a risk with no roll: add, then the script rolls the die
    {"action": "doom"}                                     read it
    The script rolls a hidden d20 (our default); at or under doom, disaster: the reply's `disaster` is the entry
    rolled from the module's table (play it at once), doom drops to its floor and the floor rises by 1 (up to 6)."""
    err = modules.need(ctx, "doom")
    if err:
        return mechanics._err(err)
    if "add" not in intent:
        modules.ensure(ctx, "doom", [])
        return mechanics._done({k: v for k, v in mechanics.change_track(ctx, "party", "doom").items() if k != "log"})
    d = step(ctx, int(intent["add"]), str(intent.get("why") or "a risk"))
    return mechanics._done(d, refresh="clocks", visible_events=_events(d))


def _after(ctx, intent: dict, out: dict) -> None:
    """Every graded Braid check adds to doom, in a campaign with the module on."""
    data = out.get("data") or {}
    if not data.get("degree") or intent.get("action") in ("doom", "pool") or data.get("error"):
        return
    if paths.campaign_system(ctx.campaign) == "d20" or "doom" not in modules.enabled(ctx.campaign):
        return
    d = step(ctx, int(modules.load("doom")["numbers"]["per_check"]), f"{intent.get('action')}: {data.get('label') or ''}".strip())
    data["doom"] = d
    out["data"] = data
    out["visible_events"] = (out.get("visible_events") or []) + _events(d)
    out.setdefault("refresh", "clocks")


turn.AFTER_ACTION.append(_after)
