#!/usr/bin/env python3
"""
encounter_gen.py — Biome-Aware 5e CR Encounter Generator.

reads the bundled SRD monster dataset (`data/dnd5e_srd.json`), auto-classifies
monsters into biomes, and deterministically builds a balanced 5e XP-budget
encounter with suggested tactical roles (`brute`, `skirmisher`, `ranged`, `caster`, `support`).

Usage:
    python3 encounter_gen.py --biome forest --party-level 3 --party-size 4 --difficulty medium [--seed 42]
    python3 encounter_gen.py --biome crypt --party-level 5 --party-size 3 --difficulty hard --json
"""

import argparse
from itertools import combinations, product
from fractions import Fraction
import json
import os
import random
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from paths import srd_path
import worldkit

# 5e DMG XP thresholds per character by level (1..20)
XP_THRESHOLDS = {
    1:  (25, 50, 75, 100),      2:  (50, 100, 150, 200),
    3:  (75, 150, 225, 400),    4:  (125, 250, 375, 500),
    5:  (250, 500, 750, 1100),  6:  (300, 600, 900, 1400),
    7:  (350, 750, 1100, 1700), 8:  (450, 900, 1400, 2100),
    9:  (550, 1100, 1600, 2400),10: (600, 1200, 1900, 2800),
    11: (800, 1600, 2400, 3600),12: (1000, 2000, 3000, 4500),
    13: (1100, 2200, 3400, 5100),14:(1250, 2500, 3800, 5700),
    15: (1400, 2800, 4300, 6400),16:(1600, 3200, 4800, 7200),
    17: (2000, 3900, 5900, 8800),18:(2100, 4200, 6300, 9500),
    19: (2400, 4900, 7300, 10900),20:(2800, 5700, 8500, 12700),
}
DIFF_IDX = {"easy": 0, "medium": 1, "hard": 2, "deadly": 3}

BIOME_KEYWORDS = {
    "forest":    ["wolf", "bear", "spider", "goblin", "orc", "boar", "dryad", "treant", "owlbear", "elf", "stag", "bandit", "bugbear", "ettin", "fey", "plant", "beast", "green dragon"],
    "crypt":     ["skeleton", "zombie", "ghoul", "ghast", "wight", "wraith", "ghost", "vampire", "lich", "mummy", "specter", "shadow", "undead", "gargoyle", "mimic"],
    "cave":      ["bat", "spider", "goblin", "kobold", "ooze", "slime", "jelly", "rust", "roper", "troll", "ogre", "basilisk", "stirge", "beetle", "rat", "carrion", "darkmantle"],
    "desert":    ["scorpion", "camel", "vulture", "hyena", "gnoll", "jackal", "mummy", "sphinx", "lamia", "blue dragon", "brass dragon", "dust", "air elemental", "efreeti"],
    "swamp":     ["lizardfolk", "crocodile", "frog", "toad", "hag", "troll", "hydra", "will-o", "shambling", "black dragon", "snake", "stirge", "ooze", "bullywug"],
    "mountain":  ["eagle", "griffon", "wyvern", "giant", "roc", "manticore", "harpy", "orc", "ogre", "red dragon", "silver dragon", "gorgon", "chimera", "earth elemental"],
    "city":      ["bandit", "guard", "assassin", "spy", "thug", "cult", "mage", "noble", "knight", "veteran", "rat", "mimic", "doppelganger", "gargoyle", "wererat", "humanoid"],
    "coastal":   ["crab", "shark", "octopus", "sahuagin", "merfolk", "sea hag", "harpy", "kraken", "water elemental", "pirate", "bandit", "bronze dragon", "plesiosaurus"],
    "plains":    ["lion", "horse", "gnoll", "orc", "goblin", "centaur", "griffon", "ankheg", "bulette", "bandit", "hobgoblin", "worg", "wolf", "cyclops"],
    "arctic":    ["polar", "winter wolf", "yeti", "remorhaz", "mammoth", "white dragon", "frost giant", "ice mephit", "owl", "elk"],
    "underdark": ["drow", "drider", "duergar", "mind", "aboleth", "cloaker", "roper", "ooze", "spider", "purple worm", "beholder", "deep", "aberration", "fiend"],
}


