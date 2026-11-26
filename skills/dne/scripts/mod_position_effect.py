#!/usr/bin/env python3
"""mod_position_effect.py — the position_effect module's engine action, `position` (data/modules/position_effect.json).

Before a risky roll the GM names the position (controlled / risky / desperate: how bad a miss gets) and the effect
(limited / standard / great: how much a hit does). The roll is the usual Braid check; this only reads its result
through the two: the consequence, the harm if the GM makes it harm, and the clock ticks it earns."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mechanics  # noqa: E402
import modules  # noqa: E402
import paths  # noqa: E402
import resolve as checks  # noqa: E402
import turn  # noqa: E402
import world_db as wdb  # noqa: E402

POSITIONS = ("controlled", "risky", "desperate")


def current(ctx) -> str:
    """The party's position now: the last one named (by the GM or an engagement roll), else the default."""
    rec = wdb.get(ctx.db, "position", "party")
    return rec["position"] if rec else modules.load("position_effect")["numbers"]["default_position"]


def store(ctx, position: str, why: str) -> None:
    wdb.put(ctx.db, "position", "party", {"position": position, "why": why, "turn": ctx.turn_id})


def reading(position: str, effect: str, degree: str, deals: int = 0) -> dict:
    """What a degree means at this position and effect: {consequence, harm_if_hurt, ticks}. Against a foe, the harm
    starts from the larger of the position's number and the foe's `deals` (one rule, not two)."""
    mod = modules.load("position_effect")
    n = mod["numbers"]
    step = checks.LADDER.index(degree)
    harm = 0
    if step <= 2:                                 # a miss or a cost: what it costs, if the GM makes it harm
        harm = max(n["harm"][position], deals) + (n["harm_on_critical_failure_more"] if step == 0 else 0) \
            - (n["harm_on_cost_less"] if step == 2 else 0)
    ticks = 0 if step <= 1 else n["ticks"][effect] + (n["critical_extra_ticks"] if step == 4 else 0)
    return {"position": position, "effect": effect, "consequence": mod["tables"][position][step],
            "harm_if_hurt": max(0, min(n["harm_max"], harm)), "ticks": ticks}


@turn.handler("position")
@modules.requires("position_effect")
def _position(ctx, intent: dict) -> dict:
    """position — a risky action read through position and effect (module position_effect).

    {"action": "position", "actor": "Mira", "approach": "finesse", "position": "risky", "effect": "standard",
     "label": "crack the strongbox", "clock": "The vault"}
    The check is the usual one (sheet approach or "spec", conditions, "push", "help"). The reply's `reading` says
    the consequence for that degree, `harm_if_hurt` (controlled 1, risky 2, desperate 3, or the foe's `deals` if
    "against": "<foe>" names a larger one; one less on a cost, one more on a critical failure, our defaults) and `ticks` (limited 1, standard 2, great 3; +1 on a critical; none on
    a miss), and ticks `clock` by them at once. A critical success suggests the easier position in `eases_to`
    (the stored one changes only when the GM sends `set`). "use_label" and "against" work as on `roll`. Position left out = the party's current one (an engagement roll or
    the last one named); effect left out = standard.
    {"action": "position", "set": "desperate", "why": "the alarm"}   name the position without a roll
    {"action": "position"}                                           read it"""
    nums = modules.load("position_effect")["numbers"]
    if "set" in intent:
        if intent["set"] not in POSITIONS:
            return mechanics.error(f"position: one of {', '.join(POSITIONS)}")
        store(ctx, intent["set"], str(intent.get("why", "")))
        return mechanics.done({"position": intent["set"]})
    if not intent.get("actor"):
        return mechanics.done({"position": current(ctx)})
    position = intent.get("position") or current(ctx)
    effect = intent.get("effect") or nums["default_effect"]
    if position not in POSITIONS or effect not in nums["ticks"]:
        return mechanics.error(f"position: one of {', '.join(POSITIONS)}; effect: one of {', '.join(nums['ticks'])}")
    check = {"action": "roll", "actor": intent["actor"], "label": intent.get("label") or "a risky action",
             "likelihood": {"controlled": "likely", "risky": "50/50", "desperate": "unlikely"}[position],
             **{k: intent[k] for k in ("spec", "approach", "push", "help", "use_label", "against") if k in intent}}
    out = turn._check(ctx, check, paths.campaign_system(ctx.campaign))
    data = out.get("data") or {}
    if out.get("status") != "done" or "degree" not in data:
        return out
    data.pop("spec", None)                        # read and ticked now: a token cannot reach back past it
    if data["degree"] == checks.LADDER[-1] and position != POSITIONS[0]:     # the GM decides; the stored one stays
        data["eases_to"] = POSITIONS[POSITIONS.index(position) - 1]
    store(ctx, position, f"{intent['actor']}: {data['label']}")
    deals = 0
    if intent.get("against"):
        import mod_mooks
        foe = wdb.get(ctx.db, "foe", str(intent["against"]).strip().casefold())
        rec = foe and wdb.get(ctx.db, "track", mechanics.key_of(foe["name"], "harm"))
        deals = mod_mooks._view(foe, rec)["deals"] if rec else 0
    data["reading"] = read = reading(position, effect, data["degree"], deals)
    events = [{"type": "position", "recipient": "dm",
               "text": f"{position}/{effect}, {data['degree']}: {read['consequence']}"
                       + (f" (harm {read['harm_if_hurt']} if it is harm)" if read["harm_if_hurt"] else "")}]
    if intent.get("clock") and read["ticks"]:
        ticked = turn.HANDLERS["clock"](ctx, {"action": "clock", "name": str(intent["clock"]), "tick": read["ticks"],
                                              "why": data["label"]})
        data["clock"] = ticked["data"]
        events += ticked.get("visible_events") or []
    out["visible_events"] = (out.get("visible_events") or []) + events
    out["refresh"] = "clocks"
    return out
