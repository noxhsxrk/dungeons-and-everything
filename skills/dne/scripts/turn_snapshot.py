#!/usr/bin/env python3
"""
turn_snapshot.py — Per-turn atomic snapshots & whole-round rollback (/dne undo).

Inspired by DiceFrame ADR-0003 (whole-round rollback) and round_safety snapshots.
Snapshots all authoritative campaign files + display runtime state before a turn
mutates anything, enabling clean atomic undo/rewind without leaving partial HP,
gold, inventory, graph, or log deltas behind.

Usage:
    python3 turn_snapshot.py -c <campaign> save [--label "Before tavern fight"]
    python3 turn_snapshot.py -c <campaign> list
    python3 turn_snapshot.py -c <campaign> undo [--to N] [--dry-run] [--no-display]
    python3 turn_snapshot.py -c <campaign> redo [--dry-run] [--no-display]
    python3 turn_snapshot.py -c <campaign> prune [--keep 20]
"""

import argparse
import json
import os
import pathlib
import shutil
import ssl
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timezone

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from paths import find_campaign, runtime_dir, display_dir

MAX_SNAPSHOTS_DEFAULT = 20

# Authoritative campaign-level files to snapshot
CAMPAIGN_FILES = [
    "state.md",
    "world.md",
    "world-nodes.md",
    "world-map.json",
    "npcs.md",
    "npcs-full.md",
    "arc.md",
    "session-log.md",
    "graph.json",
    "tracker.json",
    "lorebook.json",
    "entropy.json",
    "battlemap.json",
    "events.jsonl",
    ".economy_ledger.json",
    "calendar.json",
    "xp-ledger.jsonl",
    "worldkit.json",
    "session_tail.json",
    "session-tail.md",
]

#: What snapshots tracked before "tracked" was recorded in meta.json.
_LEGACY_TRACKED = [f for f in CAMPAIGN_FILES if f not in (
    "calendar.json", "xp-ledger.jsonl", "worldkit.json", "session_tail.json", "session-tail.md",
)]

# Optional runtime display files to snapshot alongside campaign state
RUNTIME_FILES = [
    ".stats.json",
    ".log.json",
]


def _snapshots_root(campaign: str, redo: bool = False) -> pathlib.Path:
    return find_campaign(campaign) / (".redo-snapshots" if redo else ".snapshots")


def _list_snapshots(campaign: str, redo: bool = False) -> list[dict]:
    sdir = _snapshots_root(campaign, redo)
    items = []
    for entry in sorted(sdir.glob("turn_*")):
        if not entry.is_dir():
            continue
        meta_path = entry / "meta.json"
        meta = {}
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                meta = {}
        try:
            turn_num = int(entry.name.split("_", 1)[1])
        except ValueError:
            continue
        meta.setdefault("turn", turn_num)
        meta["dir"] = str(entry)
        meta.setdefault("label", "")
        meta.setdefault("timestamp", "")
        items.append(meta)
    items.sort(key=lambda x: x["turn"])
    return items


def _next_turn_number(campaign: str, redo: bool = False) -> int:
    snaps = _list_snapshots(campaign, redo)
    return (snaps[-1]["turn"] + 1) if snaps else 1


