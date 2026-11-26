#!/usr/bin/env python3
"""
content.py — genre-tagged World Kit content for a Braid world (labels, equipment, threats).

data/content.json holds entries tagged with the genre ids they fit; one entry may carry several tags. A mix draws
from the union of its genres' tags, the first genre's entries first, and the era bans of story_gen.py apply (a
western mix leaves out the radio operator) unless the players mix eras on purpose. The output is kit-shaped: copy
what fits into the seed's `worldkit`, then rewrite names and descriptions for this world.

Usage:
    python3 content.py western,horror                 kit-shaped JSON: {"labels": [...], "equipment": [...], "threats": [...]}
    python3 content.py western horror --mix-eras      keep values from other eras
    python3 content.py mystery --kind threats         one part only
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths  # noqa: E402
import story_gen  # noqa: E402

KINDS = ("labels", "equipment", "threats")


def library() -> dict:
    return json.loads((paths.data_dir() / "content.json").read_text(encoding="utf-8"))


def for_mix(genres: list, mix_eras: bool = False) -> dict:
    """The kit parts a mix draws from: entries whose tags meet the mix, in the order of the first matching genre."""
    known = story_gen.genre_ids()
    bad = [g for g in genres if g not in known]
    if bad or not genres:
        raise ValueError(f"unknown genre {', '.join(bad) or '(none)'} (genres.py list)")
    words = [] if mix_eras else [w for g in genres for w in story_gen.ban_words(story_gen.load_genre(g))]
    lib, out = library(), {}
    for kind in KINDS:
        rank = {}
        for e in lib[kind]:
            hits = [genres.index(t) for t in e["tags"] if t in genres]
            text = " ".join([e["name"], e.get("description", ""), *e.get("moves", [])])
            if hits and not story_gen._mentions(text, words):
                rank[e["name"]] = (min(hits), {k: v for k, v in e.items() if k != "tags"})
        out[kind] = [entry for _, entry in sorted(rank.values(), key=lambda r: r[0])]
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Genre-tagged World Kit content for a Braid mix.")
    ap.add_argument("genres", nargs="+", help="genre ids, the main one first (commas or spaces)")
    ap.add_argument("--kind", choices=KINDS)
    ap.add_argument("--mix-eras", action="store_true", help="the players want eras mixed: no era bans")
    args = ap.parse_args(argv)
    ids = [g.strip().casefold() for a in args.genres for g in re.split(r"[,\s]+", a) if g.strip()]
    try:
        parts = for_mix(ids, args.mix_eras)
    except (ValueError, OSError) as exc:
        print(f"content.py: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(parts[args.kind] if args.kind else parts, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
