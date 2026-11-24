#!/usr/bin/env python3
"""
character.py — D&D 5e character stat calculator

Derives all secondary stats from raw inputs. Used by the DM (Claude)
to verify and generate character sheets without manual arithmetic.

Usage:
    python3 character.py calc --class fighter --level 1 \\
        STR=15 DEX=10 CON=15 INT=9 WIS=11 CHA=14 \\
        --proficient STR CON Athletics Intimidation Perception Survival

    python3 character.py calc --class cleric --level 1 --race dwarf \\
        --subrace hill-dwarf STR=15 DEX=10 CON=14 INT=9 WIS=13 CHA=11
        Scores given are the BASE array; racial bonuses are applied here and
        shown as base / race / final. An unknown race exits non-zero rather
        than applying nothing.

    python3 character.py calc --class fighter --level 1 --background soldier \\
        --background-asi STR=2,CON=1 STR=15 DEX=13 CON=14 INT=8 WIS=12 CHA=10
        2024 rules: the background raises its three listed abilities, either
        +2/+1 or +1/+1/+1 (`--background-asi +1/+1/+1`). SRD 5.2 backgrounds
        only; an unknown background or an ability it does not list exits
        non-zero.

    python3 character.py calc --class fighter ... --armor chain-mail --shield \\
        [--fighting-style defense]
        Armor Class from the SRD armor record. `--armor none` gives
        unarmored AC, with Unarmored Defense for a barbarian or monk.

    calc also accepts --expertise <skill> [<skill> ...], --subclass <name>,
        --ruleset 2014|2024, and -c/--campaign <campaign>.

    python3 character.py levelup --class fighter --from 1 --to 2 \\
        --hp-roll 6 --con-mod 2 [--con-mod-before 1] [--subclass champion] \\
        [--ruleset 2014|2024]
        Also lists the choices the new level owes: an Ability Score
        Improvement, the subclass, invocations, a pact boon, a fighting style,
        and HP owed retroactively when the CON modifier rose.

    python3 character.py hitdie --die d10 --con-mod 2 --hp 9 --max-hp 20 \\
        --remaining 3 [--count 2] [--roll N[,N…]] [--ruleset 2014|2024 | -c <campaign>]
        Spend Hit Dice on a short rest: each die rolls + CON mod.

    python3 character.py rest long --level 5 --hd-remaining 1 --hp 9 \\
        --max-hp 38 [--exhaustion 1] [--ruleset 2014|2024 | -c <campaign>]
        What a long rest restores, gated on the character having at least 1 HP.

    python3 character.py xp --level 1 --gained 150
        Print XP total and whether level-up threshold is reached.

    python3 character.py hero <use|award|reset|recover> --char <name> -c <campaign>
    python3 character.py focus <use|refocus|reset> --char <name> -c <campaign> [--max N]
        Update the optional point pools on a character sheet.
"""

import argparse
import json
import os
import re
import secrets
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import worldkit
from paths import campaign_ruleset, find_character_file, norm_key, srd_path

# Windows / non-UTF-8 consoles: the output carries arrows and dashes, which a
# cp1252, GBK or ASCII stdout cannot encode. Same fix as the sibling scripts.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:
        pass


# ─── Racial ability bonuses (SRD, 2014 rules) ────────────────────────────────
#
# THESE ARE APPLIED HERE, NOT REMEMBERED. The character-creation flow used to
# say "Apply racial bonuses" and then "run character.py calc" -- but calc had no
# `--race` parameter at all, so it never saw the race and could not check the
# step had happened. A Dwarf and an Elf built the same way came out with the
# same Constitution, and nothing in the toolchain could notice.
#
# Keyed by SRD index (lower-case, hyphenated), which is what `lookup.py race`
# reports, so the two agree by construction. Reconciled against the built SRD
# dataset by tests/test_racial_bonuses.py -- a drifted value fails there rather
# than silently producing a wrong sheet.
RACE_BONUSES = {
    "dwarf":      {"CON": 2},
    "elf":        {"DEX": 2},
    "halfling":   {"DEX": 2},
    "human":      {"STR": 1, "DEX": 1, "CON": 1, "INT": 1, "WIS": 1, "CHA": 1},
    "dragonborn": {"STR": 2, "CHA": 1},
    "gnome":      {"INT": 2},
    "half-elf":   {"CHA": 2},
    "half-orc":   {"STR": 2, "CON": 1},
    "tiefling":   {"INT": 1, "CHA": 2},
}

#: Subrace bonuses STACK on top of the parent race's. Half-Elf is the SRD's
#: one irregular case -- it grants +1 to two abilities of the player's choice
#: on top of its +2 CHA, which no table can express, so it is passed through
#: as a prompt rather than a number (see apply_racial_bonuses).
SUBRACE_BONUSES = {
    "hill-dwarf":         {"WIS": 1},
    "high-elf":           {"INT": 1},
    "lightfoot-halfling": {"CHA": 1},
    "rock-gnome":         {"CON": 1},
}

SUBRACE_PARENT = {
    "hill-dwarf": "dwarf", "high-elf": "elf",
    "lightfoot-halfling": "halfling", "rock-gnome": "gnome",
}

#: Races whose SRD entry grants a player CHOICE the tables above cannot hold.
#: Reported so the sheet writer is told to resolve it, instead of the choice
#: being silently dropped.
RACE_CHOICES = {
    "half-elf": "+1 to two abilities of your choice (SRD Half-Elf)",
}


def _race_key(name: str) -> str:
    """Normalise a race or subrace name to its SRD index."""
    from paths import norm_key
    return norm_key(name)


def apply_racial_bonuses(scores: dict, race: str = "", subrace: str = "") -> tuple:
    """Return (final_scores, applied, notes).

    `applied` maps stat -> total bonus added, so the caller can show base,
    racial and final rather than only the result. An unknown race RAISES: a
    typo that silently applied nothing is the whole defect this exists to
    stop, and a sheet that is quietly wrong is worse than a command that
    refuses.
    """
    out = dict(scores)
    applied: dict = {}
    notes: list = []
    if not race and not subrace:
        return out, applied, notes

    rkey = _race_key(race)
    skey = _race_key(subrace)

    if skey:
        if skey not in SUBRACE_BONUSES:
            raise ValueError(
                f"Unknown subrace {subrace!r}. Known: "
                f"{', '.join(sorted(SUBRACE_BONUSES))}")
        parent = SUBRACE_PARENT[skey]
        if rkey and rkey != parent:
            raise ValueError(
                f"Subrace {subrace!r} belongs to {parent!r}, not {race!r}")
        rkey = parent

    if rkey not in RACE_BONUSES:
        raise ValueError(
            f"Unknown race {race!r}. Known: {', '.join(sorted(RACE_BONUSES))}")

    for stat, bonus in RACE_BONUSES[rkey].items():
        applied[stat] = applied.get(stat, 0) + bonus
    if skey:
        for stat, bonus in SUBRACE_BONUSES[skey].items():
            applied[stat] = applied.get(stat, 0) + bonus

    for stat, bonus in applied.items():
        out[stat] = out.get(stat, 10) + bonus
    if rkey in RACE_CHOICES:
        notes.append(RACE_CHOICES[rkey])
    return out, applied, notes


