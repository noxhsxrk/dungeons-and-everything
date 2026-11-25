#!/usr/bin/env python3
"""
stakes.py — what the players prepare for and prevent changes what can happen next.

  beat       "<id>" → {text, requires, status: pending | landed | prevented | needs_revision, prevented_by}
  situation  "<id>" → {sides: [{who, wants, limit, will_trade}], if_left_alone, facts, difficulty, plans}
  encounter  "<id>" → {rewarded, outcome}                         (one reward per encounter, ever)

Engine actions (turn.py help <name>):
  beat       register a story beat with the conditions it needs to still be possible
  set        change a piece of world state ("Velkyn is captured"), with its cause
  situation  write down what each side wants, what limits them, what they would trade, and what
             the world does if nobody acts
  judge      rule on a plan the players came up with, from those facts
  reward     XP for a whole plan (the scouting and the preparation count), once per encounter

A BEAT is checked after every action. If its conditions no longer hold, the beat is over: under
`beat_policy: players_can_prevent` (the default for sandbox and dynamic campaigns) it is `prevented`
and the cause is recorded; under `must_land` (the default when the campaign has an arc.md) it becomes
`needs_revision`: the consequence still has to land, in a shape that fits what really happened.

JUDGING A PLAN. Say what could still go wrong (`risk`) and what changes if it does (`if_fails`).
A plan that leaves no risk succeeds with no roll. A roll that lands on "success at a cost" stops the
turn: the player hears the price and chooses to pay it or not. Nothing is decided for them.
"""
from __future__ import annotations

import datetime
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import paths  # noqa: E402
import scheduler  # noqa: E402
import turn  # noqa: E402


def _world(ctx):
    return scheduler.World(ctx.campaign, ctx.db)


def policy(world) -> str:
    """Whether a beat the players made impossible is gone (players_can_prevent) or must be reshaped (must_land)."""
    flag = paths.session_flag(world.campaign, "beat_policy", "")
    if flag in ("players_can_prevent", "must_land"):
        return flag
    return "must_land" if (world.camp / "arc.md").exists() else "players_can_prevent"


def check_beats(world, cause: str = "") -> list:
    """Beats whose conditions stopped being true are closed now, with what closed them. Returns the GM's notices."""
    cause = cause or getattr(world, "cause", "")
    out = []
    for bid, beat in sorted(world.all("beat").items()):
        if beat.get("status") != "pending":
            continue
        broken = [c for c in beat.get("requires") or [] if not scheduler._holds(world, c)]
        if not broken:
            continue
        prevented = policy(world) == "players_can_prevent"
        beat["status"] = "prevented" if prevented else "needs_revision"
        beat["prevented_by"] = {"cause": cause, "condition": broken[0], "minute": world.minute}
        world.put("beat", bid, beat)
        text = (f"BEAT PREVENTED: \"{beat['text']}\" can no longer happen ({cause or 'its conditions are gone'}). "
                "Do not bring it back in another form. Build the next scene from what actually happened."
                if prevented else
                f"BEAT NEEDS A NEW SHAPE: \"{beat['text']}\" cannot happen as written ({cause or 'its conditions are gone'}). "
                "Its consequence still has to land: revise how, from what actually happened (/dne arc revise).")
        out.append({"type": "beat_" + beat["status"], "recipient": "dm", "beat": bid, "text": text})
    return out


@turn.handler("beat")
def _beat(ctx, intent: dict) -> dict:
    """beat — a story beat, with what must still be true for it to happen.

    {"action": "beat", "id": "betrayal-at-the-gate", "text": "Velkyn opens the gate to the Pale Court.",
     "requires": [{"thing": ["state", "Velkyn"], "path": "status", "not": "captured"}]}
    {"action": "beat", "id": "betrayal-at-the-gate", "status": "landed"}      (it happened)
    A condition is {"thing": [kind, id], "path": "a.b", "equals" | "not": value}. When the players make one false,
    the beat is closed and you are told why (see `beat_policy` in Table Dials)."""
    world = _world(ctx)
    bid = str(intent.get("id") or f"beat-{ctx.action_id}")
    beat = world.get("beat", bid) or {"text": "", "requires": [], "status": "pending"}
    for key in ("text", "requires", "status"):
        if key in intent:
            beat[key] = intent[key]
    world.put("beat", bid, beat)
    return {"status": "done", "elapsed_minutes": 0, "data": {"beat": bid, **beat, "policy": policy(world)},
            "visible_events": check_beats(world, "its conditions were already false")}


