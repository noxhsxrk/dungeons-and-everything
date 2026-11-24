#!/usr/bin/env python3
"""
npc.py — NPC records that exist from the first scene and grow with in-world time.

A character the story names gets a full record the turn they appear, and nobody stays
frozen while the party is elsewhere: after enough in-world time an NPC is due to grow
(a level or CR step, and a line in their History about what they did meanwhile).

    npc.py -c <campaign> add --name "<Name>" --role "<role>" --cr <CR> --aliases "<names used in play>"
                             [--faction F] [--location L] [--attitude neutral] [--notes "<one line>"]
        Writes the npcs.md row and the npcs-full.md entry with fair stats for that CR.
        The prose is left as `<fill: …>` marks for the GM to write.
    npc.py -c <campaign> check
        Lists records that are unfinished, missing parts, or due to grow. Exit 1 if any.
    npc.py -c <campaign> advance "<Name>" --what "<what they did meanwhile>" [--levels N]
        Grows one NPC: raises CR/Level, HP and AC (never lowers them) and adds the History line.

In-world time comes from calendar.json. Growth speed is the `npc_growth` Session Flag:
off | slow (120 days a step) | normal (60, default) | fast (30).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths  # noqa: E402
import worldkit  # noqa: E402

GROWTH_DAYS = {"off": 0, "slow": 120, "normal": 60, "fast": 30}
#: The display's TTS voices (display/tts.py). An NPC keeps one, so the table hears who is speaking.
VOICES = ("Charon", "Enceladus", "Fenrir", "Umbriel", "Aoede", "Gacrux", "Kore", "Vindemiatrix", "Zephyr")
TIMELINE = "npc-timeline.json"   # {name: {"grown": <absolute in-world day of the last growth>}}
FILL = re.compile(r"<fill: ([^>]*)>")
INDEX_HEAD = ("| Name | Role | Faction | Location | Attitude | Notes |\n"
              "|------|------|---------|----------|----------|-------|\n")
AXES = ("Trustworthy ↔ Deceptive", "Ambitious ↔ Content", "Loyal ↔ Opportunistic", "Brave ↔ Cowardly")


# ── in-world time ─────────────────────────────────────────────────────────────

def today(camp: Path) -> "tuple[int, str] | None":
    """(absolute day number, '15 May 2026') from calendar.json; None when the campaign has no calendar."""
    try:
        cal = json.loads((camp / "calendar.json").read_text(encoding="utf-8"))
        day, month, year = int(cal["day"]), int(cal["month"]), int(cal.get("year", 1))
    except (OSError, ValueError, KeyError, TypeError):
        return None
    months = cal.get("months") or []
    if cal.get("gregorian"):
        number = date(year, month, day).toordinal()
    else:
        number = ((year - 1) * (len(months) or 12) + month - 1) * int(cal.get("month_length", 30)) + day - 1
    name = months[month - 1] if 1 <= month <= len(months) else f"Month {month}"
    return number, f"{day} {name} {year}"


def growth_days(campaign: str) -> int:
    return GROWTH_DAYS.get(paths.session_flag(campaign, "npc_growth", "normal"), 60)


def _timeline(camp: Path) -> dict:
    try:
        data = json.loads((camp / TIMELINE).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_timeline(camp: Path, data: dict) -> None:
    try:
        (camp / TIMELINE).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass


# ── the two files ─────────────────────────────────────────────────────────────

def index_names(camp: Path) -> list[str]:
    """Names in the npcs.md table, in order."""
    try:
        rows = (camp / "npcs.md").read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    names, header = [], False
    for line in rows:
        if not line.strip().startswith("|"):
            continue
        cols = [re.sub(r"\*\*|`", "", c).strip() for c in line.strip().strip("|").split("|")]
        if all(re.fullmatch(r":?-{2,}:?", c) for c in cols if c):
            continue
        if not header:
            header = True
            continue
        if cols[0]:
            names.append(cols[0])
    return names


def entries(camp: Path) -> dict:
    """{name: entry text} for every `## <Name>` section of npcs-full.md."""
    try:
        text = (camp / "npcs-full.md").read_text(encoding="utf-8")
    except OSError:
        return {}
    return {m.group(1).strip(): m.group(0)
            for m in re.finditer(r"^## ([^\n]+)\n.*?(?=^## |\Z)", text, re.M | re.S)}


def aliases(name: str, entry: "str | None") -> list[str]:
    """Every string that means this NPC in narration: full name, first name, listed aliases (3+ characters)."""
    found = [name, name.split()[0]]
    m = entry and re.search(r"\*\*(?:Aliases|Also called|ชื่อเรียก)\s*:?\*\*\s*:?\s*([^\n|]+)", entry)
    if m:
        found += [a.strip() for a in re.split(r"[,/、]", m.group(1))]
    return [a for a in dict.fromkeys(found) if len(a) >= 3 and not a.startswith("<")]


def unfinished(camp: Path) -> dict:
    """{name: [parts still marked <fill: …>]}: records npc.py created that the GM has not written yet."""
    out = {}
    for name, entry in entries(camp).items():
        marks = list(dict.fromkeys(m.split(",")[0] for m in FILL.findall(entry)))
        if marks:
            out[name] = marks
    return out


def graph_names(camp: Path) -> "set | None":
    """Lower-cased node names in graph.json, or None when the campaign has no graph yet."""
    try:
        nodes = json.loads((camp / "graph.json").read_text(encoding="utf-8")).get("nodes") or []
    except (OSError, ValueError, AttributeError):
        return None
    return {str(n.get("name", "")).casefold() for n in nodes if isinstance(n, dict)} if nodes else None


def backlog(camp: Path) -> dict:
    """{name: [what is missing]} for records that predate this script: no entry, no history, no aliases."""
    full = entries(camp)
    graph = graph_names(camp)
    out = {}
    for name in index_names(camp):
        if graph is not None and name.casefold() not in graph:
            out.setdefault(name, []).append("not in graph.json")
        entry = full.get(name)
        if entry is None:
            out.setdefault(name, []).append("no entry in npcs-full.md")
            continue
        missing = []
        if not re.search(r"\*\*HP:\*\*\s*\d", entry):
            missing.append("stats")
        if not re.search(r"^### History\s*\n\s*-\s*\S", entry, re.M):
            missing.append("history")
        if "**Aliases:**" not in entry:
            missing.append("aliases")
        if missing:
            out.setdefault(name, []).extend(missing)
    return out


def due(campaign: str, only: "set | None" = None) -> list:
    """[(name, in-world days since they last grew, steps)] for NPCs whose growth is due.

    An NPC met before this script existed starts counting today; one with no full entry is skipped.
    """
    camp = paths.find_campaign(campaign)
    now, period = today(camp), growth_days(campaign)
    if not now or not period:
        return []
    line, changed, out = _timeline(camp), False, []
    full = entries(camp)
    for name in index_names(camp):
        rec = line.get(name)
        if name not in full:        # nothing to grow yet: `check` reports the missing entry first
            continue
        if not isinstance(rec, dict) or "grown" not in rec:
            line[name], changed = {"grown": now[0]}, True
            continue
        days = now[0] - int(rec["grown"])
        if days >= period and (only is None or name in only):
            out.append((name, days, days // period))
    if changed:
        _save_timeline(camp, line)
    return out


def on_stage(camp: Path, text: str) -> set:
    """NPCs named (by name or alias) in `text`. Thai has no word breaks, so this is a substring match."""
    full, low = entries(camp), text.casefold()
    return {n for n in index_names(camp) if any(a.casefold() in low for a in aliases(n, full.get(n)))}


# ── stats by CR ───────────────────────────────────────────────────────────────

def _ladder() -> list:
    return sorted(worldkit.monster_table(), key=float)


def _typical(key: str) -> dict:
    row = worldkit.monster_table()[key]
    return {stat: row[stat][1] for stat in ("ac", "hp", "attack", "dc", "damage") if row.get(stat)}


def _step(key: str, steps: int) -> str:
    ladder = _ladder()
    return ladder[min(len(ladder) - 1, ladder.index(key) + steps)]


# ── commands ──────────────────────────────────────────────────────────────────

def cmd_add(campaign: str, args) -> int:
    camp = paths.find_campaign(campaign)
    if not camp.is_dir():
        print(f"npc.py: no campaign folder {camp}", file=sys.stderr)
        return 1
    name = " ".join(args.name.split())
    if name.casefold() in (n.casefold() for n in entries(camp)):
        print(f"{name} already has a record. Update it in npcs-full.md, or grow it with `advance`.")
        return 1
    listed = next((n for n in index_names(camp) if n.casefold() == name.casefold()), None)
    name = listed or name          # a row with no full entry yet: keep the row, write the entry
    try:
        key = worldkit._cr_key(args.cr)
        stats = _typical(key)
    except (ValueError, ZeroDivisionError, KeyError):
        print(f"npc.py: bad --cr {args.cr!r} (use 0, 1/8, 1/4, 1/2 or 1-30)", file=sys.stderr)
        return 1
    now = today(camp)
    when = now[1] if now else "session start"
    voice = args.voice or VOICES[int(hashlib.sha256(name.encode("utf-8")).hexdigest(), 16) % len(VOICES)]
    cell = lambda s: (s or "").replace("|", "/").strip()  # noqa: E731
    row = "| " + " | ".join(cell(c) for c in (name, args.role, args.faction, args.location, args.attitude, args.notes)) + " |\n"
    index = camp / "npcs.md"
    text = index.read_text(encoding="utf-8") if index.exists() else f"# NPCs — {campaign}\n\n{INDEX_HEAD}"
    lines = [l for l in text.splitlines(keepends=True) if not re.fullmatch(r"\|(\s*\|)+\s*\n?", l)]  # the template's empty row
    table = [i for i, l in enumerate(lines) if l.lstrip().startswith("|")]
    if listed:
        pass
    elif table:
        if not lines[table[-1]].endswith("\n"):
            lines[table[-1]] += "\n"
        lines.insert(table[-1] + 1, row)
    else:
        lines += ["\n", INDEX_HEAD, row]
    index.write_text("".join(lines), encoding="utf-8")

    entry = (
        f"## {name}\n"
        f"- **Aliases:** {cell(args.aliases) or name}\n"
        f"- **Voice:** {voice} | <fill: how they talk: what they call themselves and others, pace, a pet phrase>\n"
        f"- **Role:** {cell(args.role)} | **CR/Level:** CR {worldkit.format_cr(key)} | **Location:** {cell(args.location)}\n"
        f"- **HP:** {stats['hp']} | **AC:** {stats['ac']} | **Attack:** <fill: name of their main attack> "
        f"+{stats['attack']} ({stats['damage']} damage) | **Save DC:** {stats['dc']} | "
        "**Notable abilities:** <fill: one or two abilities>\n"
        "- **Demeanor:** <fill: demeanor> | **Motivation:** <fill: motivation> | **Secret:** <fill: secret>\n"
        "- **Speech quirk:** <fill: speech quirk>\n"
        f"- **Attitude toward party:** {cell(args.attitude)}\n"
        f"- **Faction:** {cell(args.faction)}\n"
        "- **Current goal:** <fill: what they are doing right now>\n"
        "- **Schedule:** <fill: when and where they are usually found>\n\n"
        "### Personality\n" + "".join(f"- **{axis}:** <fill: personality>\n" for axis in AXES) +
        "\n### Relationships\n"
        "- <fill: at least two relationships, as **Knows / Owes / Hates / Fears / Allied with:** name — why>\n"
        "\n### History\n"
        "- **Background:** <fill: background, 3-5 sentences on where they come from and what made them who they are>\n"
        f"- {when}: first met the party. <fill: how they met>\n")
    full = camp / "npcs-full.md"
    old = full.read_text(encoding="utf-8") if full.exists() else f"# NPCs (full entries) — {campaign}\n"
    full.write_text(old.rstrip("\n") + "\n\n" + entry, encoding="utf-8")
    if now:
        line = _timeline(camp)
        line[name] = {"grown": now[0]}
        _save_timeline(camp, line)
    graph = graph_names(camp)
    if graph is not None and name.casefold() not in graph:   # scene-context finds them from the first scene on
        import campaign_graph
        data = campaign_graph._load(campaign)
        node_id = f"npc_{campaign_graph._slug(name)}"
        if not campaign_graph._node_by_id(data, node_id):
            data["nodes"].append({"id": node_id, "type": "npc", "name": name})
            campaign_graph._save(campaign, data)
    print(f"Created {name}: CR {worldkit.format_cr(key)}, HP {stats['hp']}, AC {stats['ac']}, attack +{stats['attack']} "
          f"({stats['damage']} damage), save DC {stats['dc']}.")
    print(f"Now write every `<fill: …>` part of `## {name}` in {full}: "
          + ", ".join(dict.fromkeys(m.split(",")[0] for m in FILL.findall(entry))) + ".")
    return 0


def cmd_check(campaign: str) -> int:
    camp = paths.find_campaign(campaign)
    todo, old, grow = unfinished(camp), backlog(camp), due(campaign)
    for name, marks in todo.items():
        print(f"UNFINISHED  {name}: write {', '.join(marks)}")
    for name, missing in old.items():
        if name not in todo:
            print(f"INCOMPLETE  {name}: {', '.join(missing)}")
    for name, days, steps in grow:
        print(f"GROWTH DUE  {name}: {days} in-world days since they last grew"
              + (f" (+{steps} step{'s' if steps > 1 else ''})" if steps else ""))
    if not (todo or old or grow):
        print("Every NPC has a full record and none is due to grow.")
        return 0
    if old:
        print(f"\nIncomplete records: add what is missing in {camp / 'npcs-full.md'} "
              "(`### History` with a **Background:** line, `- **Aliases:**` with the names used in play, an HP/AC line). "
              f"Not in graph.json: `campaign_graph.py add-node --campaign {campaign} --type npc --name \"<Name>\"`.")
    if grow:
        print(f'\nGrow one: python3 "{Path(__file__).resolve()}" -c {campaign} advance "<Name>" --what "<what they did meanwhile>"'
              "  (--levels 0 for someone who changed but did not get stronger)")
    return 1


def cmd_advance(campaign: str, args) -> int:
    camp = paths.find_campaign(campaign)
    full = camp / "npcs-full.md"
    found = entries(camp)
    name = next((n for n in found if n.casefold() == args.name.casefold()), None)
    if not name:
        print(f"No `## {args.name}` entry in {full}. Create it first with `npc.py add`.")
        return 1
    now = today(camp)
    line = _timeline(camp)
    days = now[0] - int(line.get(name, {}).get("grown", now[0])) if now else 0
    period = growth_days(campaign)
    steps = args.levels if args.levels is not None else (days // period if period else 0)
    entry = found[name]
    changes = []
    m = re.search(r"(\*\*CR/Level:\*\*\s*)([^|\n]*)", entry)
    num = m and re.search(r"\d+/\d+|\d+(?:\.\d+)?", m.group(2))
    if steps > 0 and num:
        is_level = "cr" not in m.group(2).lower() and re.search(r"lev|lv|เลเวล", m.group(2).lower())
        try:
            old_key = worldkit._cr_key(num.group(0))
            if old_key not in worldkit.monster_table():
                raise ValueError
        except (ValueError, ZeroDivisionError):
            old_key = None
        if old_key:
            new_key = _step(old_key, steps)
            new_num = str(int(float(num.group(0))) + steps) if is_level else worldkit.format_cr(new_key)
            value = m.group(2)[:num.start()] + new_num + m.group(2)[num.end():]
            entry = entry[:m.start(2)] + value + entry[m.end(2):]
            changes.append(f"{'level' if is_level else 'CR'} {num.group(0)} to {new_num}")
            was, will = _typical(old_key), _typical(new_key)
            hp = re.search(r"(\*\*HP:\*\*\s*)(\d+)", entry)
            if hp and was.get("hp") and will.get("hp"):
                new_hp = max(int(hp.group(2)), round(int(hp.group(2)) * will["hp"] / was["hp"]))
                entry = entry[:hp.start(2)] + str(new_hp) + entry[hp.end(2):]
                changes.append(f"HP {hp.group(2)} to {new_hp}")
            ac = re.search(r"(\*\*AC:\*\*\s*)(\d+)", entry)
            if ac and will.get("ac", 0) > was.get("ac", 0):
                new_ac = int(ac.group(2)) + will["ac"] - was["ac"]
                entry = entry[:ac.start(2)] + str(new_ac) + entry[ac.end(2):]
                changes.append(f"AC {ac.group(2)} to {new_ac}")
            up = [f"{label} +{will[stat] - was[stat]}" for stat, label in (("attack", "to-hit"), ("dc", "save DC"),
                                                                                ("damage", "damage per hit"))
                  if will.get(stat, 0) > was.get(stat, 0)]
            if up:
                changes.append("raise in the Attack line: " + ", ".join(up))
    when = now[1] if now else "later"
    away = f" after {days} days" if days else ""
    grew = f" ({changes[0]})" if changes else ""
    note = f"- {when}:{away}{grew} {args.what.strip()}\n"
    body = entry.rstrip("\n")
    tail = ""
    if body.endswith("---"):
        body, tail = body[:-3].rstrip("\n"), "\n\n---"
    if re.search(r"^### History\s*$", body, re.M):
        body += "\n" + note.rstrip("\n")
    else:
        body += "\n\n### History\n" + note.rstrip("\n")
    text = full.read_text(encoding="utf-8")
    full.write_text(text.replace(found[name], body + tail + "\n\n", 1).rstrip("\n") + "\n", encoding="utf-8")
    if now:
        line[name] = {"grown": now[0]}
        _save_timeline(camp, line)
    print(f"{name}: " + ("; ".join(changes) if changes else "no level change") + ".")
    print(f"History line added. Also update their Current goal, Location and Relationships in {full} if those moved.")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="NPC records: create, check, grow.")
    p.add_argument("-c", "--campaign", required=True)
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("--name", required=True)
    a.add_argument("--role", required=True)
    a.add_argument("--cr", required=True, help="challenge rating for their stats: 0, 1/8, 1/4, 1/2, 1-30")
    a.add_argument("--aliases", default="", help="every name the story uses for them, comma-separated")
    a.add_argument("--faction", default="independent")
    a.add_argument("--location", default="")
    a.add_argument("--attitude", default="neutral")
    a.add_argument("--notes", default="")
    a.add_argument("--voice", default="", choices=("",) + VOICES,
                   help="their TTS voice on the display (default: one is picked for them and kept)")
    sub.add_parser("check")
    g = sub.add_parser("advance")
    g.add_argument("name")
    g.add_argument("--what", required=True, help="what they did while the party was away")
    g.add_argument("--levels", type=int, help="steps to raise (default: by in-world time away; 0 = story only)")
    args = p.parse_args()
    if args.cmd == "add":
        return cmd_add(args.campaign, args)
    if args.cmd == "check":
        return cmd_check(args.campaign)
    return cmd_advance(args.campaign, args)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
