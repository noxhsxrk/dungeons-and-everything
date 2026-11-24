#!/usr/bin/env python3
"""
save_check.py — the /dne save checklist, worked out from the files themselves.

A save touches many files (state.md, the session log, characters, NPCs, the
graph, factions, calendar, world.md). Written as prose, steps get skipped:
relationships especially, because they live in three places. This script
lists every part of the save, marks what was already written this session
(by file time; relationships are never marked, the GM answers them by name) and
names the NPCs who appeared in this session's narration,
so nothing is skipped and "no change" is a decision, not an omission.

Usage:
    save_check.py -c <campaign>            # run at the start and again at the end of /dne save
    save_check.py -c <campaign> --since "2026-11-23 14:00"   # override the session start

Session start = when /dne load marked the campaign active (runtime marker), else 12 hours ago.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paths import find_campaign, runtime_dir  # noqa: E402


def session_start(since: str | None) -> float:
    if since:
        # no strptime: it imports the stdlib calendar, which scripts/calendar.py shadows
        m = re.fullmatch(r"\s*(\d{4})-(\d{1,2})-(\d{1,2})[ T](\d{1,2}):(\d{2})\s*", since)
        if not m:
            raise ValueError('--since must look like "2026-11-23 14:00"')
        return datetime(*map(int, m.groups())).timestamp()
    marker = runtime_dir() / "active-campaign.json"
    try:
        return marker.stat().st_mtime
    except OSError:
        return time.time() - 12 * 3600


def _mtime(p: Path) -> float | None:
    try:
        return p.stat().st_mtime
    except OSError:
        return None


def _section(text: str, title: str) -> str:
    m = re.search(rf"^## {re.escape(title)}[^\n]*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    return m.group(1) if m else ""


def session_count(camp: Path) -> int | None:
    """`**Session count:** N` from the state.md header, or None."""
    try:
        m = re.search(r"\*\*Session count:\*\*\s*(\d+)", (camp / "state.md").read_text(encoding="utf-8"))
    except OSError:
        return None
    return int(m.group(1)) if m else None


def logged_sessions(camp: Path) -> set[int]:
    """Session numbers with a `## Session N` entry in session-log.md or session-log-archive.md."""
    found: set[int] = set()
    for name in ("session-log.md", "session-log-archive.md"):
        try:
            text = (camp / name).read_text(encoding="utf-8")
        except OSError:
            continue
        found.update(int(n) for n in re.findall(r"^## Session (\d+)\b", text, re.M))
    return found


def missing_sessions(camp: Path) -> list[int]:
    """Sessions the header counts that have no log entry: what a save that skipped the log leaves behind."""
    count = session_count(camp) or 0
    logged = logged_sessions(camp)
    return [n for n in range(1, count + 1) if n not in logged]


def npc_index(camp: Path) -> list[dict]:
    """NPCs from npcs.md (name, attitude) plus any `**Aliases:**` from npcs-full.md."""
    npcs = []
    try:
        rows = (camp / "npcs.md").read_text(encoding="utf-8").splitlines()
    except OSError:
        rows = []
    header = None
    for line in rows:
        if not line.strip().startswith("|"):
            continue
        cols = [re.sub(r"\*\*|`", "", c).strip() for c in line.strip().strip("|").split("|")]
        if all(re.fullmatch(r":?-{2,}:?", c) for c in cols if c):
            continue
        if header is None:
            header = [c.lower() for c in cols]
            continue
        rec = dict(zip(header, cols))
        name = cols[0]
        if name:
            npcs.append({"name": name, "attitude": rec.get("attitude", ""), "aliases": []})
    try:
        full = (camp / "npcs-full.md").read_text(encoding="utf-8")
    except OSError:
        full = ""
    for n in npcs:
        body = _section(full, n["name"])
        m = re.search(r"\*\*(?:Aliases|Also called|ชื่อเรียก)\s*:?\*\*\s*:?\s*(.+)", body)
        if m:
            n["aliases"] = [a.strip() for a in re.split(r"[,/、]", m.group(1)) if a.strip()]
    return npcs


def session_text(camp: Path) -> str:
    try:
        tail = json.loads((camp / "session_tail.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        tail = []
    return "\n".join(str(e.get("text", "")) for e in tail if isinstance(e, dict))


def appeared(npc: dict, text: str) -> bool:
    names = [npc["name"], npc["name"].split()[0]] + npc["aliases"]
    return any(n and len(n) >= 2 and n.casefold() in text.casefold() for n in names)


def checklist(campaign: str, since: float) -> list[tuple[bool, str]]:
    camp = find_campaign(campaign)
    if not camp.is_dir():
        raise ValueError(f"no campaign folder {camp}")
    done = lambda name: (_mtime(camp / name) or 0) >= since  # noqa: E731
    items: list[tuple[bool, str]] = []
    count = session_count(camp)
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        header_today = f"**Last session:** {today}" in (camp / "state.md").read_text(encoding="utf-8")
    except OSError:
        header_today = False
    items.append((header_today, f"state.md header: on the first save of a session, `**Session count:**` +1 and "
                                f"`**Last session:** {today}`"))
    if count:
        # A header bumped with no `## Session N` entry is how a whole session's events got lost: tick on the entry, not the file time.
        items.append((done("session-log.md") and count in logged_sessions(camp),
                      f"session-log.md: a `## Session {count}` entry for this session (Session count is {count}) with "
                      "Recap, Key Events, XP, Loot, Open Threads. Every win, level-up, pact and item that matters "
                      "later also goes to state.md → ## Pinned Facts"))
    else:
        items.append((done("session-log.md"), "session-log.md: this session's entry (events, rolls that changed things, open threads)"))
    items.append((done("state.md"), "state.md: Current Situation (location, time, party HP/resources, Inspiration), "
                                    "Recent Events, Active Quests, Open Threads"))
    state = (camp / "state.md").read_text(encoding="utf-8") if (camp / "state.md").exists() else ""
    flags = _section(state, "Live State Flags")
    text = session_text(camp)
    npcs = npc_index(camp)
    seen = [n for n in npcs if text and appeared(n, text)]
    others = [n for n in npcs if n not in seen]
    # Never ticked by file time: a touched npcs.md says nothing about whether *these* relationships
    # were written (one edited row used to tick the whole item, and the save skipped the rest).
    now = lambda ns: "; ".join(f"{n['name']} (now: {n['attitude'] or '?'})" for n in ns)  # noqa: E731
    how = (". This row never ticks itself. For each one that changed (toward the party or another NPC, romance "
           "and grudges included): update the Attitude column in npcs.md, `NPC dispositions` in state.md → Live "
           "State Flags, and a graph edge (`campaign_graph.py set-disposition` / add-edge). Then name every NPC "
           "here in your save summary with its change, or 'no change'")
    if seen:
        items.append((False, "Relationships for NPCs in this session's narration: " + now(seen) + how))
    if others:
        items.append((False, "Other NPCs (didn't match the narration by name; check if they took part): "
                      + now(others) + how
                      + ". Add `- **Aliases:** <names used in play>` to their npcs-full.md entry so this check finds them"))
    try:
        import npc
        open_records = {**npc.backlog(camp), **{n: ["unfinished"] for n in npc.unfinished(camp)}}
        growing = [n for n, _d, _s in npc.due(campaign)]
        label = "NPC records: every character the story named has a full entry (stats, background, aliases) and has grown with time"
        if open_records or growing:
            label += (" — still open: " + "; ".join(f"{n} ({', '.join(m)})" for n, m in list(open_records.items())[:8])
                      + ("; due to grow: " + ", ".join(growing[:8]) if growing else "")
                      + f". Run `npc.py -c {campaign} check`; add anyone met this session with `npc.py add`")
        items.append((not open_records and not growing, label))
    except Exception:
        pass
    items.append(("Faction stances" in flags or "NPC dispositions" in flags,
                  "state.md → Live State Flags: Cover, Faction stances, NPC dispositions present and current"))
    chars = sorted((camp / "characters").glob("*.md")) if (camp / "characters").is_dir() else []
    for c in chars:
        items.append((done(f"characters/{c.name}"),
                      f"characters/{c.name}: HP, XP, slots/resources, inventory, money, conditions, bonds"))
    for name, what in (("calendar.json", "in-world time advanced (`calendar.py advance`)"),
                       ("factions.json", "faction numbers: `faction.py adjust` for what the party did to them"),
                       ("graph.json", "relationship edges opened/closed this session"),
                       ("world.md", "threat stage, faction attitudes, settlement facts that changed")):
        if (camp / name).exists():
            items.append((done(name), f"{name}: {what}"))
    items.append((done("session-tail.md") or done("session_tail.json"),
                  "session tail: `verify_tail.sh` / `write_canonical_tail.py` (SKILL-commands → /dne save)"))
    return items


def main() -> int:
    p = argparse.ArgumentParser(description="Checklist for /dne save.")
    p.add_argument("-c", "--campaign", required=True)
    p.add_argument("--since", help='session start, "YYYY-MM-DD HH:MM" (default: when /dne load ran)')
    args = p.parse_args()
    try:
        since = session_start(args.since)
        items = checklist(args.campaign, since)
    except (OSError, ValueError) as exc:
        print(f"save_check.py: {exc}", file=sys.stderr)
        return 1
    todo = sum(1 for ok, _ in items if not ok)
    print(f"Save checklist for {args.campaign} (session since {datetime.fromtimestamp(since):%Y-%m-%d %H:%M}): "
          f"{len(items) - todo} done, {todo} to do")
    for ok, label in items:
        print(f"{'✓' if ok else '☐'} {label}")
    gaps = missing_sessions(find_campaign(args.campaign))
    if gaps:
        print(f"\n☐ Earlier sessions with no log entry: {', '.join(map(str, gaps))}. Write them now (ask the players what happened).")
    if todo:
        print("\nEvery ☐ must be updated now, or named in your save summary with the reason it didn't change. "
              "/dne end is not finished while the session-log row is ☐.")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
