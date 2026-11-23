#!/usr/bin/env python3
"""
campaign_version.py — which DnE version a world was made with, and whether to update it.

Each campaign keeps `dne-version.json`: the engine version it was created with,
the version its world was last brought up to, and a version the players chose
not to update to (so they are not asked again until a newer one).

Usage:
    campaign_version.py -c <camp> stamp            # at /dne new
    campaign_version.py -c <camp> check            # at /dne load: says whether to ask the players
    campaign_version.py -c <camp> mark             # after updating the world to this version
    campaign_version.py -c <camp> mark --declined  # the players said no to this version
    campaign_version.py -c <camp> audit            # everything in this world that differs from the
                                                   # current templates, World Kit and tools
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paths import find_campaign, skill_root  # noqa: E402

FILE = "dne-version.json"


def engine_version() -> str:
    """The running engine's version, from the SKILL.md picker prefix ("vX.Y.Z ·")."""
    text = (skill_root() / "SKILL.md").read_text(encoding="utf-8")
    m = re.search(r"\bv(\d+\.\d+(?:\.\d+)?) ·", text)
    if not m:
        raise ValueError("cannot find the engine version in SKILL.md")
    return m.group(1)


def vkey(v: str | None) -> tuple:
    return tuple(int(x) for x in v.split(".")) if v else (0,)


def changelog_since(old: str | None, new: str) -> list[str]:
    """Headline additions from CHANGELOG.md for versions after `old` up to `new`."""
    path = skill_root().resolve().parent.parent / "CHANGELOG.md"
    if not path.exists():
        return []
    out, take, in_added = [], False, False
    for line in path.read_text(encoding="utf-8").splitlines():
        head = re.match(r"## \[(\d+\.\d+(?:\.\d+)?)\](.*)", line)
        if head:
            ver = head.group(1)
            take = vkey(old) < vkey(ver) <= vkey(new)
            in_added = False
            if take:
                title = head.group(2).split("—")[-1].strip()
                out.append(f"v{ver}" + (f": {title}" if title else ""))
            continue
        if line.startswith("## "):
            take = False
        if not take:
            continue
        if line.startswith("### "):
            in_added = line.startswith("### Added")
        elif in_added:
            bold = re.match(r"- \*\*(.+?)\*\*", line)
            if bold:
                out.append(f"  - {bold.group(1).rstrip('.:')}")
    return out


def _path(campaign: str) -> Path:
    camp = find_campaign(campaign)
    if not camp.is_dir():
        raise ValueError(f"no campaign folder {camp}")
    return camp / FILE


