#!/usr/bin/env python3
"""
world_migrate.py — bring an existing campaign onto the world engine, safely, and take it off again.

    world_migrate.py -c <campaign> inspect            # dry run: what would be matched, what is unclear, what would change
    world_migrate.py -c <campaign> enable [--shadow]  # back the whole campaign up, then turn the engine on (or shadow it)
    world_migrate.py -c <campaign> shadow --intents '<JSON list>'   # run actions on a throwaway copy and show the result
    world_migrate.py -c <campaign> disable            # park the open turn, write what the engine knows, turn it off
    world_migrate.py -c <campaign> backups            # list the backups
    world_migrate.py -c <campaign> restore [--backup <stamp>] [--yes]   # go back; says first what would be lost

The engine's schema has its own version (world_db.SCHEMA_VERSION), separate from the plugin's.
`enable` never converts prose for you: an NPC's written Schedule stays as it is and is listed as
"waiting for you to read it" until you give that NPC a structured one. In shadow mode the engine
writes nothing to the campaign: it only logs the scene context it would have given, and `shadow`
runs actions on a separate copy, so the GM and the engine never spend the same resource twice.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import paths  # noqa: E402
import world_db as wdb  # noqa: E402

BACKUPS = ".world-backups"
SKIP = {BACKUPS, ".snapshots", ".redo-snapshots"}
EXPORT = "world-export.md"


def _slug(name: str) -> str:
    out = "".join(c if c.isalnum() else "-" for c in name.casefold()).strip("-")
    return re.sub(r"-+", "-", out) or "unnamed"


def entity_index(campaign: str) -> dict:
    """Stable ids for every NPC, PC and companion: {"entities": [{id, name, aliases, source}], "unclear": [...]}.

    Two records with the same name get -2, -3 in file order, so an id keeps meaning the same record. An alias
    that two records share, and a PC and an NPC answering to the same first name, are reported as unclear."""
    import scene_context
    seen, entities, by_alias = {}, [], {}
    for e in scene_context.entities(campaign):
        if e["kind"] == "place":
            continue
        base = f"{e['kind']}:{_slug(e['name'])}"
        seen[base] = seen.get(base, 0) + 1
        eid = base if seen[base] == 1 else f"{base}-{seen[base]}"
        entities.append({"id": eid, "name": e["name"], "aliases": e["aliases"], "source": e["source"]})
        for alias in e["aliases"]:
            by_alias.setdefault(alias.casefold(), []).append(eid)
    unclear = [{"alias": a, "could_mean": ids} for a, ids in sorted(by_alias.items()) if len(set(ids)) > 1]
    return {"entities": entities, "unclear": unclear}


def _prose_schedules(camp: Path) -> list:
    """NPCs whose Schedule is written in prose: [(name, text)]. The engine cannot use these until the GM reads them."""
    try:
        import npc
        full = npc.entries(camp)
    except Exception:
        return []
    out = []
    for name, entry in full.items():
        m = re.search(r"\*\*Schedule:\*\*\s*([^\n]+)", entry)
        if m and m.group(1).strip() and not m.group(1).strip().startswith("<"):
            out.append((name, m.group(1).strip()))
    return out


def inspect(campaign: str) -> dict:
    """Everything `enable` would do and everything it cannot decide, without changing a byte."""
    camp = paths.find_campaign(campaign)
    index = entity_index(campaign)
    with wdb.reader(campaign) as db:
        structured = set(wdb.all_of(db, "schedule")) if db is not None else set()
        version = wdb.meta(db, "schema_version", "") if db is not None else ""
    waiting = [{"npc": n, "schedule": text} for n, text in _prose_schedules(camp) if n not in structured]
    missing = [f for f in ("calendar.json", "world-map.json") if not (camp / f).exists()]
    notes = []
    if "calendar.json" in missing:
        notes.append("no calendar.json: in-world time, faction weeks and NPC growth need one (calendar.py init)")
    if "world-map.json" in missing:
        notes.append("no world-map.json: travel, caravans and news by road need places and routes (world_map.py)")
    return {"campaign": campaign, "engine_now": paths.session_flag(campaign, "world_engine", "off"),
            "schema_version": {"store": version or None, "engine": wdb.SCHEMA_VERSION},
            "entities": index["entities"], "unclear": index["unclear"], "waiting_for_the_gm": waiting,
            "would_change": [f"{camp / 'state.md'}: Session Flags gets `- world_engine: on`",
                             f"{camp / wdb.DB_NAME}: created (the engine's store)",
                             f"{camp / BACKUPS}/<time>/: a full copy of the campaign as it is now"],
            "would_not_change": "every other campaign file, until an engine action changes it in play",
            "notes": notes}


def set_flag(campaign: str, key: str, value: str) -> None:
    """Write `- key: value` in state.md → ## Session Flags (replacing the line if it is there)."""
    state = paths.find_campaign(campaign) / "state.md"
    text = state.read_text(encoding="utf-8")
    line = f"- {key}: {value}"
    pattern = re.compile(rf"^\s*-\s*{re.escape(key)}\s*:.*$", re.M)
    section = re.search(r"^## Session Flags[^\n]*\n", text, re.M)
    if section and pattern.search(text, section.end()):
        text = text[:section.end()] + pattern.sub(line, text[section.end():], count=1)
    elif section:
        text = text[:section.end()] + line + "\n" + text[section.end():]
    else:
        text = text.rstrip("\n") + f"\n\n## Session Flags\n{line}\n"
    state.write_text(text, encoding="utf-8")


