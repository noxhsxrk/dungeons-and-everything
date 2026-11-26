#!/usr/bin/env python3
"""mod_memories.py — the memories module (data/modules/memories.json, rules in .md): a mind with a few slots.

Each character holds up to N memories (5, default). Keeping a new one when the slots are full waits for the
player to choose which one fades, unless the intent names it. Amnesia takes one the script picks."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mechanics  # noqa: E402
import modules  # noqa: E402
import turn  # noqa: E402
import world_db as wdb  # noqa: E402


def _which(held: list, value) -> "int | None":
    """A memory named by its number (1 = oldest) or its exact text; None if no such memory."""
    text = str(value).strip()
    if text.isdigit() and 1 <= int(text) <= len(held):
        return int(text) - 1
    return next((i for i, m in enumerate(held) if m.casefold() == text.casefold()), None)


@turn.handler("memories")
@modules.requires("memories")
def _memories(ctx, intent: dict) -> dict:
    """memories — what a character still remembers (module memories).

    {"action": "memories", "owner": "Mira", "keep": "my brother's laugh at the harbour"}
        a new memory. When the slots are full the action waits for the player to answer which one fades (the
        number); or name it now: "forget": 2 (or its text).
    {"action": "memories", "owner": "Mira", "forget": 2}   let one go
    {"action": "memories", "owner": "Mira", "lose": true}  amnesia: the script picks one and it is gone
    {"action": "memories", "owner": "Mira", "slots": 6}    a mind that grows (or shrinks; the newest stay)
    {"action": "memories", "owner": "Mira"}                read them, oldest first"""
    owner = str(intent.get("owner") or "").strip()
    if not owner:
        return mechanics.error("memories needs an owner")
    key = mechanics.key_of(owner)
    rec = wdb.get(ctx.db, "memory", key) or {"owner": owner, "slots": int(modules.load("memories")["numbers"]["slots"]),
                                              "held": []}
    held, gone = rec["held"], []
    if "slots" in intent:
        rec["slots"] = max(1, int(intent["slots"]))
        gone += held[:max(0, len(held) - rec["slots"])]
        del held[:max(0, len(held) - rec["slots"])]
    keep = str(intent.get("keep") or "").strip()
    pick = intent.get("forget")
    if pick is None and keep and len(held) >= rec["slots"] and "forget" in ctx.answers:
        pick = ctx.answers["forget"]["value"]
    if keep and len(held) >= rec["slots"] and pick is None:
        listed = "; ".join(f"{i}) {m}" for i, m in enumerate(held, 1))
        return {"status": "waiting_for_player",
                "requests": [{"key": "forget", "kind": "decision", "expected": owner,
                              "text": f"{owner}'s mind is full. To keep \"{keep}\", one memory fades. Which? {listed}"}]}
    if pick is not None:
        i = _which(held, pick)
        if i is None:
            return mechanics.error(f"forget: no memory {pick!r} (1 to {len(held)}, or its text)")
        gone.append(held.pop(i))
    if intent.get("lose") and held:
        gone.append(held.pop(ctx.roll("lose", len(held))[0] - 1))
    if keep:
        held.append(keep)
    wdb.put(ctx.db, "memory", key, rec)
    return mechanics.done({"owner": owner, "slots": rec["slots"], "held": held, "forgotten": gone},
                           visible_events=[{"type": "memory", "recipient": "party", "text": f"{owner} forgets: {m}"}
                                           for m in gone])
