#!/usr/bin/env python3
"""mod_gm_budget.py — the gm_budget module's engine action, `complicate` (data/modules/gm_budget.json).

The GM's unprompted complications come out of a party pool that refills each session; every spend is written down
with its turn, so the table can check it."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mechanics  # noqa: E402
import modules  # noqa: E402
import turn  # noqa: E402
import world_db as wdb  # noqa: E402


@turn.handler("complicate")
def _complicate(ctx, intent: dict) -> dict:
    """complicate — the GM spends from the session's budget of complications (module gm_budget).

    {"action": "complicate", "what": "the guard's relief comes early", "cost": 1}   1 small, 2 big, 3 scene-changing
    {"action": "complicate"}   what is left, and every spend so far (with its turn)
    Refused if the budget is short. A new session refills it: {"action": "pool", "refill": "session"}."""
    err = modules.need(ctx, "gm_budget")
    if err:
        return mechanics._err(err)
    modules.ensure(ctx, "gm_budget", [])
    spent = sorted(wdb.all_of(ctx.db, "complication").values(), key=lambda r: r["seq"])
    if "what" not in intent:
        pool = wdb.get(ctx.db, "pool", "party/complications")
        return mechanics._done({"left": pool["value"], "max": pool["max"], "spent": spent})
    cost, what = int(intent.get("cost", 1)), str(intent["what"]).strip()
    if not what or not 1 <= cost <= int(modules.load("gm_budget")["numbers"]["max_cost"]):
        return mechanics._err("complicate needs what happens and a cost of 1 to 3")
    pool = mechanics._pool(ctx, {"action": "pool", "owner": "party", "id": "complications", "spend": cost, "why": what})["data"]
    if pool.get("error"):
        return mechanics._err(f"the budget is short: {pool['error']}. It does not happen; find another way")
    rec = {"seq": len(spent) + 1, "what": what, "cost": cost, "left": pool["value"], "turn": ctx.turn_id}
    wdb.put(ctx.db, "complication", ctx.action_id, rec)
    return mechanics._done({**rec, "max": pool["max"]}, refresh="clocks",
                           visible_events=[{"type": "complication", "recipient": "party",
                                            "text": f"GM budget: {pool['value']}/{pool['max']} left"}])
