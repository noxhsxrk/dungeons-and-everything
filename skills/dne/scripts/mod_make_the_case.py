#!/usr/bin/env python3
"""mod_make_the_case.py — the make_the_case module's engine action (data/modules/make_the_case.json, rules in .md).

An open case (`{"action": "case", "open": true}`) has no hidden answer. The players argue a theory; the usual Braid
check with Wits, plus the found clues it explains, minus the case's complexity, decides whether it becomes the truth.
No new way to roll: the modifier is all that changes."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mechanics  # noqa: E402
import modules  # noqa: E402
import paths  # noqa: E402
import resolve as checks  # noqa: E402
import turn  # noqa: E402


def _odds(diff: int) -> str:
    """Story mode: explained clues minus complexity as the oracle's likelihood."""
    return "no-way" if diff <= -4 else "unlikely" if diff <= -2 else "50/50" if diff <= 0 else "likely" if diff <= 2 else "sure-thing"


@turn.handler("make_the_case")
@modules.requires("make_the_case")
def _make_the_case(ctx, intent: dict) -> dict:
    """make_the_case — the players put forward their theory of an open case (module make_the_case).

    {"action": "make_the_case", "actor": "Mira", "case": "the-lighthouse", "theory": "The keeper faked his own
     drowning to escape his debts.", "explains": ["c2", "c5", "c9"]}
    Only clues someone has found count (the reply lists the rest under `not_counted`). The check is the usual one
    with Wits (2d6 + Wits from the sheet, or send "spec" for the base) + clues explained − the case's complexity;
    "push" and "help" as on `roll`. 7 or more: the theory is now the case's truth (7-9 with a complication); the
    GM must play it as true. 6 or less: it is wrong, and the GM makes a move. Story mode: the oracle answers, with
    odds from explained − complexity. Settled at once: no token steps it up afterwards."""
    import scheduler
    world = scheduler.World(ctx.campaign, ctx.db)
    cid = str(intent.get("case", ""))
    case = world.get("case", cid)
    if not case:
        return mechanics.error(f"no case {cid!r}")
    if not case.get("open"):
        return mechanics.error(f"case {cid} has a fixed answer: make_the_case is for open cases (`case` with open: true)")
    if case.get("truth"):
        return mechanics.error(f"case {cid} is already settled: {case['truth']}")
    actor, theory = str(intent.get("actor") or "").strip(), str(intent.get("theory") or "").strip()
    if not actor or not theory:
        return mechanics.error("make_the_case needs an actor and the theory, in the players' words")
    nums = modules.load("make_the_case")["numbers"]
    found = {c["id"] for c in case["clues"] if c.get("found_by")}
    cited = list(dict.fromkeys(str(c) for c in intent.get("explains") or []))
    counted = [c for c in cited if c in found]
    if len(counted) < int(nums["min_explained"]):
        return mechanics.error("the theory must explain at least one clue the party has found (`explains`)")
    system = paths.campaign_system(ctx.campaign)
    complexity = int(case.get("complexity") or nums["complexity"])
    diff = len(counted) - complexity
    if system == "core":
        if intent.get("spec"):
            base = checks.dice_for(system, intent["spec"])[2]
        else:
            import sheet
            base = sheet.approach(ctx.campaign, actor, nums["approach"])
            if base is None:
                return mechanics.error(f"no {nums['approach']} on {actor}'s sheet: send a spec (\"2d6+1\")")
        spec = f"{checks.CORE_DICE}{base + diff:+d}"
    else:
        spec = None
    check = {"action": "roll", "actor": actor, "spec": spec, "approach": nums["approach"], "label": "make the case",
             "likelihood": _odds(diff), **{k: intent[k] for k in ("push", "help") if k in intent}}
    out = turn._check(ctx, check, system)
    data = out.get("data") or {}
    if out.get("status") != "done" or "degree" not in data:
        return out
    data.pop("spec", None)                            # settled now: no token reaches back past the verdict
    entry = {"by": actor, "theory": theory, "explains": counted, "degree": data["degree"], "minute": world.minute}
    case.setdefault("theories", []).append(entry)
    if data["passed"]:
        case["truth"] = theory
        case["settled_by"] = entry
    world.put("case", cid, case)
    data.update(case=cid, theory=theory, explains=counted, not_counted=[c for c in cited if c not in found],
                complexity=complexity, holds=data["passed"],
                note=("The theory is now the truth: play it as true." + (" Add a complication."
                      if data["degree"] == "success at a cost" else "")) if data["passed"]
                else "The theory is wrong. Make a move; they may make the case again with more clues.")
    out["visible_events"] = (out.get("visible_events") or []) + [
        {"type": "case", "recipient": "party",
         "text": f"The case holds: {theory}" if data["passed"] else "The case does not hold."}]
    return out
