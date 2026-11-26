#!/usr/bin/env python3
"""mod_heat.py — the heat module's engine action, `crew_heat` (data/modules/heat.json).

After each job the crew takes heat by how loud it was; at 9 the heat turns into a wanted level and starts again
from what is left over. Between jobs the script rolls the trouble that finds them: dice equal to the wanted level
(none: two dice, the lower counts), read in the column of the crew's heat. (`heat` is a different action: one
faction's attention in one area.)"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mechanics  # noqa: E402
import modules  # noqa: E402
import turn  # noqa: E402


def _state(ctx) -> dict:
    return {t: mechanics.change_track(ctx, "party", t)["value"] for t in ("crew_heat", "wanted")}


@turn.handler("crew_heat")
@modules.requires("heat")
def _crew_heat(ctx, intent: dict) -> dict:
    """crew_heat — the crew's heat and wanted level (module heat).

    {"action": "crew_heat", "job": "loud", "high_profile": true, "hostile_turf": false, "war": false, "killing": false}
        after a job: quiet 0, contained 2, loud 4, wild 6; +1 high-profile target, +1 hostile turf, +1 at war,
        +2 if someone was killed (our defaults). At 9 heat: wanted +1 (up to 4) and heat keeps the rest.
    {"action": "crew_heat", "add": -2, "why": "laid low for a week"}
    {"action": "crew_heat", "entangle": true}   between jobs: the script rolls the trouble that finds the crew
    {"action": "crew_heat"}                     read heat and wanted"""
    mod = modules.load("heat")
    nums = mod["numbers"]
    modules.ensure(ctx, "heat", [])
    now = _state(ctx)
    if intent.get("entangle"):
        n = now["wanted"]
        dice = ctx.roll("entangle", 6, n or 2)
        got = max(dice) if n else min(dice)
        column = next(name for lo, hi, name in nums["columns"] if lo <= now["crew_heat"] <= hi)
        row = next(i for i, top in enumerate(nums["rows"]) if got <= top)
        what = mod["tables"][column][row]
        return mechanics.done({**now, "dice": dice, "result": got, "column": column, "entanglement": what},
                               visible_events=[{"type": "entanglement", "recipient": "dm", "text": f"Entanglement ({got}): {what}"}])
    if "job" in intent:
        if intent["job"] not in nums["job"]:
            return mechanics.error(f"job: one of {', '.join(nums['job'])}")
        add = nums["job"][intent["job"]] + sum(v for k, v in nums["extra"].items() if intent.get(k))
        why = f"a {intent['job']} job" + "".join(f", {k.replace('_', ' ')}" for k in nums["extra"] if intent.get(k))
    elif "add" in intent:
        add, why = int(intent["add"]), str(intent.get("why") or "")
    else:
        return mechanics.done(now)
    total, wanted = max(0, now["crew_heat"] + add), now["wanted"]
    while total >= nums["overflow"] and wanted < 4:
        total, wanted = total - nums["overflow"], wanted + 1
    heat = mechanics.change_track(ctx, "party", "crew_heat", set_to=total, why=why)
    if wanted != now["wanted"]:
        mechanics.change_track(ctx, "party", "wanted", set_to=wanted, why=why)
    data = {"crew_heat": heat["value"], "wanted": wanted, "added": add, "wanted_up": wanted - now["wanted"]}
    text = f"Heat {heat['value']}/{nums['overflow'] - 1}, wanted {wanted}" + (" (wanted level up!)" if data["wanted_up"] else "")
    return mechanics.done(data, refresh="clocks", visible_events=[{"type": "track", "recipient": "party", "text": text}])
