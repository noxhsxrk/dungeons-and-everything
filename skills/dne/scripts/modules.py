#!/usr/bin/env python3
"""
modules.py — Braid modules: optional rules a campaign switches on in Session Flags (`- modules: composure, clues`).

A module is one data file, data/modules/<id>.json, its rules text for the GM, data/modules/<id>.md (40 lines at
most), and, only when it needs an engine action of its own, scripts/mod_<id>.py (named in the JSON's `script`).
A module adds tracks, pools, thresholds and tables over Braid's one roll; it never adds a second way to roll.
Shared ids are shared tracks: panic's `stress` is the stress a push marks.

  modules.py list                          every module: id, name, when to use it
  modules.py show <id>                     its data and rules
  modules.py check [<id> …] [-c <camp>]    requires, conflicts, unknown ids, more than 8 switched on
  modules.py rules [<id> …] [-c <camp>]    the rules text of those modules only (the campaign's switched-on ones)
  modules.py apply -c <camp>               prints the engine action that gives every PC the modules' tracks

Engine action: {"action": "modules", "apply": true} (turn.py help modules).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.modules.setdefault("modules", sys.modules[__name__])   # run as a script, `import modules` must still mean this one
import mechanics  # noqa: E402
import paths  # noqa: E402
import turn  # noqa: E402
import world_db as wdb  # noqa: E402

DIR = HERE.parent / "data" / "modules"
LIMIT = 8                     # more switched on than this is a warning (plan §2: our default)
RULES_LINES = 40              # rules text per module, at most
OWNERS = ("pc", "party")
FIELDS = {"id": str, "name": str, "use_when": str, "genres": list, "requires": list, "conflicts": list,
          "tracks": list, "pools": list, "tables": dict, "numbers": dict}


# ── reading ───────────────────────────────────────────────────────────────────

def catalog() -> dict:
    """{id: module} for every data/modules/<id>.json."""
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(DIR.glob("*.json"))}


def load(mid: str) -> dict:
    if not re.fullmatch(r"[a-z0-9_]+", str(mid)):
        raise ValueError(f"module id {mid!r}: lower-case letters, digits and _ only")
    path = DIR / f"{mid}.json"
    if not path.exists():
        raise ValueError(f"no module {mid!r} (modules.py list)")
    return json.loads(path.read_text(encoding="utf-8"))


def rules_of(mid: str) -> str:
    return (DIR / f"{mid}.md").read_text(encoding="utf-8")


def enabled(campaign: str) -> list:
    """The campaign's `- modules: a, b` Session Flag as a list (none / (none) / missing = [])."""
    try:
        text = (paths.find_campaign(campaign) / "state.md").read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        return []
    block = re.search(r"^## Session Flags[^\n]*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    m = block and re.search(r"^\s*-\s*modules\s*:\s*(.*)$", block.group(1), re.M | re.I)
    ids = [x.strip().casefold() for x in re.split(r"[,\s]+", m.group(1)) if x.strip()] if m else []
    return [] if ids in (["none"], ["(none)"]) else list(dict.fromkeys(ids))


def problems(ids: list) -> "tuple[list, list]":
    """(errors, warnings) for a set of switched-on modules: unknown ids, a missing requirement, a conflict, too many."""
    known, errors = catalog(), []
    for mid in ids:
        if mid not in known:
            errors.append(f"unknown module {mid!r}")
            continue
        for need in known[mid].get("requires") or []:
            if need not in ids:
                errors.append(f"{mid} requires {need}: switch it on too")
        for other in ids:
            if other != mid and other in known and (other in (known[mid].get("conflicts") or [])
                                                    or mid in (known[other].get("conflicts") or [])) and mid < other:
                errors.append(f"{mid} and {other} conflict: pick one")
    warnings = [f"{len(ids)} modules switched on: more than {LIMIT} is a lot of rules to keep in mind"] if len(ids) > LIMIT else []
    return errors, warnings


def validate(mid: str) -> list:
    """What is wrong with one module's files (the format every module must keep)."""
    try:
        mod = load(mid)
    except (ValueError, json.JSONDecodeError) as exc:
        return [str(exc)]
    out = [f"{f}: must be a {t.__name__}" for f, t in FIELDS.items() if not isinstance(mod.get(f), t)]
    if out:
        return out
    if mod["id"] != mid:
        out.append(f"id {mod['id']!r} is not the file name {mid!r}")
    md = DIR / f"{mid}.md"
    if not md.exists():
        out.append(f"no rules text {md.name}")
    elif len(md.read_text(encoding="utf-8").splitlines()) > RULES_LINES:
        out.append(f"{md.name} is longer than {RULES_LINES} lines")
    known = catalog()
    out += [f"{k} names unknown module {x!r}" for k in ("requires", "conflicts") for x in mod[k] if x not in known]
    import story_gen
    out += [f"genre {g!r} is not a story_axes id" for g in mod["genres"] if g not in story_gen.genre_ids()]
    for name, entries in mod["tables"].items():
        if not entries or not all(isinstance(e, str) and e.strip() for e in entries):
            out.append(f"table {name} must be a non-empty list of text")
    for t in mod["tracks"]:
        if not t.get("id") or t.get("owner") not in OWNERS:
            out.append(f"track {t.get('id')!r}: needs an id and owner pc|party")
        out += [f"track {t.get('id')}: threshold table {th['table']!r} is not in tables"
                for th in t.get("thresholds") or [] if th.get("table") and th["table"] not in mod["tables"]]
    out += [f"pool {p.get('id')!r}: needs an id and owner pc|party" for p in mod["pools"]
            if not p.get("id") or p.get("owner") not in OWNERS]
    if mod.get("script") and not (HERE / f"{mod['script']}.py").exists():
        out.append(f"script {mod['script']}.py does not exist")
    return out


def _import_scripts() -> None:
    """Each module's own engine actions register on import, like the engine's other modules."""
    for mod in catalog().values():
        if mod.get("script"):
            __import__(mod["script"])


# ── the engine side ───────────────────────────────────────────────────────────

def need(ctx, mid: str) -> "str | None":
    """An error when module `mid` may not run in this campaign (5e, or not switched on); None when it may."""
    if paths.campaign_system(ctx.campaign) == "d20":
        return f"{mid} is a Braid module (System: core or story)"
    if mid not in enabled(ctx.campaign):
        return f"module {mid} is not switched on: add it to `- modules:` in Session Flags"
    return None


def _same(a: dict, b: dict) -> bool:
    return (int(a["at"]), a.get("dir", "up"), a.get("note", "")) == (int(b["at"]), b.get("dir", "up"), b.get("note", ""))


def ensure(ctx, mid: str, owners: list) -> list:
    """Give each owner (PC names; "party" tracks ignore it) the tracks and pools module `mid` declares. A track that
    exists keeps its value and size and only gains the module's thresholds; a pool that exists is left alone. Safe
    to repeat. Returns what was made or changed."""
    mod, made = load(mid), []
    for decl in mod["tracks"]:
        for owner in (["party"] if decl["owner"] == "party" else owners):
            cur = wdb.get(ctx.db, "track", mechanics._key(owner, decl["id"]))
            base = cur or mechanics._new_track(owner, decl["id"], mechanics._braid(ctx))
            marks = list(base["thresholds"])
            for th in decl.get("thresholds") or []:
                th = {**th, "table": mod["tables"][th["table"]]} if th.get("table") else dict(th)   # inline: self-contained
                if not any(_same(th, have) for have in marks):
                    marks.append(th)
            if cur and len(marks) == len(cur["thresholds"]):
                continue
            size = base if cur else {"min": decl.get("min", base["min"]), "max": decl.get("max", base["max"])}
            mechanics.change_track(ctx, owner, decl["id"], set_to=None if cur else decl.get("start"), why=f"module {mid}",
                                   define={"min": size["min"], "max": size["max"], "thresholds": marks})
            made.append(f"{owner} {decl['id']}")
    for decl in mod["pools"]:
        for owner in (["party"] if decl["owner"] == "party" else owners):
            if wdb.get(ctx.db, "pool", mechanics._key(owner, decl["id"])) is None:
                mechanics._pool(ctx, {**{k: v for k, v in decl.items() if k != "owner"}, "action": "pool", "owner": owner})
                made.append(f"{owner} {decl['id']}")
    return made


def prune(ctx, off: list) -> list:
    """Take the thresholds of switched-off modules back off the tracks (panic's off: stress keeps only its own).
    The tracks themselves and their values stay: a number in play is never thrown away."""
    gone = []
    for key, rec in wdb.all_of(ctx.db, "track").items():
        drop = [th for mid in off for decl in load(mid)["tracks"] if decl["id"].casefold() == rec["id"].casefold()
                for th in decl.get("thresholds") or []]
        kept = [t for t in rec["thresholds"] if not any(_same(t, d) for d in drop)]
        if len(kept) != len(rec["thresholds"]):
            mechanics.change_track(ctx, rec["owner"], rec["id"], why="module off",
                                   define={"min": rec["min"], "max": rec["max"], "thresholds": kept})
            gone.append(f"{rec['owner']} {rec['id']}")
    return gone


@turn.handler("modules")
def _modules(ctx, intent: dict) -> dict:
    """modules — the campaign's switched-on modules (`- modules: a, b` in Session Flags).

    {"action": "modules"}                 which are on, and any problem with the set
    {"action": "modules", "apply": true}  give every player character (characters/*.md) the tracks and pools
        those modules declare: composure for each PC, doom for the party, panic's thresholds on each stress.
    Send `apply` once the sheets exist, and again when a module is switched on or off or a PC joins: a track that
    exists keeps its value and only gains the new thresholds; a switched-off module's thresholds come off again. Rules: `modules.py -c <campaign> rules`."""
    on = enabled(ctx.campaign)
    errors, warnings = problems(on)
    if errors:
        return mechanics._err("modules: " + "; ".join(errors))
    if not intent.get("apply"):
        return mechanics._done({"modules": on, "warnings": warnings})
    if paths.campaign_system(ctx.campaign) == "d20":
        return mechanics._err("modules are Braid rules (System: core or story)")
    import table
    pcs = list(table.pcs(ctx.campaign))
    dropped = prune(ctx, [m for m in catalog() if m not in on])
    made = {mid: ensure(ctx, mid, pcs) for mid in on}
    return mechanics._done({"modules": on, "pcs": pcs, "made": made, "dropped": dropped, "warnings": warnings},
                           refresh="clocks")


_import_scripts()


# ── CLI ───────────────────────────────────────────────────────────────────────

def _ids(args) -> list:
    ids = [x.strip().casefold() for arg in args.ids for x in arg.split(",") if x.strip()]
    if not ids and args.campaign:
        ids = enabled(args.campaign)
    return ids


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Braid modules: list, show, check, rules, apply.")
    ap.add_argument("-c", "--campaign")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    s = sub.add_parser("show")
    s.add_argument("id")
    for name in ("check", "rules"):
        sub.add_parser(name).add_argument("ids", nargs="*")
    sub.add_parser("apply")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "list":
            for mid, mod in catalog().items():
                print(f"{mid:16} {mod['name']}: {mod['use_when']}")
            return 0
        if args.cmd == "show":
            print(json.dumps(load(args.id), ensure_ascii=False, indent=1))
            print(rules_of(args.id))
            return 0
        if args.cmd == "apply":
            if not args.campaign:
                raise ValueError("apply needs -c <campaign>")
            print(f"Modules on: {', '.join(enabled(args.campaign)) or 'none'}. Send in a turn:")
            print(f"turn.py -c {args.campaign} resolve --intents '[{{\"action\": \"modules\", \"apply\": true}}]'")
            return 0
        ids = _ids(args)
        if not ids:
            print("No modules switched on." if args.campaign else "Name modules, or give -c <campaign>.")
            return 0 if args.campaign else 2
        errors, warnings = problems(ids)
        for line in errors + warnings:
            print(f"{'ERROR' if line in errors else 'WARN'}: {line}")
        if args.cmd == "check":
            print("ok" if not errors else "")
            return 1 if errors else 0
        known = catalog()
        for mid in ids:
            if mid in known:
                print(f"\n## {known[mid]['name']} (`{mid}`)\n{known[mid]['use_when']}\n\n{rules_of(mid).rstrip()}")
        return 1 if errors else 0
    except ValueError as exc:
        print(f"modules: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
