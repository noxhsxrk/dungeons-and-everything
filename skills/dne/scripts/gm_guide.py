#!/usr/bin/env python3
"""
gm_guide.py — what the GM is told by the scripts it runs anyway.

Some agents read only the top of SKILL.md and then play with three scripts (send.py,
push_stats.py, autorun_wait.py): rules written further down never reach them, and no
hook runs on their host. So the rules that keep a campaign sound travel in the output
of those scripts, worked out from the files, with real paths and names:

    gm_guide.py -c <campaign> start   # printed by `push_stats.py --set-campaign` (session start)
    gm_guide.py -c <campaign> turn    # appended by autorun_wait.py to every player action

`start` also marks the campaign active (the step /dne load used to leave to the GM).
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import paths  # noqa: E402

sys.modules.setdefault("gm_guide", sys.modules[__name__])   # run as a script, `import gm_guide` is still this module

SKILL = HERE.parent
TURNS = ".autorun-turns.json"   # player turns handed out since state.md was last written


def _py(script: str) -> str:
    return f'python3 "{HERE / script}"'


def section_lines(doc: str, heading: str) -> str:
    """'<file> lines A-B' for the section whose heading line contains `heading` (agents read by line range)."""
    path = SKILL / doc
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return str(path)
    start = next((i for i, l in enumerate(lines) if l.lstrip("> ").startswith("#") and heading in l), None)
    if start is None:
        return str(path)
    quoted = lines[start].startswith(">")
    end = next((i for i in range(start + 1, len(lines))
                if (not lines[i].startswith(">") if quoted else re.match(r"#{1,2} ", lines[i]))), len(lines))
    return f"{path} lines {start + 1}-{end}"


def session_start(campaign: str) -> list[str]:
    """Mark the campaign active and list what a session start still needs."""
    camp = paths.find_campaign(campaign)
    xp0 = {}
    try:
        import xp
        for sheet in sorted((camp / "characters").glob("*.md")):
            xp0[sheet.stem] = xp._read_char_state(sheet)[0]
    except Exception:
        pass
    marker = {"name": campaign, "since": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
              "xp": xp0}   # XP on each sheet as the session opens: everything above it must come from xp.py
    try:
        (paths.runtime_dir() / "active-campaign.json").write_text(json.dumps(marker), encoding="utf-8")
    except OSError:
        pass
    steps = [
        f"Read {section_lines('SKILL.md', 'Four rules')} (the rules for the whole session) and "
        f"{section_lines('SKILL-commands.md', '/dne load')} (/dne load, all of it). "
        "A skill you read earlier in this conversation may be out of date: read them again.",
        f"Read from disk now, not from memory: state.md, world.md, npcs.md and characters/*.md in {camp}. "
        "Fill the sidebar from those files.",
        f"{_py('migrate_ruleset.py')} {campaign} --check",
        f"{_py('campaign_version.py')} -c {campaign} check",
    ]
    try:
        import save_check
        gaps = save_check.missing_sessions(camp)
    except Exception:
        gaps = []
    if gaps:
        # A save that only bumped the header lost a whole session once (wins, level-ups, pacts): catch it before play.
        steps.insert(0, f"LOG GAP: state.md counts {save_check.session_count(camp)} sessions but session-log.md / "
                        f"session-log-archive.md have no `## Session N` entry for session {', '.join(map(str, gaps))}. "
                        "Before the opening scene, tell the players and ask what happened in it (fights won, levels, "
                        "items, pacts, people met); also use characters/*.md, xp-ledger.jsonl and session_tail.json. "
                        "Write the entry, and pin its lasting facts to state.md → ## Pinned Facts.")
    engine = paths.session_flag(campaign, "world_engine", "off") == "on"
    if engine:
        steps.append(f"{_py('turn.py')} -c {campaign} status   (world engine: if a turn is open, run `resume` and finish it "
                     "before anything new; faction weeks and queued events run by themselves as time passes)")
    if (camp / "factions.json").exists() and not engine:
        steps.append(f"{_py('faction.py')} -c {campaign} turn   (write its lines to state.md, section ## Faction Moves)")
    if (camp / "calendar.json").exists():
        steps.append(f"{_py('calendar.py')} -c {campaign} now   (the in-world date and time: show this one on the display)")
    steps.append(f'{_py("campaign_graph.py")} scene-context --campaign {campaign} --place "<current location>"')
    steps.append(f"{_py('npc.py')} -c {campaign} check   (NPC records that are unfinished, incomplete or due to grow: "
                 "fix the ones in the opening scene before the recap, the rest by the end of the session)")
    try:
        import story
        teller = story.STORYTELLERS.get(paths.session_flag(campaign, "storyteller", "none"))
        dna = story._dna(campaign)
        voice = [teller] if teller else []
        if dna:
            voice.append("this world's telling: " + "; ".join(
                f"{k.replace('_', ' ')}: {', '.join(v) if isinstance(v, list) else v}" for k, v in dna.items() if v))
        if voice:
            steps.append("Tell it this table's way. " + " ".join(voice))
        steps.append("Open the session in the middle of something (a cold open) when the last one ended at rest: one "
                     "urgent image first, how they got there in a line afterwards.")
    except Exception:
        pass
    return ([f"SESSION START: {campaign} is now the active campaign. The session is not ready until every line "
             "below is done, in order:"] + [f"{i}. {s}" for i, s in enumerate(steps, 1)])


def _xp_gaps(campaign: str) -> list[str]:
    """PCs holding XP that xp.py never awarded: on the display only, or written into the sheet by hand.

    The engine's figure is the sheet's XP at session start plus this session's rows in the award
    ledger. Without a session-start record the sheet itself is the figure (display-only XP still shows).
    """
    try:
        import xp
        rt = paths.runtime_dir()
        players = json.loads((rt / "stats.json").read_text(encoding="utf-8")).get("players") or []
    except Exception:
        return []
    try:
        marker = json.loads((rt / "active-campaign.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        marker = {}
    base = marker.get("xp") if marker.get("name") == campaign else None
    since = marker.get("since") or ""
    gaps = []
    for p in players:
        try:
            shown = int((p.get("xp") or {}).get("current"))
            path = xp._find_char_path(campaign, p["name"])
            sheet = xp._read_char_state(path)[0]
        except Exception:
            continue
        engine = sheet
        if isinstance(base, dict) and path.stem in base:
            engine = base[path.stem] + sum(
                int(r.get("awarded") or 0) for r in xp._read_ledger(campaign)
                if str(r.get("character", "")).casefold() == str(p["name"]).casefold() and str(r.get("at", "")) >= since)
        if max(shown, sheet) > engine:
            gaps.append(f"{p['name']}: display {shown}, sheet {sheet}, awarded by xp.py {engine}")
    return gaps


def _clock_gap(campaign: str) -> "tuple[str, str] | None":
    """('display says X but calendar.json is at Y', Y) when the two dates differ, whichever one is behind."""
    try:
        import npc
        shown = str((json.loads((paths.runtime_dir() / "stats.json").read_text(encoding="utf-8"))
                     .get("world_time") or {}).get("date") or "")
        cal = json.loads((paths.find_campaign(campaign) / "calendar.json").read_text(encoding="utf-8"))
        now = npc.today(paths.find_campaign(campaign))
    except Exception:
        return None
    numbers = [int(n) for n in re.findall(r"\d+", shown)]
    if not now or not numbers or int(cal["day"]) in numbers:   # formats differ by table: compare the day number only
        return None
    return (f"the display says '{shown}' but calendar.json is at {now[1]}", now[1])


def _npc_notes(campaign: str, text: str) -> list[str]:
    """One standing sentence, then records left unfinished and NPCs in this scene who are due to grow."""
    try:
        import npc
    except Exception:
        return []
    camp = paths.find_campaign(campaign)
    notes = [f"A named character who enters the story gets a record the same turn: `{_py('npc.py')} -c {campaign} add "
             "--name \"<Name>\" --role \"<role>\" --cr <CR> --aliases \"<names used in play>\"` (fair stats, npcs.md row, "
             "npcs-full.md entry), then write its `<fill: ...>` parts: background, personality, goal, relationships."]
    todo = npc.unfinished(camp)
    if todo:
        shown = list(todo.items())[:4]
        notes.append("NPC RECORDS UNFINISHED: " + "; ".join(f"{n} ({len(marks)} parts)" for n, marks in shown)
                     + (f"; +{len(todo) - 4} more" if len(todo) > 4 else "")
                     + f". Write every `<fill: ...>` part of those entries now in {camp / 'npcs-full.md'}.")
    try:
        log = json.loads((paths.runtime_dir() / "text_log.json").read_text(encoding="utf-8"))[-6:]
        text += "\n" + "\n".join(str(e.get("text", "")) for e in log if isinstance(e, dict))
    except Exception:
        pass
    back = npc.due(campaign, only=npc.on_stage(camp, text))[:3]
    if back:
        notes.append("NPC GROWTH DUE, they are in this scene: " + "; ".join(f"{n} ({d} in-world days)" for n, d, _s in back)
                     + f". Before they act run `{_py('npc.py')} -c {campaign} advance \"<Name>\" --what \"<what they did "
                     "meanwhile>\"` (it raises their level and stats; --levels 0 if they only changed).")
    return notes


def _turns_unsaved(campaign: str, count: bool) -> int:
    """Player turns handed out since state.md last changed (counts this one when `count`)."""
    try:
        mtime = (paths.find_campaign(campaign) / "state.md").stat().st_mtime
    except OSError:
        return 0
    path = paths.runtime_dir() / TURNS
    try:
        rec = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        rec = {}
    turns = rec.get("turns", 0) if rec.get("campaign") == campaign and rec.get("state_mtime") == mtime else 0
    if count:
        turns += 1
        try:
            path.write_text(json.dumps({"campaign": campaign, "state_mtime": mtime, "turns": turns}), encoding="utf-8")
        except OSError:
            pass
    return turns


#: The whole note is capped. What is due is never cut; the rest goes in this order until the cap is reached.
DUE, SCENE, RULE, DEPTH, NUDGE = 0, 1, 2, 3, 4
NOTE_BUDGET = 3600


def _engine_parts(campaign: str, view: "dict | None") -> list:
    """(priority, line) pairs about the engine turn that just opened (world_engine: on)."""
    if not view or not view.get("turn_id"):
        return []
    parts = []
    for done in view.get("answered") or []:
        for res in done.get("results") or []:
            d = res.get("data") or {}
            if "total" in d:
                verdict = f", {d['degree'] or ('pass' if d.get('passed') else 'fail')} against DC {d['dc']}" if "dc" in d else ""
                parts.append((DUE, f"ROLL IN: {d.get('actor')} rolled {d.get('dice')} for {d.get('label') or 'the roll'}: "
                                   f"total {d['total']}{verdict}. Narrate from this result; do not ask again."))
    if view.get("duplicate"):
        parts.append((DUE, f"This input was already received as {view['turn_id']}: do not resolve it a second time."))
    moved = _clock_moved_by_hand(campaign)
    if moved:
        parts.append((DUE, moved))
    context = view.get("context")
    if context:
        try:
            import scene_context
            parts += scene_context.render_parts(context)
        except Exception:
            pass
    else:
        for w in view.get("waiting") or []:
            parts.append((DUE, f"STILL WAITING: {w['question']} ({w['request_id']}, from {w['expected']})."))
    if view.get("waiting"):
        parts.append((DUE, "Do not decide a waited-on roll or choice for the player; their answer comes as their next message."))
    parts.append((RULE, f"World engine: {view['turn_id']} is open. Rolls, rests, travel and trade go through "
                        f"`{_py('turn.py')} -c {campaign} resolve --intents '[...]'` (`{_py('turn.py')} -c {campaign} help` "
                        "lists the actions); your plain send.py narration closes the turn."))
    return parts


def _clock_moved_by_hand(campaign: str) -> "str | None":
    """The calendar is not where the engine last left it: time was moved around the engine (a hand edit, or a
    turn answered without the scripts), so whatever was due in between has not happened."""
    try:
        import world_db as wdb
        with wdb.reader(campaign) as db:
            left = wdb.meta(db, "clock_minute") if db is not None else ""
        now = wdb.now_minute(campaign)
    except Exception:
        return None
    if not left or now is None or int(left) == now:
        return None
    gap = now - int(left)
    py = _py("turn.py")
    return (f"IN-WORLD TIME MOVED OUTSIDE THE ENGINE ({'+' if gap > 0 else ''}{gap} min since the engine last moved the clock): "
            f"what was due in that time has not happened. If the time really passed, run `{py} -c {campaign} resolve "
            f"--intents '[{{\"action\": \"wait\", \"minutes\": 0}}]'` now so it does; if the date was simply wrong, "
            f"`{_py('calendar.py')} -c {campaign} set …` records it as a correction. From now on move time only with "
            "wait / rest / travel.")


def engine_lines(campaign: str, view: "dict | None") -> list[str]:
    """What the world engine needs the GM to know about the turn that just opened, as plain lines."""
    return fit(_engine_parts(campaign, view))


def fit(parts: list, budget: "int | None" = None, rotate: int = 0) -> list[str]:
    """Order by priority and stop at the budget. Lines that are due always stay; at most one nudge is kept
    (`rotate` picks which, so the same kind of nudge does not win every turn)."""
    nudges = [p for p in parts if p[0] == NUDGE]
    if len(nudges) > 1:
        keep = nudges[rotate % len(nudges)]
        parts = [p for p in parts if p[0] != NUDGE] + [keep]
    if budget is None:
        try:
            budget = int(os.environ.get("DNE_NOTE_BUDGET", NOTE_BUDGET))
        except ValueError:
            budget = NOTE_BUDGET
    kept, used, dropped, nudged = [], 0, 0, False
    for prio, line in sorted(parts, key=lambda p: p[0]):   # stable: lines of one priority keep their order
        if prio == NUDGE and nudged:
            continue
        if prio != DUE and used + len(line) > budget:
            dropped += 1
            continue
        kept.append(line)
        used += len(line)
        nudged = nudged or prio == NUDGE
    if dropped:
        kept.append(f"({dropped} lower-priority line{'s' if dropped > 1 else ''} left out for length.)")
    return kept


def turn_parts(campaign: str, count: bool = True, text: str = "", turn: "dict | None" = None) -> list:
    """Every (priority, line) the GM could be told with this player action, before the cap is applied.

    `engine: light` in Session Flags drops the fight and XP rules: that table lets the GM judge them.
    """
    if not campaign or not paths.find_campaign(campaign).is_dir():
        return []
    cmds = SKILL / "SKILL-commands.md"
    full = paths.session_flag(campaign, "engine", "full") != "light"
    parts = _engine_parts(campaign, turn)
    if paths.session_flag(campaign, "world_engine", "off") == "on":
        if full:
            parts.append((RULE, "A fight on the world engine: `fight` (what it is for, what ends it), `combatant`, then `advise` "
                                "before an enemy acts, `move`, `spend`, `damage`, `round` (`turn.py help fight`). It ends when "
                                "its objective is settled, not when the last enemy drops."))
        parts.append((RULE, "Time passes only through the world engine: a rest is the action `rest`, a journey is "
                            "`travel`, waiting is `wait` (never calendar.py rest, economy.py rest or world_map.py travel: "
                            "they would move time or the party a second time). An interrupted rest or journey waits "
                            "for the players' choice; do not finish it for them."))
    if full:
        parts.append((RULE,
        "Fights and rests run on the engine, never on narration alone. Before the first blow run "
        f"`{_py('combat.py')} init '<JSON>'` so every enemy has HP and AC (`{_py('worldkit.py')} monster-stats "
        "--cr <CR>` prints fair numbers for its rank; a d20 the player typed goes in as \"roll\": N). Each attack is "
        "the same combat.py with `attack --atk <bonus> --ac <AC> --dmg <dice> --roll <the d20 before bonuses>`; take "
        "the damage off the target's HP. An enemy is beaten only at 0 HP or when its morale breaks. Full steps: "
        f"{section_lines('SKILL-commands.md', '/dne combat start')}; a rest: "
        f"{section_lines('SKILL-commands.md', '/dne rest').replace(str(cmds) + ' ', '')} of that file."))
    for i, line in enumerate(_npc_notes(campaign, text)):
        parts.append((RULE if i == 0 else DUE, line))
    clock = _clock_gap(campaign)
    if clock:
        parts.append((DUE,
            f"IN-WORLD CLOCK OUT OF STEP: {clock[0]}. calendar.json is the clock: NPC growth, faction turns and timed "
            f"effects count from it. If the story is later than the calendar, move it: `{_py('calendar.py')} -c {campaign} "
            "advance <N> <hours|days>` (time passes, and with the world engine on whatever is due happens), as after "
            "every rest, journey or time skip; `set \"<D Month YYYY>\"` only corrects a wrong date. If the "
            f"calendar is right, show its date: `python3 \"{SKILL / 'display' / 'push_stats.py'}\" --world-time "
            f"'{{\"date\": \"{clock[1]}\", \"time\": \"<time of day>\"}}'`."))
    gaps = _xp_gaps(campaign) if full else []
    if gaps:
        parts.append((DUE,
            "XP NOT AWARDED BY THE ENGINE (" + "; ".join(gaps) + "). XP counts only when xp.py award gave it; never "
            "write it into a sheet or set it with push_stats.py --xp yourself. Fix it now: put the **XP:** line in "
            "characters/<pc>.md back to the xp.py figure, then for each encounter won since run "
            f"`{_py('xp.py')} award --campaign {campaign} --characters \"<PC>\" --monsters \"<name>:<CR>:<count>\"` "
            "(or `--difficulty easy|medium|hard|deadly --type noncombat`). It works the amount out from the tables, "
            "writes the sheet and sets the display to match."))
    try:
        import autosave_checkpoint as ac
        every, on = ac._every_from_env(), ac.autosave_enabled(campaign)
    except Exception:
        every, on = 10, True
    turns = _turns_unsaved(campaign, count)
    if on and turns >= every:
        camp = paths.find_campaign(campaign)
        parts.append((DUE,
            f"SAVE DUE: {turns} player turns since state.md was last written; all of it is lost if this chat ends. "
            f"Before you narrate, write to {camp}: state.md (Current Situation: place, time, HP and resources; Recent "
            "Events; Live State Flags) and characters/<pc>.md (HP, slots, inventory, allies and gear gained). "
            "Quietly, no word to the players; this is not a full /dne save."))
    if paths.session_flag(campaign, "world_engine", "off") == "on":
        try:
            import turn as _turn  # noqa: F401  (loads the engine modules, which register their providers)
        except Exception:
            pass
    if paths.session_flag(campaign, "world_engine", "off") == "shadow":
        try:                                      # shadow: the engine changes nothing; it only shows and logs its context
            import scene_context
            view = scene_context.build(campaign, text)
            with open(paths.find_campaign(campaign) / ".world-shadow.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps({"input": text, "context": view}, ensure_ascii=False) + "\n")
            parts.append((DEPTH, "(world engine, shadow) It would have told you: " + " ".join(scene_context.render(view)[:4])))
        except Exception:
            pass
    global COUNTING
    COUNTING = count
    try:
        import story  # noqa: F401  (sparks, pacing, style guard: for every campaign, engine or not)
    except Exception:
        pass
    for provider in PROVIDERS:                    # story.py and the engine modules add their own lines
        try:
            parts += provider(campaign, text, turn) or []
        except Exception:
            pass
    return parts


#: Functions `fn(campaign, text, turn) -> [(priority, line)]` that other modules register.
PROVIDERS: list = []
COUNTING = True          # False while the note is only being previewed (the CLI): providers must not advance state


def turn_notes(campaign: str, count: bool = True, text: str = "", turn: "dict | None" = None) -> list[str]:
    """Lines for the GM, sent with every player action (`text`): what is due, then the scene, then standing rules."""
    parts = turn_parts(campaign, count, text, turn)
    rotate = 0
    try:
        import story
        rotate = int(story.load(campaign).get("turn", 0))
    except Exception:
        pass
    return fit(parts, rotate=rotate)


def main() -> int:
    p = argparse.ArgumentParser(description="What the GM must be told at session start and on each turn.")
    p.add_argument("-c", "--campaign", required=True)
    p.add_argument("what", choices=["start", "turn"])
    args = p.parse_args()
    lines = session_start(args.campaign) if args.what == "start" else turn_notes(args.campaign, count=False)
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
