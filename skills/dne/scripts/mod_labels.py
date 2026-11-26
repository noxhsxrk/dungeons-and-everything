#!/usr/bin/env python3
"""mod_labels.py — the labels module's engine action, `identity` (data/modules/labels.json).

Five identity labels per hero, each a track from -2 to +3. A shift moves one up and another down together; a half
that would go past the edge does not happen and the hero becomes insecure instead (emotions module). A roll with a
label is the usual Braid check with the label's value as its modifier."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mechanics  # noqa: E402
import modules  # noqa: E402
import paths  # noqa: E402
import turn  # noqa: E402
import world_db as wdb  # noqa: E402


def _names() -> list:
    return [t["id"] for t in modules.load("labels")["tracks"]]


def values(ctx, owner: str) -> dict:
    return {n: (wdb.get(ctx.db, "track", mechanics.key_of(owner, n)) or {"value": 0})["value"] for n in _names()}


@turn.handler("identity")
@modules.requires("labels")
def _identity(ctx, intent: dict) -> dict:
    """identity — a hero's five identity labels (module labels): fierce, uncanny, guardian, proud, grounded, -2..+3.

    {"action": "identity", "owner": "Kit", "set": {"fierce": 2, "uncanny": 1, "guardian": 1, "proud": 0, "grounded": -1}}
    {"action": "identity", "owner": "Kit", "up": "uncanny", "down": "grounded", "by": "Coach Reyes", "why": "…"}
        a shift: one up, one down. A half past the edge (+3 / -2) does not happen; the hero becomes insecure
        instead (emotions module on) or the reply says to name a condition.
    {"action": "identity", "owner": "Kit", "roll": "guardian", "label": "shield the bus"}   2d6 + that label;
        push, help and conditions as on any roll (conditions on the label's approach: fierce Force, uncanny
        Finesse, guardian Grit, proud Wits, grounded Heart); story mode: the label sets the oracle's odds; a
        token can step it up afterwards
    {"action": "identity", "owner": "Kit"}   read the five"""
    nums = modules.load("labels")["numbers"]
    owner, names = str(intent.get("owner") or "").strip(), _names()
    if not owner:
        return mechanics.error("identity needs an owner")
    asked = [intent.get(k) for k in ("roll", "up", "down") if intent.get(k)] + list(intent.get("set") or {})
    bad = [a for a in asked if a not in names]
    if bad:
        return mechanics.error(f"labels: {', '.join(names)} (not {', '.join(map(str, bad))})")
    modules.ensure(ctx, "labels", [owner])
    if intent.get("roll"):
        value = values(ctx, owner)[intent["roll"]]
        check = {"action": "roll", "actor": owner, "spec": f"2d6{value:+d}",
                 "label": intent.get("label") or f"as {intent['roll']}",
                 "approach": intent.get("approach") or nums["approach"][intent["roll"]],   # whose conditions count
                 "likelihood": mechanics.PROGRESS_ODDS[(value + 2) * 2],                    # story mode: the odds
                 **{k: intent[k] for k in ("push", "help") if k in intent}}
        out = turn._check(ctx, check, paths.campaign_system(ctx.campaign))
        if out.get("status") == "done" and "degree" in (out.get("data") or {}):
            out["data"]["with_label"] = intent["roll"]
        return out
    if intent.get("set"):
        for n, v in intent["set"].items():
            mechanics.change_track(ctx, owner, n, set_to=max(nums["min"], min(nums["max"], int(v))), why="starting labels")
        return mechanics.done({"owner": owner, "labels": values(ctx, owner)}, refresh="clocks")
    if not (intent.get("up") or intent.get("down")):
        return mechanics.done({"owner": owner, "labels": values(ctx, owner)})
    if not (intent.get("up") and intent.get("down")) or intent["up"] == intent["down"]:
        return mechanics.error("a shift moves one label up and a different one down: send both")
    now, why = values(ctx, owner), f"{intent.get('by') or 'someone'}: {intent.get('why') or 'told them who they are'}"
    edge = [n for n, d in ((intent["up"], 1), (intent["down"], -1)) if not nums["min"] <= now[n] + d <= nums["max"]]
    for n, d in ((intent["up"], 1), (intent["down"], -1)):
        if n not in edge:
            mechanics.change_track(ctx, owner, n, mark=d, why=why)
    data = {"owner": owner, "labels": values(ctx, owner), "edge": edge}
    events = [{"type": "identity", "recipient": "party",
               "text": f"{owner}: {intent['up']} up, {intent['down']} down ({why})"}]
    if edge:
        if "emotions" in modules.enabled(ctx.campaign):
            import mod_emotions
            data["emotion"] = mod_emotions.give(ctx, owner, nums["edge_emotion"], f"pushed past the edge: {', '.join(edge)}")
            events.append({"type": "condition", "recipient": "party", "text": f"{owner} is {nums['edge_emotion']}"})
        else:
            data["note"] = f"{', '.join(edge)} is already at the edge: name a condition for {owner} instead"
    return mechanics.done(data, refresh="clocks", visible_events=events)
