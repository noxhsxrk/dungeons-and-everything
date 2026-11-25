#!/usr/bin/env python3
"""
table.py — the people at the table: who has had the spotlight, what each of them alone has learned,
and the small things they gave meaning to that the story can give back.

  spotlight  "<PC>"  → {last_turn, count, last_what}
  group      "<id>"  → {goal, members: {PC: what they do}, lead}
  case       "<id>"  → {truth, clues: [{id, text, where, obvious, detail}], hypotheses, accusations}
  thread     "<id>"  → {owner, kind, text, about, knows, tone, payoff, used, status}

Engine actions (turn.py help <name>):
  group     several characters act together: who does what (waits for anyone who has not said)
  case      set up a mystery: what is true, and the clues that exist and where
  search    a character looks somewhere: what is plainly there is found, and told to that player alone
  tell      a character shares what they know with others
  accuse    the party names a culprit or a theory: recorded, never made true by being said
  notice    what each character's own expertise shows them in a scene, each on their own phone
  remember  keep a detail a player gave meaning to: a promise, a gift, an in-joke, a habit, a personal goal
  payoff    mark that a remembered thing came back into the story

SPOTLIGHT is advice, never a rule: after a few turns the GM is told who has not driven a decision.
A CLUE that is plainly there is found by looking in the right place; a roll changes how long it takes
and how much more is noticed, not whether the scene can go on. What a search turns up goes to the
searching player only: telling the others is their choice.
A THREAD comes back as an opening when its person, place or time is in the scene. It is offered,
never forced: the player may pick it up or leave it, and it stays open if they leave it. Some threads
are marked warm: they return as a kindness and are not clues.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gm_guide  # noqa: E402
import journey  # noqa: E402
import knowledge  # noqa: E402
import paths  # noqa: E402
import scheduler  # noqa: E402
import turn  # noqa: E402
import world_db as wdb  # noqa: E402

QUIET_AFTER = 4          # turns without driving anything before the GM is nudged
KINDS = ("bond", "promise", "goal", "detail", "joke", "gift", "habit")


def _world(ctx):
    return scheduler.World(ctx.campaign, ctx.db)


def pcs(campaign: str) -> dict:
    """{name: one-line background} for every player character sheet."""
    out = {}
    folder = paths.find_campaign(campaign) / "characters"
    for sheet in sorted(folder.glob("*.md")) if folder.is_dir() else []:
        text = sheet.read_text(encoding="utf-8", errors="replace")
        name = text.splitlines()[0].lstrip("# ").strip() if text.strip() else sheet.stem
        bits = [m.group(1).strip() for key in ("Class", "Background", "Race")
                if (m := re.search(rf"\*\*{key}:\*\*\s*([^|\n]+)", text))]
        out[name or sheet.stem] = ", ".join(bits)
    return out


def _turn_seq(db) -> int:
    return int(wdb.meta(db, "turn_seq", "0"))


# ── spotlight ─────────────────────────────────────────────────────────────────

def _acted(ctx, intent: dict, out: dict) -> None:
    """Every action a PC drives counts as their moment (the runner calls this after each action)."""
    if intent.get("action") in ("ask", "scene", "where", "knows", "market", "faction_brief"):
        return
    names = {n.casefold(): n for n in pcs(ctx.campaign)}
    actors = [intent.get("actor")] + list((intent.get("members") or {}).keys())
    for who in actors:
        key = str(who or "").casefold()
        if key in names:
            rec = wdb.get(ctx.db, "spotlight", names[key]) or {"count": 0}
            rec.update(last_turn=_turn_seq(ctx.db), count=rec.get("count", 0) + 1,
                       last_what=str(intent.get("plan") or intent.get("what") or intent.get("action")))
            wdb.put(ctx.db, "spotlight", names[key], rec)


turn.AFTER_ACTION.append(_acted)


def quiet(campaign: str, db) -> list:
    """[(PC, turns since they last drove something)] for those past QUIET_AFTER, quietest first."""
    now = _turn_seq(db)
    seen = wdb.all_of(db, "spotlight")
    if not seen:                                  # nobody has acted through the engine yet: nothing to compare
        return []
    gaps = [(name, now - int((seen.get(name) or {}).get("last_turn", 0))) for name in pcs(campaign)]
    return sorted([g for g in gaps if g[1] >= QUIET_AFTER], key=lambda g: -g[1])


@turn.handler("group")
def _group(ctx, intent: dict) -> dict:
    """group — several characters act on one thing together. Say who does what before it is resolved.

    {"action": "group", "id": "hold-the-gate", "goal": "keep the gate open", "lead": "Mira",
     "members": {"Mira": "jams the gate with a crowbar", "Theo": ""}}
    Anyone listed with nothing to do is asked, and the turn waits for their answer: nobody is carried along. Then
    resolve the lead's `judge` or `roll`; every member has had their say and gets the spotlight for it."""
    world = _world(ctx)
    gid = str(intent.get("id") or f"group-{ctx.action_id}")
    record = world.get("group", gid) or {"goal": str(intent.get("goal", "")), "lead": intent.get("lead"), "members": {}}
    record["members"].update({k: v for k, v in (intent.get("members") or {}).items() if v or k not in record["members"]})
    for name in list(record["members"]):
        if f"what-{name}" in ctx.answers:
            record["members"][name] = str(ctx.answers[f"what-{name}"]["value"])
    world.put("group", gid, record)
    silent = [n for n, what in record["members"].items() if not str(what).strip()]
    if silent:
        return {"status": "waiting_for_player",
                "requests": [{"key": f"what-{silent[0]}", "kind": "decision", "expected": silent[0],
                              "text": f"{silent[0]}: the others are working to {record['goal']}. What do you do?"}],
                "data": {"group": gid, **record}}
    return {"status": "done", "elapsed_minutes": 0, "data": {"group": gid, **record, "ready": True}}


