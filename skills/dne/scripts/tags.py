#!/usr/bin/env python3
"""
tags.py — place tags: roll a ready-to-play seed for a town, ruin, district or court.

The idea (two tags per place, each with enemies, friends, complications,
things and places) comes from Worlds Without Number; the tags are our own.
Generic tags live in data/place_tags.json; a World Kit can add its own under
`place_tags` (same fields), and those are preferred when rolling.

Usage:
    tags.py [-c <campaign>] roll [--n 2] [--seed N] [--all]   # --all prints every entry, not one pick
    tags.py [-c <campaign>] list
    tags.py [-c <campaign>] show "<tag>"
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

DATA = Path(__file__).resolve().parent.parent / "data" / "place_tags.json"
PARTS = ("enemies", "friends", "complications", "things", "places")


def generic() -> list[dict]:
    return json.loads(DATA.read_text(encoding="utf-8"))["tags"]


def world(campaign: str | None) -> list[dict]:
    """The campaign's World Kit place_tags ([] without a campaign or kit)."""
    if not campaign:
        return []
    import worldkit
    kit = worldkit.load(campaign)   # ValueError on a broken kit: say so rather than roll generic tags
    return list(kit.get("place_tags", [])) if kit else []


def pool(campaign: str | None) -> tuple[list[dict], list[dict]]:
    return world(campaign), generic()


def roll(campaign: str | None, n: int, rng: random.Random) -> list[dict]:
    """n distinct tags: the world's own first (shuffled), topped up from the generic list."""
    own, gen = pool(campaign)
    own, gen = own[:], gen[:]
    rng.shuffle(own)
    rng.shuffle(gen)
    names, picked = set(), []
    for tag in own + gen:
        if tag["name"].casefold() not in names:
            names.add(tag["name"].casefold())
            picked.append(tag)
        if len(picked) == n:
            break
    return picked


def fmt(tag: dict, rng: random.Random | None = None) -> str:
    lines = [f"## {tag['name']}", tag.get("description", "")]
    for part in PARTS:
        items = tag.get(part) or []
        if not items:
            continue
        shown = [rng.choice(items)] if rng else items
        lines.append(f"- {part.capitalize()}: " + "; ".join(shown))
    return "\n".join(lines)


def main() -> None:
    p = argparse.ArgumentParser(description="Place tags for building towns, ruins and courts.")
    p.add_argument("-c", "--campaign")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("roll", help="Roll tags for a place")
    r.add_argument("--n", type=int, default=2)
    r.add_argument("--seed", type=int)
    r.add_argument("--all", action="store_true", help="print every entry instead of one pick per list")
    sub.add_parser("list", help="List the tags")
    sub.add_parser("show", help="Show one tag in full").add_argument("name")
    args = p.parse_args()
    try:
        if args.cmd == "list":
            own, gen = pool(args.campaign)
            if own:
                print("World tags: " + ", ".join(t["name"] for t in own))
            print("Generic tags: " + ", ".join(t["name"] for t in gen))
            return
        if args.cmd == "show":
            own, gen = pool(args.campaign)
            tag = next((t for t in own + gen if t["name"].casefold() == args.name.casefold().strip()), None)
            if tag is None:
                raise ValueError(f"unknown tag {args.name!r} (see: tags.py list)")
            print(fmt(tag))
            return
        if not 1 <= args.n <= 4:
            raise ValueError("--n must be 1–4")
        rng = random.Random(args.seed)
        tags = roll(args.campaign, args.n, rng)
        print("\n\n".join(fmt(t, None if args.all else rng) for t in tags))
        print("\nTie the tags together: who links an enemy of one to a friend of the other?")
    except (OSError, ValueError) as exc:
        print(f"tags.py: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    main()
