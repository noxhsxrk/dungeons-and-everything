#!/usr/bin/env python3
"""mod_roles.py — the roles module (data/modules/roles.json, rules in .md): secret roles the script deals and seals.

The deal is shuffled by the script, salted, and its sha256 (the seal) goes to the whole table as a message before
anyone plays. Each player character hears their own role privately. At the end `reveal` shows the deal and checks it
against the seal, so nobody (the GM included) can move the traitor mid-story without it showing. NPCs act from their
role: the script draws what they do from the role's table (an entry listed twice is twice as likely)."""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mechanics  # noqa: E402
import modules  # noqa: E402
import turn  # noqa: E402
import world_db as wdb  # noqa: E402

DEFAULT_ROLE = "loyal"


def seal(deal: dict, salt: str) -> str:
    """The commitment: sha256 of the deal and its salt as canonical JSON."""
    body = json.dumps({"deal": deal, "salt": salt}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def check(db, rec: dict, expect: "str | None" = None) -> list:
    """What does not match: the seal recomputed from the deal against the stored seal, the seal the table was sent,
    and (if given) the seal a player wrote down. Empty = verified."""
    now = seal(rec["deal"], rec["salt"])
    out = [] if now == rec["seal"] else ["the deal no longer matches the stored seal"]
    row = db.execute("SELECT body FROM outbox WHERE message_id=?", (rec["message"],)).fetchone()
    sent = re.search(r"[0-9a-f]{64}", row["body"]) if row else None
    if not sent or sent.group(0) != now:
        out.append("the deal does not match the seal the table was sent")
    if expect and str(expect).strip().casefold() != now:
        out.append("the deal does not match the seal you gave")
    return out


@turn.handler("roles")
def _roles(ctx, intent: dict) -> dict:
    """roles — secret roles, dealt and sealed by the script (module roles).

    {"action": "roles", "deal": ["Mira", "Theo", "Vos", "Kell"], "roles": {"traitor": 1}}
        shuffle and deal: the named counts, everyone else "loyal" (no counts: 1 traitor per 4, default). The table is
        sent the seal (sha256); each player character is told their own role privately. Refused while a deal is
        unrevealed. The reply's data never shows the deal; the PCs' private messages pass through the turn's
        `sent` list on their way out (the GM sees PC roles there, never the NPCs'). With one player character, that PC
        is always dealt "loyal" unless "pc_may_draw": true (the player asked to maybe be the traitor). After a
        reveal, a new deal needs "new": true.
    {"action": "roles", "act": "Vos", "why": "the vote"}   what an NPC does now, drawn from its role's table
        (`<role>_acts` in the module, or send "options": [...]); refused for a player character
    {"action": "roles", "reveal": true, "expect": "<seal a player kept>"}   the end: the deal, and whether it
        still matches the seal (`verified`; `problems` says what does not)."""
    err = modules.need(ctx, "roles")
    if err:
        return mechanics._err(err)
    import table
    mod = modules.load("roles")
    rec = wdb.get(ctx.db, "roles", "deal")
    pcs = {n.casefold(): n for n in table.pcs(ctx.campaign)}
    if "deal" in intent:
        if rec and not rec.get("revealed"):
            return mechanics._err("roles are already dealt and sealed: reveal them before a new deal")
        if rec and not intent.get("new"):
            return mechanics._err("the last deal was revealed: send \"new\": true to deal a new one on purpose")
        names = [str(n).strip() for n in intent["deal"] if str(n).strip()] if isinstance(intent["deal"], list) else []
        if len(set(n.casefold() for n in names)) != len(names) or len(names) < 2:
            return mechanics._err("deal: two or more different names")
        counts = intent.get("roles") or {"traitor": max(1, len(names) // int(mod["numbers"]["one_traitor_per"]))}
        pack = [str(r) for r, n in counts.items() for _ in range(int(n))]
        # a solo player hunting the traitor must never turn out to be it, unless they asked for the chance
        kept = [n for n in names if n.casefold() in pcs] if len(pcs) == 1 and not intent.get("pc_may_draw") else []
        drawn = [n for n in names if n not in kept]
        if len(pack) > len(drawn):
            return mechanics._err(f"{len(pack)} roles for {len(drawn)} names" + (f" ({kept[0]}, the only player character, is "
                                  "always loyal unless \"pc_may_draw\": true)" if kept else ""))
        pack += [DEFAULT_ROLE] * (len(drawn) - len(pack))
        r = wdb.rng(ctx.db, f"{ctx.action_id}:deal")          # seeded: a retry or a replay deals the same
        r.shuffle(pack)
        salt = f"{r.getrandbits(128):032x}"
        deal = {**dict(zip(drawn, pack)), **{n: DEFAULT_ROLE for n in kept}}
        deal = {n: deal[n] for n in names}
        rec = {"deal": deal, "salt": salt, "seal": seal(deal, salt), "message": f"{ctx.action_id}-m1",
               "revealed": False, "turn": ctx.turn_id}
        wdb.put(ctx.db, "roles", "deal", rec)
        msgs = [{"to": "party", "kind": "notice",
                 "text": f"Roles are dealt in secret to {', '.join(names)}. Seal: {rec['seal']} (keep it: at the end the "
                         "reveal must match it)"}]
        msgs += [{"to": pcs[n.casefold()], "text": f"Your secret role: {role}. Tell no one."}
                 for n, role in deal.items() if n.casefold() in pcs]
        return mechanics._done({"dealt": names, "seal": rec["seal"], "told": [m["to"] for m in msgs[1:]]}, messages=msgs,
                               visible_events=[{"type": "roles", "recipient": "party", "text": f"Seal: {rec['seal']}"}])
    if not rec:
        return mechanics._err("no roles dealt yet")
    if intent.get("act"):
        name = next((n for n in rec["deal"] if n.casefold() == str(intent["act"]).strip().casefold()), None)
        if name is None:
            return mechanics._err(f"{intent['act']!r} was not dealt a role")
        if name.casefold() in pcs:
            return mechanics._err(f"{name} is a player character: the player chooses")
        options = intent.get("options") or mod["tables"].get(f"{rec['deal'][name]}_acts")
        if not options:
            return mechanics._err(f"no table for this role: send \"options\": [...] (repeat an entry to make it likelier)")
        got = mechanics.roll_table(ctx, list(options), f"act-{name}")
        return mechanics._done({"npc": name, "act": got["result"], "why": str(intent.get("why", ""))})
    if intent.get("reveal"):
        problems = check(ctx.db, rec, intent.get("expect"))
        rec["revealed"] = True
        wdb.put(ctx.db, "roles", "deal", rec)
        shown = ", ".join(f"{n}: {r}" for n, r in rec["deal"].items())
        verdict = "the seal matches" if not problems else "THE SEAL DOES NOT MATCH: " + "; ".join(problems)
        return mechanics._done({"deal": rec["deal"], "salt": rec["salt"], "seal": rec["seal"], "verified": not problems,
                                "problems": problems},
                               messages=[{"to": "party", "kind": "notice",
                                          "text": f"Roles revealed: {shown}. Salt {rec['salt']}. {verdict}."}])
    return mechanics._done({"dealt": list(rec["deal"]), "seal": rec["seal"], "revealed": rec["revealed"]})
