#!/usr/bin/env python3
"""
genres.py — genre presets: which modules, dials and GM moves a genre brings, and how 1–5 genres mix.

A preset is data/genres/<id>.json; its id is the story_axes id story_gen.py rolls from. Kinds: plot (one drives the
story), mood (stack), setting (content tags), frame (wraps the whole story). Presets never pick the rules: the system
is Braid (`core`) unless the players ask for 5e.

  genres.py list                                         every preset: id, name, the stories it fits, modules ("early" marked)
  genres.py show <id>                                    one preset
  genres.py combine <id,id,… | id id …> [--drives <id>] [--set k=v …]   the mix, every conflict, exit 1 when it cannot be played
  genres.py apply <id,id,…> [--drives <id>] [--set k=v …] --seed <seed.json | ->   write the flags into a new world's seed
  genres.py apply <id,id,…> [--drives <id>] [--set k=v …] -c <campaign>          print the Session Flags lines to write

Mixing (plan §2): the first genre is primary. List fields are joined (modules, optional, gm_moves, tags, checks);
single values (dials, suggestions) come from the first genre that has them, and every disagreement is reported. Only
one plot genre drives: with two or more, `--drives` must name one. Modules go through modules.problems (requires,
conflicts, more than 8). `--set key=value` is the players' change (`modules=a,b` replaces the list).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

DIR = HERE.parent / "data" / "genres"
KINDS = ("plot", "mood", "setting", "frame")
MAX = 5
LISTS = ("modules", "optional", "gm_moves", "tags", "checks")
#: Dials a preset may set (written to Session Flags), and suggestions (asked at /dne new, never written: 18/20
#: is the players confirming their age).
DIALS = {"storyteller": ("none", "pulp", "noir", "banter", "dread"), "pacing": ("adventure", "mixed", "slow"),
         "difficulty": ("easy", "standard", "hard", "deadly"), "claims": ("grounded", "declare", "open"),
         "when_down": ("saves", "choices")}
SUGGEST = {"content": ("standard", "18", "20"), "romance": ("off", "fade", "open")}
FIELDS = {"id": str, "name": str, "kind": str, "system": str, "early": bool, "story_axes": str, "dials": dict,
          "suggest": dict, "fits": list, **{f: list for f in LISTS}}


def catalog() -> dict:
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(DIR.glob("*.json"))}


def load(gid: str) -> dict:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", str(gid)):
        raise ValueError(f"genre id {gid!r}: lower-case letters, digits and - only")
    path = DIR / f"{gid}.json"
    if not path.exists():
        raise ValueError(f"no genre {gid!r} (genres.py list)")
    return json.loads(path.read_text(encoding="utf-8"))


def validate(gid: str) -> list:
    """What is wrong with one preset file."""
    try:
        g = load(gid)
    except (ValueError, json.JSONDecodeError) as exc:
        return [str(exc)]
    out = [f"{f}: must be a {t.__name__}" for f, t in FIELDS.items() if not isinstance(g.get(f), t)]
    if out:
        return out
    import modules
    import story_gen
    if g["id"] != gid:
        out.append(f"id {g['id']!r} is not the file name {gid!r}")
    if g["kind"] not in KINDS:
        out.append(f"kind must be one of {', '.join(KINDS)}")
    if g["system"] != "core":
        out.append("system must be core: presets never force 5e")
    if g["story_axes"] not in story_gen.genre_ids():
        out.append(f"story_axes {g['story_axes']!r} is not a data/story_axes file")
    if not g["fits"]:
        out.append("fits: at least one story it fits (genres.py list matches players' words to these)")
    for f in (*LISTS, "fits"):
        if not all(isinstance(x, str) and x.strip() for x in g[f]):
            out.append(f"{f}: a list of non-empty text")
    known = modules.catalog()
    out += [f"{f}: unknown module {m!r}" for f in ("modules", "optional") for m in g[f] if m not in known]
    out += modules.problems(g["modules"])[0]
    for table, allowed in ((g["dials"], DIALS), (g["suggest"], SUGGEST)):
        for k, v in table.items():
            if k not in allowed or v not in allowed[k]:
                out.append(f"{k}: {v!r} is not one of {', '.join(allowed.get(k, ()))}")
    return out


def _ids(text) -> list:
    """Ids as "a,b", "a b" or ["a", "b,c"]."""
    ids = [x.strip().casefold() for t in (text if isinstance(text, list) else [text]) for x in re.split(r"[,\s]+", str(t))
           if x.strip()]
    if not 1 <= len(ids) <= MAX or len(set(ids)) != len(ids):
        raise ValueError(f"give 1 to {MAX} different genres (genres.py list)")
    return ids


def _sets(pairs) -> dict:
    out = {}
    for p in pairs or []:
        k, sep, v = str(p).partition("=")
        if not sep or not k.strip():
            raise ValueError(f"--set {p!r}: key=value")
        k, v = re.sub(r"^(dials|suggest)\.", "", k.strip()), v.strip()
        if k not in DIALS and k not in SUGGEST and k != "modules":
            raise ValueError(f"--set {k}: not a key this sets; one of {', '.join([*DIALS, *SUGGEST, 'modules'])}")
        if k in DIALS and v not in DIALS[k]:
            raise ValueError(f"--set {k}: {v!r} is not one of {', '.join(DIALS[k])}")
        out[k] = v
    return out


def combine(ids, drives=None, sets=None) -> dict:
    """The mixed preset. `errors` (empty when it can be played), `conflicts` (single values the genres disagree on,
    with what was chosen), `warnings`. Raises ValueError for unknown genres or a bad count."""
    ids = _ids(ids)
    gs = [load(g) for g in ids]
    sets = _sets(sets) if not isinstance(sets, dict) else sets
    out = {"genres": ids, "primary": ids[0], "kinds": {g["id"]: g["kind"] for g in gs}, "system": gs[0]["system"],
           "errors": [], "warnings": [], "conflicts": []}
    for f in LISTS:
        out[f] = list(dict.fromkeys(x for g in gs for x in g[f]))
    out["optional"] = [m for m in out["optional"] if m not in out["modules"]]
    for field in ("dials", "suggest"):
        merged = {}
        for g in gs:
            for k, v in g[field].items():
                merged.setdefault(k, (v, g["id"]))
        out[field] = {k: v for k, (v, _src) in merged.items()}
        for k, (v, src) in merged.items():
            others = {g["id"]: g[field][k] for g in gs if k in g[field] and g[field][k] != v}
            if others:
                out["conflicts"].append({"field": f"{field}.{k}", "chosen": v, "from": src, "others": others})
    plots = [g for g in ids if out["kinds"][g] == "plot"]
    if drives:
        if drives not in plots:
            out["errors"].append(f"--drives {drives}: not a plot genre of this mix (plot genres here: {', '.join(plots) or 'none'})")
    elif len(plots) > 1:
        out["errors"].append(f"{', '.join(plots)} are plot genres and only one drives the story: choose one "
                             f"(--drives <id>); the others become threads inside it")
    out["drives"] = drives if drives in plots else (plots[0] if len(plots) == 1 else None)
    # story_gen takes the first plot genre in list order as the driver
    order = [g["story_axes"] for g in gs]
    if out["drives"] and len(plots) > 1:
        order.remove(out["drives"])
        order.insert(min(order.index(p) for p in plots if p != out["drives"]), out["drives"])
    out["story_axes"] = order
    out["set"] = dict(sets)
    for k, v in sets.items():
        if k == "modules":
            out["modules"] = [] if v.casefold() in ("", "none", "(none)") else list(
                dict.fromkeys(x.strip().casefold() for x in re.split(r"[,\s]+", v) if x.strip()))
        elif k in SUGGEST:
            out["suggest"][k] = v
        else:
            out["dials"][k] = v
    # what the table settled is no longer a conflict, and a module switched on is no longer one to add
    out["conflicts"] = [c for c in out["conflicts"] if c["field"].split(".", 1)[1] not in sets]
    out["optional"] = [m for m in out["optional"] if m not in out["modules"]]
    # the clues module plays the case that only story_gen's mystery thread builds
    if "clues" in out["modules"] and "mystery" not in out["story_axes"]:
        if len(out["story_axes"]) < MAX:
            out["story_axes"].append("mystery")
            out["warnings"].append("clues: mystery added to the story generator as a thread, so a case is built")
        else:
            out["warnings"].append("clues: no case without mystery in the story generator: drop a genre or use make_the_case")
    import modules
    errors, warnings = modules.problems(out["modules"])
    out["errors"] += errors
    out["warnings"] += warnings
    out["early"] = [g["id"] for g in gs if g["early"]]
    out["warnings"] += [f"{g}: early — its modules are our own design and not yet proven in long play" for g in out["early"]]
    return out


def flag_lines(mix: dict, system: str = "core") -> list:
    """The Session Flags the mix writes. 5e (d20) keeps its own rules: dials only, no modules, and no `when_down`
    (a preset's `choices` means Braid's harm 4; on 5e it would replace death saves)."""
    lines = [f"- {k}: {v}" for k, v in mix["dials"].items() if system != "d20" or k != "when_down"]
    if system != "d20":
        lines.insert(0, f"- modules: {', '.join(mix['modules']) or '(none)'}")
    return lines


def apply_to_seed(seed: dict, mix: dict) -> dict:
    """The seed for campaign_init with the mix's flags. A flag the seed already has is the table's own answer and
    stays, unless `--set` changed it; the system is the seed's (none = d20, as campaign_init reads it).
    Returns {"seed", "kept"}: the seed's flags that differ from the preset."""
    seed = json.loads(json.dumps(seed))
    flags = seed.setdefault("flags", {})
    kept = {}
    for line in flag_lines(mix, str(seed.get("system", "d20"))):
        k, v = line[2:].split(": ", 1)
        if k in flags and k not in mix.get("set", {}):
            if str(flags[k]) != v:
                kept[k] = flags[k]
            continue
        flags[k] = v
    kit = seed.get("worldkit")
    if isinstance(kit, dict) and not (kit.get("_meta") or {}).get("genre"):
        kit.setdefault("_meta", {})["genre"] = mix["genres"]
    return {"seed": seed, "kept": kept}


