#!/usr/bin/env python3
"""
campaign_init.py — create a campaign from one seed file, checked first, ready to play and to run on its own.

    campaign_init.py --seed seed.json [--check]

The GM writes the seed from the players' premise; this script checks all of it before anything is created,
builds the campaign in a staging folder with the same scripts `/dne new` uses by hand (templates, calendar.py,
faction.py, npc.py, campaign_version.py, the world engine's turn runner), and moves it into place only when every
step worked. A failed run leaves nothing behind and can simply be run again; an existing campaign of that name is
never touched.

Seed, version 1 (only `seed_version` and `campaign` are required; each system's data is needed only when that
system is on):

  {"seed_version": 1, "campaign": "hollow", "system": "d20", "ruleset": "2014", "party_size": 3, "starting_level": 1,
   "flags": {"display": "none", "roll_mode": "players", "engine": "full", "world_engine": "on", "survival": "off"},
   "calendar": {"date": "1 Thaw 412", "time": "morning", "months": ["Thaw", "Bloom"], "month_length": 30,
                "day_names": [...], "gregorian": false},
   "worldkit": {...} (omit for classic SRD fantasy),
   "map": {"party_location": "ford", "places": {"ford": {"name": "The Ford"}, ...}, "edges": [{"a": "ford", "b": "market", "miles": 12}]},
   "npcs": [{"name": "Jonas", "role": "mechanic", "cr": "1/2", "aliases": ["Jo"], "faction": "Hollow-9", "location": "The Ford"}],
            (Braid: "threat": 1-5 instead of "cr")
   "factions": [{"name": "Tollmen", "force": 3, "wealth": 4, "influence": 2, "goal": "Tax the bridge", "clock": 6,
                 "goal_stat": "wealth", "rivals": ["Millers' Guild"]}],
   "setup": [ engine intents, run once as the world's first turn:
              {"action": "settlement", "at": "The Ford", "template": "hollow-9"},
              {"action": "route", "between": ["The Ford", "Market"], "access": "toll", "owner": "Tollmen"},
              {"action": "schedule", "in_minutes": 2880, "text": "The rider reaches the ford."} ]}

`system` is d20 (5e, the default; `ruleset` picks 2014 or 2024), core (Braid) or story (Braid without dice).
Braid's checks are engine actions, so a core or story campaign always runs with `world_engine: on` (and so needs a
calendar); it has no `ruleset`.

Every problem comes back as {"path": "setup[2].at", "error": "…"}: the place in the seed to fix.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import paths  # noqa: E402

SEED_VERSION = 1
TEMPLATES = ("state.md", "world.md", "npcs.md", "npcs-full.md", "session-log.md")
#: Fields that name a map place, per action. Other actions are checked when they run (errors come back by index).
PLACE_FIELDS = {"settlement": ("at",), "market": ("at",), "caravan": ("from", "to"), "appointment": ("place", "from"),
                "community": ("at",), "travel": ("to",)}
FACTION_STATS = ("force", "wealth", "influence")
#: Session Flags the engine reads. Anything else is kept but reported, in case it is a typo.
KNOWN_FLAGS = {"display", "roll_mode", "autorun", "autorun_interval", "autosave", "tutor_mode", "tts_voice", "sfx_languages",
               "difficulty", "survival", "beat_policy", "cover_rule", "ooc_minutes", "spotlight", "content", "romance",
               "pacing", "companions", "rolls", "show_dc", "turn_end", "engine", "npc_growth", "world_engine", "sparks",
               "style_guard", "storyteller", "lines", "veils", "success_at_cost", "degrees", "hero_points", "when_down", "modules", "claims"}


def _err(out: list, path: str, msg: str) -> None:
    out.append({"path": path, "error": msg})


def _place_key(places: dict, ref) -> "str | None":
    if not isinstance(ref, str) or not ref.strip():
        return None
    low = ref.strip().casefold()
    for key, p in places.items():
        if low in (key.casefold(), str((p or {}).get("name", "")).casefold()):
            return key
    return None


def warnings(seed) -> list:
    """Things that are allowed but probably not meant: a flag the engine does not read, an NPC name another
    campaign already uses."""
    flags = seed.get("flags") if isinstance(seed, dict) and isinstance(seed.get("flags"), dict) else {}
    out = [{"path": f"flags.{k}", "warning": "not a flag the engine reads (kept as written): a typo?"}
           for k in sorted(flags) if k not in KNOWN_FLAGS]
    for i, n in enumerate(seed.get("npcs") or [] if isinstance(seed, dict) else []):
        if isinstance(n, dict) and n.get("name"):
            code, text = _run({**os.environ, "PYTHONIOENCODING": "utf-8"}, "name_registry.py", "check", str(n["name"]), "--json")
            if code:
                out.append({"path": f"npcs[{i}].name", "warning": f"{n['name']!r} is already used: {text[:200]}"})
    return out


def _with_system(seed):
    """The seed as it will be built: a core or story campaign runs on the world engine, so its flag is set on.
    An explicit `world_engine: off` is left for check() to report."""
    if not isinstance(seed, dict) or str(seed.get("system", "d20")) not in ("core", "story"):
        return seed
    flags = seed.get("flags") if isinstance(seed.get("flags"), dict) else {}
    if "world_engine" in flags:
        return seed
    return {**seed, "flags": {**flags, "world_engine": "on"}}


def check(seed) -> list:
    """Every problem in the seed, with where it is. Nothing is written."""
    errors: list = []
    if not isinstance(seed, dict):
        return [{"path": "", "error": "the seed must be a JSON object"}]
    seed = _with_system(seed)
    system = str(seed.get("system", "d20"))
    if system not in paths.SYSTEMS:
        _err(errors, "system", " or ".join(paths.SYSTEMS) + " (d20 = 5e, core = Braid, story = Braid without dice)")
    elif system != "d20" and str((seed.get("flags") or {}).get("world_engine")) != "on":
        _err(errors, "flags.world_engine", f"a {system} campaign runs on the world engine: leave it out or set it on")
    if seed.get("seed_version") != SEED_VERSION:
        _err(errors, "seed_version", f"must be {SEED_VERSION} (this engine reads version {SEED_VERSION})")
    name = seed.get("campaign")
    if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", name or ""):
        _err(errors, "campaign", "a folder name: lowercase letters, digits, - or _")
    elif paths.find_campaign(name).exists():
        _err(errors, "campaign", f"a campaign called {name!r} already exists: choose another name (it is left as it is)")
    if str(seed.get("ruleset", "2014")) not in paths.VALID_RULESETS:
        _err(errors, "ruleset", " or ".join(paths.VALID_RULESETS))

    flags = seed.get("flags") or {}
    if not isinstance(flags, dict) or not all(isinstance(k, str) and isinstance(v, (str, int, bool)) for k, v in flags.items()):
        _err(errors, "flags", "an object of flag: value")
        flags = {}
    engine_on = str(flags.get("world_engine", "off")) == "on"
    if str(flags.get("world_engine", "off")) not in ("on", "off"):
        _err(errors, "flags.world_engine", "on or off (shadow is for existing campaigns: world_migrate.py)")
    if str(flags.get("survival", "off")) == "on" and not engine_on:
        _err(errors, "flags.survival", "survival needs world_engine: on")
    setup = seed.get("setup") or []
    if setup and not engine_on:
        _err(errors, "setup", "setup actions run on the world engine: set flags.world_engine to on, or leave setup out")
    cal = seed.get("calendar")
    if engine_on and not cal:
        _err(errors, "calendar", "the world engine needs a calendar: time only passes through it")
    if cal is not None and (not isinstance(cal, dict) or not str(cal.get("date", "")).strip()):
        _err(errors, "calendar.date", "the starting in-world date, e.g. \"1 Thaw 412\"")

    kit = seed.get("worldkit")
    if kit is not None:
        try:
            import worldkit
            for e in worldkit.validate(kit, system=system):
                _err(errors, "worldkit", e)
        except Exception as exc:                  # a kit the validator cannot even read
            _err(errors, "worldkit", f"could not be checked: {exc}")

    places: dict = {}
    mp = seed.get("map")
    if mp is not None:
        if not isinstance(mp, dict) or not isinstance(mp.get("places"), dict) or not mp["places"]:
            _err(errors, "map.places", "an object of place key → {name, …}")
        else:
            places = mp["places"]
            for key, p in places.items():
                if not isinstance(p, dict) or not str(p.get("name", "")).strip():
                    _err(errors, f"map.places.{key}.name", "every place needs a name")
            for i, e in enumerate(mp.get("edges") or []):
                for end in ("a", "b"):
                    if not isinstance(e, dict) or e.get(end) not in places:
                        _err(errors, f"map.edges[{i}].{end}", f"not a place key in map.places ({', '.join(sorted(places))})")
            if mp.get("party_location") and mp["party_location"] not in places:
                _err(errors, "map.party_location", "not a place key in map.places")

    for where, items in ([("calendar.months", (cal or {}).get("months") if isinstance(cal, dict) else None),
                          ("calendar.day_names", (cal or {}).get("day_names") if isinstance(cal, dict) else None)]
                         + [(f"npcs[{i}].aliases", n.get("aliases")) for i, n in enumerate(seed.get("npcs") or []) if isinstance(n, dict)]
                         + [(f"factions[{i}].rivals", f.get("rivals")) for i, f in enumerate(seed.get("factions") or []) if isinstance(f, dict)]):
        for j, item in enumerate(items or []):
            if "," in str(item):
                _err(errors, f"{where}[{j}]", "no commas inside one name (the list is passed comma-separated)")
    for i, f in enumerate(seed.get("factions") or []):
        if isinstance(f, dict) and "," in str(f.get("name", "")):
            _err(errors, f"factions[{i}].name", "no commas in a faction name (rival lists are comma-separated)")

    npc_names: set = set()
    for i, n in enumerate(seed.get("npcs") or []):
        if not isinstance(n, dict) or not str(n.get("name", "")).strip():
            _err(errors, f"npcs[{i}].name", "every NPC needs a name")
            continue
        key = n["name"].strip().casefold()
        if key in npc_names:
            _err(errors, f"npcs[{i}].name", f"{n['name']!r} appears twice: two people need two names (or one entry)")
        npc_names.add(key)
        npc_names.update(str(a).strip().casefold() for a in n.get("aliases") or [])
        if not str(n.get("role", "")).strip():
            _err(errors, f"npcs[{i}].role", "what they do, in a few words")
        if system != "d20":                       # Braid: a threat rating 1-5, no challenge rating
            if str(n.get("threat", "")) not in ("1", "2", "3", "4", "5"):
                _err(errors, f"npcs[{i}].threat", "a Braid threat rating 1-5 (SKILL-core.md, Enemies)")
            continue
        try:
            import worldkit
            worldkit._cr_key(str(n.get("cr", "")))
        except Exception:
            _err(errors, f"npcs[{i}].cr", "a challenge rating for their stats: 0, 1/8, 1/4, 1/2 or 1-30")

    fac_names = set()
    for i, f in enumerate(seed.get("factions") or []):
        if not isinstance(f, dict) or not str(f.get("name", "")).strip():
            _err(errors, f"factions[{i}].name", "every faction needs a name")
            continue
        if f["name"].casefold() in fac_names:
            _err(errors, f"factions[{i}].name", f"{f['name']!r} appears twice")
        fac_names.add(f["name"].casefold())
        for s in FACTION_STATS:
            if not isinstance(f.get(s), int) or not 1 <= f[s] <= 5:
                _err(errors, f"factions[{i}].{s}", "a whole number 1–5")
    for i, f in enumerate(seed.get("factions") or []):
        for j, r in enumerate((f or {}).get("rivals") or [] if isinstance(f, dict) else []):
            if str(r).casefold() not in fac_names:
                _err(errors, f"factions[{i}].rivals[{j}]", f"{r!r} is not one of the seed's factions")

    if setup:
        if not isinstance(setup, list):
            _err(errors, "setup", "a list of engine actions")
            setup = []
        import turn
        for i, intent in enumerate(setup):
            if not isinstance(intent, dict) or intent.get("action") not in turn.HANDLERS:
                _err(errors, f"setup[{i}].action", "not an engine action (`turn.py -c <campaign> help` lists them)")
                continue
            for field in PLACE_FIELDS.get(intent["action"], ()):
                if field in intent and isinstance(intent[field], str):
                    if not places and intent["action"] != "settlement":
                        _err(errors, f"setup[{i}].{field}", "names a place but the seed has no map")
                    elif places and not _place_key(places, intent[field]):
                        _err(errors, f"setup[{i}].{field}", f"unknown place {intent[field]!r}")
            between = intent.get("between") if intent["action"] == "route" and isinstance(intent.get("between"), list) else []
            for j, ref in enumerate(between):
                if not _place_key(places, ref):
                    _err(errors, f"setup[{i}].between[{j}]", f"unknown place {ref!r}")
            if isinstance(intent.get("npc"), str) and intent["npc"].casefold() not in npc_names:
                _err(errors, f"setup[{i}].npc", f"{intent['npc']!r} is not one of the seed's NPCs")
    return errors


def _run(env: dict, script: str, *args: str) -> "tuple[int, str]":
    r = subprocess.run([sys.executable, str(HERE / script), *args], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=env)
    return r.returncode, (r.stdout + r.stderr).strip()


def build(seed: dict) -> dict:
    """Check, build in staging, move into place. {"ok", "errors", "campaign", …}."""
    errors = check(seed)
    if errors:
        return {"ok": False, "errors": errors}
    seed = _with_system(seed)
    name = seed["campaign"]
    root = paths._root()
    stage_root = root / f".dne-init-{name}"
    if stage_root.exists():                       # what a failed run left: ours to clear
        shutil.rmtree(stage_root)
    camp = stage_root / "campaigns" / name
    (camp / "characters").mkdir(parents=True)
    env = {**os.environ, "DNE_CAMPAIGN_ROOT": str(stage_root), "DNE_RUNTIME_DIR": str(stage_root / "rt"),
           "DNE_OUTBOX_LOG": str(stage_root / "outbox.jsonl"), "DNE_DISPLAY_HOST": "127.0.0.1:9",
           "PYTHONIOENCODING": "utf-8"}
    (stage_root / "rt").mkdir()
    steps, fail = [], []
    try:
        today = datetime.date.today().isoformat()
        tdir = HERE.parent / "templates"
        for t in TEMPLATES:
            text = (tdir / t).read_text(encoding="utf-8")
            text = text.replace("<campaign-name>", name).replace("<date>", today).replace("# Campaign: <name>", f"# Campaign: {name}")
            if t == "state.md":
                text = text.replace("**Ruleset:** 2014  **System:** d20", f"**System:** {seed['system']}"
                                    if seed.get("system", "d20") != "d20" else f"**Ruleset:** {seed.get('ruleset', '2014')}  **System:** d20")
                text = text.replace("**Party size:** <N>", f"**Party size:** {seed.get('party_size', '<N>')}")
                text = text.replace("**Starting level:** <N>", f"**Starting level:** {seed.get('starting_level', '<N>')}")
                if seed.get("worldkit") is not None:
                    text = text.replace("<worldkit.json | none — classic SRD fantasy>", "worldkit.json")
                if seed.get("system", "d20") != "d20":    # Braid has no levels, HP or AC
                    text = text.replace("<worldkit.json | none — classic SRD fantasy>", "none")
                    text = text.replace(f"  **Starting level:** {seed.get('starting_level', '<N>')}", "")
                    text = re.sub(r"<Origin/Race> <Class> <Level> \| HP X/X \| AC X", "<concept> | harm X/4 | stress X/6", text)
            if t == "npcs-full.md" and seed.get("system", "d20") != "d20":   # the entry pattern, in Braid's stat line
                text = text.replace("**CR/Level:**", "**Threat:**").replace(
                    "- **HP:** | **AC:** | **Attack:** | **Notable abilities:**", "- **Harm:** | **Deals:** | **Moves:**")
            (camp / t).write_text(text, encoding="utf-8")
        steps.append("templates")
        import world_migrate
        saved = os.environ.get("DNE_CAMPAIGN_ROOT")
        os.environ["DNE_CAMPAIGN_ROOT"] = str(stage_root)
        try:
            for key, value in (seed.get("flags") or {}).items():
                world_migrate.set_flag(name, key, str(value).lower() if isinstance(value, bool) else str(value))
        finally:
            os.environ["DNE_CAMPAIGN_ROOT"] = saved if saved is not None else ""
            if saved is None:
                os.environ.pop("DNE_CAMPAIGN_ROOT")
        steps.append("flags")
        if seed.get("worldkit") is not None:
            (camp / "worldkit.json").write_text(json.dumps(seed["worldkit"], indent=2, ensure_ascii=False), encoding="utf-8")
            steps.append("worldkit")
        if seed.get("map"):
            mp = {"party_location": "", "edges": [], **seed["map"]}
            mp["places"] = {k: {"x": 0, "y": 0, "biome": "", "kind": "town", "desc": "", "secret": "", "hidden": False,
                                "visited": k == mp.get("party_location"), "danger": 1, **v} for k, v in seed["map"]["places"].items()}
            (camp / "world-map.json").write_text(json.dumps(mp, indent=2, ensure_ascii=False), encoding="utf-8")
            steps.append("map")
        cal = seed.get("calendar")
        if cal:
            args = ["-c", name, "init", "--date", str(cal["date"]), "--time", str(cal.get("time", "morning"))]
            if cal.get("gregorian"):
                args.append("--gregorian")
            if cal.get("months"):
                args += ["--months", ",".join(cal["months"])]
            if cal.get("month_length"):
                args += ["--month-length", str(cal["month_length"])]
            if cal.get("day_names"):
                args += ["--day-names", ",".join(cal["day_names"])]
            if cal.get("lang"):
                args += ["--lang", str(cal["lang"])]
            code, out = _run(env, "calendar.py", *args)
            (fail.append({"path": "calendar", "error": out}) if code else steps.append("calendar"))
        for i, f in enumerate(seed.get("factions") or []):
            if fail:
                break
            code, out = _run(env, "faction.py", "-c", name, "add", f["name"],
                             *[x for s in FACTION_STATS for x in (f"--{s}", str(f[s]))])
            if not code and any(k in f for k in ("goal", "clock", "goal_stat", "rivals")):
                extra = []
                for k in ("goal", "clock"):
                    if f.get(k) is not None:
                        extra += [f"--{k}", str(f[k])]
                if f.get("goal_stat"):
                    extra += ["--goal-stat", f["goal_stat"]]
                if f.get("rivals"):
                    extra += ["--rivals", ",".join(f["rivals"])]
                code, out = _run(env, "faction.py", "-c", name, "set", f["name"], *extra)
            if code:
                fail.append({"path": f"factions[{i}]", "error": out})
        if seed.get("factions") and not fail:
            steps.append("factions")
        for i, n in enumerate(seed.get("npcs") or []):
            if fail:
                break
            args = ["-c", name, "add", "--name", n["name"], "--role", n["role"],
                    *(["--threat", str(n["threat"])] if seed.get("system", "d20") != "d20" else ["--cr", str(n["cr"])])]
            for k in ("faction", "location", "attitude", "notes", "voice"):
                if n.get(k):
                    args += [f"--{k}", str(n[k])]
            if n.get("aliases"):
                args += ["--aliases", ",".join(n["aliases"])]
            code, out = _run(env, "npc.py", *args)
            if code:
                fail.append({"path": f"npcs[{i}]", "error": out})
        if seed.get("npcs") and not fail:
            steps.append("npcs")
        if not fail:
            code, out = _run(env, "campaign_version.py", "-c", name, "stamp")
            (fail.append({"path": "", "error": f"campaign_version stamp: {out}"}) if code else steps.append("version"))
        engine_on = str((seed.get("flags") or {}).get("world_engine", "off")) == "on"
        if engine_on and not fail:
            code, out = _run(env, "world_migrate.py", "-c", name, "register")
            if code:
                fail.append({"path": "flags.world_engine", "error": out})
            else:
                steps.append("world engine store")
        if seed.get("setup") and not fail:
            fail += _setup(env, name, seed["setup"])
            if not fail:
                steps.append("setup")
        if not fail:
            fail += _complete(camp, seed)
        if fail:
            return {"ok": False, "errors": fail, "done_before_the_error": steps,
                    "note": "nothing was created: fix the seed and run it again"}
        shutil.rmtree(camp / ".snapshots", ignore_errors=True)     # the build itself is not a turn to undo to
        dest = paths.find_campaign(name)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            return {"ok": False, "errors": [{"path": "campaign", "error": f"{name!r} appeared while building: left as it is"}]}
        os.replace(camp, dest)
        notes = warnings(seed)
        for n in seed.get("npcs") or []:          # the registry lives at the real root, so this comes after the move
            code, out = _run({**os.environ, "PYTHONIOENCODING": "utf-8"}, "name_registry.py", "add", "--name", n["name"],
                             "--type", "npc", "--campaign", name, "--session", "0")
            if code:
                notes.append({"path": "npcs", "warning": f"name registry: {out}"})
        return {"ok": True, "campaign": str(dest), "steps": steps, "warnings": notes,
                "next": f"/dne load {name} — or play on: the world engine is {'on' if engine_on else 'off'}"}
    finally:
        shutil.rmtree(stage_root, ignore_errors=True)


def _setup(env: dict, name: str, setup: list) -> list:
    code, out = _run(env, "turn.py", "-c", name, "begin", "--text", "campaign init: the world's starting state")
    if code:
        return [{"path": "setup", "error": f"turn begin: {out}"}]
    r = subprocess.run([sys.executable, str(HERE / "turn.py"), "-c", name, "resolve", "--intents", "-"],
                       input=json.dumps(setup, ensure_ascii=False), capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=env)
    try:
        res = json.loads(r.stdout)
    except ValueError:
        return [{"path": "setup", "error": (r.stdout + r.stderr).strip()[-2000:]}]
    errors = []
    for i, item in enumerate(res.get("results") or []):
        data = item.get("data") or {}
        if data.get("error"):
            errors.append({"path": f"setup[{i}]", "error": str(data["error"])})
    if res.get("status") == "waiting_for_player":
        errors.append({"path": "setup", "error": "a setup action waits on a player: setup must not need anyone's answer"})
    if len(res.get("results") or []) < len(setup) and not errors:
        errors.append({"path": f"setup[{len(res.get('results') or [])}]", "error": "did not run"})
    if errors:
        return errors
    code, out = _run(env, "turn.py", "-c", name, "finish", "--narration", "The world is set up.")
    if code:
        return [{"path": "setup", "error": f"turn finish: {out}"}]
    import sqlite3
    db = sqlite3.connect(str(Path(env["DNE_CAMPAIGN_ROOT"]) / "campaigns" / name / "world.db"))
    try:                                          # the build is not a scene: nothing of it goes to the table's screens
        with db:
            db.execute("DELETE FROM outbox")
    finally:
        db.close()
    return []


def _complete(camp: Path, seed: dict) -> list:
    """What must exist before anyone plays: the files every command reads, and the store if the engine is on."""
    missing = [t for t in TEMPLATES if not (camp / t).is_file()]
    if seed.get("calendar") and not (camp / "calendar.json").is_file():
        missing.append("calendar.json")
    if str((seed.get("flags") or {}).get("world_engine", "off")) == "on" and not (camp / "world.db").is_file():
        missing.append("world.db")
    if not (camp / "dne-version.json").is_file():
        missing.append("dne-version.json")
    out = [{"path": "", "error": f"not created: {m}"} for m in missing]
    if (camp / "world.db").is_file():
        import sqlite3
        db = sqlite3.connect(str(camp / "world.db"))
        try:
            open_turns = db.execute("SELECT COUNT(*) FROM turns WHERE status != 'finished'").fetchone()[0]
            waiting = db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0]
        finally:
            db.close()
        if open_turns or waiting:
            out.append({"path": "setup", "error": f"the build left {open_turns} open turn(s) and {waiting} message(s) to send"})
        out += _references(camp / "world.db", seed)
    return out


def _references(db_file: Path, seed: dict) -> list:
    """What the world's rules point at must exist: stores a rule spends or fills, rules an agent's duties name."""
    import sqlite3
    db = sqlite3.connect(str(db_file))
    try:
        rows = {(k, i): json.loads(d) for k, i, d in db.execute("SELECT kind, id, data FROM things WHERE kind IN ('rule','store','agent')")}
    finally:
        db.close()
    stores = {i for k, i in rows if k == "store"}
    rules = {i for k, i in rows if k == "rule"}
    where = {}
    for n, intent in enumerate(seed.get("setup") or []):
        if isinstance(intent, dict) and intent.get("action") in ("rule", "agent"):
            where[(intent["action"], str(intent.get("id") or intent.get("name")))] = n
    out = []
    for (kind, ident), rec in sorted(rows.items()):
        at = f"setup[{where.get((kind, ident), '?')}]"
        if kind == "rule":
            for field in ("cost", "gives"):
                for sid in rec.get(field) or {}:
                    if sid not in stores:
                        out.append({"path": f"{at}.{field}.{sid}", "error": f"rule {ident!r} uses store {sid!r}, which no store action creates"})
        if kind == "agent":
            for j, d in enumerate(rec.get("duties") or []):
                if d.get("rule") not in rules:
                    out.append({"path": f"{at}.duties[{j}].rule", "error": f"{ident}'s duty names rule {d.get('rule')!r}, which is not declared"})
    return out


def main() -> int:
    p = argparse.ArgumentParser(description="Create a campaign from a checked seed file.")
    p.add_argument("--seed", required=True, help="seed JSON file, or - for stdin")
    p.add_argument("--check", action="store_true", help="only check the seed; create nothing")
    a = p.parse_args()
    try:
        raw = sys.stdin.read() if a.seed == "-" else Path(a.seed).read_text(encoding="utf-8")
        seed = json.loads(raw)
    except (OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "errors": [{"path": "", "error": f"cannot read the seed: {exc}"}]}, ensure_ascii=False, indent=1))
        return 1
    if a.check:
        errs = check(seed)
        out = {"ok": not errs, "errors": errs, "warnings": warnings(seed)}
    else:
        out = build(seed)
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