def _infer_role(m: dict) -> str:
    if m.get("role"):
        return m["role"]
    desc = str(m.get("description", "")).lower()
    name = str(m.get("name", "")).lower()
    if any(k in desc or k in name for k in ("spellcasting", "mage", "lich", "shaman", "priest", "acolyte", "druid", "cult fanatic")):
        return "support" if any(k in desc for k in ("cure wounds", "heal", "bless")) else "caster"
    if any(k in desc for k in ("longbow", "shortbow", "crossbow", "sling", "ranged weapon attack")):
        return "ranged"
    if int(m.get("dex", 10) or 10) >= 14 and int(m.get("hp", 20) or 20) <= 45:
        return "skirmisher"
    return "brute"


def _encounter_multiplier(count: int) -> float:
    if count <= 1: return 1.0
    if count == 2: return 1.5
    if count <= 6: return 2.0
    if count <= 10: return 2.5
    if count <= 14: return 3.0
    return 4.0


def generate_encounter(
    biome: str,
    party_level: int = 3,
    party_size: int = 4,
    difficulty: str = "medium",
    seed: "int | None" = None,
    ruleset: str = "2014",
    campaign=None,
) -> dict:
    rng = random.Random(seed)
    lvl = max(1, min(20, int(party_level)))
    size = max(1, min(10, int(party_size)))
    diff_i = DIFF_IDX.get(difficulty.lower(), 1)
    budget = XP_THRESHOLDS[lvl][diff_i] * size

    kit = worldkit.load(campaign) if campaign else None
    world_monsters = kit is not None
    if world_monsters:
        monsters = kit.get("monsters", [])
    else:
        spath = srd_path(ruleset)
        if not spath.exists():
            spath = srd_path("2014")
        data = json.loads(spath.read_text(encoding="utf-8"))
        monsters = data.get("monsters", [])

    b_key = biome.strip().lower()
    kws = BIOME_KEYWORDS.get(b_key, BIOME_KEYWORDS["forest"])

    def _matches_biome(m: dict) -> bool:
        hay = f"{m.get('name', '')} {m.get('type', '')}".lower()
        if world_monsters:
            return b_key in [b.lower() for b in m.get("biomes", [])] or b_key in hay
        return any(kw in hay for kw in kws)

    if world_monsters and not any(_matches_biome(m) for m in monsters):
        biomes = sorted({b for m in monsters for b in m.get("biomes", [])})
        raise ValueError(f"Unknown biome {biome!r}. Known biomes: {', '.join(biomes)}")

    # Filter monsters whose base XP fits within budget (and not trivial 0 XP critters)
    eligible = [
        m for m in monsters
        if _matches_biome(m) and 10 <= int(m.get("xp", 0) or 0) <= budget * (1.15 if world_monsters else 1)
    ]
    if not eligible and not world_monsters:
        eligible = [m for m in monsters if 10 <= int(m.get("xp", 0) or 0) <= budget]
    if not eligible:
        raise RuntimeError(f"No monsters fit XP budget {budget} for biome '{biome}'.")

    if world_monsters:
        def adjusted(roster):
            count = sum(c["count"] for c in roster)
            return sum(int(c["monster"]["xp"]) * c["count"] for c in roster) * _encounter_multiplier(count)

        candidates = []
        for _ in range(25):
            roster = []
            for count in range(8):
                available = [m for m in eligible
                             if (len(roster) < 3 or any(c["monster"] is m for c in roster))
                             and (sum(int(c["monster"]["xp"]) * c["count"] for c in roster)
                                  + int(m["xp"])) * _encounter_multiplier(count + 1) <= budget * 1.15]
                if not available:
                    break
                pick = rng.choice(available)
                existing = next((c for c in roster if c["monster"] is pick), None)
                if existing:
                    existing["count"] += 1
                else:
                    roster.append({"monster": pick, "count": 1})
                candidates.append([dict(c) for c in roster])
        chosen = min(candidates, key=lambda r: abs(adjusted(r) - budget))
        # If random draws underfill, check all allowed mixes before accepting it.
        if adjusted(chosen) < budget * 0.82:
            for types in range(1, min(3, len(eligible)) + 1):
                for group in combinations(eligible, types):
                    for counts in product(range(1, 9), repeat=types):
                        if sum(counts) > 8:
                            continue
                        roster = [{"monster": m, "count": n} for m, n in zip(group, counts)]
                        xp = adjusted(roster)
                        if xp <= budget * 1.15 and abs(xp - budget) < abs(adjusted(chosen) - budget):
                            chosen = roster
        total_count = sum(c["count"] for c in chosen)
        raw_xp = sum(int(c["monster"]["xp"]) * c["count"] for c in chosen)
    else:
        # Prefer monsters with XP between 12% and 85% of budget for engaging multi-enemy fights
        sweet = [m for m in eligible if budget * 0.10 <= int(m.get("xp", 0)) <= budget * 0.85]
        pool = sweet if sweet else eligible

        # Pick 1 leader/primary type + optional support/minion type
        primary = rng.choice(pool)
        pxp = int(primary["xp"])
        chosen = [{"monster": primary, "count": 1}]

        # Fill remaining budget up to 6 total monsters
        total_count = 1
        raw_xp = pxp
        while total_count < 6:
            next_mult = _encounter_multiplier(total_count + 1)
            # Try adding another of the same or a companion monster
            candidates = [
                m for m in pool
                if (raw_xp + int(m["xp"])) * next_mult <= budget * 1.15
            ]
            if not candidates:
                break
            pick = primary if (primary in candidates and rng.random() < 0.6) else rng.choice(candidates)
            raw_xp += int(pick["xp"])
            total_count += 1
            existing = next((c for c in chosen if c["monster"]["name"] == pick["name"]), None)
            if existing:
                existing["count"] += 1
            else:
                chosen.append({"monster": pick, "count": 1})
            if raw_xp * _encounter_multiplier(total_count) >= budget * 0.82:
                break

    adj_xp = int(raw_xp * _encounter_multiplier(total_count))
    roster = []
    for c in chosen:
        m = c["monster"]
        roster.append({
            "name": m["name"],
            "count": c["count"],
            "cr": float(Fraction(str(m.get("cr", 0)))),
            "xp_each": int(m.get("xp", 0)),
            "hp": m.get("hp", "?"),
            "ac": m.get("ac", "?"),
            "type": m.get("type", ""),
            "tactical_role": _infer_role(m),
        })

    return {
        "biome": b_key,
        "party_level": lvl,
        "party_size": size,
        "difficulty": difficulty.lower(),
        "xp_budget": budget,
        "raw_xp": raw_xp,
        "adjusted_xp": adj_xp,
        "seed": seed,
        "monsters": roster,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Biome-aware 5e CR encounter generator.")
    parser.add_argument("--biome", default="forest")
    parser.add_argument("-c", "--campaign")
    parser.add_argument("--party-level", type=int, default=3)
    parser.add_argument("--party-size", type=int, default=4)
    parser.add_argument("--difficulty", choices=["easy", "medium", "hard", "deadly"], default="medium")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--ruleset", choices=["2014", "2024"], default="2014")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        kit = worldkit.load(args.campaign) if args.campaign else None
        if kit is None and args.biome not in BIOME_KEYWORDS:
            parser.error(f"argument --biome: invalid choice: {args.biome!r} (choose from {', '.join(sorted(BIOME_KEYWORDS))})")
        enc = generate_encounter(
            args.biome, args.party_level, args.party_size,
            difficulty=args.difficulty, seed=args.seed, ruleset=args.ruleset, campaign=args.campaign,
        )
        if args.json:
            print(json.dumps(enc, indent=2, ensure_ascii=False))
            return
        print(f"Encounter [{enc['biome'].title()} · {enc['difficulty'].upper()}] "
              f"Party: {enc['party_size']}×L{enc['party_level']} (budget {enc['xp_budget']} XP → adj {enc['adjusted_xp']} XP)")
        for m in enc["monsters"]:
            print(f"  {m['count']}× {m['name']} (CR {worldkit.format_cr(m['cr'])}, AC {m['ac']}, HP {m['hp']}, role={m['tactical_role']})")
    except ValueError as e:
        parser.error(str(e))
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
