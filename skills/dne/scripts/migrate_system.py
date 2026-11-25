#!/usr/bin/env python3
"""
migrate_system.py — stamp `**System:** d20` on a save from before 2.0.

Every campaign made before the system field existed is a 5e campaign, so the
only stamp it can take is d20 (a campaign cannot change system: the character
sheets are a different shape). A save without the field already plays as d20;
this makes it explicit. state.md is backed up to
state.md.backup-pre-system-YYYYMMDD-HHMMSS before the write. Idempotent.

Usage:
    python3 migrate_system.py <campaign-name> --check             # exit 0=stamped, 1=needs it, 2=missing campaign
    python3 migrate_system.py <campaign-name> --system d20 --yes  # used by /dne load
"""
from __future__ import annotations

import argparse
import datetime
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from migrate_ruleset import HEADER_LINE_PREFIX  # noqa: E402
from paths import campaign_system, find_campaign  # noqa: E402
from utf8io import read_text, TextDecodeError  # noqa: E402

SYSTEM_LABEL = "**System:**"


def _header(text: str) -> str:
    return text.split("\n## ", 1)[0]


def _inject(text: str, system: str) -> str:
    """Add the field to the **Created:** header line, or under the title when an old save has no such line."""
    lines = text.splitlines()
    at = next((i for i, line in enumerate(lines) if HEADER_LINE_PREFIX in line), None)
    if at is not None:
        lines[at] = f"{lines[at].rstrip()}  {SYSTEM_LABEL} {system}"
    else:
        title = next((i for i, line in enumerate(lines) if line.startswith("# ")), -1)
        lines.insert(title + 1, f"{SYSTEM_LABEL} {system}")
    return "\n".join(lines) + ("\n" if text.endswith("\n") else "")


def cmd_check(campaign: str) -> int:
    state = find_campaign(campaign) / "state.md"
    if not state.exists():
        print(f"[migrate_system] No state.md at {state}", file=sys.stderr)
        return 2
    if SYSTEM_LABEL in _header(state.read_text(encoding="utf-8", errors="replace")):
        print("migrated")
        return 0
    print("needs-migration")
    return 1


def cmd_migrate(campaign: str, system: str, assume_yes: bool) -> int:
    if system != "d20":
        print("[migrate_system] An old save is a 5e campaign: the only stamp is --system d20. "
              "A Braid campaign is a new campaign (/dne new).", file=sys.stderr)
        return 2
    state = find_campaign(campaign) / "state.md"
    if not state.exists():
        print(f"[migrate_system] No state.md at {state}", file=sys.stderr)
        return 2
    try:
        text = read_text(state)
    except (OSError, TextDecodeError) as e:
        print(f"[migrate_system] {e} — refusing to touch {state}", file=sys.stderr)
        return 2
    if SYSTEM_LABEL in _header(text):
        print(f"[migrate_system] Already migrated. System: {campaign_system(campaign)}")
        return 0
    if not assume_yes:
        try:
            ans = input(f"Stamp '{SYSTEM_LABEL} d20' on {state} (backed up first)? [Y/n] ").strip().lower()
        except EOFError:
            ans = ""
        if ans and ans not in ("y", "yes"):
            print("[migrate_system] Cancelled.")
            return 3
    bak = state.with_name(f"state.md.backup-pre-system-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}")
    shutil.copy2(state, bak)
    state.write_text(_inject(text, system), encoding="utf-8")
    print(f"[migrate_system] OK — '{campaign}' stamped as system {system}.\n  Backup: {bak}\n  Revert: cp '{bak}' '{state}'")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Stamp **System:** d20 on a save from before 2.0.")
    p.add_argument("campaign")
    p.add_argument("--system", default="d20", help="the stamp: d20 (the only value an old save can take)")
    p.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    p.add_argument("--check", action="store_true", help="exit 0=stamped, 1=needs it, 2=missing; writes nothing")
    args = p.parse_args(argv)
    return cmd_check(args.campaign) if args.check else cmd_migrate(args.campaign, args.system, args.yes)


if __name__ == "__main__":
    sys.exit(main())