# ── cases ─────────────────────────────────────────────────────────────────────

@turn.handler("case")
def _case(ctx, intent: dict) -> dict:
    """case — a mystery: what is true, and the evidence that exists.

    {"action": "case", "id": "missing-ledger", "truth": "The clerk hid the ledger to protect his daughter.",
     "clues": [{"id": "ash", "text": "Fresh ash in a cold grate.", "where": "clerk's office", "obvious": true,
                "detail": "A corner of ledger paper survives."},
               {"id": "key", "text": "The strongbox key is worn on one side.", "where": "counting room", "obvious": false}]}
    The truth does not change with what the party comes to believe. An `obvious` clue is found by anyone who looks
    in that place; the rest need a roll. `detail` is the extra a good roll adds."""
    world = _world(ctx)
    cid = str(intent.get("id") or f"case-{ctx.action_id}")
    record = world.get("case", cid) or {"truth": "", "clues": [], "hypotheses": [], "accusations": []}
    if "truth" in intent:
        record["truth"] = str(intent["truth"])
    have = {c["id"]: c for c in record["clues"]}
    for clue in intent.get("clues") or []:
        have[str(clue.get("id"))] = {**have.get(str(clue.get("id")), {"found_by": []}), **clue}
    record["clues"] = list(have.values())
    world.put("case", cid, record)
    return {"status": "done", "elapsed_minutes": 0, "data": {"case": cid, "clues": len(record["clues"])}}


