#!/usr/bin/env python3
"""Track Victory Points for a campaign challenge."""

import argparse
import json
import sys
import tempfile

from dice import degree
from paths import find_campaign


POINTS = {
    "critical success": 2,
    "success": 1,
    "success at a cost": 1,
    "failure": 0,
    "critical failure": -1,
}


def summary(name: str, challenge: dict) -> str:
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
    start.add_argument("--goal", type=int, required=True)
    start.add_argument("--limit", type=int)
    start.add_argument("--note", default="")

    check = sub.add_parser("check", help="Score a check")
    check.add_argument("name")
    outcome = check.add_mutually_exclusive_group(required=True)
    outcome.add_argument("--degree", help="critical-success, success, success-at-a-cost, failure, critical-failure")
    outcome.add_argument("--total", type=int)
    check.add_argument("--dc", type=int)
    check.add_argument("--natural", type=int, metavar="1–20")

    sub.add_parser("status", help="List challenges and remaining checks")
    sub.add_parser("end", help="Remove a challenge").add_argument("name")

    args = parser.parse_args()
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
                checks = "unlimited checks" if left is None else f"{left} checks left"
                note = f" · {challenge['note']}" if challenge["note"] else ""
                print(f"{summary(name, challenge)} · {checks}{note}")
            return

        name = args.name
        if args.cmd == "start":
            if name in challenges:
                raise ValueError(f"{name!r} already exists")
            challenge = {"points": 0, "goal": args.goal, "checks_left": args.limit, "note": args.note}
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
