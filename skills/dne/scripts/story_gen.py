#!/usr/bin/env python3
"""
story_gen.py — build a story that does not repeat the last one: Python rolls, the GM writes.

Four steps (GM procedure: SKILL-storygen.md):
  seed      record what the players said is true. Fixed: later steps may not contradict it.
            "mystery.culprit=the night nurse" (or "culprit=...") pins an axis; any other text is kept as a fact.
  skeleton  roll independent axes from data/story_axes/<genre>.json for each genre (the first plot-kind genre
            drives, the others become sub-threads), build each genre's structure (a mystery's case graph,
            a horror ladder, a heist plan, a romance obstacle), then check and repair it.
  flesh     the GM writes 5 candidates with probabilities (each <= 0.10); candidates that hit the ban list
            (genre clichés + recent picks) are dropped and the script picks one by rng, never the model.
  check     run every genre's validator on the skeleton file; repair what can be repaired, re-roll what cannot.

Usage:
  story_gen.py axes     mystery,horror                          (every axis and its values: what `seed` can pin)
  story_gen.py seed     --file F "fact" ["mystery.motive=an old debt" ...]
  story_gen.py skeleton --file F --genre war,mystery,horror [--seed N] [--history-at K] [--mix-eras]
  story_gen.py flesh    --file F --slot premise                 (prints the brief and the ban list)
  story_gen.py flesh    --file F --slot premise --candidates '[{"text": "...", "p": 0.08}, ...]'
  story_gen.py fill     --file F                                (plain text for every unwritten hidden clue)
  story_gen.py name     --file F s1 "Lung Chuan"                (a suspect's name, or rename a case place)
  story_gen.py check    --file F
  -c <campaign> instead of --file uses <campaign>/story-skeleton.json; a skeleton made with -c takes its case
  places from the campaign map and its suspects' names from npcs.md.

History: <campaign root>/story-history.jsonl, shared by every campaign. A skeleton line records the seed and
how many history lines it was rolled against (`history_at`): `skeleton --seed N --history-at K` replays it
exactly and records nothing. Rolling a new skeleton over one that was never fleshed takes the old line back out
(when nothing was recorded after it), so a discarded re-roll does not weigh on later stories.
"""

import argparse
import difflib
import json
import os
import random
import re
import sys
from collections import Counter

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

import paths  # noqa: E402

KINDS = ("plot", "mood", "setting", "frame")
DECAY, RECENT = 0.3, 20          # x0.3 per use in the last 20 skeletons of that genre (plan §4)
GATE, GATE_TRIES = 3, 200        # a new skeleton may share at most 3 axes with any older one of its genre
GATE_LOOKBACK = 200              # shortcut: compares with the last 200 of a genre only; raise if tables grow a lot
TRIALS, DROP, SOLVE_RATE, REPAIR_TO = 1000, 1 / 3, 0.95, 0.97
CONCLUSIONS = ("who", "how", "why")
SIMILAR = 0.8                    # a flesh candidate this close to a recent pick counts as a repeat


# ── tables and history ────────────────────────────────────────────────────────

def axes_dir():
    return paths.data_dir() / "story_axes"


def genre_ids() -> list:
    return sorted(p.stem for p in axes_dir().glob("*.json"))


def load_genre(gid: str) -> dict:
    path = axes_dir() / f"{gid}.json"
    if not path.is_file():
        raise ValueError(f"no story axes for genre {gid!r} (have: {', '.join(genre_ids())})")
    return json.loads(path.read_text(encoding="utf-8"))


def _entries(values: list) -> list:
    """Axis values as (text, weight, decays): a plain string weighs 1; {"v", "w", "decay": false}."""
    out = []
    for e in values:
        if isinstance(e, str):
            out.append((e, 1.0, True))
        else:
            out.append((e["v"], float(e.get("w", 1)), e.get("decay", True)))
    return out


def _mentions(text: str, words: list) -> bool:
    return any(w and re.search(rf"(?<!\w){re.escape(w)}(?:s|es)?(?!\w)", text, re.I) for w in words)


def ban_words(table: dict) -> list:
    """A table's bans, each "@era" expanded from data/eras.json (one shared vocabulary, so settings don't drift)."""
    eras = json.loads((paths.data_dir() / "eras.json").read_text(encoding="utf-8"))
    return [w for b in table.get("bans", []) for w in (eras[b[1:]] if b.startswith("@") else [b])]


