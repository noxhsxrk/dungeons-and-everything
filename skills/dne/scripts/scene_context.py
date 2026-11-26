#!/usr/bin/env python3
"""
scene_context.py — what a turn needs to know before it is run, and who is allowed to know it.

Built at the start of every engine turn (turn.py begin) and printed on demand:

    scene_context.py -c <campaign> [--text "<the table's input>"] [--for dm|player:<Name>|companion:<Name>]
                     [--budget 1800]

Order (and what is cut first when the budget runs out, last line first):
  1. pending — who the turn is waiting on            never cut
  2. conditions — effects and conditions in force     never cut
  3. place and who is present
  4. who the input talks about (names, nicknames in any script, "him again")
  5. what just happened
  6. the table's rules for this campaign
  7. relationships from the graph, then lore matches  cut first

Audiences: the GM sees everything. A player sees what their character was told, including whispers
sent to them and never another player's. A companion sees public events only. Secrets (DM-only lore,
other people's whispers) are dropped for anyone but the GM, never shortened into a hint.

The scene itself (place, who is present) is set by the engine action
    {"action": "scene", "place": "<place>", "present": ["<name>", ...]}
and falls back to the campaign map's party location.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import paths  # noqa: E402
import world_db as wdb  # noqa: E402

#: Words that point at someone without naming them. Resolved from who was mentioned last and who is here.
PRONOUNS = ("เขา", "เธอ", "มัน", "คนเดิม", "คนนั้น", "หล่อน", "แก",
            " he ", " she ", " him ", " her ", " them ", " they ", "that guy", "the same one", "same person")
RULE_FLAGS = ("roll_mode", "show_dc", "turn_end", "pacing", "content", "romance", "engine", "rolls")
_ALIAS = re.compile(r"\*\*(?:Aliases|Also called|ชื่อเรียก)\s*:?\*\*\s*:?\s*([^\n|]+)")


def _aliases_in(text: str) -> list[str]:
    m = _ALIAS.search(text)
    return [a.strip() for a in re.split(r"[,/、]", m.group(1)) if a.strip()] if m else []


def entities(campaign: str) -> list[dict]:
    """Everyone and everywhere the story can name: {id, name, aliases, kind, source}. `id` points back at the record."""
    camp = paths.find_campaign(campaign)
    found = []
    try:
        import npc
        full = npc.entries(camp)
        for name in dict.fromkeys(npc.index_names(camp) + list(full)):
            found.append({"id": f"npc:{name}", "name": name, "kind": "npc", "source": "npcs-full.md",
                          "aliases": npc.aliases(name, full.get(name))})
    except Exception:
        pass
    for kind, folder in (("pc", "characters"), ("companion", "companions")):
        for sheet in sorted((camp / folder).glob("*.md")) if (camp / folder).is_dir() else []:
            text = sheet.read_text(encoding="utf-8", errors="replace")
            first = text.splitlines()[0].lstrip("# ").strip() if text.strip() else sheet.stem
            name = first or sheet.stem
            names = [name, name.split()[0], sheet.stem] + _aliases_in(text)
            found.append({"id": f"{kind}:{sheet.stem}", "name": name, "kind": kind, "source": f"{folder}/{sheet.name}",
                          "aliases": [a for a in dict.fromkeys(names) if len(a) >= 2]})
    try:
        places = json.loads((camp / "world-map.json").read_text(encoding="utf-8")).get("places", {})
        for key, place in places.items():
            name = place.get("name") or key
            found.append({"id": f"place:{key}", "name": name, "kind": "place", "source": "world-map.json",
                          "aliases": [a for a in dict.fromkeys([name] + list(place.get("aliases") or [])) if len(a) >= 2]})
    except (OSError, ValueError, AttributeError):
        pass
    return found


def _said(text: str) -> str:
    """The input without its speaker tags: in "[Mira]: ask him again", Mira is talking, she is not being talked about."""
    return "\n".join(re.sub(r"^\s*\[[^\]]+\]\s*:", "", line) for line in text.splitlines())


def mentioned(campaign: str, text: str, pool: "list | None" = None) -> list[dict]:
    """Entities the text names, by full name or any alias (a Thai nickname finds the same record as the full name)."""
    low = _said(text).casefold()
    return [e for e in (pool if pool is not None else entities(campaign))
            if any(a.casefold() in low for a in e["aliases"])]


SPEECH = re.compile(r'["“”「」]|\b(?:says?|said|asks?|asked|whispers?|shouts?|repl(?:y|ies|ied))\b'
                    r"|พูด|บอก|ตอบ|ถาม|กระซิบ|ตะโกน|เอ่ย|กล่าว", re.IGNORECASE)


def absent_speakers(campaign: str, narration: str) -> list[str]:
    """Known NPCs the narration seems to have talking though the scene does not have them here. The speaker is taken
    as the NPC named nearest before the first quote or speech verb of a sentence; a heuristic, so it only warns."""
    present = {p.casefold() for p in scene(campaign).get("present") or []}
    if not present:                                   # nobody recorded here: nothing to check against
        return []
    pool = [e for e in entities(campaign) if e["kind"] == "npc"]
    out = []
    for chunk in re.split(r'\n|(?<=[”」"])\s+', narration):
        m = SPEECH.search(chunk)
        before = chunk[:m.start()].casefold() if m else ""
        spots = [(max(before.rfind(a.casefold()) for a in e["aliases"]), e) for e in pool if e["aliases"]]
        pos, who = max(spots, key=lambda s: s[0], default=(-1, None))
        if pos >= 0 and not {a.casefold() for a in who["aliases"]} & present:
            out.append(who["name"])
    return list(dict.fromkeys(out))


def scene(campaign: str) -> dict:
    """{place, present}: what the engine was told, else the map's party location and nobody known present."""
    with wdb.reader(campaign) as db:
        stored = wdb.get(db, "scene", "current") if db is not None else None
    if stored:
        return stored
    try:
        here = json.loads((paths.find_campaign(campaign) / "world-map.json").read_text(encoding="utf-8")).get("party_location")
    except (OSError, ValueError):
        here = None
    return {"place": here, "present": []}


