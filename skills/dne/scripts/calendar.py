#!/usr/bin/env python3
"""
calendar.py — in-world date and time manager

Handles time advancement for any campaign calendar — including fully custom
systems (Harvestmoon, Deepwinter, etc.). Stores the current date/time as a
structured object so arithmetic is always consistent.

The calendar is defined per-campaign in world.md under ## World Foundations →
Calendar. Run `calendar.py init` once to register it; all subsequent commands
use the stored definition.

Usage:
    # One-time setup (from the world.md calendar block):
    python3 calendar.py -c <campaign> init \
        --date "15 Harvestmoon 1247" \
        --time "morning" \
        --months "Frostfall,Deepwinter,Thawmonth,Seedtime,Bloomtide,Highsun,Harvestmoon,Duskfall" \
        --month-length 30 \
        --day-names "Sunday,Moonday,Ironday,Windday,Earthday,Fireday,Starday"

    # Advance time
    python3 calendar.py -c <campaign> advance 8 hours
    python3 calendar.py -c <campaign> advance 2 days
    python3 calendar.py -c <campaign> advance 1 week

    # Rest shortcuts
    python3 calendar.py -c <campaign> rest short    # +1 hour
    python3 calendar.py -c <campaign> rest long     # +8 hours

    Advancing or resting also advances tracker.py's timed effects by the same
    in-game time, and a rest applies the tracker's rest bookkeeping, so the
    clock and the effects cannot disagree.

    # Show current date/time
    python3 calendar.py -c <campaign> now

    # Set date/time directly (use after manual world.md edits)
    python3 calendar.py -c <campaign> set "22 Harvestmoon 1247" midday

    # Time of day only
    python3 calendar.py -c <campaign> time <morning|midday|afternoon|evening|night|midnight>

    # List upcoming events (from world.md — entered at init or updated manually)
    python3 calendar.py -c <campaign> events
"""

import json
import os
import sys
import subprocess
import argparse
from datetime import date, datetime, timedelta

GREGORIAN_MONTHS = "January February March April May June July August September October November December".split()
WEEKDAYS = "Monday Tuesday Wednesday Thursday Friday Saturday Sunday".split()
from paths import find_campaign as _find_campaign, display_dir as _display_dir

SEND_PY = str(_display_dir() / "send.py")

# Time of day labels and approximate hour ranges
TIMES_OF_DAY = [
    ("midnight",    0,  1),
    ("early morning", 1, 4),
    ("dawn",        5,  5),
    ("morning",     6,  10),
    ("midday",      11, 13),
    ("afternoon",   14, 17),
    ("evening",     18, 21),
    ("night",       22, 23),
]

HOURS_PER_TIME = {
    "midnight":      0,
    "early morning": 3,
    "dawn":          5,
    "morning":       8,
    "midday":        12,
    "afternoon":     15,
    "evening":       19,
    "night":         22,
}

MINUTES_PER_UNIT = dict.fromkeys(("minute", "minutes", "min", "m"), 1)
MINUTES_PER_UNIT.update(hour=60, hours=60, day=1440, days=1440, week=10080, weeks=10080)


def _cal_path(campaign: str) -> str:
    d = str(_find_campaign(campaign))
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "calendar.json")


