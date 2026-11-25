#!/usr/bin/env python3
"""
xp.py — XP calculation and award for D&D 5e encounters.

Handles combat (CR-based or difficulty-rated) and qualifying non-combat encounters.
Reads campaign character files for current state, updates XP, and pushes to the display.

Usage:
    # Preview calculation (no file changes):
    python3 xp.py calc --level 3 --players 2 --difficulty hard --type combat
    python3 xp.py calc --level 3 --players 2 --monsters "goblin:1/4:3,hobgoblin:1:1"

    # Award after a combat encounter — difficulty-rated:
    python3 xp.py award --campaign my-campaign --characters "Aldric,Mira" \\
        --difficulty hard --type combat

    # Award after a combat encounter — exact CR calculation:
    python3 xp.py award --campaign my-campaign --characters "Aldric,Mira" \\
        --monsters "goblin:1/4:3,hobgoblin:1:1" --event alley-ambush --note "Ambush in the alley"

    # Award for a qualifying non-combat encounter:
    python3 xp.py award --campaign my-campaign --characters "Aldric,Mira" \\
        --difficulty medium --type noncombat --event guild-informant --note "guild informant interrogation"
"""

import sys
import os
import re
import json
import datetime
import argparse
import subprocess
import pathlib

# ── Difficulty thresholds — XP per character per level (Easy/Medium/Hard/Deadly) ──
# Source: D&D 5e DMG encounter difficulty table.
# These are the MINIMUM adjusted XP values that qualify each difficulty tier.
# For difficulty-rated awards, the threshold value IS the XP awarded per player.
XP_THRESHOLDS: dict[int, tuple[int, int, int, int]] = {
    1:  (25,    50,    75,    100),
    2:  (50,    100,   150,   200),
    3:  (75,    150,   225,   400),
    4:  (125,   250,   375,   500),
    5:  (250,   500,   750,   1100),
    6:  (300,   600,   900,   1400),
    7:  (350,   750,   1100,  1700),
    8:  (450,   900,   1400,  2100),
    9:  (550,   1100,  1600,  2400),
    10: (600,   1200,  1900,  2800),
    11: (800,   1600,  2400,  3600),
    12: (1000,  2000,  3000,  4500),
    13: (1100,  2200,  3400,  5100),
    14: (1250,  2500,  3800,  5700),
    15: (1400,  2800,  4300,  6400),
    16: (1600,  3200,  4800,  7200),
    17: (2000,  3900,  5900,  8800),
    18: (2100,  4200,  6300,  9500),
    19: (2400,  4900,  7300,  10900),
    20: (2800,  5700,  8500,  12700),
}

# ── XP by CR (D&D 5e standard table) ─────────────────────────────────────────
CR_XP: dict[str, int] = {
    "0":   10,    "1/8": 25,    "1/4": 50,    "1/2": 100,
    "1":   200,   "2":   450,   "3":   700,   "4":   1100,
    "5":   1800,  "6":   2300,  "7":   2900,  "8":   3900,
    "9":   4700,  "10":  5900,  "11":  7200,  "12":  8400,
    "13":  10000, "14":  11500, "15":  13000, "16":  15000,
    "17":  18000, "18":  20000, "19":  22000, "20":  25000,
    "21":  33000, "22":  41000, "23":  50000, "24":  62000,
    "25":  75000, "26":  90000, "27":  105000,"28":  120000,
    "29":  135000,"30":  155000,
}

# ── Number of monsters → XP multiplier ────────────────────────────────────────
# Applied to total monster XP to reflect action economy advantage of groups.
# Reduce by one step when party is 6+ players; increase one step for parties of 1-2.
MONSTER_MULTIPLIERS: list[tuple[int, float]] = [
    (1,   1.0),
    (2,   1.5),
    (6,   2.0),
    (10,  2.5),
    (14,  3.0),
    (999, 4.0),
]

# ── XP to reach each level (total accumulated XP) ─────────────────────────────
LEVEL_XP: dict[int, int] = {
    1: 0,       2: 300,    3: 900,    4: 2700,   5: 6500,
    6: 14000,   7: 23000,  8: 34000,  9: 48000,  10: 64000,
    11: 85000,  12: 100000,13: 120000,14: 140000, 15: 165000,
    16: 195000, 17: 225000,18: 265000,19: 305000, 20: 355000,
}

