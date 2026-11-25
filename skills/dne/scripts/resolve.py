"""resolve.py — one check, graded on the engine's five-step ladder, whatever the campaign's system.

Every character check (`roll` with a target, `judge`, `flashback`, `bargain`, `search`) comes here, so a module
never brings a second way to roll.

  d20    5e: the dice vs a DC, graded by dice.degree exactly as before 2.0.
  core   Braid: 2d6 + modifier, no target. 3 or less critical failure / 4-6 failure / 7-9 success at a cost /
         10-11 success / 12+ critical success.
  story  Braid without dice: a d100 on the yes/no oracle. yes-and critical success / yes success / yes-but success
         at a cost / no and no-but failure / no-and critical failure.

The caller rolls (through the turn's ctx.roll, so a retry repeats) or takes the player's number, and hands the dice
here. Under core and story `passed` means the step is success at a cost or better: in Braid a 7-9 works, at a price.
"""
from __future__ import annotations

import dice
import oracle
import paths

LADDER = ("critical failure", "failure", "success at a cost", "success", "critical success")
CORE_DICE = "2d6"
#: Braid's ladder: the highest total of each step below critical success (our defaults, adjustable).
CORE_STEPS = (3, 6, 9, 11)
STORY_STEPS = {"yes-and": 4, "yes": 3, "yes-but": 2, "no-but": 1, "no": 1, "no-and": 0}


def dice_for(system: str, spec) -> "tuple[int, int, int]":
    """(count, sides, modifier) to roll for `spec` under `system`. Story rolls the oracle's d100."""
    if system == "story":
        return 1, 100, 0
    num, sides, mod, *_ = dice.parse_notation(str(spec or (CORE_DICE if system == "core" else "1d20")))
    return num, sides, mod


def spec_error(system: str, spec) -> "str | None":
    """Why `spec` cannot be a check in this system (core takes 2d6 + modifier only), or None."""
    if system != "core" or not spec:
        return None
    try:
        num, sides, *_ = dice.parse_notation(str(spec))
    except ValueError as exc:
        return str(exc)
    if (num, sides) != (2, 6):
        return (f"Braid checks roll 2d6 + modifier, not {spec}: send a spec like \"2d6+1\" "
                "(the modifier is the approach, -1 to +3; there is no DC)")
    return None


def shown(system: str, spec) -> str:
    """The dice a player is asked to roll, as text."""
    if system != "core":
        return str(spec or "1d20")
    mod = dice_for(system, spec)[2]
    return f"{CORE_DICE}{mod:+d} (send the two dice added together)" if mod else f"{CORE_DICE} (send the two dice added together)"


def chaos(campaign: str, system: str) -> int:
    """The campaign's oracle chaos factor; only story checks read it (a d20 or core check never opens state.md here)."""
    if system != "story":
        return oracle.CHAOS_DEFAULT
    try:
        return oracle.read_chaos((paths.find_campaign(campaign) / "state.md").read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return oracle.CHAOS_DEFAULT


def resolve(system: str, spec, target=None, rolled=(), *, step_up: int = 0, likelihood: str = "50/50",
            chaos: int = oracle.CHAOS_DEFAULT) -> dict:
    """Grade one check. {"degree", "raw", "total", "passed"}.

    d20: `rolled` are the dice that count (a d20 check reads one); target is the DC; with no target, degree and
    passed are None. core: `rolled` are both d6; target is ignored. story: `rolled` is [d100].
    `step_up` moves a core/story result up the ladder (a story token spent; the token itself is PR 2's pool)."""
    rolled = [int(d) for d in rolled]
    mod = dice_for(system, spec)[2]
    if system == "d20":
        total = sum(rolled) + mod
        if target is None:
            return {"degree": None, "raw": rolled[0], "total": total, "passed": None}
        return {"degree": dice.degree(rolled[0], total, int(target)), "raw": rolled[0], "total": total,
                "passed": total >= int(target)}
    if system == "core":
        total = sum(rolled) + mod
        step = next((i for i, top in enumerate(CORE_STEPS) if total <= top), 4)
        raw = rolled
    elif system == "story":
        raw = total = rolled[0]
        step = STORY_STEPS[oracle.verdict(raw, likelihood, chaos)]
    else:
        raise ValueError(f"unknown system {system!r}: one of {', '.join(paths.SYSTEMS)}")
    step = max(0, min(4, step + int(step_up)))
    return {"degree": LADDER[step], "raw": raw, "total": total, "passed": step >= 2}