def backup(campaign: str, why: str) -> dict:
    """Copy the whole campaign (snapshots and older backups aside) and record what state it was taken from."""
    camp = paths.find_campaign(campaign)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = camp / BACKUPS / stamp
    n = 1
    while dest.exists():
        n += 1
        dest = camp / BACKUPS / f"{stamp}-{n}"
    shutil.copytree(camp, dest, ignore=lambda _d, names: [x for x in names if x in SKIP])
    with wdb.reader(campaign) as db:
        turns = db.execute("SELECT COUNT(*) AS n FROM turns").fetchone()["n"] if db is not None else 0
        revision = wdb.revision(db) if db is not None else 0
    manifest = {"campaign": campaign, "taken": dest.name, "why": why, "revision": revision, "turns": turns,
                "world_minute": wdb.now_minute(campaign), "state_hash": wdb.state_hash(campaign),
                "files": sorted(str(p.relative_to(dest)) for p in dest.rglob("*") if p.is_file()),
                "covers": "every file of the campaign folder except .snapshots, .redo-snapshots and earlier backups",
                "format": {"store": "sqlite (world.db), schema " + str(wdb.SCHEMA_VERSION), "files": "as written"}}
    (dest / "manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8")
    return {"backup": dest.name, "path": str(dest), **{k: manifest[k] for k in ("revision", "turns", "world_minute")}}


def enable(campaign: str, shadow: bool = False) -> dict:
    """Back up, then turn the engine on (or to shadow). The campaign's own files are not converted."""
    report = inspect(campaign)
    made = backup(campaign, "before enabling the world engine" + (" (shadow)" if shadow else ""))
    set_flag(campaign, "world_engine", "shadow" if shadow else "on")
    if not shadow:
        with wdb.writer(campaign) as db:              # create the store and note what each name means from now on
            for e in report["entities"]:
                wdb.put(db, "entity", e["id"], {"name": e["name"], "aliases": e["aliases"], "source": e["source"]})
    return {"enabled": "shadow" if shadow else "on", "backup": made, "unclear": report["unclear"],
            "waiting_for_the_gm": report["waiting_for_the_gm"], "notes": report["notes"]}


