#!/usr/bin/env python3
"""mod_strings.py — the strings module's engine action, `string` (data/modules/strings.json).

A string is a hold one character has on another: a bond point (mechanics `bond`) held by one side. Spent, it gives
+1 to the holder's next roll, -1 to the other's next roll, an emotion (with the emotions module), or a temptation
that pays the other 1 XP if they go along. The +1 and -1 are one-roll conditions, cleared after the next check."""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mechanics  # noqa: E402
import modules  # noqa: E402
import paths  # noqa: E402
import turn  # noqa: E402
import world_db as wdb  # noqa: E402

SPENDS = ("plus", "minus", "tempt", "emotion")
ONE_ROLL = "next roll"


def _one_roll(ctx, owner: str, name: str, mod: int, note: str) -> dict:
    rec = {"owner": owner, "name": name, "mod": mod, "approaches": [], "clears": ONE_ROLL, "note": note}
    wdb.put(ctx.db, "condition", mechanics._key(owner, name), rec)
    return rec


@turn.handler("string")
def _string(ctx, intent: dict) -> dict:
    """string — one character's hold on another (module strings).

    {"action": "string", "by": "Mira", "on": "Theo", "gain": 1, "why": "she saw him cry"}    gain a string
    {"action": "string", "by": "Mira", "on": "Theo", "spend": "plus"}     +1 on Mira's next roll (one about Theo)
    {"action": "string", "by": "Mira", "on": "Theo", "spend": "minus"}    -1 on Theo's next roll (one against Mira)
    {"action": "string", "by": "Mira", "on": "Theo", "spend": "emotion", "emotion": "insecure"}   (emotions module)
    {"action": "string", "by": "Mira", "on": "Theo", "spend": "tempt", "offer": "skip the trial and run with me"}
    {"action": "string", "on": "Theo", "accept": true}    Theo went along: 1 XP for Theo (the reply has the command);
                                                          "accept": false closes it with nothing
    {"action": "string", "by": "Mira", "on": "Theo"}      read: who holds how many on whom
    Strings are bond points: the same bond record, shown in state.md. Spending is refused if there is none."""
    err = modules.need(ctx, "strings")
    if err:
        return mechanics._err(err)
    nums = modules.load("strings")["numbers"]
    by, on = str(intent.get("by") or "").strip(), str(intent.get("on") or "").strip()
    if "accept" in intent:
        offer = wdb.get(ctx.db, "temptation", on.casefold())
        if not offer:
            return mechanics._err(f"no open temptation on {on or '(on)'}")
        wdb.delete(ctx.db, "temptation", on.casefold())
        data = {"on": offer["on"], "by": offer["by"], "offer": offer["offer"], "accepted": bool(intent["accept"])}
        if intent["accept"]:
            event = re.sub(r"[^a-z0-9]+", "-", f"tempt {offer['action']}".casefold()).strip("-")
            data["xp"] = int(nums["tempt_xp"])
            data["xp_command"] = (f'sheet.py -c {ctx.campaign} xp "{offer["on"]}" --mark {data["xp"]} '
                                  f'--why "went along with {offer["by"]}: {offer["offer"]}" --event {event}')
        return mechanics._done(data)
    if not by or not on or by.casefold() == on.casefold():
        return mechanics._err("string needs two different characters: by (who holds it) and on (whom)")
    spend = intent.get("spend")
    if spend is not None and spend not in SPENDS:
        return mechanics._err(f"spend: one of {', '.join(SPENDS)}")
    if spend == "emotion" and "emotions" not in modules.enabled(ctx.campaign):
        return mechanics._err("spending a string on an emotion needs the emotions module switched on")
    if spend == "tempt" and not str(intent.get("offer") or "").strip():
        return mechanics._err("a temptation needs the offer: what Theo is asked to do")
    move = {"action": "bond", "a": by, "b": on, "why": str(intent.get("why") or spend or "")}
    if spend:
        move["spend"] = 1
    elif intent.get("gain"):
        move["gain"] = int(intent["gain"])
    bond = mechanics._bond(ctx, move)["data"]
    if bond.get("error"):
        return mechanics._err(f"{by} holds no string on {on} to spend")
    data = {"by": by, "on": on, "strings": bond["points"], "bond": bond["value"]}
    events = []
    if spend == "plus":
        data["condition"] = _one_roll(ctx, by, f"Hold on {on}", int(nums["plus"]), f"spent a string on {on}")
        events.append(f"{by} spends a string on {on}: +1 on the next roll")
    elif spend == "minus":
        data["condition"] = _one_roll(ctx, on, f"{by}'s hold", int(nums["minus"]), f"{by} spent a string")
        events.append(f"{by} spends a string on {on}: {on} is -1 on the next roll")
    elif spend == "emotion":
        import mod_emotions
        rec = mod_emotions.give(ctx, on, str(intent.get("emotion") or ""), f"{by} got to them")
        if rec.get("error"):
            return mechanics._err(rec["error"])
        data["condition"] = rec
        events.append(f"{by} gets under {on}'s skin: {on} is {rec['name'].casefold()}")
    elif spend == "tempt":
        offer = {"by": by, "on": on, "offer": str(intent["offer"]).strip(), "action": ctx.action_id}
        wdb.put(ctx.db, "temptation", on.casefold(), offer)
        data["temptation"] = offer
        events.append(f"{by} tempts {on}: {offer['offer']} ({on} gains {nums['tempt_xp']} XP for going along)")
    elif intent.get("gain"):
        events.append(f"{by} gains a string on {on}")
    return mechanics._done(data, visible_events=[{"type": "string", "recipient": "party", "text": t} for t in events])


def _after(ctx, intent: dict, out: dict) -> None:
    """A one-roll +1 or -1 from a string is used up by the actor's next graded check."""
    data = out.get("data") or {}
    if not data.get("degree") or not data.get("actor") or intent.get("action") == "string":
        return
    if paths.campaign_system(ctx.campaign) == "d20":
        return
    for key, rec in wdb.all_of(ctx.db, "condition").items():
        if rec.get("clears") == ONE_ROLL and rec["owner"].casefold() == str(data["actor"]).casefold():
            wdb.delete(ctx.db, "condition", key)
            data.setdefault("used", []).append(rec["name"])


turn.AFTER_ACTION.append(_after)