DIFF_IDX: dict[str, int] = {"easy": 0, "medium": 1, "hard": 2, "deadly": 3,
                            "low": 0, "moderate": 1, "high": 2}   # 2024 names
#: 2024 bands. The 2024 budget is a ceiling: an encounter is the lowest band whose budget it fits in.
BANDS_2024 = ("low", "moderate", "high")


def band_name(difficulty: str, ruleset: str = "2014") -> str:
    """The difficulty name the ruleset uses (2024: Low/Moderate/High; there is no Deadly)."""
    if ruleset == "2024":
        return BANDS_2024[min(DIFF_IDX.get(difficulty.lower(), 1), 2)]
    return difficulty.lower()
DIFF_LABELS: dict[int, str] = {0: "Easy", 1: "Medium", 2: "Hard", 3: "Deadly"}

from paths import CHARACTER_LEVEL_RE, find_campaign as _find_campaign, campaigns_dir as _campaigns_dir, display_dir as _display_dir, campaign_ruleset
CAMPAIGNS_DIR = _campaigns_dir()
DISPLAY_SCRIPT = _display_dir() / "push_stats.py"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _normalise_cr(cr_str: str) -> str:
    """Convert any CR representation to a CR_XP key.
    Accepts: "1/4", "0.25", "1", "5", "1/2", "0.5", "1/8", "0.125"
    """
    s = cr_str.strip()
    try:
        f = float(s)
        if abs(f - 0.125) < 0.001: return "1/8"
        if abs(f - 0.25)  < 0.001: return "1/4"
        if abs(f - 0.5)   < 0.001: return "1/2"
        return str(int(round(f)))
    except ValueError:
        pass
    return s  # already "1/4", "1/2", etc.


def _monster_multiplier(count: int, players: int = 4) -> float:
    steps = [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0]
    index = next((i + 1 for i, (threshold, _) in enumerate(MONSTER_MULTIPLIERS)
                  if count <= threshold), 6)
    index += 1 if players < 3 else -1 if players >= 6 else 0
    return steps[index]


def _parse_monsters(monsters_str: str) -> list[tuple[str, str, int]]:
    """Parse "goblin:1/4:3,orc:1/2:2" → [(name, cr_key, count), ...]"""
    result = []
    for entry in monsters_str.split(","):
        parts = [p.strip() for p in entry.strip().split(":")]
        if len(parts) == 2:
            name, cr_raw, count = parts[0], parts[1], 1
        elif len(parts) == 3:
            name, cr_raw, count = parts[0], parts[1], int(parts[2])
        else:
            print(f"  Warning: skipping malformed entry '{entry.strip()}'", file=sys.stderr)
            continue
        cr_key = _normalise_cr(cr_raw)
        if cr_key not in CR_XP:
            print(f"  Warning: unknown CR '{cr_raw}' for '{name}' — skipping", file=sys.stderr)
            continue
        result.append((name, cr_key, count))
    return result


def _calc_monster_xp(monsters: list[tuple[str, str, int]], players: int = 4,
                     ruleset: str = "2014") -> tuple[int, float, int]:
    """Returns (raw_xp, multiplier, adjusted_xp). 2024 has no group multiplier."""
    raw = sum(CR_XP[cr] * cnt for _, cr, cnt in monsters)
    total_count = sum(cnt for _, _, cnt in monsters)
    mult = 1 if ruleset == "2024" else _monster_multiplier(total_count, players)
    return raw, mult, int(raw * mult)


#: 2024 DMG XP budget per character: (Low, Moderate, High) by level. No group multiplier in 2024.
XP_BUDGETS_2024 = dict(enumerate((
    (50, 75, 100),
    (100, 150, 200),
    (150, 225, 400),
    (250, 375, 500),
    (500, 750, 1100),
    (600, 1000, 1400),
    (750, 1300, 1700),
    (1000, 1700, 2100),
    (1300, 2000, 2600),
    (1600, 2300, 3100),
    (1900, 2900, 4100),
    (2200, 3700, 4700),
    (2600, 4200, 5400),
    (2900, 4900, 6200),
    (3300, 5400, 7800),
    (3800, 6100, 9800),
    (4500, 7200, 11700),
    (5000, 8700, 14200),
    (5500, 10700, 17200),
    (6400, 13200, 22000),
), 1))


