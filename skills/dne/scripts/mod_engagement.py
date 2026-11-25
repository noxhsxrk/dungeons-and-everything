#!/usr/bin/env python3
"""mod_engagement.py — the engagement module's engine action (data/modules/engagement.json).

A job starts with one plan and its one detail, then one roll for how the opening goes: the usual Braid roll, 2d6
plus the plan's factors, with no approach (it is the crew's luck, not one person's skill). The result sets the
starting position that the position_effect module reads, and play cuts to the first obstacle."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mechanics  # noqa: E402
import modules  # noqa: E402
import mod_position_effect  # noqa: E402
import paths  # noqa: E402
import turn  # noqa: E402


@turn.handler("engagement")
def _engagement(ctx, intent: dict) -> dict:
    """engagement — the opening roll of a job (module engagement, needs position_effect).

    {"action": "engagement", "actor": "Mira", "plan": "stealth", "detail": "the laundry chute",
     "bold": true, "weakness": true, "interfere": true, "other": 0, "job": "the Gilded Vault"}
    Plans: assault, deception, stealth, uncanny, social, transport; each needs its one detail. Factors, +1 or -1 each
    (our defaults): bold (simple, daring) / complex (too many moving parts); weakness (the detail hits the target's
    weak spot) / strength (the target is strongest there); help (friends lend a hand) / interfere (enemies get in the
    way); other: -2..+2 for anything else. The roll is 2d6 + the sum; the reply's `position` is where play starts:
    critical success: controlled and past the first obstacle; success: controlled; at a cost: risky; a miss:
    desperate. It is stored as the party's position at once, so no token steps it up."""
    err = modules.need(ctx, "engagement") or modules.need(ctx, "position_effect")
    if err:
        return mechanics._err(err)
    nums = modules.load("engagement")["numbers"]
    plan, detail = str(intent.get("plan", "")).casefold(), str(intent.get("detail") or "").strip()
    if plan not in nums["plans"]:
        return mechanics._err(f"plan: one of {', '.join(nums['plans'])}")
    if not detail:
        return mechanics._err(f"a {plan} plan needs its detail: {nums['plans'][plan]}")
    other = int(intent.get("other", 0))
    if abs(other) > nums["other_max"]:
        return mechanics._err(f"other: -{nums['other_max']}..+{nums['other_max']}")
    used = [f for f in nums["factors"] if intent.get(f)]
    mod = sum(nums["factors"][f] for f in used) + other
    job = str(intent.get("job") or "the job")
    check = {"actor": str(intent.get("actor") or "Party"), "spec": f"2d6{mod:+d}", "label": f"engagement: {job}",
             "likelihood": "likely" if mod > 0 else "unlikely" if mod < 0 else "50/50"}
    out = turn._check(ctx, check, paths.campaign_system(ctx.campaign))
    data = out.get("data") or {}
    if out.get("status") != "done" or "degree" not in data:
        return out
    data.pop("spec", None)
    position = nums["position"][data["degree"]]
    mod_position_effect.store(ctx, position, f"engagement: {job}")
    data.update(plan=plan, detail=detail, factors=used, other=other, position=position,
                past_first_obstacle=data["degree"] == "critical success")
    out["visible_events"] = (out.get("visible_events") or []) + [
        {"type": "position", "recipient": "party",
         "text": f"{job}: the crew starts {position}" + (", already past the first obstacle" if data["past_first_obstacle"] else "")}]
    return out