def load(campaign: str) -> dict | None:
    try:
        return json.loads(_path(campaign).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


def save(campaign: str, data: dict) -> None:
    path = _path(campaign)
    with tempfile.TemporaryDirectory(dir=path.parent) as stage:
        staged = Path(stage) / path.name
        staged.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        staged.replace(path)


def check(campaign: str) -> tuple[str, str]:
    """(status, message). status: current | update | declined | newer."""
    engine = engine_version()
    data = load(campaign)
    world = data.get("world_version") if data else None
    shown = f"v{world}" if world else "an older version (before version tracking)"
    if world and vkey(world) == vkey(engine):
        return "current", f"World is up to date with the engine (v{engine})."
    if world and vkey(world) > vkey(engine):
        return "newer", (f"This world was made with v{world}, newer than the engine (v{engine}). "
                         "Update the engine (`/dne update`) before playing.")
    if data and data.get("declined") and vkey(data["declined"]) >= vkey(engine):
        return "declined", f"World stays at {shown}; the players chose not to update to v{engine}."
    lines = [f"UPDATE AVAILABLE: this world is at {shown}; the engine is v{engine}."]
    news = changelog_since(world, engine)
    if news:
        lines += ["New since then:"] + news
    lines += ["Ask the players: bring this world up to v" + engine + "? (SKILL-commands.md → "
              "\"Update a world to the engine version\"). Yes → run `audit`, do every item, then `mark`; "
              "no → `mark --declined` (they won't be asked again until a newer version)."]
    return "update", "\n".join(lines)


#: Session Flags every campaign should carry now, with their defaults.
FLAGS = {"success_at_cost": "on", "degrees": "on", "hero_points": "off", "content": "standard", "romance": "fade", "pacing": "mixed",
         "companions": "normal", "rolls": "normal", "show_dc": "on", "turn_end": "open",
         "engine": "full", "npc_growth": "normal", "world_engine": "off",
         "lines": "(none)", "veils": "(none)"}
#: Character-sheet sections a non-caster may leave out.
OPTIONAL_SHEET = {"Spell Slots", "Known Spells / Cantrips"}


def _sections(text: str) -> list[str]:
    return [l[3:].strip() for l in text.splitlines() if l.startswith("## ")]


def _template_keys(text: str) -> list[str]:
    """Template headings as match keys: '## The Settlement — <Name>' → 'The Settlement'."""
    keys = []
    for h in _sections(text):
        key = h.split("<")[0].rstrip(" —-:").strip()
        if key and not re.match(r"Session (X|Template)\b", key):   # session-log's per-session headings
            keys.append(key)
    return keys


def _missing(template: Path, target: Path) -> list[str]:
    have = _sections(target.read_text(encoding="utf-8"))
    return [k for k in _template_keys(template.read_text(encoding="utf-8"))
            if not any(h.casefold().startswith(k.casefold()) for h in have)]


def audit(campaign: str) -> list[str]:
    """Every gap between this campaign and what the current engine writes for a new one."""
    camp = find_campaign(campaign)
    if not camp.is_dir():
        raise ValueError(f"no campaign folder {camp}")
    tpl = skill_root() / "templates"
    todo = []
    for name in ("state.md", "world.md", "npcs.md", "npcs-full.md", "session-log.md"):
        target = camp / name
        if not target.exists():
            todo.append(f"{name}: missing; create it from templates/{name}")
            continue
        for key in _missing(tpl / name, target):
            todo.append(f"{name}: add section `## {key}` (see templates/{name}; fill it from this world, don't invent canon)")
    state = (camp / "state.md").read_text(encoding="utf-8") if (camp / "state.md").exists() else ""
    flags = state.split("## Session Flags", 1)[1].split("\n## ", 1)[0] if "## Session Flags" in state else ""
    for flag, default in FLAGS.items():
        if not re.search(rf"^\s*-\s*{flag}\s*:", flags, re.M):
            ask = " (ask the table)" if flag in ("content", "romance", "pacing", "lines", "veils", "hero_points") else ""
            todo.append(f"state.md Session Flags: add `- {flag}: {default}`{ask}")
    sheet_tpl = tpl / "character-sheet.md"
    for sheet in sorted((camp / "characters").glob("*.md")) if (camp / "characters").is_dir() else []:
        gaps = [k for k in _missing(sheet_tpl, sheet) if k not in OPTIONAL_SHEET]
        if gaps:
            todo.append(f"characters/{sheet.name}: add " + ", ".join(f"`## {k}`" for k in gaps)
                        + " (Moves from the class, Bonds by asking the players, Flaws & Quirks optional)")
    kit_path = camp / "worldkit.json"
    if kit_path.exists():
        import worldkit
        try:
            kit = json.loads(kit_path.read_text(encoding="utf-8"))
        except ValueError as exc:
            kit = None
            todo.append(f"worldkit.json: invalid JSON ({exc}); fix first")
        if kit is not None:
            todo += [f"worldkit.json: fix: {e}" for e in worldkit.validate(kit, campaign)]
            todo += [f"worldkit.json: review warning: {w}" for w in worldkit.warnings(kit)]
            meta = kit.get("_meta", {})
            for field, what in (("tech_level", "0–12, what the world can build"),
                                ("status_levels", "social ranks, lowest first")):
                if field not in meta:
                    todo.append(f"worldkit.json: add `_meta.{field}` ({what})")
            for cls in kit.get("classes", []):
                for field, what in (("moves", "1–3 playbook moves"), ("template", "a quick build")):
                    if field not in cls:
                        todo.append(f"worldkit.json: class {cls.get('name')}: add `{field}` ({what})")
            for field, what in (("disadvantages", "4–8 disadvantages and quirks"),
                                ("place_tags", "3–6 place tags in this world's voice")):
                if not kit.get(field):
                    todo.append(f"worldkit.json: add `{field}` ({what})")
            bare = [m.get("name") for m in kit.get("monsters", []) if "morale" not in m]
            if bare:
                todo.append("worldkit.json: add `morale`, `instinct` and `instincts` to monsters: " + ", ".join(bare))
            if not any("rarity" in r for cat in ("equipment", "spells") for r in kit.get(cat, [])):
                todo.append("worldkit.json: mark special gear with `rarity`/`traits` (and `tl` where tech matters)")
    else:
        todo.append("worldkit.json: none (classic SRD fantasy); nothing to add unless the table wants a World Kit")
    world = (camp / "world.md").read_text(encoding="utf-8") if (camp / "world.md").exists() else ""
    if "## Factions" in world and not (camp / "factions.json").exists():
        todo.append("factions: track every faction in world.md `## Factions` with `faction.py add` "
                    "(Force/Wealth/Influence 1–5, current goal on a clock, rivals)")
    if not (camp / "calendar.json").exists():
        todo.append("calendar: `calendar.py init` from state.md's in-world date (faction turns run on it)")
    if not (camp / "graph.json").exists():
        todo.append("graph: none yet; run `/dne graph init <campaign>` (SKILL-commands.md)")
    return todo


def main() -> None:
    p = argparse.ArgumentParser(description="Track the DnE version a world was made with.")
    p.add_argument("-c", "--campaign", required=True)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("stamp", help="Record the engine version on a new campaign")
    sub.add_parser("check", help="Compare the world's version with the engine")
    sub.add_parser("audit", help="List what to change to bring this world up to the engine")
    sub.add_parser("mark", help="Record that the world was updated (or declined)").add_argument(
        "--declined", action="store_true")
    args = p.parse_args()
    try:
        engine = engine_version()
        today = date.today().isoformat()
        if args.cmd == "check":
            print(check(args.campaign)[1])
            return
        if args.cmd == "audit":
            todo = audit(args.campaign)
            print(f"Bring this world up to v{engine}: {len(todo)} item(s)" if todo else
                  f"Nothing to change: this world matches v{engine}.")
            for item in todo:
                print(f"- [ ] {item}")
            return
        data = load(args.campaign) or {}
        if args.cmd == "stamp":
            if data.get("created_with"):
                print(f"Already stamped: created with v{data['created_with']}, world at v{data.get('world_version')}.")
                return
            data = {"created_with": engine, "world_version": engine, "declined": None,
                    "history": [f"{today} created with v{engine}"]}
            msg = f"Campaign stamped with engine v{engine}."
        elif args.declined:
            data.setdefault("created_with", None)
            data.setdefault("world_version", None)
            data["declined"] = engine
            data.setdefault("history", []).append(f"{today} players declined v{engine}")
            msg = f"Noted: the players keep this world as it is (not updated to v{engine})."
        else:
            old = data.get("world_version")
            data.setdefault("created_with", None)
            data.update(world_version=engine, declined=None)
            data.setdefault("history", []).append(f"{today} world updated {('v' + old) if old else 'from untracked'} → v{engine}")
            msg = f"World marked as up to date with v{engine}."
        save(args.campaign, data)
        print(msg)
    except (OSError, ValueError) as exc:
        print(f"campaign_version.py: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    main()