def _thresholds(level: int, ruleset: str = "2014") -> tuple:
    """(easy, medium, hard, deadly) per character. 2024 has three bands: Low, Moderate, High."""
    if ruleset == "2024":
        low, moderate, high = XP_BUDGETS_2024.get(level, XP_BUDGETS_2024[20])
        return (low, moderate, high, float("inf"))
    return XP_THRESHOLDS.get(level, XP_THRESHOLDS[20])


def party_xp_thresholds(levels, ruleset: str = "2014") -> tuple:
    return tuple(map(sum, zip(*(_thresholds(level, ruleset) for level in levels))))


def classify_difficulty(adjusted_xp: int, thresholds: tuple, ruleset: str = "2014") -> str:
    if ruleset == "2024":
        return next((name for name, limit in zip(BANDS_2024, thresholds) if adjusted_xp <= limit), "beyond high")
    tiers = zip(("easy", "medium", "hard", "deadly"), thresholds)
    return next((name for name, limit in reversed(list(tiers)) if adjusted_xp >= limit), "trivial")


def _xp_per_player(difficulty: str, level: int, ruleset: str = "2014") -> int:
    """XP per player for a difficulty-rated encounter at a given level (2024: deadly = High)."""
    idx = min(DIFF_IDX.get(difficulty.lower(), 1), 2 if ruleset == "2024" else 3)
    return int(_thresholds(level, ruleset)[idx])


def _next_level_xp(current_level: int) -> int:
    return LEVEL_XP.get(current_level + 1, 999_999_999)


# ── Character file I/O ────────────────────────────────────────────────────────

from paths import find_character_file as _find_char_path


def _read_char_state(path: pathlib.Path) -> tuple[int, int]:
    """Read current XP and level from a character file. Returns (xp, level)."""
    text = path.read_text(encoding="utf-8")
    xp_m   = re.search(r"\*\*(?:XP|经验|经验值):\*\*\s*(\d+)", text)
    level_m = CHARACTER_LEVEL_RE.search(text)
    xp    = int(xp_m.group(1))    if xp_m    else 0
    level = int(level_m.group(1)) if level_m else 1
    return xp, level


def _write_char_xp(path: pathlib.Path, new_xp: int, current_level: int) -> bool:
    """Update XP field in character file. Returns True if level-up threshold crossed."""
    text = path.read_text(encoding="utf-8")
    next_lvl = _next_level_xp(current_level)
    leveled = new_xp >= next_lvl

    if leveled:
        new_level = current_level + 1
        next_lvl   = _next_level_xp(new_level)
        suffix = f" ⚠ LEVEL UP PENDING (Level {new_level})"
    else:
        suffix = ""

    # Replace the XP field, preserving the header style (XP / 经验 / 经验值).
    # Handles plain, level-up-pending, and pipe-delimited variants.
    def _repl(m: re.Match) -> str:
        return f"**{m.group(1)}:** {new_xp} / {next_lvl}" + suffix
    # subn, not sub: `updated == text` is also true when the field WAS found and
    # the rendered value simply did not change, which is every award that leaves
    # the total where it was. Warning on that told a player their XP had not been
    # written when it had. The substitution COUNT is the only thing that answers
    # "did the regex match", which is what the warning is actually about.
    updated, hits = re.subn(
        r"\*\*(XP|经验|经验值):\*\*\s*(?:\d+)?\s*/\s*\d+[^\n|]*",
        _repl,
        text,
        count=1,
    )
    if hits == 0:
        # Fresh template sheets hold "**XP:** / 2700" (empty before the slash) — a
        # regex mismatch would silently skip writing; warn explicitly instead of
        # pretending the award succeeded.
        print(f"xp.py: warning — no XP field found in {path.name} ({new_xp} not written)", file=sys.stderr)
    path.write_text(updated, encoding="utf-8")
    return leveled


def _push_xp_display(char_name: str, new_xp: int, current_level: int) -> None:
    """Push updated XP to the display sidebar (fire-and-forget)."""
    next_lvl = _next_level_xp(current_level)
    subprocess.run(
        [sys.executable, str(DISPLAY_SCRIPT),
         "--player", char_name, "--xp", str(new_xp), str(next_lvl)],
        capture_output=True,
    )


