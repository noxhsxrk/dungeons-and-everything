#!/usr/bin/env python3
"""mod_composure.py — the composure module's engine action, `fright` (data/modules/composure.json, rules in .md).

A frightening sight is the usual Braid check with Heart (turn._check, so conditions, push and help apply); a miss
costs composure by the horror's rating, and the track's thresholds roll the module's tables."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mechanics  # noqa: E402
import modules  # noqa: E402
import paths  # noqa: E402
import turn  # noqa: E402


@turn.handler("fright")
def _fright(ctx, intent: dict) -> dict:
    """fright — a character meets something that should not be (module composure).

    {"action": "fright", "actor": "Mira", "rating": "serious", "what": "the drowned man stands up"}
    rating: minor (lose 1 on a miss) | serious (2) | overwhelming (3); a critical failure loses 1 more. The check is
    the usual one with Heart (2d6 + Heart from the sheet, or send "spec"); "push" and "help" as on `roll`. Story mode:
    the oracle answers (minor likely, serious 50/50, overwhelming unlikely). The loss lands at once, so a token
    cannot step this check up afterwards. The reply's `crossed` carries any threshold and the table entry rolled."""
    err = modules.need(ctx, "composure")
    if err:
        return mechanics._err(err)
    nums = modules.load("composure")["numbers"]
    rating = str(intent.get("rating", "serious")).casefold()
    if rating not in nums["ratings"]:
        return mechanics._err(f"rating: one of {', '.join(nums['ratings'])}")
    actor, what = str(intent.get("actor") or "").strip(), str(intent.get("what") or "something terrible")
    if not actor:
        return mechanics._err("fright needs an actor")
    check = {"action": "roll", "actor": actor, "approach": intent.get("approach") or nums["approach"],
             "label": f"keep composure: {what}", "likelihood": nums["story_odds"][rating],
             **{k: intent[k] for k in ("spec", "push", "help") if k in intent}}
    out = turn._check(ctx, check, paths.campaign_system(ctx.campaign))
    data = out.get("data") or {}
    if out.get("status") != "done" or "degree" not in data:
        return out                                    # waiting for the player's dice, or an error
    data.pop("spec", None)                            # settled now: no token reaches back past the loss
    lost = {"failure": nums["ratings"][rating],
            "critical failure": nums["ratings"][rating] + nums["critical_failure_extra"]}.get(data["degree"], 0)
    modules.ensure(ctx, "composure", [actor])
    rec = mechanics.change_track(ctx, actor, "composure", mark=-lost, why=what) if lost else \
        mechanics.change_track(ctx, actor, "composure")
    data.update(rating=rating, lost=lost, composure=rec["value"], max=rec["max"], crossed=rec["crossed"])
    out["visible_events"] = (out.get("visible_events") or []) + (
        [{"type": "track", "recipient": "party", "text": f"{actor} loses {lost} composure ({rec['value']}/{rec['max']})"}]
        if lost else []) + [
        {"type": "threshold", "recipient": "dm",
         "text": f"{actor} composure crossed {c['at']}: " + "; ".join(x for x in (c["note"], c.get("result", "")) if x)}
        for c in rec["crossed"]]
    out["refresh"] = "clocks"
    return out
