#!/usr/bin/env python3
"""Track Victory Points for a campaign challenge, or a Braid contest between two sides (module contest:
`start NAME --race 3 --sides "A,B"` or `--countdown 6 --sides "A,B"`, then `check NAME --side A --total 9`)."""

import argparse
import json
import sys
import tempfile

from dice import degree
from paths import campaign_system, find_campaign


POINTS = {
    "critical success": 2,
    "success": 1,
    "success at a cost": 1,
    "failure": 0,
    "critical failure": -1,
}
#: Contest scoring (module contest, our defaults): (the side that rolled, the other side) per degree.
RACE = {"critical success": (2, 0), "success": (1, 0), "success at a cost": (1, 0), "failure": (0, 1),
        "critical failure": (0, 2)}
COUNTDOWN = {"critical success": (0, -3), "success": (0, -2), "success at a cost": (-1, -1), "failure": (-1, 0),
             "critical failure": (-2, 0)}


def contest_summary(name: str, c: dict) -> str:
    """One line for a contest: the scores, and the winner (with the concession a countdown winner owes)."""
    race = c["mode"] == "race"
    scores = " · ".join(f"{side} {n}" + ("" if race else f"/{c['goal']}") for side, n in c["sides"].items())
    result = f"{name}: {scores} ({'race to' if race else 'countdown from'} {c['goal']})"
    winner = next((s for s, n in c["sides"].items() if n >= c["goal"]), None) if race else \
        next((s for s, n in c["sides"].items() if all(m <= 0 for o, m in c["sides"].items() if o != s)), None)
    if winner and not race:
        lost = c["goal"] - c["sides"][winner]
        size = "none" if lost == 0 else "small" if lost * 2 < c["goal"] else "a real one"
        return f"{result} · WON BY {winner} · concession owed: {size}"
    if winner:
        return f"{result} · WON BY {winner}"
    return f"{result} · OUT OF TIME" if c["checks_left"] == 0 else result