def shadow_run(campaign: str, intents: list, text: str = "shadow run") -> dict:
    """Run engine actions on a throwaway copy of the campaign and report what they would have done.

    The real campaign is not touched, so the GM can resolve the same thing by hand and compare."""
    camp = paths.find_campaign(campaign)
    before = wdb.state_hash(campaign)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        copy = root / "campaigns" / campaign
        shutil.copytree(camp, copy, ignore=lambda _d, names: [x for x in names if x in SKIP])
        saved = {k: os.environ.get(k) for k in ("DNE_CAMPAIGN_ROOT", "DNE_RUNTIME_DIR", "DNE_OUTBOX_LOG")}
        os.environ.update(DNE_CAMPAIGN_ROOT=str(root), DNE_RUNTIME_DIR=str(root / "rt"), DNE_OUTBOX_LOG=str(root / "out.jsonl"))
        try:
            (root / "rt").mkdir()
            set_flag(campaign, "world_engine", "on")
            set_flag(campaign, "display", "none")
            import turn
            turn.begin(campaign, text)
            out = turn.resolve(campaign, intents)
            changed = sorted(str(p.relative_to(copy)) for p in copy.rglob("*")
                             if p.is_file() and p.name not in (wdb.DB_NAME,) and ".snapshots" not in p.parts
                             and (not (camp / p.relative_to(copy)).exists()
                                  or (camp / p.relative_to(copy)).read_bytes() != p.read_bytes()))
        finally:
            for k, v in saved.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
    return {"would_have": out, "files_it_would_change": [c for c in changed if c != "state.md"],
            "real_campaign_untouched": wdb.state_hash(campaign) == before}


def export(campaign: str) -> str:
    """What the engine knows, as a page a GM can run the campaign from by hand."""
    with wdb.reader(campaign) as db:
        if db is None:
            return "# World engine export\n\nThe engine has no store for this campaign.\n"
        lines = ["# World engine export", "",
                 f"*Written when the engine was turned off. Revision {wdb.revision(db)}, in-world minute {wdb.now_minute(campaign)}. "
                 "The store (world.db) is kept: turning the engine back on continues from here.*", ""]
        pending = db.execute("SELECT * FROM events WHERE status='pending' ORDER BY due_minute IS NULL, due_minute, event_id").fetchall()
        lines += ["## Still to happen", ""] + [
            f"- {r['event_id']} — due minute {r['due_minute']} — {json.loads(r['effect']).get('text') or r['effect']}"
            + (f" (because: {r['cause_id']})" if r["cause_id"] else "") for r in pending] + ([""] if pending else ["- nothing queued", ""])
        for kind, title in (("route", "Roads and bridges"), ("market", "Markets"), ("caravan", "Caravans"), ("npcpos", "Where NPCs are"),
                            ("appointment", "Appointments"), ("belief", "Who believes what"), ("heat", "Heat"),
                            ("beat", "Story beats"), ("situation", "Situations"), ("case", "Cases"), ("thread", "Threads to pay back"),
                            ("upkeep", "Supplies"), ("truce", "Truces"), ("decision", "Faction decisions")):
            rows = wdb.all_of(db, kind)
            if rows:
                lines += [f"## {title}", ""] + [f"- **{k}**: {json.dumps(v, ensure_ascii=False)}" for k, v in rows.items()] + [""]
    return "\n".join(lines)


def disable(campaign: str) -> dict:
    """Turn the engine off for now: nothing half done, a readable record left behind, history kept."""
    import turn
    parked = None
    if wdb.db_path(campaign).exists():
        view = turn.resume(campaign)                  # finish what a crash left, deliver what is waiting
        if view.get("turn_id") and view.get("status") in ("open", "waiting_for_player"):
            with wdb.writer(campaign) as db:
                db.execute("UPDATE turns SET status='abandoned' WHERE turn_id=?", (view["turn_id"],))
                db.execute("UPDATE requests SET status='stale' WHERE turn_id=? AND status='open'", (view["turn_id"],))
            parked = {"turn_id": view["turn_id"], "was_waiting_on": [w["question"] for w in view.get("waiting", [])]}
    camp = paths.find_campaign(campaign)
    (camp / EXPORT).write_text(export(campaign), encoding="utf-8")
    set_flag(campaign, "world_engine", "off")
    return {"disabled": True, "parked_turn": parked, "export": str(camp / EXPORT),
            "kept": f"{camp / wdb.DB_NAME} (queue and history): `enable` continues from it"}