# ── Subcommands ───────────────────────────────────────────────────────────────

def cmd_calc(args: argparse.Namespace) -> None:
    """Print XP calculation without modifying any files."""
    level   = args.level
    players = args.players
    ruleset = args.ruleset or (campaign_ruleset(args.campaign) if args.campaign else "2014")

    if args.monsters:
        monsters = _parse_monsters(args.monsters)
        if not monsters:
            print("No valid monsters parsed.", file=sys.stderr)
            sys.exit(1)
        raw_xp, mult, adj_xp = _calc_monster_xp(monsters, players, ruleset)
        total_count = sum(c for _, _, c in monsters)
        per_player  = raw_xp // players
        diff        = classify_difficulty(adj_xp, party_xp_thresholds([level] * players, ruleset), ruleset)

        print(f"\n  Combat encounter — CR-based calculation")
        for name, cr, count in monsters:
            print(f"    {count}× {name} (CR {cr}): {CR_XP[cr] * count:,} XP")
        print(f"\n  Raw XP:       {raw_xp:,}")
        print(f"  Multiplier:   ×{mult}  ({total_count} monsters)")
        print(f"  Adjusted XP:  {adj_xp:,}")
        print(f"  Difficulty:   {diff.upper()}  (Level {level} party of {players})")
        print(f"  Per player:   {per_player:,} XP")
        print(f"  Total:        {per_player * players:,} XP")

    elif args.difficulty:
        per_player = _xp_per_player(args.difficulty, level, ruleset)
        if ruleset == "2024" and args.difficulty == "deadly":
            print("  note: 2024 has no Deadly tier — rated as High")
        enc_type   = (args.type or "combat").upper()
        print(f"\n  {band_name(args.difficulty, ruleset).upper()} {enc_type} — Level {level} party of {players}")
        print(f"  Per player:  {per_player:,} XP")
        print(f"  Total:       {per_player * players:,} XP")

    else:
        print("Provide --difficulty or --monsters.", file=sys.stderr)
        sys.exit(1)


# ─── Award ledger ─────────────────────────────────────────────────────────────
#
# An award used to leave no trace except a number on a sheet. So when one did
# not happen — the GM moved to the next scene without running this — there was
# nothing to compare against and no way to find out except a player noticing
# weeks later that their total had not moved, by which point the encounters
# that should have fed it are gone.
#
# Append-only and additive: a new file per campaign, no existing format
# changed. `xp.py check` reconciles it against the sheets.

LEDGER_NAME = "xp-ledger.jsonl"


def _ledger_path(campaign: str) -> pathlib.Path:
    return CAMPAIGNS_DIR / campaign / LEDGER_NAME


def _record_award(campaign: str, entries: list, note: str, event: str = "") -> None:
    """Append one line per character. Never raises — a ledger write must not
    cost a player their XP, which is already on the sheet by the time we run.
    `event` names the encounter, so the same one is not awarded twice."""
    try:
        path = _ledger_path(campaign)
        path.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.datetime.now(datetime.timezone.utc).isoformat(
            timespec="seconds")
        with open(path, "a", encoding="utf-8") as f:
            for e in entries:
                f.write(json.dumps({
                    "at": stamp,
                    "character": e["name"],
                    "awarded": e["awarded"],
                    "total_after": e["total_after"],
                    "note": note,
                    **({"event": event} if event else {}),
                }, ensure_ascii=False) + "\n")
    except Exception as exc:                      # noqa: BLE001
        print(f"xp.py: warning — could not write the award ledger: {exc}",
              file=sys.stderr)


def _read_ledger(campaign: str) -> list:
    path = _ledger_path(campaign)
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue                              # a torn line is not fatal
    return rows