def tables_for(genres: list, mix_eras: bool = False) -> dict:
    """Each genre's table with the values a setting genre in play rules out (radios in a wuxia siege) taken out.
    A list the bans would empty is kept whole; a pinned value is never filtered. `mix_eras`: the players want the
    eras mixed (pirates with phones), so nothing is taken out."""
    tables = {g: load_genre(g) for g in genres}
    bans = [] if mix_eras else [b for t in tables.values() for b in ban_words(t)]
    if not bans:
        return tables

    def keep(values):
        left = [e for e in values if not _mentions(e if isinstance(e, str) else e["v"], bans)]
        return left or values
    for t in tables.values():
        for part in ("axes", "pools", "ladder"):
            if part in t:
                t[part] = {k: keep(v) for k, v in t[part].items()}
    return tables


def history_path():
    return paths._root() / "story-history.jsonl"   # resolved per call: tests move the root


def read_history(at=None) -> list:
    path = history_path()
    if not path.is_file():
        return []
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    out = []
    for ln in lines[:at]:
        try:
            out.append(json.loads(ln))
        except ValueError:
            out.append({})   # keep the line count right so history_at still points at the same place
    return out


def append_history(record: dict) -> None:
    path = history_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def drop_unused(old: dict) -> bool:
    """Take `old`'s skeleton line back out of the history if it is still the last line: it was re-rolled before
    anything was fleshed, so the table never used it. An older line stays (removing it would move every later
    `history_at`)."""
    path = history_path()
    if not old.get("threads") or old.get("flesh") or not path.is_file():
        return False
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    try:
        last = json.loads(lines[-1]) if lines else {}
    except ValueError:
        return False
    if last.get("kind") != "skeleton" or (last.get("seed"), last.get("history_at")) != (old.get("seed"), old.get("history_at")):
        return False
    path.write_text("".join(ln + "\n" for ln in lines[:-1]), encoding="utf-8")
    return True


def _past_axes(history: list, gid: str) -> list:
    return [r["axes"][gid] for r in history if r.get("kind") == "skeleton" and gid in (r.get("axes") or {})]


# ── rolling ───────────────────────────────────────────────────────────────────

def pick(rng, weighted: list):
    """weighted: [(item, weight)] → item. Zero total falls back to an even pick."""
    total = sum(w for _, w in weighted)
    if total <= 0:
        return rng.choice(weighted)[0]
    x = rng.random() * total
    for item, w in weighted:
        x -= w
        if x < 0:
            return item
    return weighted[-1][0]


def roll_axes(rng, table: dict, recent: list, pins: dict) -> dict:
    """One value per axis. `recent` = axis dicts of the last skeletons of this genre (newest last)."""
    used = Counter((k, v) for axes in recent[-RECENT:] for k, v in axes.items())
    out = {}
    for axis, values in table["axes"].items():
        if axis in pins:
            out[axis] = pins[axis]
            continue
        out[axis] = pick(rng, [(v, w * (DECAY ** used[(axis, v)] if decays else 1.0))
                               for v, w, decays in _entries(values)])
    return out


def overlap(a: dict, b: dict, skip=()) -> int:
    return sum(1 for k, v in a.items() if k not in skip and b.get(k) == v)


def parse_pins(facts: list, gid: str, table: dict) -> dict:
    """`genre.axis=value` or `axis=value` facts that name an axis of this genre."""
    pins = {}
    for fact in facts:
        key, sep, value = fact.partition("=")
        if not sep:
            continue
        g, dot, axis = key.strip().rpartition(".")
        if (not dot or g == gid) and axis in table["axes"]:
            pins[axis] = value.strip()
    return pins


# ── structures ────────────────────────────────────────────────────────────────

def build_ladder(rng, table: dict) -> list:
    tiers = sorted(table.get("ladder", {}), key=int)
    return [{"step": int(t), "text": pick(rng, [(v, w) for v, w, _ in _entries(table["ladder"][t])])} for t in tiers]


def build_heist(rng, axes: dict, table: dict) -> dict:
    other = [v for v, _, _ in _entries(table["axes"]["defence"]) if v != axes["defence"]]
    return {"target": axes["target"], "defences": [axes["defence"], rng.choice(other)],
            "insider": axes["insider"], "goes_wrong": axes["goes_wrong"]}


def build_romance(axes: dict) -> list:
    return [{"src": "character", "who": axes["obstacle_holder"], "text": axes["obstacle"]},
            {"src": "circumstance", "who": "", "text": axes["pressure"]}]


