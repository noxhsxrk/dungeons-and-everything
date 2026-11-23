#!/usr/bin/env python3
"""Roll an NPC's reaction and optionally update its Attitude in npcs.md."""

import argparse
import re
import sys

from dice import roll_dice
from paths import find_campaign


def _parse_roll(value: str) -> tuple[int, int]:
    match = re.fullmatch(r"\s*([1-6])\s*,\s*([1-6])\s*", value)
    if not match:
        raise argparse.ArgumentTypeError("expected two d6 faces separated by a comma, e.g. 4,3")
    return int(match[1]), int(match[2])


def _row(line: str) -> tuple[list[str], int, int]:
    parts = re.split(r"(?<!\\)\|", line)
    start, end = int(not parts[0].strip()), len(parts) - int(not parts[-1].strip())
    return parts, start, end


def apply_attitude(campaign: str, npc: str, band: str) -> None:
    path = find_campaign(campaign) / "npcs.md"
    lines = path.read_bytes().decode("utf-8").splitlines(keepends=True)
    name_col = attitude_col = None
    skip_separator = False
    for index, line in enumerate(lines):
        if skip_separator:
            skip_separator = False
            continue
        body = line.rstrip("\r\n")
        parts, start, end = _row(body)
        cells = [cell.strip().casefold() for cell in parts[start:end]]
        if len(parts) < 2 or not cells:
            name_col = attitude_col = None
            continue
        if "name" in cells and index + 1 < len(lines):
            separator, first, last = _row(lines[index + 1])
            if last - first == len(cells) and all(
                re.fullmatch(r":?-+:?", cell.strip()) for cell in separator[first:last]
            ):
                name_col = cells.index("name")
                attitude_col = cells.index("attitude") if "attitude" in cells else None
                skip_separator = True
                continue
        if name_col is None or name_col >= len(cells) or cells[name_col] != npc.casefold():
            continue
        if attitude_col is None or attitude_col >= len(cells):
            raise ValueError(f"No Attitude column for {npc!r} in {path.name}")
        column = start + attitude_col
        spacing = re.fullmatch(r"([ \t]*).*?([ \t]*)", parts[column])
        parts[column] = f"{spacing[1]}{band}{spacing[2]}"
        lines[index] = "|".join(parts) + line[len(body):]
        path.write_bytes("".join(lines).encode("utf-8"))
        return
    raise ValueError(f"No NPC named {npc!r} in {path.name}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-c", "--campaign", required=True)
    parser.add_argument("--roll", type=_parse_roll, metavar="A,B")
    parser.add_argument("--cha-mod", type=int, default=0)
    parser.add_argument("--status-diff", type=int, default=0)
    parser.add_argument("--mod", type=int, default=0)
    parser.add_argument("--npc")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.apply and not args.npc:
        parser.error("--apply requires --npc")

    a, b = args.roll or roll_dice(2, 6)
    modifiers = (args.cha_mod, args.status_diff, args.mod)
    total = a + b + sum(modifiers)
    if total <= 2:
        band = "hostile"
    elif total <= 5:
        band = "unfriendly"
    elif total <= 8:
        band = "indifferent"
    elif total <= 11:
        band = "friendly"
    else:
        band = "helpful"

    if args.apply:
        try:
            apply_attitude(args.campaign, args.npc, band)
        except (OSError, ValueError) as exc:
            print(f"reaction.py: {exc}", file=sys.stderr)
            sys.exit(1)
    terms = "".join(f" {value:+d}" for value in modifiers if value)
    print(f"Reaction: 2d6({a}+{b}){terms} = {total} → {band}")


if __name__ == "__main__":
    main()