def _report(mix: dict) -> str:
    lines = [f"Genres: {', '.join(f'{g} ({k})' for g, k in mix['kinds'].items())}; primary {mix['primary']}"
             + (f"; {mix['drives']} drives the story" if mix["drives"] else ""),
             f"System: Braid (core) unless the players ask for 5e",
             f"Modules: {', '.join(mix['modules']) or '(none)'}" + (f"  (could add: {', '.join(mix['optional'])})" if mix["optional"] else ""),
             "Dials: " + ", ".join(f"{k} {v}" for k, v in mix["dials"].items()),
             "Ask the table: " + ", ".join(f"{k} (suggested {v})" for k, v in mix["suggest"].items()),
             f"Story generator: story_gen.py skeleton --genre {','.join(mix['story_axes'])}",
             "GM moves: " + "; ".join(mix["gm_moves"]),
             "Content tags: " + ", ".join(mix["tags"]),
             "Checks: " + "; ".join(mix["checks"])]
    lines += [f"CONFLICT {c['field']}: {c['chosen']} (from {c['from']}); "
              + ", ".join(f"{g} wants {v}" for g, v in c["others"].items()) + " — the table may pick" for c in mix["conflicts"]]
    lines += [f"WARN: {w}" for w in mix["warnings"]] + [f"ERROR: {e}" for e in mix["errors"]]
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Genre presets: list, show, combine, apply.")
    ap.add_argument("-c", "--campaign")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    sub.add_parser("show").add_argument("id")
    for name in ("combine", "apply"):
        s = sub.add_parser(name)
        s.add_argument("ids", nargs="+", help="1-5 genre ids, comma- or space-separated, primary first")
        s.add_argument("--drives", help="the plot genre that drives the story, when the mix has two or more")
        s.add_argument("--set", action="append", default=[], metavar="KEY=VALUE", help="the players' change")
        s.add_argument("--json", action="store_true")
        if name == "apply":
            s.add_argument("--seed", help="campaign_init seed file to update (- = stdin to stdout)")
            s.add_argument("-c", "--campaign", dest="campaign_apply")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "list":
            for gid, g in catalog().items():
                print(f"{gid:14} {g['name']}{'  [early]' if g['early'] else ''}: fits {', '.join(g.get('fits') or ['?'])}"
                      f" | modules {', '.join(g.get('modules', []))}")
            return 0
        if args.cmd == "show":
            print(json.dumps(load(args.id), ensure_ascii=False, indent=1))
            return 0
        mix = combine(args.ids, args.drives, args.set)
        if args.cmd == "combine":
            print(json.dumps(mix, ensure_ascii=False, indent=1) if args.json else _report(mix))
            return 1 if mix["errors"] else 0
        camp = args.campaign_apply or args.campaign
        if bool(args.seed) == bool(camp):
            raise ValueError("apply needs --seed <file> (a new world) or -c <campaign> (an existing one)")
        if mix["errors"]:
            print(_report(mix))
            return 1
        if camp:
            import paths
            system = paths.campaign_system(camp)
            print(f"Write to {camp}/state.md → ## Session Flags (replace old values):")
            print("\n".join(flag_lines(mix, system)))
            if system == "d20":
                print("(5e campaign: modules are Braid rules and stay off.)")
            else:
                print(f"Then, once the sheets exist, send in a turn: turn.py -c {camp} resolve --intents "
                      "'[{\"action\": \"modules\", \"apply\": true}]'")
            return 0
        raw = sys.stdin.read() if args.seed == "-" else Path(args.seed).read_text(encoding="utf-8")
        done = apply_to_seed(json.loads(raw), mix)
        text = json.dumps(done["seed"], ensure_ascii=False, indent=1) + "\n"
        if args.seed == "-":
            sys.stdout.write(text)
        else:
            Path(args.seed).write_text(text, encoding="utf-8")
            notes = [] if "system" in done["seed"] else ["the seed has no system: campaign_init reads that as 5e (d20), "
                                                          "so no modules were written; add \"system\": \"core\" for Braid"]
            print(json.dumps({"ok": True, "seed": args.seed, "flags": done["seed"]["flags"], "kept": done["kept"],
                              "conflicts": mix["conflicts"], "warnings": mix["warnings"] + notes}, ensure_ascii=False, indent=1))
        return 0
    except (ValueError, OSError) as exc:
        print(f"genres: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