# ─── Background ability increases (SRD 5.2, 2024 rules) ─────────────────────
#
# In the 2024 rules the ability increase comes from the background, not the
# species: +2 to one of the background's three abilities and +1 to another, or
# +1 to all three. Only the SRD 5.2 backgrounds are listed; reconciled against
# the 2024 upstream data by tests/test_character_rules.py.
BACKGROUND_ABILITIES = {
    "acolyte":  ("INT", "WIS", "CHA"),
    "criminal": ("DEX", "CON", "INT"),
    "sage":     ("CON", "INT", "WIS"),
    "soldier":  ("STR", "DEX", "CON"),
}


def parse_background_asi(spec: str, background: str, allowed=None) -> dict:
    """Validate a background increase and return {STAT: n}.

    Accepts "STR=2,CON=1" or "+1/+1/+1". Anything else -- an ability the
    background does not list, +2/+2, a total other than 3 -- raises, because
    a sheet with an increase the rules do not allow is the failure to stop.
    """
    key = _race_key(background)
    if allowed is None and key not in BACKGROUND_ABILITIES:
        raise ValueError(
            f"Unknown background {background!r}. SRD 5.2 backgrounds: "
            f"{', '.join(sorted(BACKGROUND_ABILITIES))}")
    allowed = BACKGROUND_ABILITIES[key] if allowed is None else allowed
    spec = (spec or "").replace(" ", "")
    if spec in ("+1/+1/+1", "1/1/1"):
        return {a: 1 for a in allowed}
    out: dict = {}
    for part in spec.split(","):
        if "=" not in part:
            raise ValueError(f"Bad --background-asi {spec!r}: use STR=2,DEX=1 or +1/+1/+1")
        stat, val = part.split("=", 1)
        stat = stat.upper()
        if stat not in allowed:
            raise ValueError(
                f"{background.title()} raises {', '.join(allowed)} only, not {stat}")
        if stat in out:
            raise ValueError(f"{stat} given twice in --background-asi")
        out[stat] = int(val.lstrip("+"))
    if sorted(out.values()) not in ([1, 2], [1, 1, 1]):
        raise ValueError(
            f"A background gives +2 and +1 to two of {', '.join(allowed)}, or +1 "
            f"to all three; got {spec!r}")
    return out


# ─── Armor Class ─────────────────────────────────────────────────────────────

_AC_PAT = re.compile(r"^AC\s*(\+?)(\d+)(\s*\+\s*DEX)?(?:\s*\(max\s*(\d+)\))?", re.I)


def _armor_records() -> dict:
    """SRD armor records keyed by index, from the bundled dataset."""
    data = json.loads(srd_path("2014").read_text(encoding="utf-8"))
    return {r["index"]: r for r in data.get("equipment", []) if r.get("ac")}


def armor_class(scores: dict, cls: str, armor: str = "none", shield: bool = False,
                fighting_style: str = "", records: dict | None = None) -> tuple:
    """Return (ac, breakdown, notes) from an SRD armor index.

    Light armor adds DEX, medium caps it at +2, heavy adds none, a shield is
    +2 on top. With no armor a barbarian adds CON and a monk WIS (the monk
    only without a shield); the Defense fighting style is +1 while armor is
    worn. Raises on an armor index the dataset does not hold.
    """
    records = records if records is not None else _armor_records()
    dex = mod(scores.get("DEX", 10))
    notes: list = []
    parts: list = []
    worn = _race_key(armor or "none")
    if worn in ("", "none", "unarmored"):
        if cls == "barbarian":
            ac = 10 + dex + mod(scores.get("CON", 10))
            parts.append(f"Unarmored Defense 10 + DEX {fmt(dex)} + CON {fmt(mod(scores.get('CON', 10)))}")
        elif cls == "monk" and not shield:
            ac = 10 + dex + mod(scores.get("WIS", 10))
            parts.append(f"Unarmored Defense 10 + DEX {fmt(dex)} + WIS {fmt(mod(scores.get('WIS', 10)))}")
        else:
            ac = 10 + dex
            parts.append(f"unarmored 10 + DEX {fmt(dex)}")
        wearing = False
    else:
        rec = records.get(worn)
        if rec and (re.match(r"AC\s*\+", rec.get("ac", ""), re.I)
                    or "shield" in (rec.get("category", "") + rec.get("name", "")).lower()):
            raise ValueError(f"{armor!r} is a shield; use --shield")
        if not rec:
            known = ", ".join(sorted({r.get("index", _race_key(r["name"])) for r in records.values()}))
            raise ValueError(f"Unknown armor {armor!r}. Known armor: {known}")
        m = _AC_PAT.match(rec["ac"])
        base, adds_dex, cap = int(m.group(2)), bool(m.group(3)), m.group(4)
        bonus = 0
        if adds_dex:
            bonus = min(dex, int(cap)) if cap else dex
        ac = base + bonus
        parts.append(f"{rec['name']} {base}" + (f" + DEX {fmt(bonus)}" if adds_dex else ""))
        if rec.get("str_minimum") and scores.get("STR", 10) < rec["str_minimum"]:
            notes.append(f"STR {scores.get('STR', 10)} is below {rec['name']}'s "
                         f"{rec['str_minimum']}: speed -10 ft")
        if rec.get("stealth_disadv"):
            notes.append(f"{rec['name']}: Disadvantage on Stealth")
        wearing = True
    if shield:
        bonus = next((int(m.group(1)) for r in records.values()
                      if (m := re.fullmatch(r"AC\s*\+(\d+)", r.get("ac", ""), re.I))), 2)
        ac += bonus
        parts.append(f"Shield +{bonus}")
    if _race_key(fighting_style) == "defense":
        if wearing:
            ac += 1
            parts.append("Defense +1")
        else:
            notes.append("Defense applies only while wearing armor")
    return ac, " + ".join(parts), notes


# ─── Proficiency bonus by level ──────────────────────────────────────────────
PROF_BONUS = {1:2, 2:2, 3:2, 4:2, 5:3, 6:3, 7:3, 8:3,
              9:4, 10:4, 11:4, 12:4, 13:5, 14:5, 15:5, 16:5,
              17:6, 18:6, 19:6, 20:6}

# ─── XP thresholds (total XP needed to reach level) ─────────────────────────
XP_THRESHOLDS = {
    1: 0, 2: 300, 3: 900, 4: 2700, 5: 6500, 6: 14000,
    7: 23000, 8: 34000, 9: 48000, 10: 64000, 11: 85000,
    12: 100000, 13: 120000, 14: 140000, 15: 165000,
    16: 195000, 17: 225000, 18: 265000, 19: 305000, 20: 355000,
}

# ─── Hit dice by class ───────────────────────────────────────────────────────
HIT_DICE = {
    "barbarian": 12, "fighter": 10, "paladin": 10, "ranger": 10,
    "bard": 8, "cleric": 8, "druid": 8, "monk": 8, "rogue": 8, "warlock": 8,
    "sorcerer": 6, "wizard": 6,
}