def build_case(rng, axes: dict, table: dict, cid: str) -> dict:
    """A fixed-answer case: suspects, places, clues. Clue `text` is a neutral stand-in for the GM to dress
    (it goes to a player's phone as is); what it proves and where it leads sit in their own keys."""
    pools = table["pools"]
    places = rng.sample(pools["places"], rng.randint(3, 5))
    roles = rng.sample([r for r in pools["suspects"] if r != axes["culprit"]], rng.randint(2, 4))
    people = [{"role": axes["culprit"], "means": True, "motive": True, "opportunity": True}]
    for role in roles:
        has = rng.sample(["means", "motive", "opportunity"], rng.randint(1, 2))
        people.append({"role": role, **{k: k in has for k in ("means", "motive", "opportunity")},
                       "suspicious": rng.choice(pools["suspicious"])})
    rng.shuffle(people)
    for i, p in enumerate(people, 1):
        p["id"] = f"s{i}"
    culprit = next(p["id"] for p in people if p["role"] == axes["culprit"])
    case = {"id": cid, "truth": "", "culprit": culprit, "suspects": people, "places": places, "clues": []}
    for c in CONCLUSIONS:
        for where in rng.sample(places, 3):
            _add_clue(case, c, where)
    for p in people:
        if p["id"] != culprit:
            _add_clue(case, f"clears:{p['id']}", rng.choice(places))
    for j, dest in enumerate(places[1:], 1):           # three ways into every place but the first
        sources = [places[0]] * 3 if j == 1 else rng.sample(places[:j], min(3, j)) + [places[0]] * (3 - min(3, j))
        for src in sources:
            free = [c for c in case["clues"] if c["where"] == src and not c.get("leads")]
            if free:
                free[0]["leads"] = dest
            else:
                _add_clue(case, "lead", src, leads=dest)
    for where in places:
        here = [c for c in case["clues"] if c["where"] == where]
        (here[0] if here else _add_clue(case, "lead", where, leads=places[0]))["obvious"] = True
    twist = "" if axes["twist"].startswith("no twist") else f" Twist: {axes['twist']}."
    case["truth"] = (f"{axes['culprit']} ({culprit}) is behind {axes['crime']} against {axes['victim']}, "
                     f"{axes['method']}, because of {axes['motive']}.{twist}")
    return case


def rename_place(case: dict, old: str, new: str) -> None:
    """One case place renamed everywhere: the places list, every clue's where and leads, and stand-in texts."""
    case["places"] = [new if p == old else p for p in case["places"]]
    for c in case["clues"]:
        for key in ("where", "leads"):
            if c.get(key) == old:
                c[key] = new
        if _placeholder(c.get("text", "")):
            c["text"] = c["text"].replace(f" at {old}:", f" at {new}:")


def name_suspect(case: dict, sid: str, name: str) -> None:
    s = next((s for s in case.get("suspects") or [] if s["id"] == sid), None)
    if s is None:
        raise ValueError(f"no suspect {sid!r} (have: {', '.join(x['id'] for x in case.get('suspects') or [])})")
    s["name"] = name
    if sid == case.get("culprit"):
        case["truth"] = re.sub(rf" \({re.escape(sid)}(, [^)]*)?\)", f" ({sid}, {name})", case["truth"], count=1)


def link_case(case: dict, world: dict, seed) -> None:
    """Put the case into the campaign: its places become map places (the party's place first, so the trail starts
    where they are) and its suspects get the names of campaign NPCs, as far as there are enough of each."""
    rng = random.Random(f"{seed}:link:{case.get('id')}")
    places = [p for p in world.get("places") or [] if p not in case["places"]]
    start = world.get("start")
    rng.shuffle(places)
    if start in places:
        places.remove(start)
        places.insert(0, start)
    for old, new in list(zip(case["places"], places)):
        rename_place(case, old, new)
    npcs = list(world.get("npcs") or [])
    rng.shuffle(npcs)
    for s, name in zip(case["suspects"], npcs):
        name_suspect(case, s["id"], name)