def summary(name: str, challenge: dict) -> str:
    if challenge.get("mode"):
        return contest_summary(name, challenge)
    points, goal = challenge["points"], challenge["goal"]
    result = f"{name}: {points}/{goal}"
    if points >= goal:
        return f"{result} · COMPLETE"
    if challenge["checks_left"] == 0:
        return f"{result} · OUT OF TIME"
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-c", "--campaign", required=True)
    sub = parser.add_subparsers(dest="cmd", required=True)

    start = sub.add_parser("start", help="Start a challenge")
    start.add_argument("name")
    start.add_argument("--goal", type=int)
    start.add_argument("--limit", type=int)
    start.add_argument("--note", default="")
    kind = start.add_mutually_exclusive_group()
    kind.add_argument("--race", type=int, metavar="N", help="Braid contest: first side to N points wins")
    kind.add_argument("--countdown", type=int, metavar="N", help="Braid contest: each side starts at N; first at 0 loses")
    start.add_argument("--sides", help='the two sides of a contest: "Mira,The baker"')

    check = sub.add_parser("check", help="Score a check")
    check.add_argument("name")
    outcome = check.add_mutually_exclusive_group(required=True)
    outcome.add_argument("--degree", help="critical-success, success, success-at-a-cost, failure, critical-failure "
                                          "(Braid: the check's final degree, after any token step-up)")
    outcome.add_argument("--total", type=int)
    check.add_argument("--dc", type=int, help="5e only: Braid grades the 2d6 total with no DC")
    check.add_argument("--natural", type=int, metavar="1–20", help="5e only: the d20 face")
    check.add_argument("--side", help="a contest: the side that rolled")

    sub.add_parser("status", help="List challenges and remaining checks")
    sub.add_parser("end", help="Remove a challenge").add_argument("name")

    args = parser.parse_args()
    contest = args.cmd == "start" and (args.race is not None or args.countdown is not None)
    if contest:
        if campaign_system(args.campaign) == "d20":
            start.error("contests are a Braid module (System: core or story)")
        import modules
        if "contest" not in modules.enabled(args.campaign):
            start.error("module contest is not switched on: add it to `- modules:` in Session Flags")
        sides = [x.strip() for x in (args.sides or "").split(",") if x.strip()]
        if len(sides) != 2 or sides[0].casefold() == sides[1].casefold():
            start.error('a contest needs --sides "A,B": two different sides')
        args.goal = args.race if args.race is not None else args.countdown
    elif args.cmd == "start" and (args.sides or args.goal is None):
        start.error("the following arguments are required: --goal")
    if args.cmd == "start" and (args.goal < 1 or (args.limit is not None and args.limit < 1)):
        start.error("--goal and --limit must be positive")
    if args.cmd == "check":
        if args.degree is not None:
            if args.dc is not None or args.natural is not None:
                check.error("--dc and --natural require --total")
            result = args.degree.lower().replace("-", " ")
            if result == "cost":
                result = "success at a cost"
            if result not in POINTS:
                check.error(f"unknown degree {args.degree!r}")
        elif campaign_system(args.campaign) != "d20":
            # Braid grades the 2d6 total on its own ladder; there is no DC. Story mode has no total.
            if campaign_system(args.campaign) == "story" or args.dc is not None or args.natural is not None:
                check.error("this campaign has no DC: pass the 2d6 total alone (Braid) or --degree (story mode)")
            import resolve
            result = resolve.resolve("core", "2d6", None, [args.total])["degree"]
        else:
            if args.dc is None:
                check.error("--total requires --dc")
            if args.natural is not None and not 1 <= args.natural <= 20:
                check.error("--natural must be from 1 to 20")
            result = degree(args.natural or 10, args.total, args.dc, "check")

    path = find_campaign(args.campaign) / "subsystems.json"
    try:
        try:
            challenges = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            challenges = {}
        if args.cmd == "status":
            if not challenges:
                print("No active challenges.")
            for name, challenge in challenges.items():
                left = challenge["checks_left"]
                if challenge.get("mode"):
                    checks = "no round limit" if left is None else f"{left} rounds left"
                else:
                    checks = "unlimited checks" if left is None else f"{left} checks left"
                note = f" · {challenge['note']}" if challenge["note"] else ""
                print(f"{summary(name, challenge)} · {checks}{note}")
            return

        name = args.name
        if args.cmd == "start":
            if name in challenges:
                raise ValueError(f"{name!r} already exists")
            challenge = {"points": 0, "goal": args.goal, "checks_left": args.limit, "note": args.note}
            if contest:
                challenge = {"mode": "race" if args.race is not None else "countdown", "goal": args.goal,
                             "sides": {s: 0 if args.race is not None else args.goal for s in sides},
                             "checks_left": args.limit, "note": args.note}
            challenges[name] = challenge
            message = summary(name, challenge)
        else:
            if name not in challenges:
                known = ", ".join(challenges) or "(none)"
                raise ValueError(f"Unknown challenge {name!r}. Known names: {known}")
            if args.cmd == "end":
                del challenges[name]
                message = f"Ended {name}"
            else:
                challenge = challenges[name]
                if challenge.get("mode"):
                    if "WON BY" in summary(name, challenge) or challenge["checks_left"] == 0:
                        raise ValueError(summary(name, challenge))
                    side = next((s for s in challenge["sides"] if s.casefold() == (args.side or "").casefold()), None)
                    if side is None:
                        raise ValueError(f"--side: one of {', '.join(challenge['sides'])}")
                    other = next(s for s in challenge["sides"] if s != side)
                    us, them = (RACE if challenge["mode"] == "race" else COUNTDOWN)[result]
                    challenge["sides"][other] = max(0, challenge["sides"][other] + them)
                    if challenge["mode"] == "race" or challenge["sides"][other] > 0:   # a winning blow costs nothing
                        challenge["sides"][side] = max(0, challenge["sides"][side] + us)
                elif args.side:
                    raise ValueError(f"{name!r} is not a contest: no --side")
                else:
                    if challenge["points"] >= challenge["goal"] or challenge["checks_left"] == 0:
                        raise ValueError(summary(name, challenge))
                    challenge["points"] = max(0, challenge["points"] + POINTS[result])
                if challenge["checks_left"] is not None:
                    challenge["checks_left"] -= 1
                message = summary(name, challenge)
                if result == "success at a cost":
                    message += " · success at a cost — the GM sets the price"

        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=path.parent) as stage:
            staged = path.__class__(stage) / path.name
            staged.write_text(json.dumps(challenges, indent=2, ensure_ascii=False), encoding="utf-8")
            staged.replace(path)
        print(message)
    except (OSError, ValueError) as exc:
        print(f"subsystem.py: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
