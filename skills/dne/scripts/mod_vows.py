#!/usr/bin/env python3
"""mod_vows.py — the vows module's engine action, `vow` (data/modules/vows.json).

A vow is a progress track (mechanics `progress`) with a way to end it: a fulfilment roll that is the usual progress
roll, read here: kept (XP by rank), kept at a cost, or not yet (boxes lost). Forsaking one marks stress."""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mechanics  # noqa: E402
import modules  # noqa: E402
import turn  # noqa: E402
import world_db as wdb  # noqa: E402


@turn.handler("vow")
def _vow(ctx, intent: dict) -> dict:
    """vow — a long promise kept on a 10-box progress track (module vows).

    {"action": "vow", "owner": "Mira", "name": "Get my brother out", "rank": "hard", "why": "at the gate"}   swear
    {"action": "vow", "owner": "Mira", "name": "Get my brother out", "mark": 1, "why": "the warden's ledger"}
    {"action": "vow", "owner": "Mira", "name": "Get my brother out", "fulfil": true, "actor": "Mira"}
        the usual progress roll. Success or better: kept, XP by rank (easy 1 … epic 5) as an `xp_command`;
        at a cost: kept, one XP less; a miss: two boxes lost, the vow stands. Lands at once (no token after).
    {"action": "vow", "owner": "Mira", "name": "…", "forsake": true}   stress by rank (1 / 1 / 2 / 2 / 3)
    {"action": "vow", "owner": "Mira", "name": "…"}                    read it"""
    err = modules.need(ctx, "vows")
    if err:
        return mechanics._err(err)
    nums = modules.load("vows")["numbers"]
    owner, name = str(intent.get("owner") or "party").strip(), str(intent.get("name") or "").strip()
    if not name:
        return mechanics._err("vow needs a name: what was sworn")
    key = mechanics._key(owner, name)
    rec = wdb.get(ctx.db, "progress", key)
    base = {"action": "progress", "owner": owner, "name": name}
    if not rec and "rank" not in intent:
        return mechanics._err(f"no vow {name!r} for {owner}: swear it with a rank first")
    if intent.get("forsake"):
        wdb.delete(ctx.db, "progress", key)
        stress = int(nums["forsake_stress"][rec["rank"]])
        who = str(intent.get("actor") or owner)
        st = mechanics.change_track(ctx, who, "stress", mark=stress, why=f"forsook a vow: {name}")
        return mechanics._done({"owner": owner, "name": name, "forsaken": True, "stress": stress, "crossed": st["crossed"]},
                               refresh="clocks", visible_events=[{"type": "vow", "recipient": "party",
                                                                  "text": f"{owner} forsakes the vow: {name}"}])
    if not intent.get("fulfil"):
        return mechanics._progress(ctx, {**base, **{k: intent[k] for k in ("rank", "mark", "why") if k in intent}})
    out = mechanics._progress(ctx, {**base, "roll": True, "actor": intent.get("actor") or owner})
    data = out.get("data") or {}
    if out.get("status") != "done" or "degree" not in data:
        return out
    data.pop("spec", None)
    degree = data["degree"]
    if degree in ("success", "critical success", "success at a cost"):
        wdb.delete(ctx.db, "progress", key)
        xp = max(1, int(nums["xp"][rec["rank"]]) - (int(nums["cost_xp_less"]) if degree == "success at a cost" else 0))
        event = re.sub(r"[^a-z0-9]+", "-", f"vow {owner} {name}".casefold()).strip("-")
        who = owner if owner != "party" else "<each character>"
        data.update(kept=True, xp=xp, xp_command=f'sheet.py -c {ctx.campaign} xp "{who}" --mark {xp} '
                                                 f'--why "kept a vow: {name}" --event {event}')
        text = f"{owner} keeps the vow: {name}" + (" (at a cost)" if degree == "success at a cost" else "")
    else:
        rec["ticks"] = max(0, rec["ticks"] - int(nums["miss_ticks_lost"]))
        mechanics._log(rec, {"to": rec["ticks"], "why": "a fulfilment roll missed", "turn": ctx.turn_id})
        wdb.put(ctx.db, "progress", key, rec)
        data.update(kept=False, boxes_now=rec["ticks"] // 4)
        text = f"{name}: not yet ({rec['ticks'] // 4}/10)"
    out["visible_events"] = (out.get("visible_events") or []) + [{"type": "vow", "recipient": "party", "text": text}]
    out["refresh"] = "clocks"
    return out