def campaign_world(campaign: str) -> dict:
    """Map place names (and where the party is) and NPC names of a campaign, for link_case."""
    import npc
    camp = paths.find_campaign(campaign)
    try:
        mp = json.loads((camp / "world-map.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        mp = {}
    names = {k: str((v or {}).get("name") or k) for k, v in (mp.get("places") or {}).items()}
    return {"places": list(names.values()), "start": names.get(mp.get("party_location") or ""),
            "npcs": npc.index_names(camp)}


def _placeholder(text: str) -> bool:
    return text.startswith("[clue ") and text.endswith("the GM writes it]")


def _who(case: dict, sid: str) -> str:
    s = next((s for s in case.get("suspects") or [] if s["id"] == sid), {})
    return s.get("name") or s.get("role") or sid


def clue_job(clue: dict, case: dict, axes: dict) -> str:
    """What a clue must do, in one line: what it proves, where it leads, how it is found."""
    proves = clue.get("proves", "")
    job = {"who": f"must point to the culprit, {_who(case, case.get('culprit'))}",
           "how": f"must show how it was done: {axes.get('method', '?')}",
           "why": f"must show why: {axes.get('motive', '?')}",
           "lead": "carries no answer; it only points onward"}.get(proves)
    if proves.startswith("clears:"):
        job = f"must clear {_who(case, proves[7:])}: show they could not have done it"
    job = f"Found at {clue.get('where')}. It {job or 'proves ' + proves}"
    if clue.get("leads"):
        job += f", and points to {clue['leads']} (search adds \"(This points to {clue['leads']}.)\" itself)"
    return job + (". Core clue: anyone who looks finds it, no roll, so it must be plain." if clue.get("obvious")
                  else ". Hidden: found only on a good search.")


def plain_text(clue: dict, case: dict, axes: dict) -> str:
    """A plain stand-in that still does the clue's job, for a hidden clue the GM chose not to write."""
    proves = clue.get("proves", "")
    if proves == "who":
        return f"Something here ties {_who(case, case.get('culprit'))} to it."
    if proves == "how":
        return f"Something here shows how it was done: {axes.get('method', '')}."
    if proves == "why":
        return f"Something here hints at why: {axes.get('motive', '')}."
    if proves.startswith("clears:"):
        return f"Something here shows {_who(case, proves[7:])} could not have done it."
    return "A trace that leads elsewhere."


def _add_clue(case: dict, proves: str, where: str, leads: str = "", obvious: bool = False) -> dict:
    n = len(case["clues"]) + 1
    clue = {"id": f"c{n}", "text": f"[clue {n} at {where}: the GM writes it]", "where": where,
            "obvious": obvious, "proves": proves}
    if leads:
        clue["leads"] = leads
    case["clues"].append(clue)
    return clue


# ── the mystery validator ─────────────────────────────────────────────────────

def _reach(clues: list, start: str) -> set:
    seen, todo = {start}, [start]
    while todo:
        here = todo.pop()
        for c in clues:
            if c["where"] == here and c.get("leads") and c["leads"] not in seen:
                seen.add(c["leads"])
                todo.append(c["leads"])
    return seen


def _solved(clues: list, start: str, innocents: list):
    """Which conclusions this clue set still reaches. `who` also falls by elimination: every innocent cleared."""
    reach = _reach(clues, start)
    got = {c["proves"] for c in clues if c["where"] in reach}
    missed = [c for c in CONCLUSIONS if c not in got]
    if "who" in missed and all(f"clears:{s}" in got for s in innocents):
        missed.remove("who")
    return missed, reach


def check_case(case: dict, seed) -> dict:
    """Every rule from plan §4. Returns {ok, problems: [(kind, target, text)], solve_rate, weakest}."""
    problems = []
    clues, places = case.get("clues") or [], case.get("places") or []
    if not places or not clues:
        return {"ok": False, "problems": [("empty", "", "no places or no clues")], "solve_rate": 0.0, "weakest": None}
    start = places[0]
    for c in clues:
        c.setdefault("obvious", False)
        if c.get("where") not in places:
            problems.append(("stray", c["id"], f"clue {c['id']} sits at {c.get('where')!r}, not a case place"))
    reach = _reach(clues, start)
    for p in places:
        if p not in reach:
            problems.append(("unreachable", p, f"{p} cannot be reached from {start}"))
    for con in CONCLUSIONS:
        mine = [c for c in clues if c.get("proves") == con]
        if len(mine) < 3 or len({c["where"] for c in mine}) < 2:
            problems.append(("thin", con, f"'{con}' has {len(mine)} clue(s) in {len({c['where'] for c in mine})} "
                                          "place(s): needs 3 across 2"))
    for p in places:
        if not any(c["where"] == p and c["obvious"] for c in clues):
            problems.append(("no-core", p, f"{p} has no core clue (one found without a roll)"))
    people = case.get("suspects") or []
    full = [s["id"] for s in people if s.get("means") and s.get("motive") and s.get("opportunity")]
    if full != [case.get("culprit")]:
        problems.append(("unique", ",".join(full), f"suspects with means, motive and opportunity: {full or 'none'}; "
                                                    f"must be only the culprit {case.get('culprit')}"))
    innocents = [s["id"] for s in people if s["id"] != case.get("culprit")]
    for s in innocents:
        if not any(c.get("proves") == f"clears:{s}" for c in clues):
            problems.append(("uncleared", s, f"suspect {s} has nothing that clears them"))
    rng = random.Random(f"{seed}:check:{case.get('id')}")
    k, wins, blame = round(len(clues) * DROP), 0, Counter()
    for _ in range(TRIALS):
        gone = set(rng.sample(range(len(clues)), k))
        missed, got = _solved([c for i, c in enumerate(clues) if i not in gone], start, innocents)
        if not missed:
            wins += 1
            continue
        blame.update(("thin", m) for m in missed)
        blame.update(("unreachable", p) for p in places if p not in got)
    rate = wins / TRIALS
    if rate < SOLVE_RATE:
        problems.append(("fragile", "", f"solvable in {rate:.1%} of {TRIALS} games with a third of the clues missed"))
    weakest = max(blame.items(), key=lambda kv: (kv[1], kv[0][0] == "unreachable"))[0] if blame else None
    return {"ok": not problems, "problems": problems, "solve_rate": rate, "weakest": weakest}


def repair_case(case: dict, report: dict) -> bool:
    """Fix the first problem one step. False when there is nothing it knows how to fix."""
    if not report["problems"]:
        if report["solve_rate"] >= REPAIR_TO or not report["weakest"]:
            return False
        kind, target = report["weakest"]          # passes, but too close to the line: add a margin
    else:
        kind, target = report["problems"][0][:2]
        if kind == "fragile":
            if not report["weakest"]:
                return False
            kind, target = report["weakest"]
    places, clues = case["places"], case["clues"]
    count = Counter(c["where"] for c in clues)

    def fewest(among):
        return min(among, key=lambda p: (count[p], places.index(p)))
    if kind == "unreachable":
        src = fewest([p for p in _reach(clues, places[0]) if p != target])
        _add_clue(case, "lead", src, leads=target)
    elif kind == "thin":
        have = {c["where"] for c in clues if c.get("proves") == target}
        _add_clue(case, target, fewest([p for p in places if p not in have] or places))
    elif kind == "no-core":
        here = [c for c in clues if c["where"] == target]
        if here:
            here[0]["obvious"] = True
        else:
            _add_clue(case, "lead", target, leads=places[0], obvious=True)
    elif kind == "uncleared":
        _add_clue(case, f"clears:{target}", fewest(places))
    elif kind == "unique":
        for s in case["suspects"]:
            if s["id"] == case.get("culprit"):
                s.update(means=True, motive=True, opportunity=True)
            elif s.get("means") and s.get("motive") and s.get("opportunity"):
                s["opportunity"] = False       # they have an alibi now; the clearing clue says so
                _add_clue(case, f"clears:{s['id']}", fewest(places))
    else:
        return False
    return True


def fix_case(case: dict, seed, limit: int = 40) -> dict:
    report = check_case(case, seed)
    for _ in range(limit):
        if not repair_case(case, report):
            break
        report = check_case(case, seed)
    return report


# ── per-genre validators ──────────────────────────────────────────────────────

def check_thread(thread: dict, table: dict, seed) -> dict:
    """Validate (and repair in place) one genre thread. → {ok, problems, ...}."""
    problems, extra = [], {}
    for axis in table["axes"]:
        if not str(thread.get("axes", {}).get(axis, "")).strip():
            problems.append(f"axis {axis} is empty")
    if table.get("ladder"):
        steps = [s.get("step") for s in thread.get("ladder") or []]
        if len(steps) < 3 or any(not isinstance(s, int) for s in steps) or steps != sorted(set(steps)):
            problems.append(f"needs at least 3 steps that rise one after another (has {steps})")
    gid = thread.get("genre")
    if gid == "mystery":
        report = fix_case(thread.setdefault("case", {}), seed)
        if not report["ok"]:
            problems += [p[2] for p in report["problems"]]
        extra = {"solve_rate": report["solve_rate"]}
    elif gid == "romance":
        if not any(o.get("src") == "character" and str(o.get("who", "")).strip() and str(o.get("text", "")).strip()
                   for o in thread.get("obstacles") or []):
            problems.append("no obstacle comes from a character: luck alone keeps them apart")
    elif gid == "heist":
        plan = thread.get("plan") or {}
        for key in ("target", "insider", "goes_wrong"):
            if not str(plan.get(key, "")).strip():
                problems.append(f"heist plan has no {key}")
        if len([d for d in plan.get("defences") or [] if str(d).strip()]) < 2:
            problems.append("heist plan needs at least 2 defences")
    return {"ok": not problems, "problems": problems, **extra}


def _core(value: str) -> str:
    return re.sub(r"^(a|an|the)\s+", "", value.strip(), flags=re.I)


def prose_clashes(facts: list, thread: dict, table: dict, pins: dict) -> list:
    """A free-text fact that quotes another value of one of this genre's axes ("a theft" when the skeleton rolled
    "a killing"). shortcut: only whole quoted values (article dropped, 5+ letters) are seen; a paraphrase is not."""
    out = []
    for fact in facts:
        if "=" in fact:
            continue
        for axis, values in table["axes"].items():
            rolled = str(thread["axes"].get(axis, ""))
            if axis in pins or _mentions(fact, [_core(rolled)]):
                continue
            for v, _w, _d in _entries(values):
                if v != rolled and len(_core(v)) >= 5 and _mentions(fact, [_core(v)]):
                    out.append(f"seed fact {fact!r} says {v!r} but {thread['genre']}.{axis} is {rolled!r}: "
                               f"pin it with \"{thread['genre']}.{axis}={v}\" and roll the skeleton again")
                    break
    return out


def check(skel: dict) -> dict:
    """Every thread's validator, plus the seed facts. Repairs in place; re-rolls a mystery it cannot repair,
    but only while its clue texts are still stand-ins: a written case is never thrown away, its problems are listed."""
    out, ok = {}, True
    tables = tables_for([t["genre"] for t in skel["threads"]], skel.get("mix_eras", False))
    for n, thread in enumerate(skel["threads"]):
        table = tables[thread["genre"]]
        pins = parse_pins(skel.get("facts") or [], thread["genre"], table)
        bad = [f"seed fact {a}={v} is contradicted ({thread['axes'].get(a)!r})"
               for a, v in pins.items() if thread["axes"].get(a) != v]
        bad += prose_clashes(skel.get("facts") or [], thread, load_genre(thread["genre"]), pins)
        rep = check_thread(thread, table, skel["seed"])
        tries = 0
        written = [c for c in (thread.get("case") or {}).get("clues") or [] if not _placeholder(c.get("text", ""))]
        while thread["genre"] == "mystery" and not rep["ok"] and not written and tries < 5:   # re-roll that part
            tries += 1
            rng = random.Random(f"{skel['seed']}:reroll:{n}:{tries}")
            thread["case"] = build_case(rng, thread["axes"], table, thread["case"].get("id") or f"case-{skel['seed']}")
            if skel.get("world"):
                link_case(thread["case"], skel["world"], skel["seed"])
            rep = check_thread(thread, table, skel["seed"])
            rep["rerolled"] = tries
        rep["problems"] = bad + rep["problems"]
        rep["ok"] = not rep["problems"]
        out[thread["genre"]] = rep
        ok = ok and rep["ok"]
    return {"ok": ok, "threads": out}


# ── the four steps ────────────────────────────────────────────────────────────

def generate(genres: list, seed=None, facts=None, history_at=None, record=True, world=None, mix_eras=False) -> dict:
    """Roll a skeleton for 1–5 genres. Same seed + same history_at → the same skeleton.
    `world` ({places, start, npcs}: campaign_world) puts a mystery's places and suspects into the campaign."""
    genres = [g.strip() for g in genres if g.strip()]
    if not 1 <= len(genres) <= 5 or len(set(genres)) != len(genres):
        raise ValueError("give 1 to 5 different genres")
    tables = tables_for(genres, mix_eras)
    if seed is None:
        seed = random.SystemRandom().randrange(1, 2 ** 31)
    history = read_history(history_at)
    history_at = len(history)
    facts = list(facts or [])
    rng = random.Random(seed)
    drives = next((g for g in genres if tables[g]["kind"] == "plot"), genres[0])
    threads = []
    for gid in genres:
        table = tables[gid]
        pins = parse_pins(facts, gid, table)
        past = _past_axes(history, gid)
        best = None
        for _ in range(GATE_TRIES):
            axes = roll_axes(rng, table, past, pins)
            worst = max((overlap(axes, p, skip=pins) for p in past[-GATE_LOOKBACK:]), default=0)
            if best is None or worst < best[0]:
                best = (worst, axes)
            if worst <= GATE:
                break
        thread = {"genre": gid, "kind": table["kind"], "role": "drives" if gid == drives else "sub-thread",
                  "axes": best[1], "shares_at_most": best[0]}
        if table.get("ladder"):
            thread["ladder"] = build_ladder(rng, table)
        if gid == "mystery":
            thread["case"] = build_case(rng, thread["axes"], table, f"case-{seed}")
            if world:
                link_case(thread["case"], world, seed)
        elif gid == "heist":
            thread["plan"] = build_heist(rng, thread["axes"], table)
        elif gid == "romance":
            thread["obstacles"] = build_romance(thread["axes"])
        threads.append(thread)
    skel = {"seed": seed, "history_at": history_at, "genres": genres, "drives": drives, "facts": facts,
            "threads": threads, "flesh": {}, **({"world": world} if world else {}), **({"mix_eras": True} if mix_eras else {})}
    skel["checked"] = check(skel)
    if record:
        append_history({"kind": "skeleton", "seed": seed, "history_at": history_at, "genres": genres,
                        "axes": {t["genre"]: t["axes"] for t in threads}})
    return skel


def banned(skel: dict, history: list) -> tuple:
    """(cliché phrases of every genre in play, recent flesh picks)."""
    cliches = [c for g in skel["genres"] for c in load_genre(g).get("cliches", [])]
    picks = [r["text"] for r in history if r.get("kind") == "flesh"][-GATE_LOOKBACK:]
    return cliches, picks


def flesh(skel: dict, slot: str, candidates: list, record=True) -> dict:
    """Drop banned candidates, then pick one by rng weighted by the GM's probabilities.
    Slot `clue:<id>` also writes the pick into that clue's text, which is what `search` shows the player."""
    clue = None
    if slot.startswith("clue:"):
        clue = next((c for t in skel["threads"] for c in (t.get("case") or {}).get("clues") or []
                     if c["id"] == slot[5:]), None)
        if clue is None:
            raise ValueError(f"no clue {slot[5:]!r} in this skeleton")
    if clue is not None and not clue.get("obvious"):    # a hidden clue: fewer candidates are enough
        if not 1 <= len(candidates) <= 5:
            raise ValueError(f"write 1 to 5 candidates for a hidden clue (got {len(candidates)})")
    elif len(candidates) != 5:
        raise ValueError(f"write exactly 5 candidates (got {len(candidates)})")
    for c in candidates:
        p = c.get("p")
        if not str(c.get("text", "")).strip() or not isinstance(p, (int, float)) or not 0 < p <= 0.10:
            raise ValueError(f"each candidate needs text and 0 < p <= 0.10 (got {c!r})")
    cliches, picks = banned(skel, read_history())
    kept, dropped = [], []
    for c in candidates:
        text = c["text"].casefold()
        hit = next((f"cliché: {b}" for b in cliches if b.casefold() in text), None) or next(
            (f"repeats: {r}" for r in picks if difflib.SequenceMatcher(None, text, r.casefold()).ratio() >= SIMILAR), None)
        (dropped.append({**c, "why": hit}) if hit else kept.append(c))
    if not kept:
        raise ValueError("every candidate is banned: write new ones. " + "; ".join(d["why"] for d in dropped))
    rng = random.Random(f"{skel['seed']}:flesh:{slot}")
    chosen = pick(rng, [(c, float(c["p"])) for c in kept])
    skel.setdefault("flesh", {})[slot] = {"text": chosen["text"], "p": chosen["p"], "dropped": dropped}
    if clue is not None:
        clue["text"] = chosen["text"]
    if record:
        append_history({"kind": "flesh", "seed": skel["seed"], "genres": skel["genres"], "slot": slot,
                        "text": chosen["text"]})
    return skel["flesh"][slot]


# ── CLI ───────────────────────────────────────────────────────────────────────

def _file(args):
    if args.file:
        return args.file
    if args.campaign:
        return str(paths.find_campaign(args.campaign) / "story-skeleton.json")
    raise ValueError("give --file or -c <campaign>")


def _load(path) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return {}


def _save(path, data) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
        fh.write("\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("-c", "--campaign")
    ap.add_argument("--file")
    sub = ap.add_subparsers(dest="cmd", required=True)
    x = sub.add_parser("axes", help="list each genre's axes and values (what seed can pin as genre.axis=value)")
    x.add_argument("genres", help="comma list")
    s = sub.add_parser("seed")
    s.add_argument("facts", nargs="*")
    k = sub.add_parser("skeleton")
    k.add_argument("--genre", required=True, help="comma list, main genre first")
    k.add_argument("--seed", type=int)
    k.add_argument("--history-at", type=int, help="replay against the first K history lines; records nothing")
    k.add_argument("--mix-eras", action="store_true", help="the players want eras mixed (pirates with phones): no era bans")
    f = sub.add_parser("flesh")
    f.add_argument("--slot", required=True)
    f.add_argument("--candidates", help='JSON list of 5 {"text", "p"}; omit to print the brief')
    sub.add_parser("fill", help="plain text for every hidden clue still unwritten")
    n = sub.add_parser("name", help="name a suspect (s1) or rename a case place")
    n.add_argument("target")
    n.add_argument("new_name")
    sub.add_parser("check")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "axes":
            for gid, table in tables_for(args.genres.split(",")).items():
                print(f"## {gid} ({table['kind']})" + (f" — leaves out: {', '.join(ban_words(table))}" if table.get("bans") else ""))
                for axis, values in table["axes"].items():
                    print(f"{gid}.{axis}: " + " | ".join(v for v, _w, _d in _entries(values)))
            return 0
        path = _file(args)
        data = _load(path)
        if args.cmd == "seed":
            data["facts"] = data.get("facts", []) + args.facts
            _save(path, data)
            print(json.dumps({"facts": data["facts"]}, ensure_ascii=False, indent=1))
            return 0
        if args.cmd == "skeleton":
            if args.history_at is None:
                drop_unused(data)
            skel = generate(args.genre.split(","), args.seed, data.get("facts"), args.history_at,
                            record=args.history_at is None, world=campaign_world(args.campaign) if args.campaign else None,
                            mix_eras=args.mix_eras)
            _save(path, skel)
            print(json.dumps(skel, ensure_ascii=False, indent=1))
            return 0 if skel["checked"]["ok"] else 1
        if not data.get("threads"):
            raise ValueError(f"no skeleton in {path}: run skeleton first")
        mystery = next((t for t in data["threads"] if t["genre"] == "mystery"), None)
        case = (mystery or {}).get("case") or {}
        if args.cmd == "fill":
            filled = []
            for c in case.get("clues") or []:
                if not c.get("obvious") and _placeholder(c.get("text", "")):
                    c["text"] = plain_text(c, case, mystery["axes"])
                    filled.append(c["id"])
            _save(path, data)
            print(json.dumps({"filled": filled, "still_unwritten": [c["id"] for c in case.get("clues") or []
                                                                     if _placeholder(c.get("text", ""))]},
                             ensure_ascii=False, indent=1))
            return 0
        if args.cmd == "name":
            if not case:
                raise ValueError("no mystery case in this skeleton")
            if args.target in case["places"]:
                rename_place(case, args.target, args.new_name)
            else:
                name_suspect(case, args.target, args.new_name)
            _save(path, data)
            print(json.dumps({"places": case["places"], "suspects": case["suspects"]}, ensure_ascii=False, indent=1))
            return 0
        if args.cmd == "flesh":
            if args.candidates is None:
                cliches, picks = banned(data, read_history())
                clue = next((c for c in case.get("clues") or [] if f"clue:{c['id']}" == args.slot), None)
                hidden = clue is not None and not clue.get("obvious")
                brief = {"slot": args.slot, "seed": data["seed"], "drives": data["drives"],
                         "givens": {t["genre"]: t["axes"] for t in data["threads"]},
                         "facts": data.get("facts", []), "do_not_use": cliches + picks[-30:],
                         "write": ("1 to 5" if hidden else "exactly 5") + ' candidates as JSON [{"text": "...", "p": 0.07}, ...]; '
                                  "each p <= 0.10, from the unlikely tail; none may contradict the givens"}
                if clue is not None:
                    brief["clue"] = {k: clue.get(k) for k in ("where", "proves", "leads", "obvious")}
                    brief["job"] = clue_job(clue, case, mystery["axes"]) + (
                        " Every candidate must do this job: vary the detail, not the job.")
                    brief["suspects"] = case.get("suspects")
                    brief["culprit"] = case.get("culprit")
                print(json.dumps(brief, ensure_ascii=False, indent=1))
                return 0
            got = flesh(data, args.slot, json.loads(args.candidates))
            _save(path, data)
            print(json.dumps(got, ensure_ascii=False, indent=1))
            return 0
        data["checked"] = check(data)
        _save(path, data)
        print(json.dumps(data["checked"], ensure_ascii=False, indent=1))
        return 0 if data["checked"]["ok"] else 1
    except (ValueError, KeyError) as exc:
        print(f"story_gen: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
