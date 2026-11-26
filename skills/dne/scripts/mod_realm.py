#!/usr/bin/env python3
"""mod_realm.py — the realm module (data/modules/realm.json, rules in .md): cultivation as a track.

A breakthrough is the usual Braid check (turn._check), harder by realm. Into every third realm (default) heaven
answers with a tribulation: N checks in a row, one action each (`wave`), each miss a wound; survive half and the
realm is yours. A failed breakthrough leaves Qi Deviation, a condition. You never fall a realm."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mechanics  # noqa: E402
import modules  # noqa: E402
import paths  # noqa: E402
import turn  # noqa: E402
import world_db as wdb  # noqa: E402

DEVIATION = "Qi Deviation"


def _deviate(ctx, actor: str, nums: dict, why: str) -> None:
    wdb.put(ctx.db, "condition", mechanics.key_of(actor, DEVIATION),
            {"owner": actor, "name": DEVIATION, "mod": int(nums["deviation_mod"]), "approaches": [], "clears": "rest",
             "note": why})


def _check(ctx, intent: dict, actor: str, approach: str, diff: int, label: str, system: str) -> dict:
    """The usual check, `diff` harder: core takes the spec (or the sheet's approach) minus diff; story asks the oracle."""
    spec = None
    if system == "core":
        import resolve as checks
        if intent.get("spec"):
            spec = f"{checks.CORE_DICE}{checks.dice_for(system, str(intent['spec']))[2] - diff:+d}"
        else:
            import sheet
            base = sheet.approach(ctx.campaign, actor, approach)
            if base is None:
                return mechanics.error(f"no approach {approach!r} on {actor}'s sheet: send a spec (\"2d6+1\")")
            spec = f"{checks.CORE_DICE}{base - diff:+d}"
    check = {"action": "roll", "actor": actor, "approach": approach, "label": label,
             "likelihood": ("likely", "50/50", "unlikely")[min(diff, 2)],
             **({"spec": spec} if spec else {}), **{k: intent[k] for k in ("push", "help") if k in intent}}
    return turn._check(ctx, check, system)


@turn.handler("realm")
@modules.requires("realm")
def _realm(ctx, intent: dict) -> dict:
    """realm — a cultivator's realm (module realm).

    {"action": "realm", "actor": "Lin", "breakthrough": true}   the usual check with Heart (or "approach", or a
        "spec" from the sheet), -1 from realm 3 and -2 from realm 6 (default). Passed (7+): one realm up. Missed:
        Qi Deviation (-1 on every roll, clears on a rest); a critical miss also marks 1 harm.
    Into realms 3 and 6 (default) a passed breakthrough calls a tribulation instead: 2 + realm/3 waves.
    {"action": "realm", "actor": "Lin", "wave": 1}   one wave, the usual check with Grit at the same difficulty;
        send waves 1, 2, 3 … in order, each its own action. A missed wave marks 1 harm (2 on a critical miss).
        After the last: half or more passed = the realm; fewer = Qi Deviation and no realm.
    {"action": "realm", "actor": "Lin"}   read: realm, its name, any tribulation under way.
    Push and help as on `roll`. Each result lands at once: a token cannot step it up afterwards."""
    mod = modules.load("realm")
    nums, names = mod["numbers"], mod["tables"]["realms"]
    actor = str(intent.get("actor") or "").strip()
    if not actor:
        return mechanics.error("realm needs an actor")
    modules.ensure(ctx, "realm", [actor])
    rec = mechanics.change_track(ctx, actor, "realm")
    tkey = mechanics.key_of(actor)
    trib = wdb.get(ctx.db, "tribulation", tkey)
    now = {"actor": actor, "realm": rec["value"], "name": names[min(rec["value"], len(names) - 1)], "tribulation": trib}
    if not intent.get("breakthrough") and "wave" not in intent:
        return mechanics.done(now)
    system = paths.campaign_system(ctx.campaign)
    target = (trib or {}).get("target", rec["value"] + 1)
    diff = min(int(nums["harder_max"]), target // int(nums["harder_every"]))

    if intent.get("breakthrough"):
        if trib:
            return mechanics.error(f"a tribulation is under way: send wave {len(trib['results']) + 1}")
        if rec["value"] >= rec["max"]:
            return mechanics.error(f"{actor} stands at the last realm")
        out = _check(ctx, intent, actor, str(intent.get("approach") or nums["approach"]), diff,
                     f"breakthrough to {names[min(target, len(names) - 1)]}", system)
        data = out.get("data") or {}
        if out.get("status") != "done" or "degree" not in data:
            return out
        data.pop("spec", None)                    # settled now: no token reaches back past the result
        if not data["passed"]:
            _deviate(ctx, actor, nums, "a failed breakthrough")
            if data["degree"] == "critical failure":
                data["harm"] = mechanics.change_track(ctx, actor, "harm", mark=int(nums["harm_on_critical"]),
                                                      why="breakthrough backlash")["value"]
            data.update(realm=rec["value"], deviation=True)
        elif target % int(nums["tribulation_every"]) == 0:
            trib = {"target": target, "waves": int(nums["waves_base"]) + target // int(nums["tribulation_every"]),
                    "results": []}
            wdb.put(ctx.db, "tribulation", tkey, trib)
            data.update(realm=rec["value"], tribulation=trib)
            out["visible_events"] = (out.get("visible_events") or []) + [
                {"type": "realm", "recipient": "party", "text": f"Heaven answers {actor}: a tribulation of {trib['waves']} waves"}]
        else:
            up = mechanics.change_track(ctx, actor, "realm", mark=1, why="breakthrough")
            data.update(realm=up["value"], name=names[min(up["value"], len(names) - 1)])
        out["refresh"] = "clocks"
        return out

    if not trib:
        return mechanics.error(f"{actor} faces no tribulation")
    wave = int(intent["wave"])
    if wave != len(trib["results"]) + 1:
        return mechanics.error(f"wave {wave}: the next wave is {len(trib['results']) + 1} of {trib['waves']}")
    out = _check(ctx, intent, actor, str(intent.get("approach") or nums["tribulation_approach"]), diff,
                 f"tribulation wave {wave} of {trib['waves']}", system)
    data = out.get("data") or {}
    if out.get("status") != "done" or "degree" not in data:
        return out
    data.pop("spec", None)
    trib["results"].append(bool(data["passed"]))
    if not data["passed"]:
        hurt = int(nums["harm_per_wave"]) + (1 if data["degree"] == "critical failure" else 0)
        data["harm"] = mechanics.change_track(ctx, actor, "harm", mark=hurt, why=f"tribulation wave {wave}")["value"]
    data.update(wave=wave, waves=trib["waves"], passed_waves=sum(trib["results"]))
    if len(trib["results"]) < trib["waves"]:
        wdb.put(ctx.db, "tribulation", tkey, trib)
    else:
        wdb.delete(ctx.db, "tribulation", tkey)
        if 2 * sum(trib["results"]) >= trib["waves"]:
            up = mechanics.change_track(ctx, actor, "realm", mark=1, why="survived the tribulation")
            data.update(realm=up["value"], name=names[min(up["value"], len(names) - 1)], survived=True)
        else:
            _deviate(ctx, actor, nums, "a failed tribulation")
            data.update(realm=rec["value"], survived=False, deviation=True)
    out["refresh"] = "clocks"
    return out