# ─── Saving throw proficiencies by class ─────────────────────────────────────
SAVE_PROFS = {
    "fighter":   ["STR", "CON"],
    "barbarian": ["STR", "CON"],
    "ranger":    ["STR", "DEX"],
    "paladin":   ["WIS", "CHA"],
    "rogue":     ["DEX", "INT"],
    "bard":      ["DEX", "CHA"],
    "cleric":    ["WIS", "CHA"],
    "druid":     ["INT", "WIS"],
    "monk":      ["STR", "DEX"],
    "warlock":   ["WIS", "CHA"],
    "sorcerer":  ["CON", "CHA"],
    "wizard":    ["INT", "WIS"],
}

# ─── All skills with governing ability ───────────────────────────────────────
SKILLS = {
    "Acrobatics": "DEX", "Animal Handling": "WIS", "Arcana": "INT",
    "Athletics": "STR", "Deception": "CHA", "History": "INT",
    "Insight": "WIS", "Intimidation": "CHA", "Investigation": "INT",
    "Medicine": "WIS", "Nature": "INT", "Perception": "WIS",
    "Performance": "CHA", "Persuasion": "CHA", "Religion": "INT",
    "Sleight of Hand": "DEX", "Stealth": "DEX", "Survival": "WIS",
}

STATS = ["STR", "DEX", "CON", "INT", "WIS", "CHA"]


def mod(score: int) -> int:
    return (score - 10) // 2


def fmt(n: int) -> str:
    return f"+{n}" if n >= 0 else str(n)


def parse_scores(args: list[str]) -> dict[str, int]:
    scores = {}
    for i, a in enumerate(args):
        if i and args[i - 1] in ("--background-asi", "-c", "--campaign"):
            continue   # "STR=2,CON=1" is the increase, not a score
        if "=" in a:
            k, v = a.split("=", 1)
            if k.upper() in STATS:
                scores[k.upper()] = int(v)
    return scores


def parse_proficient(args: list[str], flag="--proficient") -> list[str]:
    """Everything after --proficient until next -- flag."""
    if flag not in args:
        return []
    idx = args.index(flag)
    profs = []
    for a in args[idx + 1:]:
        if a.startswith("--") or a == "-c" or "=" in a:
            break
        profs.append(a)
    return profs


def _campaign_from(args):
    for flag in ("-c", "--campaign"):
        if flag in args:
            return args[args.index(flag) + 1]
    return None


def _world_class(args):
    campaign = _campaign_from(args)
    kit = worldkit.load(campaign) if campaign else None
    name = args[args.index("--class") + 1] if "--class" in args else "fighter"
    record = worldkit.find(kit, "classes", name) if kit else None
    if kit is not None and "classes" in kit and record is None:
        raise ValueError(f"Unknown class {name!r}. This world's classes: "
                         + ", ".join(r["name"] for r in kit["classes"]))
    cls = norm_key(record["chassis"] if record else name)
    return kit, cls, record


def _subclass_from(args, world):
    if "--subclass" not in args:
        return ""
    subclass = args[args.index("--subclass") + 1]
    options = (world or {}).get("subclasses", [])
    if not options:
        return subclass
    match = worldkit.find({"subclasses": options}, "subclasses", subclass)
    if match is None:
        raise ValueError(f"Unknown subclass {subclass!r}. Choose from: "
                         + ", ".join(r["name"] for r in options))
    return match["name"]


#: SRD 5.1 races whose traits grant a skill proficiency (Keen Senses, Menacing).
SRD_RACE_SKILLS = {"elf": ["Perception"], "half-orc": ["Intimidation"]}


def _origin_skills(record: dict, kit: dict) -> list:
    """Skills a World Kit origin grants: its `skills` list, or a trait that says proficiency/ชำนาญ + a skill."""
    if record.get("skills"):
        return list(record["skills"])
    names = list(SKILLS) + list((kit or {}).get("skills", {}).values())
    found = []
    for trait in record.get("traits", []):
        text = str(trait)
        if re.search(r"proficien|ชำนาญ|เชี่ยวชาญ", text, re.I):
            found += [n for n in names if n.lower() in text.lower() and n not in found]
    return found


