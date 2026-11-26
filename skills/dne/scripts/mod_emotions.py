#!/usr/bin/env python3
"""mod_emotions.py — the emotions module's engine action, `emotion` (data/modules/emotions.json).

An emotion is a condition that stays: -1 on one approach until the character acts on it. Stored as an ordinary
condition, so every roll already reads it."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mechanics  # noqa: E402
import modules  # noqa: E402
import turn  # noqa: E402
import world_db as wdb  # noqa: E402


def give(ctx, owner: str, name: str, why: str = "") -> dict:
    """Put emotion `name` on `owner` (a second time changes nothing). Returns the condition, or {"error"}."""
    nums = modules.load("emotions")["numbers"]
    key = name.strip().casefold()
    if key not in nums["emotions"]:
        return {"error": f"emotion: one of {', '.join(nums['emotions'])}"}
    e = nums["emotions"][key]
    rec = {"owner": owner, "name": key.title(), "mod": int(nums["mod"]), "approaches": [e["approach"]],
           "clears": "acting on it", "note": f"{why + '. ' if why else ''}Clears when they {e['clear']}"}
    wdb.put(ctx.db, "condition", mechanics.key_of(owner, rec["name"]), rec)
    return rec


@turn.handler("emotion")
@modules.requires("emotions")
def _emotion(ctx, intent: dict) -> dict:
    """emotion — a feeling that stays until the character acts on it (module emotions).

    {"action": "emotion", "owner": "Theo", "name": "afraid", "why": "the letter"}       mark it
    {"action": "emotion", "owner": "Theo", "name": "afraid", "act": true, "why": "told Mira he is scared"}   cleared
    {"action": "emotion", "owner": "Theo"}                                               list Theo's
    afraid -1 Force, angry -1 Heart, guilty -1 Wits, hopeless -1 Grit, insecure -1 Finesse (our defaults). Each
    clears when the character does what it pushes them to (the reply's note says what), or when someone comforts
    them in a real scene (send "act" then too)."""
    owner, name = str(intent.get("owner") or "").strip(), str(intent.get("name") or "").strip()
    if not owner:
        return mechanics.error("emotion needs an owner")
    known = modules.load("emotions")["numbers"]["emotions"]
    if not name:
        return mechanics.done({"owner": owner, "emotions": [r for r in wdb.all_of(ctx.db, "condition").values()
                                                             if r["owner"].casefold() == owner.casefold()
                                                             and r["name"].casefold() in known]})
    if intent.get("act"):
        key = mechanics.key_of(owner, name.title())
        had = wdb.get(ctx.db, "condition", key) is not None
        wdb.delete(ctx.db, "condition", key)
        return mechanics.done({"owner": owner, "name": name.title(), "cleared": had, "why": str(intent.get("why", ""))},
                               visible_events=[{"type": "condition", "recipient": "party",
                                                "text": f"{owner} is no longer {name.casefold()}"}] if had else [])
    rec = give(ctx, owner, name, str(intent.get("why", "")))
    if rec.get("error"):
        return mechanics.error(rec["error"])
    return mechanics.done(rec, visible_events=[{"type": "condition", "recipient": "party",
                                                 "text": f"{owner} is {name.casefold()}"}])
