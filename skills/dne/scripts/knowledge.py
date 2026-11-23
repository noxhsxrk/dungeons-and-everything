#!/usr/bin/env python3
"""
knowledge.py — what happened, who saw it, and who has heard of it since.

A FACT is what happened. A BELIEF is what one holder thinks happened: it has a holder, a claim (which
may be wrong), a source, when it was learned and how sure they are. Nobody knows a thing because the
GM knows it: a belief exists only for a witness, or for someone the news has reached.

Holders are written  npc:<Name>  faction:<Name>  place:<map key>  pc:<Name>.

  fact      id → {text, place, minute, witnesses}
  belief    "<holder>|<fact>" → {holder, fact, claim, source, learned_at, confidence, history}
  heat      "<area>|<faction>" → {level, evidence, question_at, warrant_at}

Engine actions (turn.py help <name>):
  fact       record what happened and who witnessed it
  news       send word of a fact to a holder by a channel (messenger, rumour, phone, radio)
  intercept  stop one piece of news on its way, or delay it
  belief     plant, distort or correct what a holder thinks
  knows      list what a holder actually knows, with sources
  heat       raise or lower a faction's attention in an area, on evidence it really holds

News needs a way to travel. A messenger or a rumour takes road time between the two places (a rumour
twice as long). Phone and radio take minutes, and exist only if the campaign's worldkit.json says so
under "communication": {"phone": true, "radio": true}. Each line of news is its own event: stopping
the rider does nothing to the radio.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import journey  # noqa: E402
import scheduler  # noqa: E402
import turn  # noqa: E402

CHANNELS = {"messenger": ("horse", 1.0), "rumour": ("foot", 2.0), "phone": (None, 5), "radio": (None, 5)}


def holder_id(ref: str, world=None) -> str:
    """Normalise a holder: 'faction:Tollmen' stays, a place name becomes 'place:<key>'."""
    ref = str(ref).strip()
    if ":" in ref:
        kind, name = ref.split(":", 1)
        if kind == "place" and world is not None:
            key = journey.place_key(world.json("world-map.json", {"places": {}}), name.strip())
            return f"place:{key or name.strip()}"
        return f"{kind.strip()}:{name.strip()}"
    return f"npc:{ref}"


def learn(world, holder: str, fact_id: str, claim: str, source: str, confidence: float = 1.0) -> dict:
    """`holder` now believes `claim` about the fact. An earlier belief is kept in its history."""
    key = f"{holder}|{fact_id}"
    old = world.get("belief", key)
    belief = {"holder": holder, "fact": fact_id, "claim": claim, "source": source,
              "learned_at": world.minute, "confidence": round(float(confidence), 2),
              "history": ((old or {}).get("history") or []) +
                         ([{k: old[k] for k in ("claim", "source", "learned_at", "confidence")}] if old else [])}
    world.put("belief", key, belief)
    return belief


def known_to(world, holder: str) -> list:
    """Everything this holder believes, newest first: the only ground a reaction of theirs can stand on."""
    prefix = f"{holder}|"
    rows = [b for key, b in world.all("belief").items() if key.startswith(prefix)]
    return sorted(rows, key=lambda b: -(b.get("learned_at") or 0))


def channel_open(world, channel: str) -> "str | None":
    """Why this channel cannot be used in this world, or None if it can."""
    if channel not in CHANNELS:
        return f"unknown channel {channel!r} (use {', '.join(CHANNELS)})"
    if CHANNELS[channel][0] is None:
        kit = world.json("worldkit.json")
        if not (kit.get("communication") or {}).get(channel):
            return f"this world has no {channel} (worldkit.json → communication)"
    return None


def travel_minutes(world, channel: str, src: str, dst: str) -> int:
    mode, factor = CHANNELS[channel]
    if mode is None:
        return int(factor)
    legs = journey.plan_route(world, dst, mode, from_key=src)
    return max(1, round(sum(leg["minutes"] for leg in legs) * factor))


@scheduler.effect("news_arrive")
def _news_arrive(world, row, eff):
    """Word reaches its holder: from now on they believe what they were told, as surely as the channel allows."""
    fact = world.get("fact", eff["fact"]) or {}
    belief = learn(world, eff["to"], eff["fact"], eff.get("claim") or fact.get("text", ""),
                   f"{eff['channel']}" + (f" ({eff['carrier']})" if eff.get("carrier") else ""), eff.get("confidence", 0.8))
    where = eff["to"].split(":", 1)[1] if eff["to"].startswith("place:") else None
    seen = "party" if where and world.json("world-map.json", {}).get("party_location") == where else "dm"
    return [{"type": "news_arrived", "recipient": seen, "holder": eff["to"], "fact": eff["fact"],
             "text": f"Word reaches {eff['to'].split(':', 1)[1]} by {eff['channel']}: {belief['claim']}"}]


def _world(ctx):
    return scheduler.World(ctx.campaign, ctx.db)


@turn.handler("fact")
def _fact(ctx, intent: dict) -> dict:
    """fact — record something that happened and who was there to perceive it.

    {"action": "fact", "id": "mill-fire", "text": "The mill burned; Mira was seen leaving.", "place": "Millbridge",
     "witnesses": ["npc:Bren", "faction:Tollmen"]}
    Witnesses (and the place itself, as common knowledge there) know it at once. Nobody else does until
    news of it reaches them (`news`)."""
    world = _world(ctx)
    fid = str(intent.get("id") or f"fact-{ctx.action_id}")
    place = journey.place_key(world.json("world-map.json", {"places": {}}), str(intent.get("place") or "")) or \
        world.json("world-map.json", {}).get("party_location")
    witnesses = [holder_id(w, world) for w in intent.get("witnesses") or []]
    if place and intent.get("public", True):
        witnesses.append(f"place:{place}")
    record = {"text": str(intent.get("text", "")), "place": place, "minute": world.minute, "witnesses": sorted(set(witnesses))}
    world.put("fact", fid, record)
    for w in record["witnesses"]:
        learn(world, w, fid, record["text"], "witness", 1.0)
    return {"status": "done", "elapsed_minutes": 0, "data": {"fact": fid, **record}}


@turn.handler("news")
def _news(ctx, intent: dict) -> dict:
    """news — send word of a fact to someone who was not there.

    {"action": "news", "fact": "mill-fire", "from": "Millbridge", "to": "place:Market", "channel": "messenger",
     "carrier": "a Tollmen rider", "claim": "<what they are told, if not the plain fact>", "confidence": 0.8}
    channel: messenger (road time on horseback) | rumour (twice the walking time) | phone | radio (minutes; only
    in a world whose kit has them). The reply gives the event id and when it lands; until then `to` knows nothing."""
    world = _world(ctx)
    channel, to = str(intent.get("channel", "messenger")), holder_id(intent.get("to", ""), world)
    if not world.get("fact", str(intent.get("fact"))):
        return {"status": "done", "elapsed_minutes": 0, "data": {"error": f"no fact {intent.get('fact')!r}: record it first"}}
    closed = channel_open(world, channel)
    if closed:
        return {"status": "done", "elapsed_minutes": 0, "data": {"sent": False, "error": closed}}
    data = world.json("world-map.json", {"places": {}})
    src = journey.place_key(data, str(intent.get("from") or "")) or data.get("party_location")
    dst = journey.place_key(data, str(intent.get("to_place") or (to.split(":", 1)[1] if to.startswith("place:") else "")))
    try:
        minutes = int(intent["minutes"]) if "minutes" in intent else travel_minutes(world, channel, src, dst or src)
    except (ValueError, KeyError) as exc:
        return {"status": "done", "elapsed_minutes": 0, "data": {"sent": False, "error": str(exc)}}
    event_id = f"news-{intent['fact']}-{to}-{channel}"
    scheduler.schedule(ctx.db, event_id, world.minute + minutes,
                       {"type": "news_arrive", "fact": intent["fact"], "to": to, "channel": channel,
                        "carrier": intent.get("carrier", ""), "claim": intent.get("claim", ""),
                        "confidence": intent.get("confidence", 0.8)},
                       cause_id=str(intent["fact"]), audience="dm")
    return {"status": "done", "elapsed_minutes": 0,
            "data": {"sent": True, "event_id": event_id, "arrives_minute": world.minute + minutes, "minutes": minutes}}


@turn.handler("intercept")
def _intercept(ctx, intent: dict) -> dict:
    """intercept — stop one line of news before it lands, or hold it up.

    {"action": "intercept", "event_id": "news-mill-fire-place:market-messenger", "reason": "the party caught the rider"}
    {"action": "intercept", "event_id": "…", "delay_minutes": 720, "reason": "the bridge was shut"}
    Only that line is touched: the same news sent another way still arrives."""
    row = ctx.db.execute("SELECT * FROM events WHERE event_id=?", (str(intent.get("event_id")),)).fetchone()
    if not row or row["status"] != "pending":
        return {"status": "done", "elapsed_minutes": 0,
                "data": {"stopped": False, "error": "no such news on its way" if not row else f"it has already {row['status']}"}}
    reason = str(intent.get("reason") or "intercepted")
    if intent.get("delay_minutes"):
        ctx.db.execute("UPDATE events SET due_minute = due_minute + ?, note=? WHERE event_id=?",
                       (int(intent["delay_minutes"]), f"delayed: {reason}", row["event_id"]))
        return {"status": "done", "elapsed_minutes": 0, "data": {"delayed": True, "event_id": row["event_id"],
                                                                 "arrives_minute": row["due_minute"] + int(intent["delay_minutes"])}}
    scheduler.cancel(ctx.db, row["event_id"], f"stopped: {reason}")
    return {"status": "done", "elapsed_minutes": 0, "data": {"stopped": True, "event_id": row["event_id"], "reason": reason}}


@turn.handler("belief")
def _belief(ctx, intent: dict) -> dict:
    """belief — what one holder thinks about a fact: plant a lie, pass on a distorted version, or set it right.

    {"action": "belief", "holder": "faction:Tollmen", "fact": "mill-fire", "claim": "The miller burned it himself.",
     "source": "a forged letter", "confidence": 0.6}
    The fact itself does not change. What they believed before stays in the belief's history."""
    world = _world(ctx)
    holder = holder_id(intent.get("holder", ""), world)
    belief = learn(world, holder, str(intent.get("fact")), str(intent.get("claim", "")),
                   str(intent.get("source", "told")), float(intent.get("confidence", 0.7)))
    return {"status": "done", "elapsed_minutes": 0, "data": belief}