def cmd_check(args: argparse.Namespace) -> None:
    """Reconcile the ledger against the sheets and report drift.

    Does NOT fill gaps. It answers "did every award we recorded actually land",
    which is the question nobody could ask before. Filling automatically would
    need to know which encounters happened, and nothing in the campaign format
    records that yet.
    """
    campaign = args.campaign
    rows = _read_ledger(campaign)
    if not rows:
        print(f"  No award ledger for '{campaign}' yet "
              f"({_ledger_path(campaign)}).")
        print("  It starts filling from the next `xp.py award`.")
        return

    by_char = {}
    for r in rows:
        by_char.setdefault(r.get("character", "?"), []).append(r)

    print(f"\n  XP ledger — {campaign}  ({len(rows)} awards recorded)\n")
    drift = 0
    for name, entries in sorted(by_char.items()):
        expected = entries[-1].get("total_after")
        try:
            actual, _level = _read_char_state(_find_char_path(campaign, name))
        except (FileNotFoundError, ValueError):
            print(f"    {name:<16} ledger says {expected}, no character file")
            drift += 1
            continue
        if expected is not None and actual != expected:
            # A sheet BELOW the ledger is the silent-discard case. A sheet
            # ABOVE it just means XP was awarded some other way, which is
            # normal and worth showing rather than flagging.
            marker = "  ← sheet is BEHIND the ledger" if actual < expected else ""
            print(f"    {name:<16} sheet {actual:<7} ledger {expected:<7}{marker}")
            if actual < expected:
                drift += 1
        else:
            print(f"    {name:<16} sheet {actual:<7} matches")
    print()
    if drift:
        print(f"  {drift} character(s) hold less XP than the ledger recorded.")
        print("  Re-run the missing award, or correct the sheet by hand.")
        sys.exit(1)
    print("  Every recorded award is reflected on its sheet.")