def _recent_mentions(campaign: str) -> list:
    """[(entity id, turn it was last named in)], newest first."""
    with wdb.reader(campaign) as db:
        rows = wdb.all_of(db, "mention") if db is not None else {}
    return sorted(((eid, rec.get("turn", 0)) for eid, rec in rows.items()), key=lambda r: -r[1])


def remember_mentions(db, text: str, campaign: str, turn_seq: int) -> None:
    """Called by turn.begin: note who this input named, so a later "him again" has someone to mean."""
    for e in mentioned(campaign, text):
        if e["kind"] != "place":
            wdb.put(db, "mention", e["id"], {"turn": turn_seq, "name": e["name"]})


def reference(campaign: str, text: str, named: list, here: dict, pool: list) -> "dict | None":
    """Who an unnamed "he / she / the same one" means, or the short question to ask when it is not clear."""
    padded = f" {_said(text).casefold()} "
    if any(e["kind"] != "place" for e in named) or not any(p in padded for p in PRONOUNS):
        return None
    by_id = {e["id"]: e for e in pool}
    present = {e["id"] for e in pool if e["name"] in (here.get("present") or [])}
    recent = [(i, t) for i, t in _recent_mentions(campaign) if i in by_id and by_id[i]["kind"] != "pc"]
    last_turn = [i for i, t in recent if t == recent[0][1]] if recent else []   # two people named together stay two
    candidates = ([i for i, _t in recent if i in present] or last_turn
                  or sorted(i for i in present if by_id[i]["kind"] != "pc"))
    names = list(dict.fromkeys(by_id[i]["name"] for i in candidates))   # an NPC who is also a companion is one person
    if len(names) == 1:
        return {"means": names[0], "id": candidates[0]}
    if not candidates:
        return {"ask": "Who do you mean? Nobody was named."}
    return {"ask": "Who do you mean: " + " or ".join(names[:4]) + "?", "candidates": names[:4]}


