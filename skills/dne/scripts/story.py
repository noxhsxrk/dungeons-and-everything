#!/usr/bin/env python3
"""
story.py — keeping the telling fresh: sparks, pacing, a guard against the GM's own habits, and a few
scene tools. Works for every campaign; only the last block of actions needs the world engine.

    story.py -c <campaign> guard          # what the last narrations repeat, and where they said too much
    story.py -c <campaign> spark          # one creative prompt for this scene (the GM may throw it away)
    story.py -c <campaign> campfire       # a question for the players at a rest, from their own Bonds and Flaws
    story.py -c <campaign> tone <tone>    # note the tone of the scene just told (send.py --tone does this)

What the GM is told with each player action (through gm_guide):
  STYLE     repeated openings and phrases, every turn ending on a question, the PC's feelings narrated
            for them, a line past the moment to stop, a phrase the world's `narrative_dna` bans.
  NPC       when the input names an NPC with a record: what they want from the person in front of them.
  SPARK     now and then, one prompt: two oracle words, a camera move, a question to hand a player, a
            bargain to offer, a strange rule for the place. It is an offer. If the scene already has its
            most interesting thing in front of it, the GM drops it.
  PACING    when three scenes running had the same tone, a different one is suggested.

Dials (Session Flags): `sparks: on|off`, `style_guard: on|off`, `storyteller: none|pulp|noir|banter|dread`.
World kit: "narrative_dna": {"sensory_palette": [...], "humor_style": "...", "conflict_flavor": "...",
"taboo_cliches": ["the smell of ozone", ...]}.

Engine actions (world_engine: on): flashback, bargain, place_rule, clock.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gm_guide  # noqa: E402
import paths  # noqa: E402

sys.modules.setdefault("story", sys.modules[__name__])

TONES = ("tension", "combat", "relief", "humor", "wonder", "moral", "quiet", "mystery")
NEXT_TONE = {"tension": "relief or humour", "combat": "a quiet moment between characters", "relief": "wonder or a mystery",
             "humor": "a moral choice", "wonder": "tension", "moral": "action on a big stage", "quiet": "tension or a mystery",
             "mystery": "action or a quiet moment"}
STORYTELLERS = {
    "pulp": "Pulp action: fast, big set pieces, cliffhangers; cut the talk short when a chase could start.",
    "noir": "Noir mystery: clipped dialogue, everyone holds something back, each answer opens a second question.",
    "banter": "Ensemble banter: let characters talk over the plot; give NPCs wit and the players room to riff.",
    "dread": "Creeping dread: small wrong details, long quiet, never the whole monster; explain nothing in full.",
}
#: Telling a player what their character feels or concludes: the player's job, not the narrator's.
TOLD_FEELINGS = ("คุณรู้สึก", "หัวใจคุณ", "หัวใจของคุณ", "คุณตระหนัก", "คุณเข้าใจแล้วว่า", "ความหวัง", "คุณอดไม่ได้ที่จะ",
                 "you feel ", "your heart ", "you realize", "you realise", "you can't help but", "a sense of ", "you know that ")
#: Handing the player their choices at the end of a turn (fine when the table set turn_end: options).
ASKS = ("คุณจะทำอย่างไร", "คุณจะทำอะไร", "จะทำอะไรต่อ", "คุณจะ", "หรือไม่?", "what do you do", "what will you do", "do you ")
OPENERS = {"a smell": ("กลิ่น", "smell", "scent", "odor", "stench"), "silence": ("ความเงียบ", "เงียบ", "silence", "quiet "),
           "the weather or light": ("แสง", "ฝน", "ลม", "the light", "rain", "wind"), "a sound": ("เสียง", "sound of", "a noise")}


# ── state: a few numbers per campaign, in the runtime folder ──────────────────

def _state_path(campaign: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in campaign)
    return paths.runtime_dir() / f"story-{safe}.json"


def load(campaign: str) -> dict:
    try:
        data = json.loads(_state_path(campaign).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save(campaign: str, data: dict) -> None:
    try:
        _state_path(campaign).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def note_tone(campaign: str, tone: str) -> list:
    """Record the tone of the scene just narrated. Returns the recent tones."""
    st = load(campaign)
    st["tones"] = (st.get("tones") or [])[-9:] + [tone]
    save(campaign, st)
    return st["tones"]


def narrations(campaign: str, n: int = 8) -> list:
    """The GM's last narrations from the display feed (player lines, dice and awards left out)."""
    try:
        log = json.loads((paths.runtime_dir() / "text_log.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out = [str(e["text"]).strip() for e in log if isinstance(e, dict) and e.get("text")
           and not any(e.get(k) for k in ("player", "dice", "xp_award", "tutor", "action", "whisper"))
           and e.get("_camp", campaign) == campaign]
    return [t for t in out if len(t) > 20][-n:]


# ── style guard ───────────────────────────────────────────────────────────────

def _sentences(text: str) -> list:
    return [s.strip() for s in re.split(r"(?<=[.!?。！？])\s+|\n+", text) if s.strip()]


REPEATED_IN = 4      # of the last eight narrations: fewer is how any scene talks about its own subject
THAI_MIN = 12        # characters: shorter runs are mostly nouns (a vehicle, a rank and a name), not turns of phrase


def _repeats(texts: list, names: set, said_by_players: str = "") -> list:
    """Wordings that turn up in REPEATED_IN or more of the narrations: word trigrams, and for scripts written
    without spaces the longest run of characters (twelve or more) that the narrations share. Names, and anything the
    players themselves have been saying (the scene's own subject), are left out."""
    lows = [t.casefold() for t in texts]
    inside = lambda phrase: sum(1 for t in lows if phrase in t)  # noqa: E731
    found = []
    seen: dict = {}
    for i, low in enumerate(lows):
        words = re.findall(r"[a-z']{3,}", low)
        for j in range(len(words) - 2):
            seen.setdefault(" ".join(words[j:j + 3]), set()).add(i)
    found += [g for g, where in seen.items() if len(where) >= REPEATED_IN]
    for low in lows:
        for run in re.findall(r"[\u0e00-\u0e7f]{%d,}" % THAI_MIN, low):
            j = 0
            while j <= len(run) - THAI_MIN:
                if inside(run[j:j + THAI_MIN]) < REPEATED_IN:
                    j += 1
                    continue
                k = j + THAI_MIN
                while k < len(run) and k - j < 40 and inside(run[j:k + 1]) >= REPEATED_IN:
                    k += 1
                found.append(run[j:k])
                j = k
    out = []
    for g in sorted(set(found), key=lambda g: (-len(g), g)):      # the longest wording of each habit, once
        if any(n and n in g for n in names) or any(g in kept or kept in g for kept in out):
            continue
        if said_by_players and (g in said_by_players or g[:7] in said_by_players):
            continue                              # the players brought it up: it is what the scene is about
        out.append(g)
    return out[:2]


def guard(campaign: str) -> list:
    """Short, concrete notes on the GM's recent narration. Empty when there is nothing to say."""
    texts = narrations(campaign)
    if not texts:
        return []
    notes, last, recent = [], texts[-1], texts[-4:]
    low_last = last.casefold()
    told = next((p for p in TOLD_FEELINGS if p in low_last), None)
    if told:
        notes.append(f"the last narration told the player what their character feels (\"{told.strip()}\"): show what is there "
                     "and let them supply the feeling")
    turn_end = paths.session_flag(campaign, "turn_end", "open")
    tail = _sentences(last)[-1].casefold() if _sentences(last) else ""
    if turn_end != "options" and (tail.endswith("?") or re.search(r"^\s*[1-3][.)]", tail)) and any(a in tail for a in ASKS):
        notes.append("the last narration ended by asking what they do (the table plays `turn_end: open`): end on the image "
                     "or the line that was said, and stop")
    if len(recent) >= 3:
        for kind, words in OPENERS.items():
            if sum(1 for t in recent if any(w in (_sentences(t)[0] if _sentences(t) else "").casefold()[:60] for w in words)) >= 3:
                notes.append(f"three recent narrations opened with {kind}: open this one with movement, a spoken line or something touched")
                break
        if turn_end != "options" and sum(1 for t in recent if t.rstrip().endswith(("?", "？"))) >= 3 and not any("asking what" in n for n in notes):
            notes.append("the last turns all ended on a question: let one end on a plain fact")
    names = _names(campaign)
    phrases = _repeats(texts, names, _player_words(campaign))
    if phrases:
        notes.append(f"wording that came back in {REPEATED_IN} or more of your last {len(texts)} narrations: "
                     + ", ".join(f"\"{p}\"" for p in phrases) + ". If that is habit and not the scene's own subject, vary it")
    dna = _dna(campaign)
    banned = [c for c in dna.get("taboo_cliches") or [] if any(str(c).casefold() in t.casefold() for t in texts[-3:])]
    if banned:
        notes.append("this world's own list of clichés to avoid turned up: " + ", ".join(f"\"{b}\"" for b in banned[:3]))
    return notes[:3]


def _names(campaign: str) -> set:
    """Every name the story uses, lower-cased: a name repeating is not a habit of style."""
    names = set()
    try:
        import npc
        camp = paths.find_campaign(campaign)
        full = npc.entries(camp)
        for n in dict.fromkeys(npc.index_names(camp) + list(full)):
            names |= {a.casefold() for a in npc.aliases(n, full.get(n))}
        for folder in ("characters", "companions"):
            for sheet in (camp / folder).glob("*.md") if (camp / folder).is_dir() else []:
                text = sheet.read_text(encoding="utf-8", errors="replace")
                title = text.splitlines()[0].lstrip("# ").strip() if text.strip() else sheet.stem
                names |= {title.casefold(), sheet.stem.casefold(), title.split()[0].casefold() if title else ""}
    except Exception:
        pass
    return {n for n in names if len(n) >= 2}


def _player_words(campaign: str) -> str:
    """What the players have typed lately, lower-cased, to tell the scene's subject from the GM's habits."""
    try:
        log = json.loads((paths.runtime_dir() / "text_log.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return " ".join(str(e.get("text", "")) for e in log[-40:] if isinstance(e, dict) and e.get("player")).casefold()


def _dna(campaign: str) -> dict:
    try:
        kit = json.loads((paths.find_campaign(campaign) / "worldkit.json").read_text(encoding="utf-8"))
        return kit.get("narrative_dna") or {}
    except (OSError, ValueError):
        return {}


# ── NPCs who want something ───────────────────────────────────────────────────

def npc_wants(campaign: str, text: str) -> list:
    """For NPCs the input names: what is on record about what they want, and the two questions to answer."""
    try:
        import npc
        camp = paths.find_campaign(campaign)
        full = npc.entries(camp)
    except Exception:
        return []
    low = re.sub(r"^\s*\[[^\]]+\]\s*:", "", text, flags=re.M).casefold()
    out = []
    for name, entry in full.items():
        if not any(a.casefold() in low for a in npc.aliases(name, entry)):
            continue
        field = lambda key: (m.group(1).strip() if (m := re.search(rf"\*\*{key}:\*\*\s*([^|\n]+)", entry)) else "")  # noqa: E731
        goal, why = field("Current goal"), field("Motivation")
        known = "; ".join(p for p in (f"goal: {goal}" if goal and not goal.startswith("<") else "",
                                      f"drive: {why}" if why and not why.startswith("<") else "") if p)
        out.append(f"{name} is in this ({known or 'no goal on record yet'}). Before they speak, decide: what does {name} want "
                   "from the person in front of them right now, and what would they give up to get it? Let that shape how "
                   "they answer, and let it change mid-scene if a player touches what they care about.")
    return out[:2]


# ── sparks and pacing ─────────────────────────────────────────────────────────

def spark(campaign: str, n: int) -> str:
    """One creative prompt, chosen by the turn number so it can be reproduced."""
    import oracle
    rng = random.Random(f"{campaign}:{n}")
    kind = ("meaning", "camera", "paint", "bargain", "rule", "meaning", "expertise")[rng.randrange(7)]
    if kind == "meaning":
        verb, noun = oracle.scene_meaning(rng)
        extra = ""
        try:
            import tags
            picked = tags.roll(campaign, 1, rng)
            if picked:
                extra = f" (or the place tag: {tags.fmt(picked[0], rng)})"
        except Exception:
            pass
        body = f"weave \"{verb} / {noun}\" into this scene{extra}"
    elif kind == "camera":
        body = rng.choice((
            "end the scene, then cut away for two or three sentences to someone elsewhere whom the characters cannot see "
            "(a rival, a faction, the thing that is coming)",
            "tell the next stretch of travel, searching or training as a montage of three short shots, and hand one shot "
            "to a player to tell",
            "slow one moment right down: a single action, beat by beat, then let time snap back"))
    elif kind == "paint":
        body = ("ask one player to paint the scene: one odd thing in this place that makes their character stop. Keep "
                "what they say as true (the engine's `remember`, or the lorebook) and use it later")
    elif kind == "bargain":
        body = ("before the next risky roll, offer a devil's bargain: advantage on the roll, and a named thing goes wrong "
                "whatever the dice say (a witness remembers their face, the magazine runs dry)")
    elif kind == "rule":
        body = ("give this place one strange rule the players can test (things return to where they were a minute ago; "
                "the lift always answers the floor that called first). Show it once, decide the edge cases as they try "
                "them, then keep to it")
    else:
        who = _backgrounds(campaign)
        body = ("show each character the detail their own trade or past would catch here and send it to that player "
                f"alone ({who}); do not say what the details add up to" if who else
                "show one character a detail only their trade or past would catch")
    return (f"SPARK (an offer, not an order): {body}. If the scene already has its most interesting thing in front of it, "
            "drop this and follow that.")


def _backgrounds(campaign: str) -> str:
    out = []
    folder = paths.find_campaign(campaign) / "characters"
    for sheet in sorted(folder.glob("*.md")) if folder.is_dir() else []:
        text = sheet.read_text(encoding="utf-8", errors="replace")
        name = text.splitlines()[0].lstrip("# ").strip() if text.strip() else sheet.stem
        bits = [m.group(1).strip() for key in ("Class", "Background") if (m := re.search(rf"\*\*{key}:\*\*\s*([^|\n]+)", text))]
        if bits:
            out.append(f"{name}: {', '.join(bits)}")
    return "; ".join(out[:5])


def pacing(campaign: str) -> "str | None":
    tones = load(campaign).get("tones") or []
    if len(tones) >= 3 and len(set(tones[-3:])) == 1:
        return (f"PACING: the last three scenes were all {tones[-1]}. Make the next one {NEXT_TONE.get(tones[-1], 'something else')}: "
                "a table that is tense all the time stops feeling it.")
    return None


def campfire(campaign: str, rng: "random.Random | None" = None) -> "str | None":
    """A question to put to one player at a rest, built from a line of their own Bonds or Flaws & Quirks."""
    rng = rng or random.Random()
    pool = []
    folder = paths.find_campaign(campaign) / "characters"
    for sheet in sorted(folder.glob("*.md")) if folder.is_dir() else []:
        text = sheet.read_text(encoding="utf-8", errors="replace")
        name = text.splitlines()[0].lstrip("# ").strip() if text.strip() else sheet.stem
        for title in ("Bonds", "Flaws & Quirks", "Flaws", "Ideals"):
            m = re.search(rf"^## {re.escape(title)}[^\n]*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
            for line in (m.group(1).splitlines() if m else []):
                line = line.strip().lstrip("-* ").strip()
                if len(line) > 8 and not line.startswith(("<", "*(")):
                    pool.append((name, title, line))
    if not pool:
        return None
    name, title, line = rng.choice(pool)
    frame = rng.choice(("While the others settle, {name}: tonight something reminds you of this — \"{line}\". What does the "
                        "party see you do?",
                        "{name}, on watch: \"{line}\". Who among the others has noticed, and what did they see?",
                        "{name}: someone asks you, quietly, about this — \"{line}\". What do you tell them, and what do you leave out?"))
    return frame.format(name=name, line=line)


def tool_tip(campaign: str, n: int) -> "str | None":
    """Every fourth turn, one of the table's storytelling tools with the exact command: a GM that reads little of
    the docs meets them here."""
    if n % 4:
        return None
    display, scripts = HERE.parent / "display", HERE
    tips = (
        f"Tag the tone of each scene you narrate, so the pacing can be varied: add `--tone tension|combat|relief|humor|"
        f"wonder|moral|quiet|mystery` to your `python3 \"{display / 'send.py'}\"` call.",
        f"A letter, a headline, a wanted notice or a terminal log is better shown than described: "
        f"`python3 \"{display / 'send.py'}\" --handout letter|news|poster|terminal|intercept|artifact --title \"<heading>\"` "
        "with its text on stdin.",
        f"If the players are racing or building something, show it: `python3 \"{display / 'push_stats.py'}\" --clock "
        f"\"<what it is>\" <filled> <size>` (and `--clock-remove \"<name>\"` when it is over).",
        f"Something only one character would see or know goes to that player alone: `python3 \"{display / 'send.py'}\" "
        "--to \"<PC>\"` with the detail on stdin. Do not tell the table what it means.",
        f"At a rest, let the characters talk: `python3 \"{scripts / 'story.py'}\" -c {campaign} campfire` gives a question "
        "from their own Bonds and Flaws.",
    )
    return "TABLE TOOL: " + tips[(n // 4) % len(tips)]


def provider(campaign: str, text: str, turn_view) -> list:
    """(priority, line) pairs for the GM note."""
    parts = []
    st = load(campaign)
    counting = getattr(gm_guide, "COUNTING", True)
    n = int(st.get("turn", 0)) + (1 if counting else 0)
    if paths.session_flag(campaign, "style_guard", "on") != "off":
        notes = guard(campaign)
        if notes:
            parts.append((gm_guide.SCENE, "STYLE: " + "; ".join(notes) + "."))
    for line in npc_wants(campaign, text):
        parts.append((gm_guide.SCENE, line))
    teller = STORYTELLERS.get(paths.session_flag(campaign, "storyteller", "none"))
    if teller and n % 8 == 1:
        parts.append((gm_guide.RULE, "This table's storyteller: " + teller))
    tip = tool_tip(campaign, n)
    if tip and paths.session_flag(campaign, "display", "none") != "none":
        parts.append((gm_guide.RULE, tip))
    pace = pacing(campaign)
    if pace:
        parts.append((gm_guide.NUDGE, pace))
    if paths.session_flag(campaign, "sparks", "on") != "off" and n - int(st.get("spark_turn", -99)) >= 5 and n >= 2:
        parts.append((gm_guide.NUDGE, spark(campaign, n)))
        if counting:
            st["spark_turn"] = n
    if counting:
        st["turn"] = n
        save(campaign, st)
    return parts


gm_guide.PROVIDERS.append(provider)


# ── engine actions ────────────────────────────────────────────────────────────

def _register() -> None:
    import knowledge  # noqa: F401
    import scheduler
    import turn

    def world_of(ctx):
        return scheduler.World(ctx.campaign, ctx.db)

    def _rolled(ctx, intent: dict, key: str, text: str, advantage: bool = False):
        """Shared roll step: a request to the player, or the engine's dice. Returns (waiting-result, None) or (None, data).

        Braid (core): 2d6 + modifier, no DC; Braid has no advantage, so a bargain's edge is +1 instead. The roll (or
        the intent) may carry "approach", "push" and "help" exactly as on `roll` (mechanics.edged).
        Story: the oracle answers, nobody rolls; a bargain's edge moves the answer one step up."""
        import resolve as checks
        roll = intent.get("roll") or {}
        system = paths.campaign_system(ctx.campaign)
        err = checks.spec_error(system, roll.get("spec"))
        if err:
            return {"status": "done", "elapsed_minutes": 0, "data": {"error": err}}, None
        num, sides, mod = checks.dice_for(system, roll.get("spec"))
        actor = str(intent.get("actor") or "Party")
        spec, edge = roll.get("spec"), {"notes": [], "push": False}
        if system != "d20":                                 # sheet approach, conditions, push, help: as `roll`
            import mechanics
            edge = mechanics.edged(ctx, intent, system, actor, spec)
            if edge.get("error"):
                return {"status": "done", "elapsed_minutes": 0, "data": {"error": edge["error"]}}, None
            spec = edge["spec"]
        if advantage and system == "core":
            spec = f"{checks.CORE_DICE}{checks.dice_for(system, spec)[2] + 1:+d}"
        if system != "story" and ctx.flag("roll_mode", "players") == "players" and key not in ctx.answers:
            twice = " Roll twice and send the higher." if advantage and system == "d20" else ""
            asked = roll.get("spec", "1d20") if system == "d20" else checks.shown(system, spec)
            return {"status": "waiting_for_player",
                    "requests": [{"key": key, "kind": "roll", "expected": actor,
                                  "text": f"{actor}: {text} — {asked}.{twice}"}]}, None
        if key in ctx.answers:
            got = [int(ctx.answers[key]["value"])]
        elif system == "d20":
            got = [max(ctx.roll(key, sides, 2 if advantage else 1))]
        else:
            got = ctx.roll(key, sides, num)
        dc = int(roll.get("dc", 10))
        graded = checks.resolve(system, spec, dc, got, step_up=int(advantage and system == "story"),
                                likelihood=str(roll.get("likelihood") or "50/50"), chaos=checks.chaos(ctx.campaign, system))
        if system == "d20":
            return None, {"dice": graded["raw"], "total": graded["total"], "dc": dc, "passed": graded["passed"],
                          "advantage": advantage}
        if edge["push"]:
            edge["notes"] = edge["notes"] + [f"stress crossed {c['at']}: {c['note']}" for c in mechanics.push(ctx, actor)]
        return None, {"dice": graded["raw"], "total": graded["total"], "degree": graded["degree"],
                      "passed": graded["passed"], "advantage": advantage, **({"edges": edge["notes"]} if edge["notes"] else {})}

    @turn.handler("flashback")
    def _flashback(ctx, intent: dict) -> dict:
        """flashback — a player says what their character already did to prepare, and it is resolved now.

        {"actor": "Mira", "action": "flashback", "claim": "Last night I swapped the cellar key with the gardener's.",
         "cost": "a Hero Point", "roll": {"spec": "1d20+4", "dc": 13, "label": "Sleight of Hand"}}
        Skip the planning scene: cut to the job, and let preparation be told when it is needed. The claim must be
        something the character could have done and that nothing already told rules out. It costs what the table uses
        (a Hero Point, coin, a favour: say which in `cost`), then a roll decides if it went as described. One per
        character per scene is plenty."""
        world = world_of(ctx)
        actor = str(intent.get("actor") or "Party")
        waiting, rolled = (None, {"passed": True}) if not intent.get("roll") else \
            _rolled(ctx, intent, "roll", f"flashback: {intent.get('roll', {}).get('label') or 'did it work?'}")
        if waiting:
            return waiting
        record = {"by": actor, "claim": str(intent.get("claim", "")), "cost": str(intent.get("cost", "")),
                  "worked": bool(rolled["passed"]), "minute": world.minute}
        world.put("flashback", ctx.action_id, record)
        return {"status": "done", "elapsed_minutes": 0,
                "data": {**record, **rolled, "note": "It happened as told." if record["worked"] else
                         "It was tried and something about it went wrong: say what, and let that be the new problem."}}

    @turn.handler("bargain")
    def _bargain(ctx, intent: dict) -> dict:
        """bargain — a devil's bargain, offered before the roll.

        {"actor": "Mira", "action": "bargain", "offer": "the guard will remember your face",
         "roll": {"spec": "1d20+5", "dc": 15, "label": "Deception"}}
        The player is asked first: take advantage on this roll, and `offer` happens whatever the dice say. If they
        accept, the roll is made with advantage and the price is certain; if they refuse, it is an ordinary roll.
        Name a price that makes the story more interesting, not just harder."""
        world = world_of(ctx)
        actor = str(intent.get("actor") or "Party")
        if "deal" not in ctx.answers:
            edge = {"d20": "advantage on this roll", "core": "+1 on this roll"}.get(
                paths.campaign_system(ctx.campaign), "one step better from the oracle")
            return {"status": "waiting_for_player",
                    "requests": [{"key": "deal", "kind": "decision", "expected": actor,
                                  "text": f"{actor}: a bargain. Take {edge}, and whatever you roll, "
                                          f"{intent.get('offer', 'something goes wrong')}. Accept? (accept / refuse)"}]}
        took = str(ctx.answers["deal"]["value"]).strip().lower().startswith(("a", "y", "ร", "ต"))
        waiting, rolled = _rolled(ctx, intent, "roll", intent.get("roll", {}).get("label") or "the roll", advantage=took)
        if waiting:
            return waiting
        if took:
            scheduler.schedule(ctx.db, f"bargain-{ctx.action_id}", world.minute, {"type": "note", "text": str(intent.get("offer", ""))},
                               cause_id=f"{actor} took a bargain", audience="dm") if world.minute is not None else None
        return {"status": "done", "elapsed_minutes": 0,
                "data": {"actor": actor, "accepted": took, **rolled,
                         "price": str(intent.get("offer", "")) if took else None,
                         "note": "The price is paid whatever the roll says: narrate it." if took else "No bargain: an ordinary roll."}}

    @turn.handler("place_rule")
    def _place_rule(ctx, intent: dict) -> dict:
        """place_rule — a strange rule of one place that the players can test.

        {"action": "place_rule", "place": "the storeroom", "rule": "Every object returns to where it was one minute ago; people stay.",
         "scope": "inside the door frame", "shown_by": "the maid sets a cup down; a minute later it is in her hand again"}
        {"action": "place_rule", "place": "the storeroom", "ruling": "Held in a hand counts as that hand's place, not the floor's."}
        Prepare one rule, where it applies, one thing the characters can watch, and your answer to the obvious edge case.
        Each time the players try something new, add your decision as a `ruling`: from then on it is how the place works.
        The context shows the rule and its rulings whenever the scene is there."""
        world = world_of(ctx)
        key = str(intent.get("place", "")).strip().casefold()
        record = world.get("place_rule", key) or {"place": intent.get("place"), "rule": "", "scope": "", "shown_by": "", "rulings": []}
        for field in ("rule", "scope", "shown_by"):
            if field in intent:
                record[field] = str(intent[field])
        if intent.get("ruling"):
            record["rulings"].append(str(intent["ruling"]))
        world.put("place_rule", key, record)
        return {"status": "done", "elapsed_minutes": 0, "data": record}

    @turn.handler("clock")
    def _clock(ctx, intent: dict) -> dict:
        """clock — a progress clock the whole table can see.

        {"action": "clock", "name": "The alarm", "size": 6, "filled": 3}        set it
        {"action": "clock", "name": "The alarm", "tick": 1, "why": "a door slammed"}   advance it
        {"action": "clock", "name": "The alarm", "remove": true}
        Put a clock on anything the players are racing or building: an alarm, a gang boss's trust, a ritual. It shows
        on the display as segments. When it fills the reply says so: that is when the thing happens."""
        world = world_of(ctx)
        name = str(intent.get("name", "")).strip()
        if intent.get("remove"):
            from world_db import delete
            delete(ctx.db, "clock", name)
            return {"status": "done", "elapsed_minutes": 0, "refresh": "clocks", "data": {"removed": name}}
        clock = world.get("clock", name) or {"size": 6, "filled": 0, "log": []}
        if "size" in intent:
            clock["size"] = max(2, int(intent["size"]))
        if "filled" in intent:
            clock["filled"] = int(intent["filled"])
        if "tick" in intent:
            clock["filled"] += int(intent["tick"])
            clock["log"].append({"tick": int(intent["tick"]), "why": str(intent.get("why", "")), "minute": world.minute})
        clock["filled"] = max(0, min(clock["size"], clock["filled"]))
        world.put("clock", name, clock)
        full = clock["filled"] >= clock["size"]
        return {"status": "done", "elapsed_minutes": 0, "refresh": "clocks",
                "data": {"name": name, **clock, "full": full},
                "visible_events": [{"type": "clock", "recipient": "party",
                                    "text": f"{name}: {clock['filled']}/{clock['size']}" + (" — it is full." if full else "")}]}

    def _engine_lines(campaign: str, text: str, turn_view) -> list:
        """What the engine adds to the note for the storyteller: a place's rule, and camera cues from what just happened."""
        import world_db as wdb
        if not wdb.enabled(campaign):
            return []
        parts = []
        try:
            import scene_context
            here = str(scene_context.scene(campaign).get("place") or "").casefold()
        except Exception:
            here = ""
        with wdb.reader(campaign) as db:
            rules = wdb.all_of(db, "place_rule") if db is not None else {}
        for key, r in rules.items():
            if key and (key == here or key in text.casefold()):
                rulings = (" Rulings so far: " + " | ".join(r["rulings"])) if r.get("rulings") else ""
                parts.append((gm_guide.DUE, f"THIS PLACE HAS A RULE: {r['rule']}" + (f" (where: {r['scope']})" if r.get("scope") else "")
                              + rulings + " Apply it exactly as before; a new edge case gets a `ruling` and then stays that way."))
        for done in (turn_view or {}).get("answered") or []:
            for res in done.get("results") or []:
                d = res.get("data") or {}
                if d.get("dice") in ([20], [1], 20, 1):
                    parts.append((gm_guide.SCENE, f"A natural {d['dice'][0] if isinstance(d['dice'], list) else d['dice']}: slow this "
                                                  "moment right down, beat by beat, before the scene moves on."))
        return parts

    gm_guide.PROVIDERS.append(_engine_lines)


try:
    _register()
except Exception:
    pass


def clocks(campaign: str) -> list:
    """The campaign's clocks as the display wants them: [{name, filled, size}]."""
    import world_db as wdb
    with wdb.reader(campaign) as db:
        rows = wdb.all_of(db, "clock") if db is not None else {}
    return [{"name": name, "filled": c["filled"], "size": c["size"]} for name, c in rows.items()]


def main() -> int:
    p = argparse.ArgumentParser(description="Sparks, pacing and a style guard for the GM.")
    p.add_argument("-c", "--campaign", required=True)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("guard")
    sub.add_parser("spark")
    sub.add_parser("campfire")
    t = sub.add_parser("tone")
    t.add_argument("tone", choices=TONES)
    args = p.parse_args()
    if args.cmd == "guard":
        notes = guard(args.campaign)
        print("\n".join(f"- {n}" for n in notes) if notes else "Nothing to flag in the recent narration.")
    elif args.cmd == "spark":
        print(spark(args.campaign, int(load(args.campaign).get("turn", 0)) + random.randrange(1000)))
    elif args.cmd == "campfire":
        print(campfire(args.campaign) or "No Bonds or Flaws on the character sheets to draw from.")
    else:
        tones = note_tone(args.campaign, args.tone)
        print("Recent tones: " + ", ".join(tones[-5:]))
        print(pacing(args.campaign) or "")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