def _capture_snapshot(campaign: str, label: str, redo: bool = False) -> dict:
    cdir = find_campaign(campaign)
    if not cdir.exists():
        raise FileNotFoundError(f"Campaign directory not found: {cdir}")

    turn = _next_turn_number(campaign, redo)
    snap_dir = _snapshots_root(campaign, redo) / f"turn_{turn:04d}"
    snap_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=snap_dir.parent, prefix=".capture-") as stage:
        staging_dir = pathlib.Path(stage)
        meta = _write_snapshot(campaign, cdir, staging_dir, turn, label)
        meta["dir"] = str(snap_dir)
        (staging_dir / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
        staging_dir.rename(snap_dir)
    return meta


def _write_snapshot(campaign: str, cdir: pathlib.Path, snap_dir: pathlib.Path, turn: int, label: str) -> dict:
    files_saved = []
    for rel in CAMPAIGN_FILES:
        src = cdir / rel
        if src.exists() and src.is_file():
            dst = snap_dir / "campaign" / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            files_saved.append(rel)

    # Characters directory
    chars_src = cdir / "characters"
    chars_saved = []
    if chars_src.exists() and chars_src.is_dir():
        chars_dst = snap_dir / "campaign" / "characters"
        chars_dst.mkdir(parents=True, exist_ok=True)
        for cf in sorted(chars_src.glob("*.md")):
            shutil.copy2(cf, chars_dst / cf.name)
            chars_saved.append(cf.name)

    # Display runtime state (stats + log) if present
    rdir = runtime_dir()
    rt_saved = []
    for rf in RUNTIME_FILES:
        src = rdir / rf
        if src.exists() and src.is_file():
            dst = snap_dir / "runtime" / rf
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            rt_saved.append(rf)

    return {
        "turn": turn,
        "campaign": campaign,
        "label": label.strip(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "files": files_saved,
        "tracked": list(CAMPAIGN_FILES),
        "characters": chars_saved,
        "tracked_characters": True,
        "runtime_files": rt_saved,
        "tracked_runtime": list(RUNTIME_FILES),
    }


def save_snapshot(campaign: str, label: str = "", keep: int = MAX_SNAPSHOTS_DEFAULT) -> dict:
    meta = _capture_snapshot(campaign, label)
    redo_root = _snapshots_root(campaign, redo=True)
    if redo_root.exists():
        shutil.rmtree(redo_root)
    if keep > 0:
        prune_snapshots(campaign, keep=keep)

    return meta


def prune_snapshots(campaign: str, keep: int = MAX_SNAPSHOTS_DEFAULT) -> int:
    snaps = _list_snapshots(campaign)
    if len(snaps) <= keep:
        return 0
    to_remove = snaps[: len(snaps) - keep]
    removed = 0
    for s in to_remove:
        p = pathlib.Path(s["dir"])
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)
            removed += 1
    return removed


def _notify_display_rollback(campaign: str, turn: int) -> bool:
    """Tell the running display server to reload stats/log and refresh clients."""
    scheme_file = display_dir() / ".scheme"
    scheme = scheme_file.read_text(encoding="utf-8").strip() if scheme_file.exists() else "http"
    url = f"{scheme}://localhost:5001/rollback"
    token_file = runtime_dir() / ".token"
    token = token_file.read_text(encoding="utf-8").strip() if token_file.exists() else ""

    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-DND-Token"] = token
    ctx = None
    if scheme == "https":
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

    payload = json.dumps({"campaign": campaign, "turn": turn}).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    try:
        resp = urllib.request.urlopen(req, timeout=4.0, context=ctx)
        return 200 <= getattr(resp, "status", 200) < 300
    except Exception:
        return False


def undo_snapshot(
    campaign: str,
    to_turn: "int | None" = None,
    dry_run: bool = False,
    notify_display: bool = True,
) -> dict:
    return _move_snapshot(campaign, to_turn, dry_run, notify_display, redo=False)


def redo_snapshot(campaign: str, dry_run: bool = False, notify_display: bool = True) -> dict:
    return _move_snapshot(campaign, None, dry_run, notify_display, redo=True)


def _move_snapshot(campaign: str, to_turn, dry_run: bool, notify_display: bool, redo: bool) -> dict:
    cdir = find_campaign(campaign)
    if not cdir.exists():
        raise FileNotFoundError(f"Campaign directory not found: {cdir}")

    snaps = _list_snapshots(campaign, redo)
    if not snaps:
        if redo:
            raise RuntimeError(f"No redo snapshots available for campaign '{campaign}'.")
        raise RuntimeError(f"No snapshots available for campaign '{campaign}'.")

    if to_turn is None:
        target = snaps[-1]
    else:
        matches = [s for s in snaps if s["turn"] == to_turn]
        if not matches:
            raise RuntimeError(
                f"Snapshot turn {to_turn} not found. Available: {[s['turn'] for s in snaps]}"
            )
        target = matches[0]

    restored_turn = target["turn"]
    removed_files = []

    if not dry_run:
        inverse = _capture_snapshot(campaign, target["label"], redo=not redo)
        try:
            restored_files, removed_files = _restore_snapshot(cdir, target)
        except Exception:
            _restore_snapshot(cdir, inverse)
            shutil.rmtree(inverse["dir"])
            raise

        # Discard the restored frame and any undo frames bypassed by --to.
        for s in snaps:
            if s["turn"] >= target["turn"]:
                shutil.rmtree(s["dir"], ignore_errors=True)

        if redo:
            restored_turn = inverse["turn"]
        display_ok = _notify_display_rollback(campaign, restored_turn) if notify_display else False
    else:
        restored_files = list(target.get("files", [])) + [
            f"characters/{c}" for c in target.get("characters", [])
        ]
        display_ok = False

    return {
        "campaign": campaign,
        "restored_turn": restored_turn,
        "label": target.get("label", ""),
        "timestamp": target.get("timestamp", ""),
        "restored_files": restored_files,
        "removed_files": removed_files,
        "dry_run": dry_run,
        "display_notified": display_ok,
    }


def _restore_snapshot(cdir: pathlib.Path, target: dict) -> tuple[list, list]:
    snap_dir = pathlib.Path(target["dir"])
    restored, removed = [], []

    def restore_file(src, dst, name, tracked):
        if src.is_file():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            restored.append(name)
        elif tracked and dst.is_file():
            dst.unlink()
            removed.append(name)

    snap_camp = snap_dir / "campaign"
    tracked = set(target.get("tracked") or _LEGACY_TRACKED)
    for rel in CAMPAIGN_FILES:
        restore_file(snap_camp / rel, cdir / rel, rel, rel in tracked)

    snap_chars, dst_chars = snap_camp / "characters", cdir / "characters"
    if snap_chars.exists() or target.get("tracked_characters"):
        names = {p.name for p in snap_chars.glob("*.md")} | {p.name for p in dst_chars.glob("*.md")}
        for name in sorted(names):
            restore_file(snap_chars / name, dst_chars / name, f"characters/{name}", True)

    rdir = runtime_dir()
    for name in RUNTIME_FILES:
        restore_file(snap_dir / "runtime" / name, rdir / name, f"runtime/{name}",
                     name in target.get("tracked_runtime", []))
    return restored, removed


def main() -> None:
    parser = argparse.ArgumentParser(description="Per-turn snapshots & whole-round rollback for D&D campaigns.")
    parser.add_argument("-c", "--campaign", required=True, help="Campaign name")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_save = sub.add_parser("save", help="Save a pre-turn snapshot")
    p_save.add_argument("--label", default="", help="Optional turn/scene label")
    p_save.add_argument("--keep", type=int, default=MAX_SNAPSHOTS_DEFAULT, help="Max snapshots to retain")

    sub.add_parser("list", help="List available turn snapshots")

    p_undo = sub.add_parser("undo", help="Roll back campaign state to a snapshot")
    p_undo.add_argument("--to", type=int, default=None, help="Specific turn number (default: latest)")
    p_undo.add_argument("--dry-run", action="store_true", help="Preview what would be restored")
    p_undo.add_argument("--no-display", action="store_true", help="Do not notify display server")

    p_redo = sub.add_parser("redo", help="Restore the most recently undone state")
    p_redo.add_argument("--dry-run", action="store_true", help="Preview what would be restored")
    p_redo.add_argument("--no-display", action="store_true", help="Do not notify display server")

    p_prune = sub.add_parser("prune", help="Prune old snapshots")
    p_prune.add_argument("--keep", type=int, default=MAX_SNAPSHOTS_DEFAULT)

    args = parser.parse_args()

    try:
        if args.cmd == "save":
            meta = save_snapshot(args.campaign, label=args.label, keep=args.keep)
            lbl = f" ({meta['label']})" if meta["label"] else ""
            print(f"Snapshot saved: turn {meta['turn']}{lbl} — {len(meta['files'])} files, {len(meta['characters'])} characters")
        elif args.cmd == "list":
            snaps = _list_snapshots(args.campaign)
            if not snaps:
                print(f"No snapshots found for campaign '{args.campaign}'.")
                return
            print(f"Snapshots for '{args.campaign}' ({len(snaps)}):")
            for s in snaps:
                lbl = f" — {s['label']}" if s.get("label") else ""
                print(f"  Turn {s['turn']:>3d}  {s.get('timestamp', '')[:19]}Z{lbl}")
        elif args.cmd in ("undo", "redo"):
            if args.cmd == "undo":
                res = undo_snapshot(args.campaign, args.to, args.dry_run, not args.no_display)
            else:
                res = redo_snapshot(args.campaign, args.dry_run, not args.no_display)
            prefix = "[DRY RUN] Would restore" if res["dry_run"] else ("Rolled back" if args.cmd == "undo" else "Restored")
            lbl = f" ({res['label']})" if res["label"] else ""
            print(f"{prefix} '{args.campaign}' to Turn {res['restored_turn']}{lbl}")
            print(f"  Restored ({len(res['restored_files'])}): {', '.join(res['restored_files'])}")
            if res["removed_files"]:
                print(f"  Removed ({len(res['removed_files'])}): {', '.join(res['removed_files'])}")
            if not res["dry_run"]:
                print(f"  Display refresh: {'sent' if res['display_notified'] else 'offline/skipped'}")
        elif args.cmd == "prune":
            n = prune_snapshots(args.campaign, keep=args.keep)
            print(f"Pruned {n} old snapshot(s).")
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
