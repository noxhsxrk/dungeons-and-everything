#!/usr/bin/env python3
"""
build_monster_table.py — typical monster numbers per Challenge Rating, from the bundled SRD.

The idea (monster stats looked up by level) comes from Pathfinder 2e; the numbers are measured
from the 5e SRD 5.1 monsters in data/dnd5e_srd.json, so they fit 5e maths.

For every CR it records the 10th / 50th / 90th percentile of AC, HP, attack bonus (the highest
"+N to hit"), save DC (the highest "DC N") and damage per hit (the first "Hit: N (…)" average).
A CR with fewer than 5 monsters borrows its neighbours until it has 5.

Usage:
    python3 build_monster_table.py            # writes data/monster_stats_by_cr.json
    python3 build_monster_table.py --print    # prints instead of writing
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

DATA = pathlib.Path(__file__).resolve().parent.parent / "data"
SRC = DATA / "dnd5e_srd.json"
OUT = DATA / "monster_stats_by_cr.json"
MIN_SAMPLE = 5


def cr_key(cr) -> str:
    """0.25 → "0.25", 1.0 → "1"; the key kit monsters' `cr` maps to."""
    f = float(cr)
    return str(int(f)) if f == int(f) else str(f)


def _stats(m: dict) -> dict:
    desc = m.get("description") or ""
    hits = [int(x) for x in re.findall(r"\+(\d+) to hit", desc)]
    dcs = [int(x) for x in re.findall(r"\bDC (\d+)", desc)]
    dmg = re.search(r"Hit: (\d+) \(", desc)
    return {"ac": m.get("ac"), "hp": m.get("hp"), "attack": max(hits) if hits else None,
            "dc": max(dcs) if dcs else None, "damage": int(dmg.group(1)) if dmg else None}


def _pct(values: list, p: float):
    values = sorted(values)
    i = (len(values) - 1) * p
    lo, hi = int(i), min(int(i) + 1, len(values) - 1)
    return round(values[lo] + (values[hi] - values[lo]) * (i - lo))


def build(monsters: list) -> dict:
    by_cr: dict = {}
    for m in monsters:
        if m.get("cr") is None:
            continue
        by_cr.setdefault(float(m["cr"]), []).append(_stats(m))
    crs = sorted(by_cr)
    table = {}
    for i, cr in enumerate(crs):
        sample, lo, hi = list(by_cr[cr]), i, i
        while len(sample) < MIN_SAMPLE and (lo > 0 or hi < len(crs) - 1):
            if hi < len(crs) - 1:
                hi += 1
                sample += by_cr[crs[hi]]
            if len(sample) < MIN_SAMPLE and lo > 0:
                lo -= 1
                sample += by_cr[crs[lo]]
        row = {"n": len(by_cr[cr]), "sample": len(sample)}
        for stat in ("ac", "hp", "attack", "dc", "damage"):
            vals = [s[stat] for s in sample if s[stat] is not None]
            row[stat] = [_pct(vals, .1), _pct(vals, .5), _pct(vals, .9)] if vals else None
        table[cr_key(cr)] = row
    return table


def main() -> int:
    monsters = json.loads(SRC.read_text(encoding="utf-8"))["monsters"]
    table = build(monsters)
    text = json.dumps(table, indent=1)
    if "--print" in sys.argv:
        print(text)
    else:
        OUT.write_text(text + "\n", encoding="utf-8")
        print(f"Wrote {OUT} ({len(table)} CRs from {len(monsters)} monsters)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
