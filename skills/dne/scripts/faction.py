#!/usr/bin/env python3
"""
faction.py — factions that act off-screen, one turn per in-world week.

The idea (faction turns between sessions) comes from Worlds Without Number;
the numbers are our own. world.md keeps who a faction is, state.md keeps its
stance toward the party; factions.json keeps only the numbers and the log.

Each faction has Force, Wealth and Influence (1–5), Stability (4 + the three,
its "hit points"), a goal on a clock (4, 6 or 8 segments) tied to one of the
three, and optional rivals. On a turn each faction does one thing:

  recover  — Stability at half or less: regain 2.
  attack   — a rival (about one turn in three): d10 + Force (or Influence,
             whichever is higher) against the rival's d10 + the same stat;
             the loser loses 1 Stability, 2 if beaten by 5 or more.
  advance  — d10 + the goal's stat: 8+ fills 1 segment, 12+ fills 2,
             3 or less backfires (−1 Stability).
  hold     — no goal set: regain 1 Stability; the GM should give it a goal.

A finished goal raises its stat by 1 (max 5) and waits for a new goal.
Stability 0 = COLLAPSED (it no longer acts).

Usage:
    faction.py -c <camp> add "<name>" --force 3 --wealth 2 --influence 4 \
        [--goal "<text>" --clock 6 --goal-stat influence] [--rivals "A,B"]
    faction.py -c <camp> set "<name>" [--goal … --clock N --goal-stat S] [--rivals …] [--force N …]
    faction.py -c <camp> adjust "<name>" [--stability ±N] [--progress ±N]   # the party's doing
    faction.py -c <camp> turn [--force-turn] [--seed N]   # weekly; safe to call at every /dne load
    faction.py -c <camp> act "<name>" advance|recover|attack [--target "<rival>"] [--seed N]
    faction.py -c <camp> status | remove "<name>"
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paths import find_campaign  # noqa: E402

STATS = ("force", "wealth", "influence")
CLOCKS = (4, 6, 8)
WEEK = 7 * 1440          # in-world minutes between faction turns
MAX_CATCH_UP = 4         # at most this many turns after a long gap


def _path(campaign: str) -> Path:
    return find_campaign(campaign) / "factions.json"


def load(campaign: str) -> dict:
    try:
        data = json.loads(_path(campaign).read_text(encoding="utf-8"))
    except FileNotFoundError:
        data = {}
    data.setdefault("factions", {})
    data.setdefault("last_turn", None)
    return data


def save(campaign: str, data: dict) -> None:
    path = _path(campaign)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=path.parent) as stage:
        staged = Path(stage) / path.name
        staged.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        staged.replace(path)


def _find(data: dict, name: str) -> str:
    key = name.casefold().strip()
    for n in data["factions"]:
        if n.casefold() == key:
            return n
    known = ", ".join(data["factions"]) or "(none)"
    raise ValueError(f"unknown faction {name!r}. Known: {known}")


def max_stability(f: dict) -> int:
    return 4 + sum(f[s] for s in STATS)


def summary(name: str, f: dict) -> str:
    stats = " ".join(f"{s[0].upper()}{f[s]}" for s in STATS)
    line = f"{name}: {stats} · Stability {f['stability']}/{max_stability(f)}"
    if f["stability"] <= 0:
        return line + " · COLLAPSED"
    if f.get("goal"):
        line += f" · goal \"{f['goal']}\" {f['progress']}/{f['clock']} ({f['goal_stat']})"
        if f["progress"] >= f["clock"]:
            line += " · DONE, needs a new goal"
    else:
        line += " · no goal"
    if f.get("rivals"):
        line += " · rivals: " + ", ".join(f["rivals"])
    return line


def _alive(f: dict) -> bool:
    return f["stability"] > 0


def _hurt(f: dict, n: int) -> None:
    f["stability"] = max(0, f["stability"] - n)


def _advance(name: str, f: dict, rng: random.Random) -> str:
    stat = f["goal_stat"]
    roll = rng.randint(1, 10)
    total = roll + f[stat]
    if total >= 12:
        gain, how = 2, "great progress"
    elif total >= 8:
        gain, how = 1, "progress"
    elif total <= 3:
        _hurt(f, 1)
        return (f"{name} pushed toward \"{f['goal']}\" and it backfired "
                f"(d10 {roll} + {stat} {f[stat]} = {total}): Stability −1 → {f['stability']}")
    else:
        return (f"{name} worked on \"{f['goal']}\" without result "
                f"(d10 {roll} + {stat} {f[stat]} = {total}) · {f['progress']}/{f['clock']}")
    f["progress"] = min(f["clock"], f["progress"] + gain)
    line = (f"{name}: {how} on \"{f['goal']}\" (d10 {roll} + {stat} {f[stat]} = {total}) "
            f"· {f['progress']}/{f['clock']}")
    if f["progress"] >= f["clock"]:
        f[stat] = min(5, f[stat] + 1)
        f["stability"] = min(max_stability(f), f["stability"] + 1)
        line += f" · GOAL COMPLETE: {stat} +1 → {f[stat]}; narrate it and set a new goal"
    return line


def _attack(name: str, f: dict, target: str, data: dict, rng: random.Random) -> str:
    t = data["factions"][target]
    stat = max(("force", "influence"), key=lambda s: f[s])
    a_roll, d_roll = rng.randint(1, 10), rng.randint(1, 10)
    a_tot, d_tot = a_roll + f[stat], d_roll + t[stat]
    how = "by force" if stat == "force" else "by schemes and pressure"
    if a_tot > d_tot:
        loss = 2 if a_tot - d_tot >= 5 else 1
        _hurt(t, loss)
        out = (f"{name} struck {target} {how} ({a_tot} vs {d_tot}): "
               f"{target} Stability −{loss} → {t['stability']}")
        if not _alive(t):
            out += f" · {target} COLLAPSED"
        return out
    loss = 2 if d_tot - a_tot >= 5 else 1
    _hurt(f, loss)
    out = (f"{name} moved against {target} {how} and was repelled ({a_tot} vs {d_tot}): "
           f"{name} Stability −{loss} → {f['stability']}")
    if not _alive(f):
        out += f" · {name} COLLAPSED"
    return out


def _recover(name: str, f: dict, amount: int = 2) -> str:
    f["stability"] = min(max_stability(f), f["stability"] + amount)
    return f"{name} regrouped: Stability +{amount} → {f['stability']}/{max_stability(f)}"


def act(name: str, data: dict, rng: random.Random, action: str | None = None,
        target: str | None = None) -> str:
    """One action for one faction. action=None picks one the way a turn does."""
    f = data["factions"][name]
    if not _alive(f):
        return f"{name} is collapsed and does nothing"
    rivals = [r for r in f.get("rivals", []) if r in data["factions"] and _alive(data["factions"][r])]
    if action is None:
        if f["stability"] * 2 <= max_stability(f):
            action = "recover"
        elif rivals and rng.random() < 1 / 3:
            action, target = "attack", rng.choice(rivals)
        elif f.get("goal") and f["progress"] < f["clock"]:
            action = "advance"
        else:
            return _recover(name, f, 1) + (" · no goal: give it one" if not f.get("goal")
                                           else " · goal done: give it a new one")
    if action == "recover":
        return _recover(name, f)
    if action == "attack":
        if not target:
            raise ValueError("attack needs --target")
        target = _find(data, target)
        if target == name:
            raise ValueError("a faction cannot attack itself")
        if not _alive(data["factions"][target]):
            raise ValueError(f"{target} has collapsed")
        return _attack(name, f, target, data, rng)
    if action == "advance":
        if not f.get("goal"):
            raise ValueError(f"{name} has no goal; set one with: set \"{name}\" --goal …")
        if f["progress"] >= f["clock"]:
            raise ValueError(f"{name}'s goal is already complete; set a new one")
        return _advance(name, f, rng)
    raise ValueError(f"unknown action {action!r}")


def _now(campaign: str):
    from economy import _calendar_minutes   # lazy: economy is heavier than we need at import
    return _calendar_minutes(campaign)


def run_turns(campaign: str, data: dict, rng: random.Random, force: bool = False) -> list[str]:
    """Play the turns owed since the last one (one per in-world week, at most 4)."""
    try:
        import world_db
        if world_db.enabled(campaign) and not force:
            return ["World engine is on: faction weeks run by themselves as in-world time passes "
                    "(scheduler.py -c <campaign> list shows the next one). Nothing to do at load."]
    except ImportError:
        pass
    if not data["factions"]:
        return ["No factions tracked (add them with faction.py add)."]
    now = _now(campaign)
    last = data.get("last_turn")
    if force:
        turns = 1
    elif now is None:
        return ["No calendar: run `faction.py turn --force-turn` when a week or more has passed in the world."]
    elif last is None:
        turns = 1
    else:
        elapsed = now - last
        turns = min(MAX_CATCH_UP, int(elapsed // WEEK))
        if turns < 1:
            days = max(0, elapsed) / 1440
            return [f"No faction turn yet: {days:.1f} in-world days since the last one "
                    f"(one turn per 7 days; --force-turn to run anyway)."]
    lines = []
    for i in range(turns):
        data["turn"] = data.get("turn", 0) + 1
        if turns > 1:
            lines.append(f"Week {i + 1} of {turns}:")
        for name in list(data["factions"]):
            lines.append("- " + act(name, data, rng))
    if now is not None:
        caught_up = last is None or force or turns == MAX_CATCH_UP   # a long gap is not owed later
        data["last_turn"] = now if caught_up else last + turns * WEEK
    log = data.setdefault("log", [])
    log.extend(lines)
    del log[:-60]   # keep the recent history only
    return lines


def _stat(value: int | None, label: str) -> None:
    if value is not None and not 1 <= value <= 5:
        raise ValueError(f"--{label} must be 1–5")


def main() -> None:
    p = argparse.ArgumentParser(description="Off-screen faction turns (one per in-world week).")
    p.add_argument("-c", "--campaign", required=True)
    sub = p.add_subparsers(dest="cmd", required=True)

    def stat_args(sp, required=False):
        for s in STATS:
            sp.add_argument(f"--{s}", type=int, required=required, help="1–5")
        sp.add_argument("--goal")
        sp.add_argument("--clock", type=int, choices=CLOCKS)
        sp.add_argument("--goal-stat", choices=STATS)
        sp.add_argument("--rivals", help='comma-separated faction names, e.g. "A,B"')

    stat_args(sub.add_parser("add", help="Track a faction"), required=True)
    sub.choices["add"].add_argument("name")
    stat_args(sub.add_parser("set", help="Change a faction's stats, goal or rivals"))
    sub.choices["set"].add_argument("name")
    adj = sub.add_parser("adjust", help="Apply what the party did to a faction")
    adj.add_argument("name")
    adj.add_argument("--stability", type=int, default=0)
    adj.add_argument("--progress", type=int, default=0)
    turn = sub.add_parser("turn", help="Weekly off-screen turn for every faction")
    turn.add_argument("--force-turn", action="store_true", help="run one turn now regardless of the calendar")
    turn.add_argument("--seed", type=int)
    actp = sub.add_parser("act", help="One chosen action for one faction")
    actp.add_argument("name")
    actp.add_argument("action", choices=("advance", "recover", "attack"))
    actp.add_argument("--target")
    actp.add_argument("--seed", type=int)
    sub.add_parser("status", help="List factions")
    sub.add_parser("remove", help="Stop tracking a faction").add_argument("name")
    args = p.parse_args()

    try:
        data = load(args.campaign)
        facs = data["factions"]
        if args.cmd == "status":
            if not facs:
                print("No factions tracked.")
            for name, f in facs.items():
                print(summary(name, f))
            return
        if args.cmd == "turn":
            lines = run_turns(args.campaign, data, random.Random(args.seed), args.force_turn)
            if facs:
                save(args.campaign, data)
            print("\n".join(lines))
            if facs and any(l.startswith("- ") for l in lines):
                print("\nWrite these into state.md → ## Faction Moves as things the party may hear about.")
            return
        if args.cmd == "add":
            if any(n.casefold() == args.name.casefold() for n in facs):
                raise ValueError(f"{args.name!r} already exists")
            for s in STATS:
                _stat(getattr(args, s), s)
            f = {s: getattr(args, s) for s in STATS}
            f.update(goal=None, clock=6, goal_stat="influence", progress=0, rivals=[])
            facs[args.name] = f
            name = args.name
            if data.get("last_turn") is None:   # the first turn comes a week after tracking starts
                data["last_turn"] = _now(args.campaign)
        else:
            name = _find(data, args.name)
            f = facs[name]
        if args.cmd == "remove":
            del facs[name]
            for other in facs.values():
                other["rivals"] = [r for r in other.get("rivals", []) if r != name]
            save(args.campaign, data)
            print(f"Removed {name}")
            return
        if args.cmd == "act":
            line = act(name, data, random.Random(args.seed), args.action, args.target)
            data.setdefault("log", []).append("- " + line)
            save(args.campaign, data)
            print(line)
            return
        if args.cmd == "adjust":
            f["stability"] = max(0, min(max_stability(f), f["stability"] + args.stability))
            if f.get("goal"):
                f["progress"] = max(0, min(f["clock"], f["progress"] + args.progress))
            elif args.progress:
                raise ValueError(f"{name} has no goal to move")
            save(args.campaign, data)
            print(summary(name, f))
            return
        # add / set
        for s in STATS:
            v = getattr(args, s)
            _stat(v, s)
            if v is not None:
                f[s] = v
        if args.goal is not None:
            f.update(goal=args.goal.strip() or None, progress=0)
        if args.clock is not None:
            f["clock"] = args.clock
        if args.goal_stat is not None:
            f["goal_stat"] = args.goal_stat
        if args.rivals is not None:
            rivals = [r.strip() for r in args.rivals.split(",") if r.strip()]
            if any(r.casefold() == name.casefold() for r in rivals):
                raise ValueError("a faction cannot be its own rival")
            f["rivals"] = rivals
        if args.cmd == "add" or "stability" not in f:
            f["stability"] = max_stability(f)
        f["stability"] = min(f["stability"], max_stability(f))
        f["progress"] = min(f["progress"], f["clock"])
        save(args.campaign, data)
        print(summary(name, f))
    except (OSError, ValueError) as exc:
        print(f"faction.py: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    main()
