#!/usr/bin/env python3
"""
sheet.py — Braid character sheets (System: core / story): create, check, show, XP and advances.

    sheet.py -c <campaign> new --name "Mira Vale" --concept "..." --drive "..." --flaw "..."
                               --approaches "wits=2,finesse=1,heart=1,force=0,grit=-1" --labels "Smuggler,Ex-navy pilot"
                               [--gear "a,b"] [--bonds "Theo: owes her his life"] [--player P]
        Writes characters/<name>.md from templates/sheets/core.md. The approaches must be +2 +1 +1 0 -1 in any
        order; 2-3 labels.
    sheet.py -c <campaign> check [<name>]       every sheet (or one) against the template and the rules; exit 1 on a problem
    sheet.py -c <campaign> show <name>          the sheet, with harm, stress and conditions from the world engine
    sheet.py -c <campaign> xp <name> --why "..." --event <id> [--mark N]
        Marks XP once per event id (a retry is refused, not paid twice) and logs it on the sheet.
    sheet.py -c <campaign> advance <name> (--raise <approach> | --label "..." | --move "...")
        Spends 5 XP on one advance and writes it on the sheet.

Where things live: the sheet holds who the character is, approaches, labels, bonds, gear, moves and XP. Harm and
stress are world-engine tracks (owner = the character, ids `harm` and `stress`): pushes and hits mark them inside
turns, so they undo with the turn. This script only reads them; the sheet never carries those numbers.
Numbers: data/braid.json. Rules: SKILL-core.md.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import paths  # noqa: E402

RULES = json.loads((HERE.parent / "data" / "braid.json").read_text(encoding="utf-8"))
TEMPLATE = HERE.parent / "templates" / "sheets" / "core.md"
APPROACHES = RULES["approaches"]
NONE_YET = re.compile(r"^\(none yet")


# ── reading a sheet ───────────────────────────────────────────────────────────

def sections(text: str) -> dict:
    """{heading: [body lines]} for every `## ` section."""
    out, cur = {}, None
    for line in text.splitlines():
        if line.startswith("## "):
            cur = line[3:].strip()
            out[cur] = []
        elif cur is not None:
            out[cur].append(line)
    return out


def _items(body: list) -> list:
    """The `- ` lines of a section that are filled in (not a <placeholder> or "(none yet…)")."""
    out = []
    for line in body:
        item = line.strip()[2:].strip() if line.strip().startswith("- ") else ""
        if item and not item.startswith("<") and not NONE_YET.match(item):
            out.append(item)
    return out


def _field(text: str, name: str) -> str:
    m = re.search(rf"\*\*{name}:\*\*\s*([^\n]*?)(?=\s{{2,}}\*\*|$)", text, re.M)
    return m.group(1).strip() if m else ""


def parse(text: str) -> dict:
    """A Braid sheet as data: name, concept, drive, flaw, xp, advances, approaches, labels, bonds, gear, moves, log."""
    sec = sections(text)
    m = re.search(r"^#\s+(.+?)\s*$", text, re.M)
    xp = re.search(r"\*\*XP:\*\*\s*(-?\d+)", text)
    adv = re.search(r"\*\*Advances:\*\*\s*(\d+)", text)
    approaches = {}
    for line in sec.get("Approaches", []):
        a = re.match(r"\s*-\s*\*\*(\w+):\*\*\s*([+-]?\d+)", line)
        if a:
            approaches[a.group(1).casefold()] = int(a.group(2))
    log = _items(sec.get("XP Log", []))
    return {"name": m.group(1).strip() if m else "", "concept": _field(text, "Concept"), "drive": _field(text, "Drive"),
            "flaw": _field(text, "Flaw"), "xp": int(xp.group(1)) if xp else None, "advances": int(adv.group(1)) if adv else None,
            "approaches": approaches, "labels": _items(sec.get("Labels", [])), "bonds": _items(sec.get("Bonds", [])),
            "gear": _items(sec.get("Gear", [])), "moves": _items(sec.get("Moves", [])),
            "taken": _items(sec.get("Advances", [])), "events": [i.split(":")[0].strip() for i in log],
            "sections": list(sec)}


def is_braid_sheet(text: str) -> bool:
    return bool(re.search(r"^## Approaches\s*$", text, re.M))


def find(campaign: str, name: str) -> Path:
    path = paths.find_character_file(campaign, name)
    if not path.exists():
        raise FileNotFoundError(f"no sheet for {name!r} in {path.parent}")
    return path


def approach(campaign: str, actor: str, which: str) -> "int | None":
    """The actor's approach modifier from their sheet, or None (no sheet, no such approach)."""
    try:
        return parse(find(campaign, actor).read_text(encoding="utf-8")).get("approaches", {}).get(str(which).casefold())
    except (OSError, ValueError, LookupError):
        return None