@turn.handler("search")
def _search(ctx, intent: dict) -> dict:
    """search — a character looks for evidence in one place.

    {"actor": "Theo", "action": "search", "case": "missing-ledger", "where": "clerk's office", "minutes": 10,
     "roll": {"spec": "1d20+3", "dc": 13, "label": "Investigation"}}
    What is plainly there is found without a roll. The roll, if you ask for one, decides how long it takes (a failure
    takes twice as long) and whether the finer `detail` and the hidden clues turn up. Everything found is sent to that
    player alone and recorded as known to that character: sharing it is their decision (`tell`).
    Braid (System: core): "roll": {"spec": "2d6+1"}, no DC; 7 or more helps. Story mode: the oracle answers."""
    import resolve as checks
    world = _world(ctx)
    actor, where = str(intent.get("actor") or "Party"), str(intent.get("where", "")).casefold()
    case = world.get("case", str(intent.get("case", "")))
    if not case:
        return {"status": "done", "elapsed_minutes": 0, "data": {"error": f"no case {intent.get('case')!r}"}}
    roll, good = intent.get("roll"), None
    if roll:
        system = paths.campaign_system(ctx.campaign)
        err = checks.spec_error(system, roll.get("spec"))
        if err:
            return {"status": "done", "elapsed_minutes": 0, "data": {"error": err}}
        num, sides, mod = checks.dice_for(system, roll.get("spec"))
        if system != "story" and ctx.flag("roll_mode", "players") == "players" and "roll" not in ctx.answers:
            asked = roll.get("spec", "1d20") if system == "d20" else checks.shown(system, roll.get("spec"))
            return {"status": "waiting_for_player",
                    "requests": [{"key": "roll", "kind": "roll", "expected": actor,
                                  "text": f"{actor}: roll {roll.get('label') or 'to search'} — {asked}"}]}
        got = [int(ctx.answers["roll"]["value"])] if "roll" in ctx.answers else ctx.roll("roll", sides, num)
        good = checks.resolve(system, roll.get("spec"), int(roll.get("dc", 10)), got[:1] if system == "d20" else got,
                              likelihood=str(roll.get("likelihood") or "50/50"), chaos=checks.chaos(ctx.campaign))["passed"]
    minutes = int(intent.get("minutes", 10)) * (2 if good is False else 1)
    passed = scheduler.advance(world, (world.minute or 0) + minutes) if world.minute is not None else {"elapsed_minutes": 0, "visible_events": []}
    found = []
    for clue in case["clues"]:
        if str(clue.get("where", "")).casefold() != where:
            continue
        if clue.get("obvious", True) or good:
            text = clue["text"] + (f" {clue['detail']}" if good and clue.get("detail") else "")
            found.append({"id": clue["id"], "text": text})
            if actor not in clue.setdefault("found_by", []):
                clue["found_by"].append(actor)
            knowledge.learn(world, f"pc:{actor}", f"clue:{clue['id']}", text, f"searched {intent.get('where')}", 1.0)
    world.put("case", str(intent["case"]), case)
    told = "\n".join(f"- {f['text']}" for f in found) or "Nothing here that bears on it."
    return {"status": "done", "elapsed_minutes": passed["elapsed_minutes"], "writes": world.writes(),
            "visible_events": passed["visible_events"],
            "messages": [{"to": actor, "text": f"Only you notice, searching {intent.get('where')}:\n{told}"}],
            "data": {"actor": actor, "found": found, "took_minutes": minutes, "roll_helped": good}}


@turn.handler("tell")
def _tell(ctx, intent: dict) -> dict:
    """tell — a character passes on something they know: {"actor": "Theo", "action": "tell", "to": ["Mira"], "clue": "ash"}.

    Only what the teller actually knows can be told. Those told now know it too, with the teller as the source."""
    world = _world(ctx)
    actor, fact = str(intent.get("actor", "")), f"clue:{intent.get('clue')}" if intent.get("clue") else str(intent.get("fact", ""))
    mine = world.get("belief", f"pc:{actor}|{fact}")
    if not mine:
        return {"status": "done", "elapsed_minutes": 0, "data": {"told": [], "error": f"{actor} does not know that"}}
    told = []
    for other in intent.get("to") or []:
        knowledge.learn(world, knowledge.holder_id(other if ":" in str(other) else f"pc:{other}", world), fact,
                        mine["claim"], f"told by {actor}", 0.9)
        told.append(other)
    return {"status": "done", "elapsed_minutes": 0, "data": {"teller": actor, "told": told, "what": mine["claim"]}}