def do_calc(args: list[str]):
    if "--help" in args or "-h" in args:
        print(__doc__)
        return
    allowed = {"--class", "--level", "--proficient", "--expertise", "--race", "--subrace",
               "--background", "--background-asi", "--armor", "--shield", "--fighting-style",
               "--ruleset", "--campaign", "-c", "--subclass"}
    for arg in args:
        if arg.startswith("--") and arg not in allowed:
            print(f"character.py: unknown flag {arg}", file=sys.stderr)
            sys.exit(2)
    lvl = int(args[args.index("--level") + 1]) if "--level" in args else 1
    base_scores = parse_scores(args)
    proficient = parse_proficient(args)  # list of stat names + skill names
    race = args[args.index("--race") + 1] if "--race" in args else ""
    subrace = args[args.index("--subrace") + 1] if "--subrace" in args else ""
    background = args[args.index("--background") + 1] if "--background" in args else ""
    armor = args[args.index("--armor") + 1] if "--armor" in args else None

    # The scores passed in are the BASE array, before racial bonuses. Applying
    # them here is what makes the step verifiable: an unknown race raises
    # rather than applying nothing.
    try:
        kit, cls, world = _world_class(args)
        subclass = _subclass_from(args, world)
        ruleset = _ruleset_from(args, kit)
        background_2014 = ruleset == "2014" and (_campaign_from(args) is not None or "--ruleset" in args)
        origin_traits_only = kit is not None and ruleset == "2024"
        if background_2014 and "--background-asi" in args:
            raise ValueError("2014 backgrounds do not grant ability increases (--background-asi)")
        if background and (race or subrace) and not (background_2014 or origin_traits_only):
            raise ValueError(
                "--race (2014) and --background (2024) both grant ability "
                "increases; a character takes one or the other")
        style = ""
        if "--fighting-style" in args:
            style = args[args.index("--fighting-style") + 1]
            options = [r for r in (kit or {}).get("class_options", []) if r.get("kind") == "fighting_style"]
            options += _class_options("fighting_style")
            match = worldkit.find({"styles": options}, "styles", style)
            if match is None:
                raise ValueError(f"Unknown fighting style {style!r}")
            style = match["name"]
        origin_skills: list = []
        if kit is not None and "races" in kit and (race or subrace):
            record = worldkit.find(kit, "races", race)
            if not record:
                raise ValueError(f"Unknown world race {race!r}")
            if subrace:
                raise ValueError("--subrace is only valid for SRD races")
            race = record["name"]
            origin_skills = _origin_skills(record, kit)
            racial = dict(record["ability_bonuses"])
            scores = dict(base_scores)
            for stat, bonus in racial.items():
                scores[stat] = scores.get(stat, 10) + bonus
            race_notes = []
        else:
            scores, racial, race_notes = apply_racial_bonuses(base_scores, race, subrace)
            origin_skills = SRD_RACE_SKILLS.get(_race_key(race), [])
        if origin_skills:
            proficient.extend(s for s in origin_skills if s not in proficient)
            print(f"  Origin skill proficiency: {', '.join(origin_skills)}")
        if origin_traits_only and (race or subrace):
            scores, racial = dict(base_scores), {}
            print("2024: origin grants traits only")
        bg_bonus: dict = {}
        world_bg = None
        if background and kit is not None:
            world_bg = worldkit.find(kit, "backgrounds", background)
            if not world_bg:
                raise ValueError(f"Unknown world background {background!r}")
            proficient.extend(world_bg.get("skills", []))
        if background and not background_2014:
            if world_bg is None:
                key = _race_key(background)
                if key not in BACKGROUND_ABILITIES:
                    parse_background_asi("", background)   # raises: unknown background
                allowed = BACKGROUND_ABILITIES[key]
            else:
                allowed = world_bg["ability_options"]
            bg_spec = args[args.index("--background-asi") + 1] if "--background-asi" in args else ""
            if bg_spec:
                bg_bonus = parse_background_asi(bg_spec, background, allowed)
            else:
                race_notes.append(
                    f"{background.title()} background increase: +2/+1 or +1/+1/+1 "
                    f"among {', '.join(allowed)} "
                    f"(--background-asi)")
            for stat, n in bg_bonus.items():
                scores[stat] = scores.get(stat, 10) + n
                if scores[stat] > 20:
                    raise ValueError(f"{stat} would be {scores[stat]}; an increase "
                                     f"cannot raise a score above 20")
        ac_info = None
        if armor is not None or "--shield" in args:
            records = None
            if kit is not None and "equipment" in kit:
                records = {}
                for record in kit["equipment"]:
                    if record.get("ac"):
                        for name in (record["name"], record.get("index", record["name"])):
                            records[_race_key(name)] = record
                if kit.get("_meta", {}).get("srd_fallback", False):
                    for key, record in _armor_records().items():
                        records.setdefault(key, record)
            ac_info = armor_class(scores, cls, armor or "none", "--shield" in args, style, records)
        casting = spell_progression(cls, lvl) if cls in CASTING_ABILITIES else {}
    except (ValueError, IndexError) as exc:
        print(f"character.py: {exc}", file=sys.stderr)
        sys.exit(2)

    prof = PROF_BONUS.get(lvl, 2)
    origin_feat = (world_bg or {}).get("feat") if ruleset == "2024" else None
    initiative = mod(scores.get("DEX", 10))
    if norm_key(origin_feat) == "alert":
        initiative += prof
    hd = HIT_DICE.get(cls, 8)
    con_mod = mod(scores.get("CON", 10))
    hp = hd + con_mod  # level 1 max
    save_profs = SAVE_PROFS.get(cls, [])
    class_label = f"{world['name']} ({cls} chassis)" if world else cls.title()

    print(f"\n{'='*50}")
    print(f"  {class_label} Level {lvl}  |  Proficiency Bonus: +{prof}")
    print(f"{'='*50}")
    moves = [m["name"] for m in (world or {}).get("moves", []) if m.get("level", 1) <= lvl]
    if moves:
        print(f"  Playbook moves: {', '.join(moves)}")
    if origin_feat:
        print(f"  Origin feat: {origin_feat}")

    if bg_bonus or (background and not (racial or background_2014)):
        label = background.strip().title()
        print(f"\n  Ability Scores  (base + {label} background increase):")
        print(f"  {'Stat':<6} {'Base':>6} {'Bkgd':>6} {'Score':>6} {'Mod':>5}")
        print(f"  {'-'*33}")
        for s in STATS:
            base = base_scores.get(s, 10)
            bonus = bg_bonus.get(s, 0)
            score = scores.get(s, 10)
            print(f"  {s:<6} {base:>6} {fmt(bonus) if bonus else '—':>6} "
                  f"{score:>6} {fmt(mod(score)):>5}")
        for note in race_notes:
            print(f"\n  ! Still to assign: {note}")
    elif racial:
        label = (subrace or race).strip()
        print(f"\n  Ability Scores  (base + {label} racial bonus):")
        print(f"  {'Stat':<6} {'Base':>6} {'Race':>6} {'Score':>6} {'Mod':>5}")
        print(f"  {'-'*33}")
        for s in STATS:
            base = base_scores.get(s, 10)
            bonus = racial.get(s, 0)
            score = scores.get(s, 10)
            print(f"  {s:<6} {base:>6} {fmt(bonus) if bonus else '—':>6} "
                  f"{score:>6} {fmt(mod(score)):>5}")
        for note in race_notes:
            print(f"\n  ! Still to assign: {note}")
    else:
        print(f"\n  Ability Scores:")
        print(f"  {'Stat':<6} {'Score':>6} {'Mod':>5}")
        print(f"  {'-'*20}")
        for s in STATS:
            score = scores.get(s, 10)
            print(f"  {s:<6} {score:>6} {fmt(mod(score)):>5}")

    print(f"\n  Combat Stats:")
    print(f"  HP (level 1): {hp}  ({hd} + CON {fmt(con_mod)})")
    if lvl > 1:
        print(f"  HP (level {lvl}): {hp + (lvl - 1) * max(1, hd // 2 + 1 + con_mod)}")
    print(f"  Hit Dice: {lvl}d{hd}")
    print(f"  Initiative: {fmt(initiative)}")
    if ac_info:
        ac, breakdown, ac_notes = ac_info
        print(f"  Armor Class: {ac}  ({breakdown})")
        for note in ac_notes:
            print(f"    ! {note}")

    print(f"\n  Saving Throws (* = proficient):")
    for s in STATS:
        score = scores.get(s, 10)
        is_prof = s in save_profs or s in proficient
        bonus = mod(score) + (prof if is_prof else 0)
        marker = "*" if is_prof else " "
        print(f"  {marker} {s:<4} {fmt(bonus)}")

    print(f"\n  Skills (* = proficient):")
    renamed = worldkit.skill_names(kit)
    expertise = {_race_key(p) for p in parse_proficient(args, "--expertise")}
    passive = 10
    for skill, ability in sorted(SKILLS.items()):
        score = scores.get(ability, 10)
        display = f"{renamed[skill]} [{skill}]" if skill in renamed else skill
        prof_keys = {_race_key(p) for p in proficient}
        is_prof = _race_key(skill) in prof_keys or _race_key(renamed.get(skill, skill)) in prof_keys
        expert = bool({_race_key(skill), _race_key(renamed.get(skill, skill))} & expertise)
        bonus = mod(score) + (2 * prof if expert else prof if is_prof else 0)
        if skill == "Perception":
            passive += bonus
        marker = "*" if is_prof else " "
        print(f"  {marker} {display:<22} ({ability})  {fmt(bonus)}")

    print(f"  Passive Perception: {passive}")
    if subclass:
        print(f"  Subclass: {subclass}")
    elif lvl >= (3 if ruleset == "2024" else SUBCLASS_LEVEL_2014.get(cls, 3)):
        label = (world or {}).get("subclass_label", SUBCLASS_NAME.get(cls, "subclass"))
        options = ", ".join(r["name"] for r in (world or {}).get("subclasses", []))
        print(f"  Choose a subclass — {label}" + (f": {options}" if options else ""))

    if casting:
        ability = CASTING_ABILITIES[cls]
        bonus = prof + mod(scores.get(ability, 10))
        print(f"\n  Spellcasting ability: {ability}")
        print(f"  Spell save DC: {8 + bonus}")
        print(f"  Spell attack: {fmt(bonus)}")
        if "Pact slots" in casting:
            print(f"  Pact slots: {casting.pop('Pact slots')} × level-{casting.pop('Pact slot level')}")
        for name, value in casting.items():
            if value:
                print(f"  {name}: {value}")

    print(f"\n  XP to next level: {XP_THRESHOLDS.get(lvl+1, 'MAX')} total")
    print()