def cmd_award(args: argparse.Namespace) -> None:
    """Calculate XP, update character files, and push to display."""
    campaign   = args.campaign
    char_names = [c.strip() for c in args.characters.split(",")]
    enc_type   = (args.type or ("combat" if args.monsters else "noncombat")).lower()
    note       = args.note or ""

    # Load character state from files
    chars = []
    for name in char_names:
        try:
            path = _find_char_path(campaign, name)
        except FileNotFoundError as e:
            print(f"  Error: {e}", file=sys.stderr)
            sys.exit(1)
        xp, level = _read_char_state(path)
        chars.append({"name": name, "xp": xp, "level": level, "path": path})

    players   = len(chars)
    ruleset   = campaign_ruleset(campaign)

    # Calculate XP per player
    if args.monsters:
        monsters = _parse_monsters(args.monsters)
        if not monsters:
            print("No valid monsters parsed.", file=sys.stderr)
            sys.exit(1)
        raw_xp, mult, adj_xp = _calc_monster_xp(monsters, players, ruleset)
        total_count = sum(c for _, _, c in monsters)
        per_player  = raw_xp // players
        awards = [per_player] * players
        diff = classify_difficulty(adj_xp, party_xp_thresholds((c["level"] for c in chars), ruleset), ruleset)

        print(f"\n  Combat — CR-based  [{total_count} monsters, ×{mult} multiplier]")
        for name, cr, count in monsters:
            print(f"    {count}× {name} (CR {cr}): {CR_XP[cr] * count:,} XP")
        print(f"  Raw {raw_xp:,} × {mult} = Adjusted {adj_xp:,} | Difficulty: {diff.upper()}")
        print(f"  Per player: {per_player:,} XP")

    else:
        if not args.difficulty:
            print("Provide --difficulty or --monsters.", file=sys.stderr)
            sys.exit(1)
        diff       = band_name(args.difficulty, ruleset)
        if ruleset == "2024" and args.difficulty == "deadly":
            print("  note: 2024 has no Deadly tier — rated as High")
        awards = [_xp_per_player(diff, c["level"], ruleset) for c in chars]
        type_label = f"  [{enc_type}]" if enc_type == "noncombat" else ""
        print(f"\n  {diff.upper()} {enc_type.upper()}{type_label} — Party of {players}")

    if note:
        print(f"  Note: {note}")

    # The same encounter is paid once (here or by the engine's `reward`); --event names it.
    event = (args.event or "").strip()
    done = {str(r.get("character", "")).casefold() for r in _read_ledger(campaign)
            if event and str(r.get("event", "")).casefold() == event.casefold()}
    if done and not args.again:
        print(f"\n  Already awarded for {event!r}: "
              + ", ".join(c["name"] for c in chars if c["name"].casefold() in done)
              + " — skipped (pass --again if this really is a second award).")
        kept = [(c, a) for c, a in zip(chars, awards) if c["name"].casefold() not in done]
        chars, awards = [c for c, _ in kept], [a for _, a in kept]

    # Apply XP to each character
    print()
    any_levelup = False
    _ledger_entries = []
    for c, award in zip(chars, awards):
        old_xp  = c["xp"]
        new_xp  = old_xp + award
        leveled = _write_char_xp(c["path"], new_xp, c["level"])
        _push_xp_display(c["name"], new_xp, c["level"])
        _ledger_entries.append({"name": c["name"], "awarded": award,
                                "total_after": new_xp})

        next_lvl   = _next_level_xp(c["level"])
        up_tag     = f"  ⚠ LEVEL {c['level'] + 1} UP!" if leveled else ""
        remaining  = max(0, next_lvl - new_xp)
        rem_note   = "" if leveled else f"  ({remaining:,} to Level {c['level'] + 1})"
        print(f"  {c['name']}: {award:,} XP — {old_xp:,} → {new_xp:,} / {next_lvl:,}{rem_note}{up_tag}")
        if leveled:
            any_levelup = True

    # Recorded AFTER the sheets are written, so the ledger never claims an
    # award that did not land.
    if _ledger_entries:
        _record_award(campaign, _ledger_entries,
                      note=f"{diff} {enc_type}" + (f" — {note}" if note else ""), event=event)

    if any_levelup:
        print("\n  Level-up pending — run /dne level up")


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="XP calculation and award for D&D 5e encounters.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    # ── calc ──────────────────────────────────────────────────────────────────
    calc_p = sub.add_parser("calc", help="Preview XP calculation — no files modified")
    calc_p.add_argument("--level",      type=int, default=1, metavar="N",
                        help="Average party level (default: 1)")
    calc_p.add_argument("--players",    type=int, default=4, metavar="N",
                        help="Number of players (default: 4)")
    calc_p.add_argument("--difficulty", choices=["easy", "medium", "hard", "deadly", "low", "moderate", "high"],
                        help="Encounter difficulty tier")
    calc_p.add_argument("--type",       choices=["combat", "noncombat"], default="combat",
                        help="Encounter type (default: combat)")
    calc_p.add_argument("--monsters",   metavar="LIST",
                        help="name:cr:count,... e.g. 'goblin:1/4:3,orc:1/2:2'")
    calc_p.add_argument("--ruleset",    choices=["2014", "2024"], help="default: the campaign's, else 2014")
    calc_p.add_argument("-c", "--campaign", metavar="NAME", help="read the ruleset from this campaign")

    # ── award ─────────────────────────────────────────────────────────────────
    award_p = sub.add_parser("award", help="Award XP — updates character files and display")
    award_p.add_argument("--campaign",   required=True, metavar="NAME",
                         help="Campaign folder name (e.g. my-campaign)")
    award_p.add_argument("--characters", required=True, metavar="NAMES",
                         help="Comma-separated character names matching campaign files")
    award_p.add_argument("--difficulty", choices=["easy", "medium", "hard", "deadly", "low", "moderate", "high"],
                         help="Encounter difficulty tier (required unless --monsters provided)")
    award_p.add_argument("--type",       choices=["combat", "noncombat"],
                         help="Encounter type (default: combat if --monsters, else noncombat)")
    award_p.add_argument("--monsters",   metavar="LIST",
                         help="name:cr:count,... for exact CR-based calculation")
    award_p.add_argument("--note",       metavar="TEXT",
                         help="Brief label for this award; stored in the ledger")
    award_p.add_argument("--event",      metavar="ID", default="",
                         help="Encounter id; the same one is never awarded twice (the engine's `reward` uses it too)")
    award_p.add_argument("--again",      action="store_true",
                         help="Award even though the ledger already holds this event")

    check_p = sub.add_parser(
        "check", help="Reconcile the award ledger against the character sheets")
    check_p.add_argument("--campaign", required=True, metavar="NAME")

    args = parser.parse_args()

    if   args.command == "calc":  cmd_calc(args)
    elif args.command == "award": cmd_award(args)
    elif args.command == "check": cmd_check(args)
    else:
        parser.print_help()
        sys.exit(0)


if __name__ == "__main__":
    main()