@turn.handler("set")
def _set(ctx, intent: dict) -> dict:
    """set — a piece of world state changes, and why.

    {"action": "set", "thing": ["state", "Velkyn"], "data": {"status": "captured"}, "cause": "the party caught him at the mill"}
    Anything waiting on that state reacts: queued events with a `when` trigger, and story beats that needed it otherwise."""
    world = _world(ctx)
    kind, id = intent["thing"]
    record = world.get(kind, id) or {}
    record.update(intent.get("data") or {})
    world.put(kind, id, record)
    world.cause = str(intent.get("cause") or f"{id} changed")
    visible = scheduler.fire(world, "when")       # triggers waiting on this state, then the beats that needed it
    return {"status": "done", "elapsed_minutes": 0, "writes": world.writes(), "visible_events": visible,
            "data": {"thing": [kind, id], "now": record}}


@turn.handler("situation")
def _situation(ctx, intent: dict) -> dict:
    """situation — the facts of a scene that has more than one good answer.

    {"action": "situation", "id": "gate-before-the-storm", "difficulty": "hard",
     "sides": [{"who": "the medicine carrier", "wants": "ten more minutes with the gate open", "limit": "the cart cannot be left",
                "will_trade": "the medicine can come in without the cart"},
               {"who": "the engineer", "wants": "the gate shut now", "limit": "the mechanism fails if it waits",
                "will_trade": "the mail hatch stays open in any weather"}],
     "if_left_alone": "the gate closes on schedule and the medicine stays outside",
     "facts": ["the mail hatch is big enough for a crate"]}
    Write down what is true, not what should happen. When a player proposes something you did not plan for, `judge`
    it against these facts: if it works given what is true here, it works."""
    world = _world(ctx)
    sid = str(intent.get("id") or f"situation-{ctx.action_id}")
    record = world.get("situation", sid) or {"sides": [], "facts": [], "plans": [], "difficulty": "medium", "if_left_alone": ""}
    for key in ("sides", "facts", "difficulty", "if_left_alone"):
        if key in intent:
            record[key] = intent[key]
    world.put("situation", sid, record)
    return {"status": "done", "elapsed_minutes": 0, "data": {"situation": sid, **record}}


@turn.handler("judge")
def _judge(ctx, intent: dict) -> dict:
    """judge — rule on a plan the players came up with.

    No risk left:   {"action": "judge", "situation": "gate-before-the-storm", "actor": "Mira",
                     "plan": "only the medicine comes in, through the mail hatch"}
    Still a risk:   {..., "risk": "the crate may not fit before the gate drops", "if_fails": "the crate is caught in the hatch",
                     "opens": "the party has to work the mechanism from inside", "cost": "the hatch door is torn off",
                     "roll": {"spec": "1d20+5", "dc": 13, "label": "Athletics"}}
    A plan with no `risk` succeeds without a roll (and still counts for `reward`). A roll needs both `risk` and
    `if_fails`: say what could go wrong and what changes if it does. `opens` is what a failure lets the players do
    that they could not before. On "success at a cost" the turn stops: the player is told the `cost` and chooses
    accept or refuse. Do not choose for them."""
    import dice
    world = _world(ctx)
    sid = str(intent.get("situation") or "")
    actor, plan = str(intent.get("actor") or "Party"), str(intent.get("plan", ""))
    roll = intent.get("roll")

    def close(outcome: str, **extra) -> dict:
        situation = world.get("situation", sid)
        if situation is not None:
            situation.setdefault("plans", []).append({"by": actor, "plan": plan, "outcome": outcome, "minute": world.minute})
            world.put("situation", sid, situation)
        if sid:
            enc = world.get("encounter", sid) or {}
            enc.update(outcome=outcome, by=actor)
            world.put("encounter", sid, enc)
        return {"status": "done", "elapsed_minutes": 0, "writes": world.writes(),
                "visible_events": check_beats(world, f"{actor}'s plan: {plan}"),
                "data": {"situation": sid, "actor": actor, "plan": plan, "outcome": outcome, **extra}}

    if not intent.get("risk"):
        return close("success_no_roll", why="nothing in the plan can go wrong given the facts of the situation")
    if not roll or not intent.get("if_fails"):
        return {"status": "done", "elapsed_minutes": 0,
                "data": {"error": "a risky plan needs `roll` and `if_fails`: say what could go wrong and what changes if it does"}}
    num, sides, mod, *_ = dice.parse_notation(str(roll.get("spec", "1d20")))
    dc = int(roll.get("dc", 10))
    if "cost" in ctx.answers:
        took = str(ctx.answers["cost"]["value"]).strip().lower().startswith(("a", "y"))
        return close("success_at_a_cost" if took else "failure",
                     **({"cost": intent.get("cost", "")} if took else {"if_fails": intent["if_fails"], "opens": intent.get("opens", "")}))
    if ctx.flag("roll_mode", "players") == "players" and "roll" not in ctx.answers:
        shown = f" (DC {dc})" if ctx.flag("show_dc", "on") == "on" else ""
        return {"status": "waiting_for_player",
                "requests": [{"key": "roll", "kind": "roll", "expected": actor,
                              "text": f"{actor}: roll {roll.get('label') or 'for it'} — {roll.get('spec', '1d20')}{shown}. "
                                      f"At stake: {intent['risk']}"}]}
    raw = int(ctx.answers["roll"]["value"]) if "roll" in ctx.answers else ctx.roll("roll", sides, num)[0]
    total = raw + mod
    degree = dice.degree(raw, total, dc) if ctx.flag("degrees", "on") == "on" or ctx.flag("success_at_cost", "on") == "on" \
        else ("success" if total >= dc else "failure")
    if degree == "success at a cost" and ctx.flag("success_at_cost", "on") != "on":
        degree = "failure"
    rolled = {"dice": raw, "total": total, "dc": dc, "degree": degree}
    if degree == "success at a cost":
        return {"status": "waiting_for_player", "data": rolled,
                "requests": [{"key": "cost", "kind": "decision", "expected": actor,
                              "text": f"{actor}: {total} against {dc} — it works, at a price: "
                                      f"{intent.get('cost') or 'something is lost'}. Accept the price? (accept / refuse)"}]}
    if degree in ("success", "critical success"):
        return close("success", **rolled)
    return close("failure", **rolled, if_fails=intent["if_fails"], opens=intent.get("opens", ""))