def engine_state(campaign: str, names: list) -> dict:
    """{"harm": {value, max}, "stress": {…}, "conditions": [...]} from world.db, matching any of `names`."""
    keys = {n.strip().casefold() for n in names if n and n.strip()}
    out = {tid: {"value": RULES["tracks"][tid]["min"], "max": RULES["tracks"][tid]["max"]} for tid in ("harm", "stress")}
    out["conditions"] = []
    try:
        import world_db as wdb
        with wdb.reader(campaign) as db:
            if db is None:
                return out
            for tid in ("harm", "stress"):
                for k in keys:
                    rec = wdb.get(db, "track", f"{k}/{tid}")
                    if rec:
                        out[tid] = {"value": rec["value"], "max": rec["max"]}
                        break
            out["conditions"] = [f"{c['name']} {int(c.get('mod') or 0):+d}" for c in wdb.all_of(db, "condition").values()
                                 if str(c.get("owner", "")).casefold() in keys]
            # every other track and pool the engine holds for them (composure, tokens, realm, …)
            out["other"] = [f"{r['id'].capitalize()} {r['value']}/{r.get('max', '?')}" for kind in ("track", "pool")
                            for r in wdb.all_of(db, kind).values()
                            if str(r.get("owner", "")).casefold() in keys and r.get("id") not in ("harm", "stress")
                            and isinstance(r.get("value"), int)]
    except Exception:
        pass
    return out


def names_of(path: Path, sheet: dict) -> list:
    """Every name the engine may file this character under: the full name, the first name, the file name."""
    full = sheet.get("name") or path.stem
    return [full, full.split()[0] if full.split() else full, path.stem]


# ── checking ──────────────────────────────────────────────────────────────────

def _template_headings() -> list:
    return [h for h in sections(TEMPLATE.read_text(encoding="utf-8"))]


def problems(text: str) -> list:
    """What is wrong with a Braid sheet, as fixes to make (empty = fine)."""
    s, out = parse(text), []
    for h in _template_headings():
        if h not in s["sections"]:
            out.append(f"add `## {h}` (see templates/sheets/core.md)")
    if not s["name"] or s["name"].startswith("<"):
        out.append("the first line must be `# <the character's name>`")
    for f in ("concept", "drive", "flaw"):
        if not s[f] or s[f].startswith("<"):
            out.append(f"fill **{f.capitalize()}:**")
    lo, hi = RULES["approach_min"], RULES["approach_max"]
    for a in APPROACHES:
        v = s["approaches"].get(a)
        if v is None:
            out.append(f"approach {a.capitalize()} is missing (`- **{a.capitalize()}:** +0`)")
        elif not lo <= v <= hi:
            out.append(f"approach {a.capitalize()} is {v:+d}: approaches run {lo:+d} to {hi:+d}")
    extra = [a for a in s["approaches"] if a not in APPROACHES]
    if extra:
        out.append(f"unknown approach {', '.join(extra)}: Braid has {', '.join(a.capitalize() for a in APPROACHES)}")
    raises = sum(1 for t in s["taken"] if t.casefold().startswith("raise"))
    if len(s["approaches"]) == len(APPROACHES) and sum(s["approaches"].values()) != sum(RULES["start_array"]) + raises:
        out.append(f"approaches add up to {sum(s['approaches'].values()):+d}, but +2 +1 +1 0 -1 plus {raises} raise(s) "
                   f"is {sum(RULES['start_array']) + raises:+d}")
    if len(s["labels"]) < RULES["labels_at_start"][0]:
        out.append(f"at least {RULES['labels_at_start'][0]} labels (`- <label>: <what it lets them do>`)")
    if s["xp"] is None or s["xp"] < 0:
        out.append("the **XP:** line needs a number (`**XP:** 0 / 5`)")
    if s["advances"] is None or s["advances"] != len(s["taken"]):
        out.append(f"**Advances:** should be {len(s['taken'])} (one per line under `## Advances`)")
    return out


# ── writing ───────────────────────────────────────────────────────────────────