@turn.handler("knows")
def _knows(ctx, intent: dict) -> dict:
    """knows — what a holder actually knows: {"action": "knows", "holder": "faction:Tollmen"}.

    Play that NPC or faction from this list and nothing else: it is everything they have seen or been told."""
    world = _world(ctx)
    holder = holder_id(intent.get("holder", ""), world)
    return {"status": "done", "elapsed_minutes": 0, "data": {"holder": holder, "beliefs": known_to(world, holder)}}


@turn.handler("heat")
def _heat(ctx, intent: dict) -> dict:
    """heat — how closely a faction is looking for the party in one area.

    {"action": "heat", "area": "Market", "faction": "Tollmen", "fact": "mill-fire", "delta": 1}
    Heat is local and belongs to one faction. It can only rise on a fact that faction has heard of: no belief,
    no heat. The reply says what they may now do: question people at `question_at` (default 2), seek an arrest
    at `warrant_at` (default 4) if what they hold is believed strongly enough."""
    world = _world(ctx)
    area = journey.place_key(world.json("world-map.json", {"places": {}}), str(intent.get("area", ""))) or str(intent.get("area", ""))
    faction = str(intent.get("faction", ""))
    key, delta = f"{area}|{faction}", int(intent.get("delta", 1))
    heat = world.get("heat", key) or {"level": 0, "evidence": [], "question_at": 2, "warrant_at": 4}
    for field in ("question_at", "warrant_at"):
        if field in intent:
            heat[field] = int(intent[field])
    fact = intent.get("fact")
    if delta > 0:
        belief = world.get("belief", f"faction:{faction}|{fact}") if fact else None
        if not belief:
            return {"status": "done", "elapsed_minutes": 0,
                    "data": {"changed": False, "level": heat["level"],
                             "error": f"{faction} has not heard of {fact!r}: nothing for their attention to rise on"}}
        if fact not in heat["evidence"]:
            heat["evidence"].append(fact)
    heat["level"] = max(0, min(5, heat["level"] + delta))
    strongest = max((world.get("belief", f"faction:{faction}|{f}") or {}).get("confidence", 0) for f in heat["evidence"]) \
        if heat["evidence"] else 0
    heat["may_question"] = heat["level"] >= heat["question_at"] and bool(heat["evidence"])
    heat["may_seek_arrest"] = heat["level"] >= heat["warrant_at"] and strongest >= 0.6
    world.put("heat", key, heat)
    if paths_flag(ctx, "heat_entropy") == "on" and delta:
        entropy = world.json("entropy.json")
        if isinstance(entropy, dict) and "value" in entropy:
            entropy["value"] = max(0, min(100, int(entropy["value"]) + 5 * delta))
            world.touch("entropy.json")
    return {"status": "done", "elapsed_minutes": 0, "writes": world.writes(), "data": {"changed": True, "area": area, "faction": faction, **heat}}


def paths_flag(ctx, key: str) -> str:
    return ctx.flag(key, "off")