# ─── Choices a level-up owes ─────────────────────────────────────────────────
#
# A level-up was reported as HP and proficiency only, so the choices the new
# level grants were left to memory: a fighter reaching 6 with no ASI taken, a
# warlock at 2 with no invocations, a paladin at 2 with no fighting style.

ASI_LEVELS = {
    "fighter": (4, 6, 8, 12, 14, 16, 19),
    "rogue":   (4, 8, 10, 12, 16, 19),
}
ASI_LEVELS_DEFAULT = (4, 8, 12, 16, 19)

#: Level the subclass is chosen, 2014 (SRD 5.1). Every class chooses at 3 in 2024.
SUBCLASS_LEVEL_2014 = {
    "barbarian": 3, "bard": 3, "cleric": 1, "druid": 2, "fighter": 3, "monk": 3,
    "paladin": 3, "ranger": 3, "rogue": 3, "sorcerer": 1, "warlock": 1, "wizard": 2,
}
SUBCLASS_NAME = {
    "barbarian": "Primal Path", "bard": "Bard College", "cleric": "Divine Domain",
    "druid": "Druid Circle", "fighter": "Martial Archetype", "monk": "Monastic Tradition",
    "paladin": "Sacred Oath", "ranger": "Ranger Archetype", "rogue": "Roguish Archetype",
    "sorcerer": "Sorcerous Origin", "warlock": "Otherworldly Patron",
    "wizard": "Arcane Tradition",
}

#: Eldritch Invocations known, from the class tables. The 2014 column follows
#: the SRD 5.1 Warlock table; the 5e-database Levels file has it one higher at
#: levels 4 and 6, which would owe a warlock an invocation the rules do not
#: grant. tests/test_character_rules.py pins both columns.
INVOCATIONS_KNOWN = {
    "2014": {1: 0, 2: 2, 3: 2, 4: 2, 5: 3, 6: 3, 7: 4, 8: 4, 9: 5, 10: 5, 11: 5,
             12: 6, 13: 6, 14: 6, 15: 7, 16: 7, 17: 7, 18: 8, 19: 8, 20: 8},
    "2024": {1: 1, 2: 3, 3: 3, 4: 3, 5: 5, 6: 5, 7: 6, 8: 6, 9: 7, 10: 7, 11: 7,
             12: 8, 13: 8, 14: 8, 15: 9, 16: 9, 17: 9, 18: 10, 19: 10, 20: 10},
}

FIGHTING_STYLE_LEVEL = {"fighter": 1, "paladin": 2, "ranger": 2}
#: Champion's Additional Fighting Style: level 10 in 2014, 7 in 2024.
CHAMPION_STYLE_LEVEL = {"2014": 10, "2024": 7}
WEAPON_MASTERY_KNOWN = {
    "fighter": {1: 3, 4: 4, 10: 5, 16: 6},
    "barbarian": {1: 2, 4: 3, 10: 4},
    "paladin": {1: 2},
    "ranger": {1: 2},
    "rogue": {1: 2},
}