def backups(campaign: str) -> list:
    root = paths.find_campaign(campaign) / BACKUPS
    out = []
    for d in sorted(root.iterdir()) if root.is_dir() else []:
        try:
            out.append(json.loads((d / "manifest.json").read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return out


def restore(campaign: str, stamp: "str | None" = None, yes: bool = False) -> dict:
    """Go back to a backup. Without `yes` it only says what would be lost."""
    found = backups(campaign)
    if not found:
        return {"error": "no backups for this campaign"}
    chosen = next((m for m in found if m["taken"] == stamp), None) if stamp else found[-1]
    if not chosen:
        return {"error": f"no backup {stamp!r}", "have": [m["taken"] for m in found]}
    with wdb.reader(campaign) as db:
        turns = db.execute("SELECT COUNT(*) AS n FROM turns").fetchone()["n"] if db is not None else 0
    now = wdb.now_minute(campaign)
    lost = {"turns": max(0, turns - int(chosen.get("turns", 0))),
            "in_world_minutes": (now - chosen["world_minute"]) if now is not None and chosen.get("world_minute") is not None else None}
    loss = (f"{lost['turns']} engine turn(s)" + (f" and {lost['in_world_minutes'] // 1440} in-world day(s) "
            f"{lost['in_world_minutes'] % 1440 // 60}h of play" if lost["in_world_minutes"] else "") + f" since {chosen['taken']} would be lost")
    if not yes:
        return {"would_restore": chosen["taken"], "would_lose": lost, "say": loss + ". Run again with --yes to go back."}
    camp = paths.find_campaign(campaign)
    safety = backup(campaign, f"before restoring {chosen['taken']}")
    src = camp / BACKUPS / chosen["taken"]
    for item in list(camp.iterdir()):
        if item.name in SKIP:
            continue
        shutil.rmtree(item) if item.is_dir() else item.unlink()
    for item in src.iterdir():
        if item.name == "manifest.json":
            continue
        shutil.copytree(item, camp / item.name) if item.is_dir() else shutil.copy2(item, camp / item.name)
    return {"restored": chosen["taken"], "lost": lost, "safety_backup": safety["backup"],
            "say": loss.replace("would be", "were") + f". The state just before this is kept as backup {safety['backup']}."}


def main() -> int:
    p = argparse.ArgumentParser(description="Move a campaign onto or off the world engine.")
    p.add_argument("-c", "--campaign", required=True)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("inspect")
    e = sub.add_parser("enable")
    e.add_argument("--shadow", action="store_true")
    s = sub.add_parser("shadow")
    s.add_argument("--intents", required=True)
    sub.add_parser("disable")
    sub.add_parser("backups")
    r = sub.add_parser("restore")
    r.add_argument("--backup")
    r.add_argument("--yes", action="store_true")
    args = p.parse_args()
    if args.cmd == "inspect":
        out = inspect(args.campaign)
    elif args.cmd == "enable":
        out = enable(args.campaign, args.shadow)
    elif args.cmd == "shadow":
        out = shadow_run(args.campaign, json.loads(args.intents))
    elif args.cmd == "disable":
        out = disable(args.campaign)
    elif args.cmd == "backups":
        out = [{k: m.get(k) for k in ("taken", "why", "turns", "revision", "world_minute")} for m in backups(args.campaign)]
    else:
        out = restore(args.campaign, args.backup, args.yes)
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
