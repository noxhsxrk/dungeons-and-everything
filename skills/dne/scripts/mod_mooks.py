#!/usr/bin/env python3
"""mod_mooks.py — the mooks module's engine action, `foe` (data/modules/mooks.json).

A group of nameless foes is one harm track, a box per mook: any hit drops one, and each point of harm past the
first drops another (a single nameless foe of any threat falls to one hit). A named
foe takes the harm boxes of its threat, at least two. The harm a group deals rises with its size, as in the core
rules, and falls as they drop."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mechanics  # noqa: E402
import modules  # noqa: E402
import turn  # noqa: E402
import world_db as wdb  # noqa: E402


def _deals(foe: dict, left: int) -> int:
    threat = foe["threat"]
    if foe["kind"] == "mooks":
        threat += next((b for lo, hi, b in modules.load("mooks")["numbers"]["pack"] if lo <= left <= hi), 0)
    return int(mechanics.BRAID["threats"][str(min(5, threat))]["deals"]) if left else 0


def _view(foe: dict, rec: dict) -> dict:
    left = rec["max"] - rec["value"]
    return {"name": foe["name"], "kind": foe["kind"], "threat": foe["threat"], "boxes": rec["max"], "harm": rec["value"],
            "left": left, "down": left == 0, "deals": _deals(foe, left if foe["kind"] == "mooks" else int(left > 0))}


@turn.handler("foe")
@modules.requires("mooks")
def _foe(ctx, intent: dict) -> dict:
    """foe — an enemy or a group of nameless ones (module mooks).

    {"action": "foe", "name": "Dock thugs", "threat": 1, "count": 5}   mooks: one box each, a hit drops one
    {"action": "foe", "name": "Captain Hale", "threat": 3}             named: harm boxes of the threat, at least 2
    {"action": "foe", "name": "Dock thugs", "hit": 2}                  mooks: one down per point of harm dealt
    {"action": "foe", "name": "Captain Hale", "hit": 2}                named: the harm dealt marks its boxes
    {"action": "foe", "name": "Dock thugs"}                            read: left, down, deals (harm per hit)"""
    name = str(intent.get("name") or "").strip()
    if not name:
        return mechanics.error("foe needs a name")
    foe = wdb.get(ctx.db, "foe", name.casefold())
    if "threat" in intent:
        threat = int(intent["threat"])
        if str(threat) not in mechanics.BRAID["threats"]:
            return mechanics.error("threat: 1 to 5")
        count = int(intent.get("count", 1))
        if count < 1 or count > 10:
            return mechanics.error("count: 1 to 10 mooks in a group (split a bigger crowd)")
        kind = "mooks" if count > 1 or intent.get("mook") else "named"
        boxes = count if kind == "mooks" else max(int(modules.load("mooks")["numbers"]["named_min_boxes"]),
                                                  int(mechanics.BRAID["threats"][str(threat)]["harm"]))
        foe = {"name": name, "threat": threat, "kind": kind}
        wdb.put(ctx.db, "foe", name.casefold(), foe)
        rec = mechanics.change_track(ctx, name, "harm", set_to=0, why="enters",
                                     define={"min": 0, "max": boxes, "thresholds": []})
        return mechanics.done(_view(foe, rec), refresh="clocks")
    if not foe:
        return mechanics.error(f"no foe {name!r}: bring it in with a threat first")
    if "hit" not in intent:
        return mechanics.done(_view(foe, wdb.get(ctx.db, "track", mechanics.key_of(name, "harm"))))
    hit = int(intent["hit"])
    rec = mechanics.change_track(ctx, name, "harm", mark=hit, why=str(intent.get("why") or "a hit"))
    view = _view(foe, rec)
    text = f"{name}: down" if view["down"] else (f"{name}: {view['left']} left" if foe["kind"] == "mooks"
                                                  else f"{name}: {view['harm']}/{view['boxes']} harm")
    return mechanics.done(view, refresh="clocks", visible_events=[{"type": "foe", "recipient": "party", "text": text}])