def _chassis_data() -> dict:
    """Load the bundled 2014 class chassis dataset when available."""
    try:
        return json.loads(srd_path("2014").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _ruleset_data(ruleset: str) -> dict:
    """The bundled dataset for a ruleset (2014 when the 2024 one is missing)."""
    try:
        return json.loads(srd_path(ruleset).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _chassis_data()


def _srd_subclass_index(subclass: str, world: dict | None, ruleset: str) -> str | None:
    """SRD subclass index a chosen subclass maps to, so only its features are listed.

    A World Kit subclass names its SRD chassis in its description ("Chassis: Champion");
    a re-skin of a non-SRD subclass maps to nothing and lists no SRD subclass features.
    """
    if not subclass:
        return None
    text = subclass
    for s in (world or {}).get("subclasses", []):
        if _race_key(s.get("name", "")) == _race_key(subclass):
            m = re.search(r"chassis:\s*([^.;(—–]+)", s.get("description", ""), re.I)
            text = m.group(1) if m else ""
            break
    key = _race_key(text)
    known = {r["subclass"] for r in _ruleset_data(ruleset).get("features", []) if r.get("subclass")}
    return next((i for i in sorted(known, key=len, reverse=True) if i in key), None)


def _class_options(kind: str) -> list:
    return [r for r in _chassis_data().get("class_options", []) if r.get("kind") == kind]


#: Levels that grant two more Expertise picks (the 2024 data lists only the first).
EXPERTISE_LEVELS = {"2014": {"rogue": (1, 6), "bard": (3, 10)},
                    "2024": {"rogue": (1, 6), "bard": (2, 9)}}


def owed_choices(cls: str, from_lvl: int, to_lvl: int, ruleset: str = "2014",
                 subclass: str = "") -> list:
    """The choices reaching `to_lvl` grants, as human-readable lines."""
    cls = cls.lower()
    out: list = []
    masteries = WEAPON_MASTERY_KNOWN.get(cls, {}) if ruleset == "2024" else {}
    if any(from_lvl < lvl <= to_lvl for lvl in masteries):
        import lookup
        names = ", ".join(r["name"] for r in lookup._get_records("weapon_mastery_properties", "2024"))
    for lvl in range(from_lvl + 1, to_lvl + 1):
        if lvl in masteries:
            count = masteries[lvl]
            choice = str(count) if lvl == 1 else f"1 more ({count} known)"
            options = f" — {names}" if names else ""
            out.append(f"Level {lvl}: Weapon Mastery: choose {choice}{options}")
        if lvl in EXPERTISE_LEVELS[ruleset if ruleset in EXPERTISE_LEVELS else "2014"].get(cls, ()):
            out.append(f"Level {lvl}: Expertise: choose 2 proficient skills (or thieves' tools) to double")
        if lvl in ASI_LEVELS.get(cls, ASI_LEVELS_DEFAULT):
            if ruleset == "2024" and lvl == 19:
                out.append(f"Level {lvl}: Epic Boon feat")
            elif ruleset == "2024":
                out.append(f"Level {lvl}: Ability Score Improvement feat (or another feat)")
            else:
                out.append(f"Level {lvl}: Ability Score Improvement — +2 to one score or "
                           f"+1 to two (or a feat, if the table uses feats)")
        sub_lvl = 3 if ruleset == "2024" else SUBCLASS_LEVEL_2014.get(cls)
        if lvl == sub_lvl and not subclass:
            out.append(f"Level {lvl}: choose a subclass ({SUBCLASS_NAME.get(cls, 'subclass')})")
        if lvl == FIGHTING_STYLE_LEVEL.get(cls):
            out.append(f"Level {lvl}: choose a Fighting Style")
        if cls == "fighter" and _race_key(subclass) == "champion" \
                and lvl == CHAMPION_STYLE_LEVEL.get(ruleset, 10):
            out.append(f"Level {lvl}: Champion — choose an Additional Fighting Style")
        if cls == "warlock":
            table = INVOCATIONS_KNOWN.get(ruleset, INVOCATIONS_KNOWN["2014"])
            gained = table.get(lvl, 0) - table.get(lvl - 1, 0)
            if gained > 0:
                out.append(f"Level {lvl}: learn {gained} Eldritch Invocation"
                           f"{'s' if gained > 1 else ''} (now {table[lvl]} known)")
            if ruleset != "2024" and lvl == 3:
                out.append("Level 3: choose a Pact Boon (Chain, Blade or Tome)")
    return out


# PHB spell progression, indexed by character level (0 is no spellcasting).
FULL_SLOTS = [tuple(map(int, row)) for row in (
    "000000000", "200000000", "300000000", "420000000", "430000000",
    "432000000", "433000000", "433100000", "433200000", "433310000",
    "433320000", "433321000", "433321000", "433321100", "433321100",
    "433321110", "433321110", "433321111", "433331111", "433332111", "433332211")]
CANTRIPS_START = {"bard": 2, "cleric": 3, "druid": 2, "sorcerer": 4, "warlock": 2, "wizard": 3}
CASTING_ABILITIES = {"wizard": "INT", "cleric": "WIS", "druid": "WIS", "ranger": "WIS",
                     "bard": "CHA", "sorcerer": "CHA", "warlock": "CHA", "paladin": "CHA"}
SPELLS_KNOWN = {name: [0] + list(map(int, values.split())) for name, values in {
    "bard": "4 5 6 7 8 9 10 11 12 14 15 15 16 18 19 19 20 22 22 22",
    "ranger": "0 2 3 3 4 4 5 5 6 6 7 7 8 8 9 9 10 10 11 11",
    "sorcerer": "2 3 4 5 6 7 8 9 10 11 12 12 13 13 14 14 15 15 15 15",
    "warlock": "2 3 4 5 6 7 8 9 10 10 11 11 12 12 13 13 14 14 15 15",
}.items()}


def spell_progression(cls: str, level: int) -> dict:
    if not 0 <= level <= 20:
        raise ValueError("Spell progression requires level 0–20")
    out = {}
    if cls in CANTRIPS_START:
        out["Cantrips known"] = CANTRIPS_START[cls] + (level >= 4) + (level >= 10) if level else 0
    if cls in SPELLS_KNOWN:
        out["Spells known"] = SPELLS_KNOWN[cls][level]
    if cls == "wizard":
        out["Spells in spellbook"] = 6 + 2 * (level - 1) if level else 0
    if cls == "warlock":
        out["Pact slots"] = (1 if level == 1 else 2 if level < 11 else 3 if level < 17 else 4) if level else 0
        out["Pact slot level"] = min(5, (level + 1) // 2)
    elif cls in CASTING_ABILITIES:
        caster_level = (level + 1) // 2 if cls in ("paladin", "ranger") and level >= 2 else level
        if cls in ("paladin", "ranger") and level < 2:
            caster_level = 0
        for index, slots in enumerate(FULL_SLOTS[caster_level], 1):
            ordinal = {1: "1st", 2: "2nd", 3: "3rd"}.get(index, f"{index}th")
            out[f"{ordinal}-level slots"] = slots
    return out


def retro_hp(con_before: int, con_after: int, levels: int) -> int:
    """HP owed for earlier levels when the CON modifier changes: one per level."""
    return (con_after - con_before) * levels


def _ruleset_from(args: list, kit=None) -> str:
    if "--ruleset" in args:
        rs = args[args.index("--ruleset") + 1]
        if rs not in ("2014", "2024"):
            print(f"character.py: --ruleset must be 2014 or 2024, not {rs!r}", file=sys.stderr)
            sys.exit(2)
        return rs
    # The campaign's state.md is authoritative (SKILL.md); the kit's base_ruleset only fills in
    # when no campaign is given.
    campaign = _campaign_from(args)
    if campaign:
        return campaign_ruleset(campaign)
    return (kit or {}).get("_meta", {}).get("base_ruleset") or "2014"


def do_levelup(args: list[str]):
    if "--help" in args or "-h" in args:
        print(__doc__)
        return
    try:
        kit, cls, world = _world_class(args)
        subclass = _subclass_from(args, world)
    except (ValueError, IndexError) as exc:
        print(f"character.py: {exc}", file=sys.stderr)
        sys.exit(2)
    from_lvl = int(args[args.index("--from") + 1]) if "--from" in args else 1
    to_lvl = from_lvl + 1
    hp_roll = int(args[args.index("--hp-roll") + 1]) if "--hp-roll" in args else None
    con_mod_val = int(args[args.index("--con-mod") + 1]) if "--con-mod" in args else 0
    con_before = (int(args[args.index("--con-mod-before") + 1])
                  if "--con-mod-before" in args else None)
    ruleset = _ruleset_from(args, kit)

    hd = HIT_DICE.get(cls, 8)
    prof_old = PROF_BONUS.get(from_lvl, 2)
    prof_new = PROF_BONUS.get(to_lvl, 2)

    class_label = f"{world['name']} ({cls} chassis)" if world else cls.title()
    print(f"\n  Level Up: {class_label} {from_lvl} → {to_lvl}")
    print(f"  Proficiency bonus: +{prof_old} → +{prof_new}")

    if hp_roll is not None:
        hp_gained = hp_roll + con_mod_val
        print(f"  HP gained: d{hd}({hp_roll}) + CON({fmt(con_mod_val)}) = {hp_gained}")
    else:
        avg = (hd // 2 + 1) + con_mod_val
        print(f"  HP gained (avg): {avg}  ({hd//2+1} + CON {fmt(con_mod_val)})")

    if con_before is not None and con_before != con_mod_val:
        owed = retro_hp(con_before, con_mod_val, from_lvl)
        print(f"  CON modifier {fmt(con_before)} → {fmt(con_mod_val)}: "
              f"{fmt(owed)} max HP for the {from_lvl} earlier level"
              f"{'s' if from_lvl != 1 else ''} as well")

    print(f"  XP threshold for level {to_lvl}: {XP_THRESHOLDS.get(to_lvl, 'MAX')}")

    chassis = _chassis_data()
    world_options = (kit or {}).get("class_options", [])
    replaced_kinds = {r["kind"] for r in world_options}
    replaced_options = {r["index"] for r in chassis.get("class_options", []) if r.get("kind") in replaced_kinds}
    sub_idx = _srd_subclass_index(subclass, world, ruleset)
    features = [r["name"] for r in _ruleset_data(ruleset).get("features", [])
                if r.get("class") == cls and r.get("level_req") == to_lvl and not r.get("parent")
                and r.get("subclass") in (None, sub_idx) and r.get("index") not in replaced_options]
    if world and world.get("subclasses"):
        shown = subclass or world.get("subclass_label", "specialisation")
        features = [shown if name == SUBCLASS_NAME.get(cls) else name for name in features]
    if features:
        print(f"  New features: {', '.join(dict.fromkeys(features))}")
    moves = [m["name"] for m in (world or {}).get("moves", []) if m.get("level") == to_lvl]
    if moves:
        print(f"  Playbook moves: {', '.join(moves)}")

    # Powers already on the character's sheet are not offered again.
    known_text = ""
    if "--char" in args and _campaign_from(args):
        try:
            from paths import find_character_file
            known_text = find_character_file(_campaign_from(args), args[args.index("--char") + 1]).read_text(encoding="utf-8")
        except (OSError, FileNotFoundError, IndexError) as exc:
            print(f"character.py: {exc}", file=sys.stderr)
            sys.exit(2)
    before, after = spell_progression(cls, from_lvl), spell_progression(cls, to_lvl)
    powers = worldkit.class_powers(kit, world)
    highest = max((int(name[0]) for name, n in after.items()
                   if n and name.endswith("-level slots")), default=after.get("Pact slot level", 0))
    for name, value in after.items():
        old = before.get(name, 0)
        if value != old:
            print(f"  {name}: {old} → {value}")
        if value > old and name in ("Cantrips known", "Spells known", "Spells in spellbook"):
            names = [p["name"] for p in powers if (p["level"] == 0 if name == "Cantrips known"
                                                   else 1 <= p["level"] <= highest)
                     and p["name"] not in known_text]
            if names:
                print(f"    Learn {value - old}: {', '.join(names)}"
                      + ("" if known_text else "  (add --char <name> to hide ones already known)"))
    if subclass:
        print(f"  Subclass: {subclass}")
    pact_boons = [r["name"] for r in world_options if r.get("kind") == "pact_boon"]
    owed_list = owed_choices(cls, from_lvl, to_lvl, ruleset, subclass)
    if owed_list:
        print(f"\n  Choices owed ({ruleset} rules):")
        world_subs = [s.get("name", "") for s in (world or {}).get("subclasses", [])]
        for line in owed_list:
            if "Pact Boon" in line and pact_boons:
                line = "Level 3: choose a Pact Boon (" + ", ".join(pact_boons) + ")"
            if world and "choose a subclass" in line:
                # A world class picks from its own subclasses, never the chassis's SRD ones.
                line = (f"{line.split(':')[0]}: choose a subclass — {world.get('subclass_label', 'specialisation')}"
                        + (f": {', '.join(world_subs)}" if world_subs else ""))
            print(f"    - {line}")
        for kind, needed, label in (
                ("invocation", cls == "warlock" and any("Invocation" in x for x in owed_list), "invocations"),
                ("fighting_style", any("Fighting Style" in x for x in owed_list), "fighting styles")):
            if not needed:
                continue
            options = [r for r in world_options if r.get("kind") == kind]
            uses_world_options = bool(options)
            if not options:
                options = _class_options(kind)
                if kind == "fighting_style":
                    options = [r for r in options if r.get("class", "").lower() == cls]
            names = sorted(r["name"] for r in options if (r.get("level") or 0) <= to_lvl)
            if names:
                heading = label if uses_world_options else (f"SRD {label} (re-skin names with the world lexicon)" if kit else f"SRD {label} available")
                print(f"      {heading}: {', '.join(names)}")
        if not pact_boons and any("Pact Boon" in x for x in owed_list):
            print("      (lookup.py pact-boon <name> for Chain, Blade and Tome)")
    print()


# ─── Hit Dice and long rests ─────────────────────────────────────────────────

def _int_arg(args: list, flag: str, default=None):
    if flag in args:
        return int(args[args.index(flag) + 1])
    if default is None:
        print(f"character.py: {flag} is required", file=sys.stderr)
        sys.exit(2)
    return default


def spend_hit_dice(die: int, con_mod: int, hp: int, max_hp: int, remaining: int,
                   count: int = 1, ruleset: str = "2014", rolls: list | None = None) -> dict:
    """Spend `count` Hit Dice. Raises ValueError when the rules refuse it.

    Each die heals its roll + CON modifier, never below 0 (2014) or 1 (2024),
    and the total stops at max HP. A character at 0 HP cannot spend them,
    and nobody can spend dice they do not have.
    """
    if hp <= 0:
        raise ValueError("at 0 HP a character cannot spend Hit Dice — they need "
                         "at least 1 HP (stabilize and heal first)")
    if remaining <= 0:
        raise ValueError("no Hit Dice left to spend")
    if count > remaining:
        raise ValueError(f"only {remaining} Hit Dice left, cannot spend {count}")
    if count < 1 or die < 1:
        raise ValueError("Hit Die size and count must be positive")
    floor = 1 if ruleset == "2024" else 0
    if rolls is None:
        rolls = [secrets.randbelow(die) + 1 for _ in range(count)]
    else:
        rolls = list(rolls)
        if len(rolls) != count or any(not 1 <= n <= die for n in rolls):
            raise ValueError(f"--roll requires {count} result(s) between 1 and {die}")
    per_die = [max(floor, r + con_mod) for r in rolls]
    new_hp = min(max_hp, hp + sum(per_die))
    return {"rolls": rolls, "healed": per_die, "hp": new_hp,
            "remaining": remaining - count, "wasted": hp + sum(per_die) - new_hp}


def long_rest(level: int, hd_remaining: int, hp: int, max_hp: int,
              ruleset: str = "2014", exhaustion: int = 0) -> dict:
    """What a long rest restores. A character at 0 HP gains nothing from it.

    Hit Dice: half the character's total, rounded down, minimum 1 (2014), or
    all of them (2024). Exhaustion drops one level.
    """
    if hp <= 0:
        return {"benefit": False,
                "reason": "at 0 HP — a long rest gives no benefit until the "
                          "character has at least 1 HP"}
    regained = level if ruleset == "2024" else max(1, level // 2)
    new_hd = min(level, hd_remaining + regained)
    return {"benefit": True, "hp": max_hp, "hd_remaining": new_hd,
            "hd_regained": new_hd - hd_remaining, "exhaustion": max(0, exhaustion - 1)}


def do_hitdie(args: list[str]):
    die_s = args[args.index("--die") + 1] if "--die" in args else ""
    m = re.match(r"^d?(\d+)$", die_s.strip().lower())
    if not m:
        print("character.py: --die d6|d8|d10|d12 is required", file=sys.stderr)
        sys.exit(2)
    ruleset = _ruleset_from(args)
    try:
        rolls = [int(n) for n in args[args.index("--roll") + 1].split(",")] if "--roll" in args else None
        r = spend_hit_dice(int(m.group(1)), _int_arg(args, "--con-mod", 0),
                           _int_arg(args, "--hp"), _int_arg(args, "--max-hp"),
                           _int_arg(args, "--remaining"), _int_arg(args, "--count", 1),
                           ruleset, rolls=rolls)
    except (ValueError, IndexError) as exc:
        print(f"character.py: {exc}", file=sys.stderr)
        sys.exit(2)
    con = _int_arg(args, "--con-mod", 0)
    for roll, healed in zip(r["rolls"], r["healed"]):
        print(f"  Hit Die: d{m.group(1)}({roll}) + CON {fmt(con)} = {healed}")
    print(f"  HP: {_int_arg(args, '--hp')} → {r['hp']} / {_int_arg(args, '--max-hp')}"
          + (f"  ({r['wasted']} over max, lost)" if r["wasted"] else ""))
    print(f"  Hit Dice left: {r['remaining']}")


def do_rest(args: list[str]):
    if not args or args[0] != "long":
        print("character.py: usage: rest long --level N --hd-remaining N --hp N --max-hp N",
              file=sys.stderr)
        sys.exit(2)
    ruleset = _ruleset_from(args)
    r = long_rest(_int_arg(args, "--level"), _int_arg(args, "--hd-remaining"),
                  _int_arg(args, "--hp"), _int_arg(args, "--max-hp"), ruleset,
                  _int_arg(args, "--exhaustion", 0))
    if not r["benefit"]:
        print(f"  No long-rest benefit: {r['reason']}")
        return
    print(f"  Long rest ({ruleset} rules):")
    print(f"    HP: → {r['hp']} (full)")
    print(f"    Hit Dice: +{r['hd_regained']} → {r['hd_remaining']} / {_int_arg(args, '--level')}")
    if _int_arg(args, "--exhaustion", 0):
        print(f"    Exhaustion: {_int_arg(args, '--exhaustion', 0)} → {r['exhaustion']}")
    casting = True
    if "--class" in args:
        _, cls, _ = _world_class(args)
        casting = cls in ("bard", "cleric", "druid", "sorcerer", "warlock", "wizard") or (
            cls in ("paladin", "ranger") and _int_arg(args, "--level") >= 2)
    print("    " + ("Spell slots and long-rest features" if casting else "Long-rest features")
          + ": restored. Concentration: ends.")


def do_xp(args: list[str]):
    lvl = int(args[args.index("--level") + 1]) if "--level" in args else 1
    gained = int(args[args.index("--gained") + 1]) if "--gained" in args else 0
    current = XP_THRESHOLDS.get(lvl, 0)
    next_lvl = XP_THRESHOLDS.get(lvl + 1)
    new_total = current + gained

    print(f"\n  XP: {current} + {gained} gained = {new_total}")
    if next_lvl:
        if new_total >= next_lvl:
            print(f"  *** Level up available! Reached {next_lvl} (Level {lvl+1} threshold) ***")
        else:
            print(f"  Next level ({lvl+1}) at: {next_lvl}  ({next_lvl - new_total} XP remaining)")
    else:
        print("  Maximum level reached.")
    print()


HP_RE = re.compile(r"(\*\*HP:\*\*\s*)(\d+)\s*/\s*(\d+)")
HERO_POINTS_RE = re.compile(r"(\*\*Hero Points:\*\*[ \t]*)(\d+)[ \t]*/[ \t]*(\d+)")
FOCUS_POINTS_RE = re.compile(r"(\*\*Focus Points:\*\*[ \t]*)(\d+)[ \t]*/[ \t]*(\d+)")


def insert_after_hp(text: str, line: str) -> str:
    hp = HP_RE.search(text)
    if hp is None:
        raise ValueError("Character sheet has no HP line")
    end = text.find("\n", hp.end())
    if end < 0:
        return f"{text}\n{line}\n"
    return f"{text[:end + 1]}{line}\n{text[end + 1:]}"


def do_points(pool: str, args: list[str]) -> None:
    hero = pool == "hero"
    label = "Hero Points" if hero else "Focus Points"
    actions = ("use", "award", "reset", "recover") if hero else ("use", "refocus", "reset")
    parser = argparse.ArgumentParser(prog=f"character.py {pool}", description=f"Manage {label}.")
    parser.add_argument("action", choices=actions)
    parser.add_argument("--char", required=True)
    parser.add_argument("-c", "--campaign", required=True)
    parser.add_argument("--reason", default="", help="why: shown in the output")
    if not hero:
        parser.add_argument("--max", type=int, help="Set the maximum when resetting Focus Points")
    opts = parser.parse_args(args)
    if not hero and opts.max is not None and (opts.max < 1 or opts.action != "reset"):
        parser.error("--max must be positive and used with reset")

    try:
        path = find_character_file(opts.campaign, opts.char)
        text = path.read_text(encoding="utf-8")
        pattern = HERO_POINTS_RE if hero else FOCUS_POINTS_RE
        match = pattern.search(text)
        current = int(match[2]) if match else 0
        if hero:
            maximum = 3
        elif match:
            maximum = int(match[3])
        else:
            maximum = None
        if not hero and maximum is None and opts.action == "reset" and opts.max is None:
            parser.error("--max is required to initialize Focus Points")
        if not hero and maximum is None and opts.action == "refocus":
            raise ValueError("Focus Points must be initialized with reset --max N")

        if opts.action == "reset":
            if not hero and opts.max is not None:
                maximum = opts.max
            current = 1 if hero else maximum
        elif opts.action in ("award", "refocus"):
            current = min(maximum, current + 1)
        else:
            if current < 1:
                raise ValueError(f"{opts.char} has no {label} to spend")
            if opts.action == "recover":
                hp = HP_RE.search(text)
                if hp is None or int(hp[2]) != 0:
                    raise ValueError("Hero Point recovery requires a character at 0 HP")
                current = 0
                death_saves = "**Death Saves:** Successes: 0 | Failures: 0"
                text, count = re.subn(r"\*\*Death Saves:\*\*[^\n]*", death_saves, text, count=1)
                if not count:
                    text = insert_after_hp(text, f"- {death_saves}")
            else:
                current -= 1

        if match:
            text = pattern.sub(rf"\g<1>{current} / {maximum}", text, count=1)
        else:
            text = insert_after_hp(text, f"- **{label}:** {current} / {maximum}")
        path.write_text(text, encoding="utf-8")
    except (OSError, ValueError) as exc:
        print(f"character.py: {exc}", file=sys.stderr)
        sys.exit(1)
    result = f"{opts.char}: {label} {current} / {maximum}"
    if opts.action == "recover":
        result += " — stable at 0 HP"
    print(result + (f" ({opts.reason})" if opts.reason else ""))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]
    args = sys.argv[2:]

    if cmd in ("--help", "-h"):
        print(__doc__)
    elif cmd == "calc":
        do_calc(args)
    elif cmd == "levelup":
        do_levelup(args)
    elif cmd == "xp":
        do_xp(args)
    elif cmd == "hitdie":
        do_hitdie(args)
    elif cmd == "rest":
        do_rest(args)
    elif cmd in ("hero", "focus"):
        do_points(cmd, args)
    else:
        print(f"Unknown command: {cmd}. Use: calc | levelup | hitdie | rest | xp | hero | focus")
        sys.exit(1)