@turn.handler("reward")
def _reward(ctx, intent: dict) -> dict:
    """reward — XP for a whole plan, once.

    {"action": "reward", "encounter": "gate-before-the-storm", "characters": ["Mira", "Theo"],
     "difficulty": "hard", "note": "scouted the hatch, talked to both sides, got the medicine in"}
    Rate the difficulty of the whole problem, the scouting and the preparation included: a plan that worked without a
    single roll earns it too. The same `encounter` is never paid twice. The amount comes from the XP tables, the sheet
    and the award ledger are written."""
    import journey
    import xp
    world = _world(ctx)
    eid = str(intent.get("encounter") or "")
    if not eid:
        return {"status": "done", "elapsed_minutes": 0, "data": {"error": "a reward needs an encounter id"}}
    enc = world.get("encounter", eid) or {}
    try:
        ledger = (world.camp / "xp-ledger.jsonl").read_text(encoding="utf-8")
    except OSError:
        ledger = ""
    paid = set()
    for line in ledger.splitlines():
        try:
            paid.add(str(json.loads(line).get("event", "")).casefold())
        except (ValueError, AttributeError):
            continue
    if not enc.get("rewarded") and eid.casefold() in paid:
        return {"status": "done", "elapsed_minutes": 0,
                "data": {"awarded": False, "error": f"{eid} was already awarded with xp.py award (see xp-ledger.jsonl)"}}
    if enc.get("rewarded"):
        return {"status": "done", "elapsed_minutes": 0,
                "data": {"awarded": False, "error": f"{eid} was already rewarded ({enc['rewarded']['total']} XP)"}}
    situation = world.get("situation", eid) or {}
    difficulty = str(intent.get("difficulty") or situation.get("difficulty") or "medium")
    ruleset = paths.campaign_ruleset(ctx.campaign)
    writes, given = {}, []
    stamp = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    for rel, (title, text) in journey._pc_sheets(world, intent.get("characters")).items():
        m = re.search(r"(\*\*(?:XP|经验|经验值):\*\*\s*)(\d+)", text)
        level_m = paths.CHARACTER_LEVEL_RE.search(text)
        if not m:
            continue
        level = int(level_m.group(1)) if level_m else 1
        gain = xp._xp_per_player(difficulty, level, ruleset)
        total = int(m.group(2)) + gain
        writes[rel] = text[:m.start(2)] + str(total) + text[m.end(2):]
        given.append({"character": title, "awarded": gain, "total_after": total,
                      "level_up": total >= xp._next_level_xp(level)})
        ledger += json.dumps({"at": stamp, "character": title, "awarded": gain, "total_after": total,
                              "note": f"{eid}: {intent.get('note', '')}", "event": eid}, ensure_ascii=False) + "\n"
    if not given:
        return {"status": "done", "elapsed_minutes": 0, "data": {"awarded": False, "error": "no character sheet with an XP line"}}
    writes["xp-ledger.jsonl"] = ledger
    enc["rewarded"] = {"total": sum(g["awarded"] for g in given), "difficulty": difficulty, "minute": world.minute}
    world.put("encounter", eid, enc)
    return {"status": "done", "elapsed_minutes": 0, "writes": writes,
            "data": {"awarded": True, "encounter": eid, "difficulty": difficulty, "characters": given,
                     "outcome": enc.get("outcome")}}


scheduler.AFTER_CHANGE.append(check_beats)   # time passing can close a beat too