@turn.handler("accuse")
def _accuse(ctx, intent: dict) -> dict:
    """accuse — the party's theory or accusation, right or wrong.

    {"actor": "Mira", "action": "accuse", "case": "missing-ledger", "claim": "The toll captain stole it.", "public": true}
    It is written down as what they said. It does not change what is true, and the reply to the players never says
    whether it is right: the world answers through what happens next."""
    world = _world(ctx)
    case = world.get("case", str(intent.get("case", "")))
    if not case:
        return {"status": "done", "elapsed_minutes": 0, "data": {"error": f"no case {intent.get('case')!r}"}}
    entry = {"by": str(intent.get("actor", "Party")), "claim": str(intent.get("claim", "")), "minute": world.minute}
    case["accusations" if intent.get("public", True) else "hypotheses"].append(entry)
    world.put("case", str(intent["case"]), case)
    return {"status": "done", "elapsed_minutes": 0,
            "data": {"recorded": entry, "truth_for_the_gm": case["truth"],
                     "note": "The truth stands. Play the consequences of what they claimed, from who heard it."}}


@turn.handler("notice")
def _notice(ctx, intent: dict) -> dict:
    """notice — the same scene through each character's own eyes.

    {"action": "notice", "scene": "the room that is too clean",
     "details": {"Mira": "The vent cover's screws were turned lately: the paint round them is cracked.",
                 "Theo": "The bed was made from the door side. Whoever did it had never done this room."}}
    One true detail per character, drawn from their trade, their past or who they know. Each goes to that player's
    phone only. Do not explain what the details mean together: let the players put them side by side."""
    world = _world(ctx)
    messages = []
    for who, text in (intent.get("details") or {}).items():
        messages.append({"to": who, "text": f"Only you would see this: {text}"})
        knowledge.learn(world, f"pc:{who}", f"notice:{ctx.action_id}:{who}", str(text), f"noticed ({intent.get('scene', '')})", 1.0)
    return {"status": "done", "elapsed_minutes": 0, "messages": messages,
            "data": {"scene": intent.get("scene"), "told": sorted((intent.get("details") or {}).keys())}}


# ── threads: what the players gave meaning to ─────────────────────────────────

@turn.handler("remember")
def _remember(ctx, intent: dict) -> dict:
    """remember — keep something a player gave meaning to, so the story can give it back.

    {"action": "remember", "id": "two-taps", "owner": "Mira", "kind": "habit", "tone": "warm",
     "text": "Her father taps the relay cover twice before he switches it on.",
     "about": ["father", "relay", "station"], "knows": ["Mira", "Theo"],
     "payoff": {"place": "Market", "person": "Bren", "after_minutes": 10080}}
    kind: bond | promise | goal | detail | joke | gift | habit. tone: warm (returns as a kindness, never a clue) |
    clue | either. `about` are the people, places and things that should bring it to mind; `payoff` (optional) is
    where, with whom or how much later it is best brought back. Record these at the end of a scene, for details the
    player invented or cared about."""
    world = _world(ctx)
    tid = str(intent.get("id") or f"thread-{ctx.action_id}")
    payoff = dict(intent.get("payoff") or {})
    if "after_minutes" in payoff:
        payoff["after_minute"] = (world.minute or 0) + int(payoff.pop("after_minutes"))
    if payoff.get("place"):
        payoff["place"] = journey.place_key(world.json("world-map.json", {"places": {}}), str(payoff["place"])) or payoff["place"]
    record = {"owner": str(intent.get("owner", "")), "kind": str(intent.get("kind", "detail")), "text": str(intent.get("text", "")),
              "about": [str(a) for a in intent.get("about") or []], "knows": [str(k) for k in intent.get("knows") or []],
              "tone": str(intent.get("tone", "either")), "payoff": payoff, "used": 0, "status": "open",
              "minute": world.minute, "turn": _turn_seq(ctx.db)}
    world.put("thread", tid, record)
    return {"status": "done", "elapsed_minutes": 0, "data": {"thread": tid, **record}}


