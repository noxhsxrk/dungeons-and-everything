#!/usr/bin/env python3
"""mod_status_window.py — the status_window module (data/modules/status_window.json, rules in .md).

LitRPG system messages written from the state itself: after every action the script compares the tracks, pools,
progress and conditions with what it saw last, and sends the table one "[System]" line per change. The model never
types a number into them. Achievements are recorded once; loot boxes are rolled from the module's tables."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mechanics  # noqa: E402
import modules  # noqa: E402
import paths  # noqa: E402
import turn  # noqa: E402
import world_db as wdb  # noqa: E402


def seen(db) -> dict:
    """{key: (label, shown value)} for every number a status window shows. Only these kinds: never roles or secrets."""
    out = {}
    for t in wdb.all_of(db, "track").values():
        out[f"track:{t['owner']}/{t['id']}".casefold()] = [f"{t['owner']} — {t['id']}", f"{t['value']}/{t['max']}"]
    for p in wdb.all_of(db, "pool").values():
        out[f"pool:{p['owner']}/{p['id']}".casefold()] = [f"{p['owner']} — {p['id']}",
                                                         (p.get("die") or "gone") if p.get("die") or p.get("gone")
                                                         else f"{p['value']}/{p['max']}"]
    for g in wdb.all_of(db, "progress").values():
        out[f"progress:{g['name']}".casefold()] = [g["name"], f"{g['ticks'] // 4}/10 boxes"]
    for c in wdb.all_of(db, "condition").values():
        out[f"condition:{c['owner']}/{c['name']}".casefold()] = [f"{c['owner']} — {c['name']}",
                                                                f"{int(c.get('mod') or 0):+d}" if c.get("mod") else "on"]
    return out


def diff(before: dict, after: dict) -> list:
    lines = []
    for key in sorted(set(before) | set(after)):
        was, now = before.get(key), after.get(key)
        if was == now:
            continue
        cond = key.startswith("condition:")
        if was is None:
            lines.append(f"[System] {now[0]}: {'gained' if cond else 'new'} ({now[1]})")
        elif now is None:
            lines.append(f"[System] {was[0]}: {'ended' if cond else 'gone'}")
        else:
            lines.append(f"[System] {now[0]}: {was[1]} → {now[1]}")
    return lines


def award(ctx, owner: str, title: str, why: str, key: str = "") -> "str | None":
    """Record an achievement once per owner (and key); the announcement, or None if they had it already."""
    key = key or mechanics._key(owner, title)
    if wdb.get(ctx.db, "achievement", key):
        return None
    wdb.put(ctx.db, "achievement", key, {"owner": owner, "title": title, "why": why, "turn": ctx.turn_id})
    return f"[System] Achievement unlocked — {owner}: {title}" + (f" ({why})" if why else "")


def _say(out: dict, lines: list) -> None:
    if lines:
        out["messages"] = (out.get("messages") or []) + [{"to": "party", "kind": "system", "text": "\n".join(lines)}]
        out["visible_events"] = (out.get("visible_events") or []) + [
            {"type": "system", "recipient": "party", "text": line} for line in lines]


def _after(ctx, intent: dict, out: dict) -> None:
    """After every action, in a campaign with the module on: the changes, as system lines, and first-time feats."""
    if paths.campaign_system(ctx.campaign) == "d20" or "status_window" not in modules.enabled(ctx.campaign):
        return
    now, last = seen(ctx.db), wdb.get(ctx.db, "status_seen", "all")
    lines = diff(last["seen"], now) if last else []
    data = out.get("data") or {}
    firsts = modules.load("status_window")["tables"]
    table = f"first_{str(data.get('degree') or '').replace(' ', '_')}"
    key = mechanics._key(data.get("actor") or "", table)
    if data.get("actor") and table in firsts and not data.get("error") and not wdb.get(ctx.db, "achievement", key):
        title = mechanics.roll_table(ctx, firsts[table], f"status-{table}")["result"]
        lines.append(award(ctx, str(data["actor"]), title, f"first {data['degree']}", key))
    if not last or last["seen"] != now:
        wdb.put(ctx.db, "status_seen", "all", {"seen": now})
    _say(out, lines)


turn.AFTER_ACTION.append(_after)


def window(db, owner: str) -> str:
    """The status window: every number the store holds for `owner`, and their achievements."""
    me = owner.casefold()
    rows = [f"{v[0].split(' — ', 1)[-1]}: {v[1]}" for k, v in sorted(seen(db).items())
            if k.split(":", 1)[1].startswith(me + "/")]
    got = [a["title"] for a in wdb.all_of(db, "achievement").values() if a["owner"].casefold() == me]
    return "\n".join([f"[Status — {owner}]"] + (rows or ["(nothing tracked yet)"]) +
                     ([f"Achievements: {', '.join(got)}"] if got else []))


@turn.handler("status")
def _status(ctx, intent: dict) -> dict:
    """status — the LitRPG system (module status_window). Every change to a track, pool, progress or condition is
    announced by itself after each action as a "[System]" line; these are for the rest.

    {"action": "status", "show": "Mira"}                     the status window: Mira's numbers and achievements
    {"action": "status", "achievement": "Bridge Burner", "to": "Mira", "why": "burned the only way back"}
                                                             awarded once; a second time says nothing
    {"action": "status", "loot": "silver", "to": "Mira"}     a loot box (bronze | silver | gold): the script rolls
        d100 for its tier (common, rare, epic) and an item from that tier's table
    The first critical success and the first critical failure of each character earn an achievement by themselves."""
    err = modules.need(ctx, "status_window")
    if err:
        return mechanics._err(err)
    mod = modules.load("status_window")
    who = str(intent.get("to") or intent.get("show") or "").strip()
    if not who:
        return mechanics._err("status needs \"show\" or \"to\": a character")
    out, lines = {}, []
    if intent.get("achievement"):
        line = award(ctx, who, str(intent["achievement"]).strip(), str(intent.get("why") or ""))
        lines += [line] if line else []
        out = {"owner": who, "achievement": intent["achievement"], "new": bool(line)}
    elif intent.get("loot"):
        box = str(intent["loot"]).casefold()
        odds = mod["numbers"]["boxes"].get(box)
        if not odds:
            return mechanics._err(f"loot: one of {', '.join(mod['numbers']['boxes'])}")
        d100 = ctx.roll("loot-tier", 100)[0]
        tier = next(t for t, cap in zip(mod["numbers"]["tiers"], _cumulative(odds)) if d100 <= cap)
        item = mechanics.roll_table(ctx, mod["tables"][f"loot_{tier}"], "loot-item")["result"]
        lines.append(f"[System] {who} opens a {box} box: {item} ({tier})")
        out = {"owner": who, "box": box, "d100": d100, "tier": tier, "item": item}
    else:
        text = window(ctx.db, who)
        return mechanics._done({"owner": who, "window": text}, messages=[{"to": "party", "kind": "system", "text": text}])
    done = mechanics._done(out)
    _say(done, lines)
    return done


def _cumulative(odds: list) -> list:
    total, out = 0, []
    for n in odds:
        total += int(n)
        out.append(total)
    return out