def set_section(text: str, heading: str, items: list) -> str:
    """Replace the `- ` lines of a section with `items` (other lines in it are kept)."""
    lines, out, inside, done = text.splitlines(), [], False, False
    for line in lines:
        if line.startswith("## "):
            if inside and not done:
                out += [f"- {i}" for i in items] + [""]
                done = True
            inside = line[3:].strip() == heading
            out.append(line)
            continue
        if inside and line.strip().startswith("- "):
            if not done:
                out += [f"- {i}" for i in items]
                done = True
            continue
        out.append(line)
    if inside and not done:
        out += [f"- {i}" for i in items]
    return "\n".join(out) + "\n"


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def cmd_new(campaign: str, a) -> int:
    name = " ".join(a.name.split())
    try:
        given = {k.strip().casefold(): int(v) for k, v in (p.split("=") for p in a.approaches.split(",") if p.strip())}
    except ValueError:
        print("sheet.py: --approaches is name=value pairs, e.g. wits=2,finesse=1,heart=1,force=0,grit=-1", file=sys.stderr)
        return 1
    if set(given) != set(APPROACHES) or sorted(given.values()) != sorted(RULES["start_array"]):
        print(f"sheet.py: give each of {', '.join(APPROACHES)} one of +2 +1 +1 0 -1 (got {a.approaches})", file=sys.stderr)
        return 1
    labels = [x.strip() for x in a.labels.split(",") if x.strip()]
    lo, hi = RULES["labels_at_start"]
    if not lo <= len(labels) <= hi:
        print(f"sheet.py: a new character has {lo}-{hi} labels (got {len(labels)})", file=sys.stderr)
        return 1
    path = paths.find_campaign(campaign) / "characters" / f"{paths.norm_key(name)}.md"
    if path.exists():
        print(f"sheet.py: {path} already exists", file=sys.stderr)
        return 1
    text = TEMPLATE.read_text(encoding="utf-8").replace("# <Name>", f"# {name}", 1)
    for old, new in (("<player>", a.player or "—"), ("<campaign>", campaign), ("<name>", name.split()[0]),
                     ("<who they are, in one sentence>", a.concept), ("<what they want; acting on it when it costs them earns XP>", a.drive),
                     ("<what gets them in trouble; it earns XP when it does>", a.flaw)):
        text = text.replace(old, new)
    for k, v in given.items():
        text = re.sub(rf"(- \*\*{k.capitalize()}:\*\*) \+0", rf"\g<1> {v:+d}", text)
    text = set_section(text, "Labels", labels)
    if a.bonds:
        text = set_section(text, "Bonds", [b.strip() for b in a.bonds.split(";") if b.strip()])
    if a.gear:
        text = set_section(text, "Gear", [g.strip() for g in a.gear.split(",") if g.strip()])
    path.parent.mkdir(parents=True, exist_ok=True)
    _write(path, text)
    left = problems(text)
    print(f"Created {path}." + ("" if not left else " Still to fill: " + "; ".join(left)))
    return 0


def cmd_check(campaign: str, name: "str | None") -> int:
    cdir = paths.find_campaign(campaign) / "characters"
    files = [find(campaign, name)] if name else sorted(cdir.glob("*.md"))
    bad = 0
    for f in files:
        text = f.read_text(encoding="utf-8")
        found = problems(text) if is_braid_sheet(text) else ["not a Braid sheet: write it again with `sheet.py new`"]
        if found:
            bad += 1
            print(f"characters/{f.name}: " + "; ".join(found))
        else:
            print(f"characters/{f.name}: ok")
    if not files:
        print("No character sheets yet: `sheet.py new` makes one.")
    return 1 if bad else 0


def cmd_show(campaign: str, name: str) -> int:
    path = find(campaign, name)
    s = parse(path.read_text(encoding="utf-8"))
    st = engine_state(campaign, names_of(path, s))
    print(f"{s['name']} — {s['concept']}")
    print(f"Drive: {s['drive']} | Flaw: {s['flaw']} | XP {s['xp']}/{RULES['xp_per_advance']}, advances {s['advances']}")
    print("Approaches: " + ", ".join(f"{a.capitalize()} {s['approaches'].get(a, 0):+d}" for a in APPROACHES))
    print("Labels: " + "; ".join(s["labels"]))
    print(f"Harm {st['harm']['value']}/{st['harm']['max']} | Stress {st['stress']['value']}/{st['stress']['max']}"
          + "".join(f" | {o}" for o in st.get("other", []))
          + (f" | Conditions: {', '.join(st['conditions'])}" if st["conditions"] else ""))
    for part in ("bonds", "gear", "moves"):
        if s[part]:
            print(f"{part.capitalize()}: " + "; ".join(s[part]))
    return 0