@turn.handler("payoff")
def _payoff(ctx, intent: dict) -> dict:
    """payoff — a remembered thing came back: {"action": "payoff", "id": "two-taps", "note": "the knock on the relay", "close": false}.

    Counts the use (so it is not worn out by returning every scene). `close` ends the thread: the promise was kept,
    the goal reached."""
    world = _world(ctx)
    record = world.get("thread", str(intent.get("id", "")))
    if not record:
        return {"status": "done", "elapsed_minutes": 0, "data": {"error": f"no thread {intent.get('id')!r}"}}
    record["used"] = int(record.get("used", 0)) + 1
    record["last_used_turn"] = _turn_seq(ctx.db)
    record.setdefault("uses", []).append({"minute": world.minute, "note": str(intent.get("note", ""))})
    if intent.get("close"):
        record["status"] = "paid"
    world.put("thread", str(intent["id"]), record)
    return {"status": "done", "elapsed_minutes": 0, "data": {"thread": intent["id"], **record}}


def openings(campaign: str, db, text: str = "") -> list:
    """Threads that fit this moment: their person, place or thing is in the scene, or their time has come.

    Returns [(id, record, why)], best first. One that was used in the last few turns is left to rest."""
    try:
        import scene_context
        here = scene_context.scene(campaign)
    except Exception:
        here = {}
    world = scheduler.World(campaign, db)
    place = world.json("world-map.json", {}).get("party_location")
    hay = " ".join([text, str(here.get("place") or ""), " ".join(here.get("present") or [])]).casefold()
    now, minute, out = _turn_seq(db), world.minute or 0, []
    for tid, t in sorted(wdb.all_of(db, "thread").items()):
        if t.get("status") != "open" or now - int(t.get("last_used_turn", -99)) < 6:
            continue
        pay, why = t.get("payoff") or {}, []
        if pay.get("place") and pay["place"] in (place, here.get("place")):
            why.append("you are where it belongs")
        if pay.get("person") and str(pay["person"]).casefold() in hay:
            why.append(f"{pay['person']} is here")
        hits = [a for a in t.get("about") or [] if len(a) >= 3 and a.casefold() in hay]
        if hits:
            why.append("the scene touches " + ", ".join(hits[:3]))
        if pay.get("after_minute") is not None and minute >= pay["after_minute"] and (why or not (pay.get("place") or pay.get("person"))):
            why.append("enough time has passed")
        if why:
            out.append((tid, t, "; ".join(why)))
    return sorted(out, key=lambda r: (r[1].get("used", 0), -len(r[2])))


def _provider(campaign: str, text: str, turn_view) -> list:
    """Lines for the GM note: a callback that fits, who has been quiet, whose expertise could show something."""
    if not wdb.enabled(campaign):
        return []
    parts = []
    with wdb.reader(campaign) as db:
        if db is None:
            return []
        for tid, t, why in openings(campaign, db, text)[:1]:
            tone = {"warm": "a kindness, not a clue", "clue": "it can matter to the plot"}.get(t.get("tone"), "warm or meaningful, as fits")
            parts.append((gm_guide.SCENE,
                          f"SOMETHING OF {t['owner'].upper() or 'THE TABLE'}'S CAN COME BACK ({t['kind']}, {tone}; {why}): "
                          f"\"{t['text']}\" If it fits, show it in one plain line and stop: do not explain it, let the player "
                          f"recognise it. It is an opening, not a quest: if they pass, it stays for another day. "
                          f"Used: `payoff` id {tid}."))
        shy = quiet(campaign, db)
        if shy:
            name, gap = shy[0]
            parts.append((gm_guide.NUDGE, f"SPOTLIGHT: {name} has not driven anything for {gap} turns. Give {name} the next "
                                          "opening: a question put to them, or something only they are placed to do or see."))
    return parts


gm_guide.PROVIDERS.append(_provider)