def _load(campaign: str) -> dict:
    try:
        with open(_cal_path(campaign), encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save(campaign: str, cal: dict) -> None:
    with open(_cal_path(campaign), "w", encoding="utf-8") as f:
        json.dump(cal, f, indent=2, ensure_ascii=False)


def _month_length(cal: dict) -> int:
    return cal.get("month_length", 30)


def _month_list(cal: dict) -> list[str]:
    return cal.get("months", [])


def _day_names(cal: dict) -> list[str]:
    return cal.get("day_names", [])


def _format_date(cal: dict) -> str:
    """Format current date as a human-readable string."""
    day    = cal.get("day", 1)
    month  = cal.get("month", 1)
    year   = cal.get("year", 1)
    hour   = cal.get("hour", 8)
    minute = cal.get("minute", 0)
    months = _month_list(cal)
    days   = _day_names(cal)

    month_str = months[month - 1] if months and 1 <= month <= len(months) else f"Month {month}"
    day_str   = f"Day {day}"
    if cal.get("gregorian"):
        day_str = (days if len(days) == 7 else WEEKDAYS)[date(year, month, day).weekday()]
    elif days:
        ordinal = ((year - 1) * (len(months) or 12) + month - 1) * _month_length(cal) + day - 1
        day_str = days[ordinal % len(days)]

    # Map hour to time-of-day label
    tod = "night"
    for label, lo, hi in TIMES_OF_DAY:
        if lo <= hour <= hi:
            tod = label
            break

    clock = f"{hour}:{minute:02d}" if minute else str(hour)
    return f"{day_str}, {day} {month_str} {year} — {tod} (hour {clock})"


def _advance_minutes(cal: dict, minutes: int) -> None:
    """Advance the calendar, including sub-hour time."""
    cal.setdefault("hour", 8)
    cal.setdefault("day", 1)
    cal.setdefault("month", 1)
    cal.setdefault("year", 1)
    minute = cal.get("minute", 0)

    if cal.get("gregorian"):
        value = datetime(cal["year"], cal["month"], cal["day"], cal["hour"], minute) + timedelta(minutes=minutes)
        cal.update(year=value.year, month=value.month, day=value.day, hour=value.hour, minute=value.minute)
        return
    days, minute_of_day = divmod(cal["hour"] * 60 + minute + minutes, 24 * 60)
    hour, minute = divmod(minute_of_day, 60)
    month_len = _month_length(cal)
    months, day = divmod(cal["day"] - 1 + days, month_len)
    years, month = divmod(cal["month"] - 1 + months, len(_month_list(cal)) or 12)
    cal.update(year=cal["year"] + years, month=month + 1, day=day + 1, hour=hour, minute=minute)


def _send_date(cal: dict) -> None:
    """Push the current date announcement to the display."""
    msg = f"📅 {_format_date(cal)}"
    try:
        # Popen takes neither capture_output nor timeout; run() does.
        subprocess.run([sys.executable, SEND_PY, "--dice"], input=msg.encode(),
                       capture_output=True, timeout=3)
    except Exception:
        pass


# ─── Commands ────────────────────────────────────────────────────────────────

def _set_date(cal: dict, date_str: str) -> None:
    parts = date_str.split()
    if len(parts) not in (2, 3):
        raise ValueError(f"Invalid date {date_str!r}; expected D Month YYYY")
    try:
        day, year = int(parts[0]), int(parts[2]) if len(parts) == 3 else 1
    except ValueError:
        raise ValueError(f"Invalid date {date_str!r}; expected D Month YYYY") from None
    months = cal.get("months", [])
    if not months:
        months = GREGORIAN_MONTHS[:] if parts[1].lower() in [m.lower() for m in GREGORIAN_MONTHS] else [parts[1]]
        cal["months"] = months
    try:
        month = [m.lower() for m in months].index(parts[1].lower()) + 1
    except ValueError:
        raise ValueError(f"Unknown month: {parts[1]}") from None
    if cal.get("gregorian"):
        date(year, month, day)
    elif year < 1 or not 1 <= day <= _month_length(cal):
        raise ValueError(f"Invalid date: {date_str}")
    cal.update(day=day, month=month, year=year)


def _time_hour(label: str) -> int:
    if label.lower() not in HOURS_PER_TIME:
        raise ValueError(f"Unknown time label: {label}. Valid labels: {', '.join(HOURS_PER_TIME)}")
    return HOURS_PER_TIME[label.lower()]


def cmd_init(campaign: str, args) -> None:
    gregorian = getattr(args, "gregorian", False)
    months = [m.strip() for m in (args.months or "").split(",") if m.strip()]
    day_names = [d.strip() for d in (args.day_names or "").split(",") if d.strip()]
    if gregorian:
        # Real calendar, local names allowed: 12 month names, 7 day names starting Monday.
        if months and len(months) != 12:
            raise ValueError("--gregorian with --months needs exactly 12 month names")
        if day_names and len(day_names) != 7:
            raise ValueError("--gregorian with --day-names needs exactly 7 names, starting with Monday")
        months = months or GREGORIAN_MONTHS[:]
        day_names = day_names or WEEKDAYS[:]
    cal = {"months": months,
           "month_length": int(args.month_length or 30),
           "day_names": day_names or WEEKDAYS[:],
           "hour": _time_hour(args.time or "morning"), "events": []}
    if cal["month_length"] < 1:
        raise ValueError("Month length must be positive")
    if gregorian:
        cal["gregorian"] = True
    _set_date(cal, args.date)
    _save(campaign, cal)
    print(f"Calendar initialised: {_format_date(cal)}")


def _tracker():
    # Imported lazily: tracker.py is a sibling script, and only the commands
    # that move the clock need it.
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import tracker
    return tracker


def cmd_advance(campaign: str, amount: int, unit: str) -> None:
    cal = _load(campaign)
    if not cal:
        print("Calendar not initialised. Run `calendar.py -c <campaign> init` first.")
        sys.exit(1)

    minutes = amount * MINUTES_PER_UNIT[unit]
    _advance_minutes(cal, minutes)
    _save(campaign, cal)

    label = f"+{amount} {unit}"
    print(f"  {label} → {_format_date(cal)}")
    _send_date(cal)
    _tracker().advance(campaign, minutes)


def cmd_rest(campaign: str, rest_type: str) -> None:
    cal = _load(campaign)
    if not cal:
        print("Calendar not initialised. Run `calendar.py -c <campaign> init` first.")
        sys.exit(1)

    if rest_type == "short":
        _advance_minutes(cal, 60)
        label = "Short rest (+1 hour)"
    else:
        _advance_minutes(cal, 480)
        label = "Long rest (+8 hours)"

    _save(campaign, cal)
    print(f"  {label} → {_format_date(cal)}")
    _send_date(cal)
    _tracker().cmd_rest(campaign, rest_type)


def cmd_now(campaign: str) -> None:
    cal = _load(campaign)
    if not cal:
        print("Calendar not initialised. Run `calendar.py -c <campaign> init` first.")
    else:
        print(_format_date(cal))


def cmd_set(campaign: str, date_str: str, time_str: str, hour=None) -> None:
    cal = _load(campaign) or {"months": [], "day_names": WEEKDAYS[:], "month_length": 30, "events": []}
    if len(date_str.split()) == 1:
        date_str = f"{date_str} {cal['months'][cal.get('month', 1) - 1]} {cal.get('year', 1)}"
    _set_date(cal, date_str)
    if time_str:
        cal.update(hour=_time_hour(time_str), minute=0)
    if hour is not None:
        if not 0 <= hour <= 23:
            raise ValueError("Hour must be between 0 and 23")
        cal.update(hour=hour, minute=0)
    _save(campaign, cal)
    print(f"  Date set: {_format_date(cal)}")
    _send_date(cal)


def cmd_time(campaign: str, time_str: str) -> None:
    cal = _load(campaign)
    if not cal:
        print("Calendar not initialised.")
        sys.exit(1)
    cal.update(hour=_time_hour(time_str), minute=0)
    _save(campaign, cal)
    print(f"  Time set: {_format_date(cal)}")
    _send_date(cal)


def cmd_events(campaign: str) -> None:
    cal = _load(campaign)
    events = cal.get("events", [])
    if not events:
        print("  No upcoming events registered.")
        print("  Add events by editing ~/.dne/campaigns/<name>/calendar.json")
        print('  Events format: [{"name": "Festival of Stars", "date": "1 Bloomtide 1248"}]')
    else:
        print("Upcoming events:")
        for e in events:
            print(f"  {e.get('date','?')} — {e.get('name','?')}")


# ─── Main ────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(description="In-world date and time manager.")
    p.add_argument("-c", "--campaign", required=True, metavar="NAME")
    sub = p.add_subparsers(dest="cmd")

    ini = sub.add_parser("init", help="Initialise campaign calendar (run once)")
    ini.add_argument("--gregorian", action="store_true")
    ini.add_argument("--date",         default="1 Month 1",
                     help="Starting date, e.g. '15 Harvestmoon 1247'")
    ini.add_argument("--time",         default="morning",
                     help=f"Starting time of day ({', '.join(HOURS_PER_TIME)})")
    ini.add_argument("--months",       default="",
                     help="Comma-separated month names in order")
    ini.add_argument("--month-length", default="30",
                     help="Days per month (uniform, default 30)")
    ini.add_argument("--day-names",    default="",
                     help="Comma-separated day-of-week names")

    adv = sub.add_parser("advance", help="Advance time by amount")
    adv.add_argument("amount", type=int)
    adv.add_argument("unit", choices=MINUTES_PER_UNIT)

    rst = sub.add_parser("rest", help="Advance time for a short or long rest")
    rst.add_argument("type", choices=["short","long"])

    sub.add_parser("now", help="Print current date/time")

    st = sub.add_parser("set", help="Set the current date/time directly")
    st.add_argument("--hour", type=int, choices=range(24))
    st.add_argument("date",      help="Date string, e.g. '22 Harvestmoon 1247'")
    st.add_argument("time", nargs="?", default="",
                    help="Time of day (optional)")

    tm = sub.add_parser("time", help="Set time of day without changing the date")
    tm.add_argument("tod",
                    choices=list(HOURS_PER_TIME.keys()),
                    help="Time of day label")

    sub.add_parser("events", help="List upcoming calendar events")

    args = p.parse_args()

    if   args.cmd == "init":    cmd_init(args.campaign, args)
    elif args.cmd == "advance": cmd_advance(args.campaign, args.amount, args.unit)
    elif args.cmd == "rest":    cmd_rest(args.campaign, args.type)
    elif args.cmd == "now":     cmd_now(args.campaign)
    elif args.cmd == "set":     cmd_set(args.campaign, args.date, args.time, args.hour)
    elif args.cmd == "time":    cmd_time(args.campaign, args.tod)
    elif args.cmd == "events":  cmd_events(args.campaign)
    else:                       p.print_help()


if __name__ == "__main__":
    try:
        main()
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)