def cmd_xp(campaign: str, name: str, mark: int, why: str, event: str) -> int:
    path = find(campaign, name)
    text = path.read_text(encoding="utf-8")
    s = parse(text)
    event = event.strip().replace(":", "-")
    if event in s["events"]:
        print(f"{s['name']}: XP for {event!r} was already marked (see ## XP Log); nothing changed.")
        return 1
    if mark < 1:
        print("sheet.py: --mark is 1 or more", file=sys.stderr)
        return 1
    total = (s["xp"] or 0) + mark
    text = re.sub(r"(\*\*XP:\*\*\s*)-?\d+", rf"\g<1>{total}", text, count=1)
    text = set_section(text, "XP Log", _items(sections(text).get("XP Log", [])) + [f"{event}: +{mark} {why.strip()}"])
    _write(path, text)
    per = RULES["xp_per_advance"]
    print(f"{s['name']}: +{mark} XP ({why.strip()}), now {total}/{per}."
          + (f" An advance is ready: sheet.py -c {campaign} advance \"{s['name']}\" --raise <approach> | --label | --move"
             if total >= per else ""))
    return 0


def cmd_advance(campaign: str, name: str, a) -> int:
    path = find(campaign, name)
    text = path.read_text(encoding="utf-8")
    s = parse(text)
    per = RULES["xp_per_advance"]
    if (s["xp"] or 0) < per:
        print(f"{s['name']} has {s['xp']} XP; an advance costs {per}.")
        return 1
    if a.raise_:
        key = a.raise_.casefold()
        if key not in APPROACHES:
            print(f"sheet.py: no approach {a.raise_!r} (one of {', '.join(APPROACHES)})", file=sys.stderr)
            return 1
        old = s["approaches"].get(key, 0)
        if old >= RULES["approach_max"]:
            print(f"{s['name']}'s {key.capitalize()} is already {old:+d}, the most an approach can be.")
            return 1
        text = re.sub(rf"(- \*\*{key.capitalize()}:\*\*\s*)[+-]?\d+", rf"\g<1>{old + 1:+d}", text, count=1)
        took = f"raise: {key.capitalize()} {old:+d} → {old + 1:+d}"
    elif a.label:
        text = set_section(text, "Labels", s["labels"] + [a.label.strip()])
        took = f"label: {a.label.strip().split(':')[0]}"
    else:
        text = set_section(text, "Moves", s["moves"] + [a.move.strip()])
        took = f"move: {a.move.strip()}"
    text = re.sub(r"(\*\*XP:\*\*\s*)-?\d+", rf"\g<1>{s['xp'] - per}", text, count=1)
    text = re.sub(r"(\*\*Advances:\*\*\s*)\d+", rf"\g<1>{len(s['taken']) + 1}", text, count=1)
    text = set_section(text, "Advances", s["taken"] + [took])
    _write(path, text)
    print(f"{s['name']}: {took} ({per} XP spent, {s['xp'] - per} left).")
    return 0


def main(argv: "list | None" = None) -> int:
    p = argparse.ArgumentParser(description="Braid character sheets: new, check, show, xp, advance.")
    p.add_argument("-c", "--campaign", required=True)
    sub = p.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("new")
    for f in ("name", "concept", "drive", "flaw", "approaches", "labels"):
        n.add_argument(f"--{f}", required=True)
    n.add_argument("--gear", default="")
    n.add_argument("--bonds", default="", help="'Name: what ties you; Name2: ...'")
    n.add_argument("--player", default="")
    c = sub.add_parser("check")
    c.add_argument("name", nargs="?")
    sub.add_parser("show").add_argument("name")
    x = sub.add_parser("xp")
    x.add_argument("name")
    x.add_argument("--why", required=True)
    x.add_argument("--event", required=True, help="one id per thing earned (e.g. s3-drive): a retry is refused")
    x.add_argument("--mark", type=int, default=1)
    v = sub.add_parser("advance")
    v.add_argument("name")
    g = v.add_mutually_exclusive_group(required=True)
    g.add_argument("--raise", dest="raise_")
    g.add_argument("--label")
    g.add_argument("--move")
    a = p.parse_args(argv)
    try:
        if paths.campaign_system(a.campaign) == "d20":
            print(f"sheet.py makes Braid sheets; campaign {a.campaign!r} is 5e (d20) and keeps its own character sheets.",
                  file=sys.stderr)
            return 2
        if a.cmd == "new":
            return cmd_new(a.campaign, a)
        if a.cmd == "check":
            return cmd_check(a.campaign, a.name)
        if a.cmd == "show":
            return cmd_show(a.campaign, a.name)
        if a.cmd == "xp":
            return cmd_xp(a.campaign, a.name, a.mark, a.why, a.event)
        return cmd_advance(a.campaign, a.name, a)
    except (OSError, ValueError, LookupError) as exc:
        print(f"sheet.py: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