def _recent_events(campaign: str, audience: str, n: int = 5) -> list[str]:
    """The last things shown on the feed that this audience was allowed to see."""
    try:
        log = json.loads((paths.runtime_dir() / "text_log.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    who = audience.split(":", 1)[1].casefold() if ":" in audience else ""
    out = []
    for e in log:
        if not isinstance(e, dict) or not e.get("text"):
            continue
        to = [str(t).casefold() for t in (e.get("whisper_to") or [])]
        if to or e.get("whisper"):
            if audience != "dm" and (audience.startswith("companion") or who not in to):
                continue                           # someone else's secret: gone, not shortened
            tag = f"[whisper to {', '.join(e.get('whisper_to') or [])}] " if audience == "dm" else "[told only to you] "
        else:
            tag = ""
        out.append(tag + " ".join(str(e["text"]).split())[:220])
    return out[-n:]


def _conditions(campaign: str) -> list[str]:
    try:
        state = json.loads((paths.find_campaign(campaign) / "tracker.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    lines = []
    for key, ent in state.items():
        if key.startswith("_") or not isinstance(ent, dict):
            continue
        bits = list(ent.get("conditions") or [])
        bits += [str(f.get("name")) for f in ent.get("effects") or [] if isinstance(f, dict) and f.get("name")]
        if ent.get("concentration"):
            bits.append(f"concentrating on {ent['concentration']}")
        if ent.get("exhaustion"):
            bits.append(f"exhaustion {ent['exhaustion']}")
        if bits:
            lines.append(f"{ent.get('name', key)}: {', '.join(dict.fromkeys(bits))}")
    return lines


def _graph(campaign: str, here: dict) -> str:
    seeds = [s for s in [here.get("place")] + list(here.get("present") or []) if s]
    if not seeds or not (paths.find_campaign(campaign) / "graph.json").exists():
        return ""
    try:
        import campaign_graph
        args = argparse.Namespace(campaign=campaign, place=here.get("place"), present=",".join(here.get("present") or []) or None,
                                  threads=None, hops=1, at_session=None)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            campaign_graph.cmd_scene_context(args)
        text = buf.getvalue().strip()
        return "" if text.startswith("# graph not initialized") or text.startswith("warning") and "\n" not in text else text
    except (Exception, SystemExit):
        return ""


def build(campaign: str, text: str = "", audience: str = "dm", budget: int = 1800) -> dict:
    """The context for one turn, already filtered for `audience` and fitted to `budget` characters."""
    pool = entities(campaign)
    here = scene(campaign)
    named = mentioned(campaign, text, pool) if text else []
    with wdb.reader(campaign) as db:
        pending = [] if db is None else [
            {"request_id": r["request_id"], "expected": r["expected"], "question": json.loads(r["question"]).get("text", "")}
            for r in db.execute("SELECT * FROM requests WHERE status='open' ORDER BY request_id")]
    view = {
        "audience": audience,
        "pending": pending,
        "conditions": _conditions(campaign),
        "place": here.get("place"),
        "present": list(here.get("present") or []),
        "mentioned": [{"id": e["id"], "name": e["name"], "source": e["source"]} for e in named],
        "reference": reference(campaign, text, named, here, pool) if text else None,
        "recent": _recent_events(campaign, audience),
        "heard_here": _heard_here(campaign, here) if audience == "dm" else [],
        "npc_knows": _npc_knows(campaign, here, pool) if audience == "dm" else {},   # beliefs hold secrets
        "rules": {k: v for k in RULE_FLAGS if (v := paths.session_flag(campaign, k, ""))},
    }
    if paths.campaign_system(campaign) != "d20":   # Braid dials the GM rules by (5e has none of them)
        import modules
        view["rules"].update({k: v for k in ("claims", "storyteller") if (v := paths.session_flag(campaign, k, ""))})
        view["rules"]["modules"] = ", ".join(modules.enabled(campaign)) or "(none)"
    used = len(json.dumps(view, ensure_ascii=False))
    view["relations"], view["lore"], view["cut"] = "", "", []
    if audience == "dm":                           # relationships and lore hold secrets: the GM only
        for key, text_ in (("relations", _graph(campaign, here)), ("lore", _lore(campaign, text, max(0, budget - used)))):
            room = budget - used
            if text_ and len(text_) <= room:
                view[key] = text_
                used += len(text_)
            elif text_:
                view["cut"].append(key)
    while used > budget and view["recent"]:        # then the oldest of what just happened
        used -= len(view["recent"].pop(0))
        if "recent" not in view["cut"]:
            view["cut"].append("recent")
    return view


KNOWS_PER_NPC = 3          # shortcut: newest 3 per NPC, 110 characters each; `knows` has the rest


def _npc_knows(campaign: str, here: dict, pool: list) -> dict:
    """For each NPC in the scene, what they know of the PCs: their bond line on a sheet or in the engine, and the
    beliefs they hold (knowledge.py), matched through their aliases. An empty list means only what they can see."""
    present = {p.casefold() for p in here.get("present") or []}
    npcs = [e for e in pool if e["kind"] == "npc"
            and present & {n.casefold() for n in [e["name"], *e.get("aliases", [])]}]
    if not npcs:
        return {}
    camp, sheet_bonds = paths.find_campaign(campaign), []
    try:
        import sheet
        for path in sorted((camp / "characters").glob("*.md")):
            sheet_bonds += [(path.stem, b) for b in sheet.parse(path.read_text(encoding="utf-8", errors="replace"))["bonds"]]
    except Exception:          # a 5e sheet has no bonds section
        pass
    with wdb.reader(campaign) as db:
        beliefs = wdb.all_of(db, "belief") if db is not None else {}
        bonds = wdb.all_of(db, "bond") if db is not None else {}
    out = {}
    for e in npcs:
        names = {n.casefold() for n in [e["name"], *e.get("aliases", [])]}
        known = []
        for pc, line in sheet_bonds:
            who, _, note = line.partition(":")
            if who.strip().casefold() in names:
                known.append(f"bond with {pc}: {note.strip() or '(no note)'}")
        for rec in bonds.values():
            note = str(rec.get("note") or "").strip()
            if note and names & {str(x).casefold() for x in rec.get("between") or []} and not any(note in k for k in known):
                known.append(f"bond: {note}")
        held = sorted((b for key, b in beliefs.items() if key.startswith("npc:")
                       and key.split("|", 1)[0][4:].casefold() in names), key=lambda b: -(b.get("learned_at") or 0))
        known += [f"{b['claim']} ({b['source']})" for b in held]
        out[e["name"]] = [k if len(k) <= 110 else k[:109] + "…" for k in known[:KNOWS_PER_NPC]]
    return out


def _heard_here(campaign: str, here: dict) -> list[str]:
    """What is common knowledge where the party stands (knowledge.py): the newest three things this place has heard."""
    try:
        place = here.get("place") or ""
        data = json.loads((paths.find_campaign(campaign) / "world-map.json").read_text(encoding="utf-8"))
        key = place if place in data.get("places", {}) else data.get("party_location")
        with wdb.reader(campaign) as db:
            rows = wdb.all_of(db, "belief") if db is not None else {}
    except (OSError, ValueError):
        return []
    mine = sorted((b for k, b in rows.items() if k.startswith(f"place:{key}|")), key=lambda b: -(b.get("learned_at") or 0))
    return [f"{b['claim']} (by {b['source']})" for b in mine[:3]]


def _lore(campaign: str, text: str, room: int) -> str:
    if not text or room < 200:
        return ""
    try:
        import lorebook
        return lorebook.format_scan_block(lorebook.scan_lore(campaign, text, budget=room, include_hidden=True))
    except Exception:
        return ""


def render_parts(view: dict) -> list:
    """The context as (priority, line) pairs for the GM note: 0 is binding, 1 the scene, 3 depth that is cut first."""
    parts = []
    for p in view.get("pending") or []:
        parts.append((0, f"STILL WAITING: {p['question'] or p['request_id']} ({p['request_id']}, from {p['expected']})."))
    if view.get("conditions"):
        parts.append((0, "In force: " + "; ".join(view["conditions"]) + "."))
    ref = view.get("reference")
    if ref and ref.get("ask"):
        parts.append((0, f"UNCLEAR WHO IS MEANT. Ask before anything changes in the world: \"{ref['ask']}\""))
    elif ref:
        parts.append((1, f"\"He/she/the same one\" here means {ref['means']} (last named, and present)."))
    if view.get("npc_knows"):
        parts.append((0, "What the NPCs here know of the PCs, and all they know (a PC's sheet, gear and past are the "
                      "player's; record what a PC tells them with `fact`, naming them as witnesses): "
                      + "; ".join(f"{n}: {' | '.join(k) if k else 'only what they see'}" for n, k in view["npc_knows"].items())
                      + "."))
    where = view.get("place") or "place not set"
    who = ", ".join(view.get("present") or []) or "nobody recorded"
    parts.append((1, f"Scene: {where}. Present: {who}."))
    if view.get("mentioned"):
        parts.append((1, "Named in this input: " + "; ".join(f"{m['name']} ({m['source']})" for m in view["mentioned"]) + "."))
    if view.get("recent"):
        parts.append((1, "Just happened: " + " | ".join(view["recent"][-3:])))
    if view.get("heard_here"):
        parts.append((1, "People here have heard: " + " | ".join(view["heard_here"])
                      + " Anyone elsewhere knows only what `knows` lists for them."))
    if view.get("relations"):
        parts.append((3, "Relationships here:\n" + view["relations"]))
    if view.get("lore"):
        parts.append((3, view["lore"]))
    if view.get("cut"):
        parts.append((3, "(Left out for space: " + ", ".join(view["cut"]) + ". Run scene_context.py for the rest.)"))
    return parts


def render(view: dict) -> list[str]:
    """The context as lines, most binding first."""
    return [line for _prio, line in sorted(render_parts(view), key=lambda p: p[0])]


def _scene_action(ctx, intent: dict) -> dict:
    """scene — say where the party is and who is with them. No in-world time passes.

    {"action": "scene", "place": "Millbridge market", "present": ["Bren", "the toll captain"]}
    Sets what every later turn's context starts from, and who "him" or "her" can mean."""
    data = {"place": intent.get("place"), "present": [str(p) for p in intent.get("present") or []]}
    wdb.put(ctx.db, "scene", "current", data)
    return {"status": "done", "elapsed_minutes": 0, "data": data}


def _register() -> None:
    try:
        import turn
        turn.HANDLERS.setdefault("scene", _scene_action)
    except Exception:
        pass


_register()


def main() -> int:
    p = argparse.ArgumentParser(description="Scene context for one turn, filtered by who may know it.")
    p.add_argument("-c", "--campaign", required=True)
    p.add_argument("--text", default="")
    p.add_argument("--for", dest="audience", default="dm", help="dm | player:<Name> | companion:<Name>")
    p.add_argument("--budget", type=int, default=1800)
    p.add_argument("--json", action="store_true")
    args = p.parse_args()
    view = build(args.campaign, args.text, args.audience, args.budget)
    print(json.dumps(view, ensure_ascii=False, indent=1) if args.json else "\n".join(render(view)))
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
