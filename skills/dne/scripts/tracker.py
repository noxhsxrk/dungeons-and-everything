#!/usr/bin/env python3
"""
tracker.py — session-state tracker for conditions, concentration, effects, and death saves

Stores state per-campaign. Outputs formatted status to terminal and pushes
condition updates to the display companion sidebar (via push_stats.py).

Usage:
    CAMPAIGN=my-campaign

    # Conditions (5e SRD: blinded, charmed, deafened, exhausted, frightened,
    #   grappled, incapacitated, invisible, paralyzed, petrified, poisoned,
    #   prone, restrained, stunned, unconscious)
    python3 tracker.py -c $CAMPAIGN condition add <entity> <condition> [N] [--decay] [--penalty attack,save,check]
    python3 tracker.py -c $CAMPAIGN condition remove <entity> <condition>
    python3 tracker.py -c $CAMPAIGN condition clear <entity>

    # Concentration (one spell at a time per caster; auto-clears previous)
    python3 tracker.py -c $CAMPAIGN concentrate <entity> "<spell name>"
    python3 tracker.py -c $CAMPAIGN concentrate <entity> break

    # Timed effects — duration formats: 10r (rounds), 60m (minutes), 8h (hours), indef
    python3 tracker.py -c $CAMPAIGN effect start <entity> "<spell>" <duration> [conc] [--caster <who>]
                       [--mod +1d4 --on attack,save]   # a typed modifier (Bless)
    python3 tracker.py -c $CAMPAIGN effect end   <entity> "<spell>"
    python3 tracker.py -c $CAMPAIGN effect tick  <entity>   # call on that entity's turn start
    python3 tracker.py -c $CAMPAIGN effect advance <time>   # in-game time passes: 90 / 90m / 8h / 10r

    # Durations run on IN-GAME time. Nothing expires because the session ran
    # long or the laptop slept; time moves only when a turn ticks, when
    # `effect advance` is run, or when calendar.py advances / rests.

    # Rests — advance in-game time and apply the rest's bookkeeping
    python3 tracker.py -c $CAMPAIGN rest short   # +1 hour; effects keep running
    python3 tracker.py -c $CAMPAIGN rest long    # +8 hours; concentration ends,
                                                 # exhaustion -1 (not at 0 HP)

    # Death saves (PC only — 3 successes = stable, 3 failures = dead)
    python3 tracker.py -c $CAMPAIGN saves <entity> success
    python3 tracker.py -c $CAMPAIGN saves <entity> failure
    python3 tracker.py -c $CAMPAIGN saves <entity> stable   # manually mark stable
    python3 tracker.py -c $CAMPAIGN saves <entity> reset    # regain consciousness

    # Status display
    python3 tracker.py -c $CAMPAIGN status [entity]   # all entities or one

    # Clear (end of encounter — wipes encounter conditions and round-long
    # effects; keeps minute/hour effects, exhaustion and petrification)
    python3 tracker.py -c $CAMPAIGN clear [--all]     # --all also resets death
                                                      # saves (never a dead PC's)
"""

import json
import math
import re
import os
import random
import sys
import subprocess
import argparse
import time
from datetime import datetime, timezone
from paths import campaign_ruleset, find_campaign as _find_campaign, display_dir as _display_dir

PUSH_STATS = str(_display_dir() / "push_stats.py")
SEND_PY    = str(_display_dir() / "send.py")

# 5e condition colours for display pills
CONDITION_COLOURS = {
    "unconscious":    "danger",
    "paralyzed":      "danger",
    "petrified":      "danger",
    "stunned":        "danger",
    "incapacitated":  "warn",
    "frightened":     "warn",
    "poisoned":       "warn",
    "charmed":        "warn",
    "exhausted":      "warn",
    "grappled":       "info",
    "restrained":     "info",
    "prone":          "info",
    "blinded":        "info",
    "deafened":       "info",
    "invisible":      "buff",
}

#: Conditions an encounter ending does not end. Exhaustion is removed one
#: level per long rest and petrification by magic; neither wears off because
#: the fight is over, so `clear` (and `clear --all`) leave them in place.
LASTING_CONDITIONS = {"exhausted", "petrified"}

#: Roll types a tracked modifier can apply to (`effect start --on`).
MODIFIER_TARGETS = ("attack", "save", "check", "damage")
CONDITION_PENALTY_TARGETS = ("attack", "save", "check")

#: One combat round is six seconds of in-game time.
MINUTES_PER_ROUND = 0.1


def _state_path(campaign: str) -> str:
    d = str(_find_campaign(campaign))
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "tracker.json")


def _load(campaign: str) -> dict:
    path = _state_path(campaign)
    try:
        with open(path, encoding="utf-8") as f:
            state = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    for key, ent in state.items():
        if key.startswith("_") or not isinstance(ent, dict):
            continue   # bookkeeping like "_round_checks", not an entity
        ent["effects"] = [_migrate_effect(e) for e in ent.get("effects", [])]
    return state


def _migrate_effect(eff: dict) -> dict:
    """Convert a wall-clock effect from an older tracker.json to in-game time.

    Minute and hour effects used to store `started_at=time.time()` and expire
    on the real clock, so an 8-hour Mage Armor ran out after eight real hours
    whatever happened in the fiction. An existing entry keeps the remaining
    time it showed at the moment of the update; from then on only in-game
    time moves it.
    """
    if eff.get("duration_type") not in ("minutes", "hours") or "remaining_minutes" in eff:
        return eff
    eff = dict(eff)
    secs = eff.pop("duration_seconds", 0)
    started = eff.pop("started_at", None)
    elapsed = (time.time() - started) if started else 0
    eff["remaining_minutes"] = max(0.0, (secs - elapsed) / 60.0)
    return eff


def _save(campaign: str, state: dict) -> None:
    with open(_state_path(campaign), "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def _entity(state: dict, name: str) -> dict:
    """Get or create an entity entry."""
    key = name.lower()
    if key not in state:
        state[key] = {
            "name": name,
            "conditions": [],
            "concentration": None,
            "effects": [],
            "death_saves": {"successes": 0, "failures": 0, "stable": False},
        }
    # Backfill keys for older entries
    state[key].setdefault("effects", [])
    state[key].setdefault("conditions", [])
    state[key].setdefault("death_saves", {"successes": 0, "failures": 0, "stable": False})
    if "exhaustion" not in state[key]:
        state[key]["exhaustion"] = 1 if "exhausted" in state[key]["conditions"] else 0
    return state[key]


#: Conditions that make a creature incapacitated, which ends its concentration.
ENDS_CONCENTRATION = ("incapacitated", "paralyzed", "petrified", "stunned", "unconscious")


def drop_concentration(state: dict, caster: dict) -> "str | None":
    """End what `caster` concentrates on, on every creature it was holding it on.

    A concentration spell on several targets (Bless on three allies) is one
    spell: when the caster's concentration ends, every target loses it. An
    effect placed with `--caster` names its caster; one without names nobody,
    so it belongs to the creature carrying it. Returns the spell, or None.
    """
    spell = caster.get("concentration")
    if not spell:
        return None
    caster["concentration"] = None
    me = str(caster.get("name", "")).lower()
    for key, ent in state.items():
        if key.startswith("_") or not isinstance(ent, dict):
            continue
        holder = str(ent.get("name", key)).lower()
        ent["effects"] = [e for e in ent.get("effects", [])
                          if not (e.get("concentration") and str(e.get("name", "")).lower() == spell.lower()
                                  and str(e.get("caster") or holder).lower() == me)]
    return spell


def _parse_duration(dur_str: str) -> "dict | None":
    """Parse a duration string into an effect dict fragment.
    Formats: 10r (rounds), 60m (minutes), 8h (hours), indef (indefinite).
    Returns None on bad input.
    """
    d = dur_str.strip().lower()
    if d.endswith("r"):
        try:
            return {"duration_type": "rounds", "duration_remaining": int(d[:-1])}
        except ValueError:
            return None
    elif d.endswith("m"):
        try:
            return {"duration_type": "minutes", "remaining_minutes": float(int(d[:-1]))}
        except ValueError:
            return None
    elif d.endswith("h"):
        try:
            return {"duration_type": "hours", "remaining_minutes": float(int(d[:-1]) * 60)}
        except ValueError:
            return None
    elif d == "indef":
        return {"duration_type": "indefinite"}
    return None


def _fmt_effect(eff: dict) -> str:
    """Return a short human-readable remaining-duration string."""
    dt = eff.get("duration_type", "indefinite")
    if dt == "rounds":
        r = eff.get("duration_remaining", 0)
        return f"{r} rnd"
    elif dt in ("minutes", "hours"):
        remaining = eff.get("remaining_minutes", 0)
        if remaining <= 1e-9:
            return "expired"
        if remaining < 1:
            return f"{math.ceil(round(remaining / MINUTES_PER_ROUND, 6))} rnd"
        m = math.ceil(round(remaining, 6))
        if m >= 60:
            h, m = divmod(m, 60)
            return f"{h}h {m}m"
        return f"{m}m"
    return "∞"


def _fmt_modifier(eff: dict) -> str:
    mod = eff.get("modifier")
    if not mod:
        return ""
    return f" · {mod['value']} {'/'.join(mod.get('applies', []))}"


def parse_time(spec: str) -> "float | None":
    """In-game time for `effect advance`: 90 / 90m (minutes), 8h, 10r (rounds)."""
    d = (spec or "").strip().lower()
    try:
        if d.endswith("h"):
            return float(d[:-1]) * 60
        if d.endswith("r"):
            return float(d[:-1]) * MINUTES_PER_ROUND
        if d.endswith("m"):
            return float(d[:-1])
        return float(d)
    except ValueError:
        return None


def _run_down(ent: dict, minutes: float) -> list:
    """Spend `minutes` of in-game time on one entity's effects.

    Returns the effects that ran out; the survivors stay on the entity. A
    round-counted effect loses ten rounds per minute, so a 10-round Bless
    does not outlast an hour of travel.
    """
    kept, expired = [], []
    for e in ent.get("effects", []):
        dt = e.get("duration_type")
        if dt == "rounds":
            e = dict(e)
            rounds = int(round(minutes / MINUTES_PER_ROUND))
            e["duration_remaining"] = max(0, e.get("duration_remaining", 1) - rounds)
            (expired if e["duration_remaining"] <= 0 else kept).append(e)
        elif dt in ("minutes", "hours"):
            e = dict(e)
            e["remaining_minutes"] = max(0.0, e.get("remaining_minutes", 0) - minutes)
            (expired if e["remaining_minutes"] <= 1e-9 else kept).append(e)
        else:
            kept.append(e)
    ent["effects"] = kept
    return expired


def _report_expired(ent: dict, expired: list, state: "dict | None" = None) -> None:
    entity_name = ent["name"]
    for e in expired:
        spell_name = e["name"]
        if e.get("concentration") and (ent.get("concentration") or "").lower() == spell_name.lower():
            if state is not None:
                drop_concentration(state, ent)
            ent["concentration"] = None
            _send_announce(f"{entity_name} — {spell_name} expired (concentration ends)")
            print(f"  ! {entity_name}: {spell_name} EXPIRED — concentration ends")
        else:
            _send_announce(f"{entity_name} — {spell_name} expired")
            print(f"  ! {entity_name}: {spell_name} EXPIRED")


def advance(campaign: str, minutes: float, quiet: bool = False) -> list:
    """Advance in-game time for every tracked entity. Returns [(entity, effect)].

    Called by `effect advance`, by `rest`, and by calendar.py when it moves
    the clock, so a journey or a rest runs effects down by the time it took.
    """
    state = _load(campaign)
    out = []
    for k, ent in state.items():
        if k.startswith("_") or not isinstance(ent, dict):
            continue
        expired = _run_down(ent, minutes)
        if not quiet:
            _report_expired(ent, expired, state)
        else:
            for e in expired:
                if e.get("concentration") and (ent.get("concentration") or "").lower() == str(e.get("name", "")).lower():
                    drop_concentration(state, ent)
        out.extend((ent["name"], e) for e in expired)
    if state:
        _save(campaign, state)
    return out


def active_modifiers(campaign: str, entity_name: str, roll_type: str) -> list:
    """[(label, '+1d4'), ...] for effects and conditions that apply to roll_type.

    dice.py and combat.py call this for `--effects <entity>`, so a Bless that
    tracker.py holds is added to the roll instead of being remembered.
    """
    ent = _load(campaign).get(entity_name.lower())
    if not ent:
        return []
    out = []
    for e in ent.get("effects", []):
        mod = e.get("modifier")
        if mod and roll_type in mod.get("applies", []):
            out.append((e["name"], mod["value"]))
    exhaustion = ent.get("exhaustion", int("exhausted" in ent.get("conditions", [])))
    if exhaustion > 0 and roll_type in ("attack", "save", "check", "death") and campaign_ruleset(campaign) == "2024":
        out.append((f"Exhaustion {exhaustion}", str(-2 * exhaustion)))
    for cond, entry in ent.get("values", {}).items():
        if roll_type in entry["penalty_on"]:
            value = entry["value"]
            out.append((f"{cond} {value}", f"-{value}"))
    return out


def _push_conditions(entity_name: str, conditions: list[str]) -> None:
    """Push condition list to display sidebar via push_stats.py."""
    cond_str = ",".join(conditions)
    try:
        subprocess.run(
            [sys.executable, PUSH_STATS, "--player", entity_name,
             "--conditions", cond_str],
            capture_output=True, timeout=3,
        )
    except Exception:
        pass  # Display not running — fail silently


def _send_announce(msg: str) -> None:
    """Send a one-line announcement to the display companion."""
    try:
        # Popen takes neither capture_output nor timeout; run() does.
        subprocess.run([sys.executable, SEND_PY, "--dice"], input=msg.encode(),
                       capture_output=True, timeout=3)
    except Exception:
        pass


# ─── Commands ────────────────────────────────────────────────────────────────

def cmd_effect(campaign: str, action: str, entity_name: str,
               spell: str = "", duration: str = "", is_conc: bool = False,
               mod: str = "", on: str = "", until: str = "", caster: str = "") -> None:
    if action == "advance":
        # `effect advance <time>` — the time arrives in the entity slot.
        minutes = parse_time(entity_name)
        if minutes is None or minutes < 0:
            print(f"  error: bad time '{entity_name}' — use 90 / 90m / 8h / 10r")
            sys.exit(2)
        expired = advance(campaign, minutes)
        if not expired:
            print(f"  +{minutes:g} min in-game — nothing expired")
        return

    state = _load(campaign)
    ent   = _entity(state, entity_name)

    if action == "start":
        if not spell or not duration:
            print("  error: effect start requires <entity> <spell> <duration>")
            return
        dur = _parse_duration(duration)
        if dur is None:
            print(f"  error: bad duration '{duration}' — use 10r / 60m / 8h / indef")
            return

        effect = {"name": spell, "concentration": is_conc, **dur}
        if until.strip():
            # "Until the end/start of the caster's next turn": counts down on that turn.
            effect["until"] = until.strip()
        if mod:
            applies = [t.strip().lower() for t in (on or "").split(",") if t.strip()]
            bad = [t for t in applies if t not in MODIFIER_TARGETS]
            if not applies or bad:
                print(f"  error: --mod needs --on with any of {', '.join(MODIFIER_TARGETS)}")
                sys.exit(2)
            if not re.match(r"^[+-](\d*d\d+|\d+)$", mod.strip().lower()):
                print(f"  error: bad modifier '{mod}' — use +1d4 / -1d4 / +2")
                sys.exit(2)
            effect["modifier"] = {"value": mod.strip().lower(), "applies": applies}

        caster = caster.strip()
        if caster and caster.lower() == entity_name.strip().lower():
            caster = ""
        if caster and is_conc:
            effect["caster"] = caster

        # Mirror concentration onto whoever holds it: the caster, or this entity.
        if is_conc:
            holder = _entity(state, caster) if caster else ent
            old = holder.get("concentration")
            if old and old.lower() != spell.lower():
                drop_concentration(state, holder)
                print(f"  {holder['name']}: dropped concentration on '{old}'")
            holder["concentration"] = spell
            if caster and not any(e["name"].lower() == spell.lower() for e in holder["effects"]):
                # The caster carries the spell's clock (no modifier), so it ends for everyone together.
                holder["effects"].append({"name": spell, "concentration": True, "holding": True, **dur})
            if old is None or old.lower() != spell.lower():
                _send_announce(f"{holder['name']} — concentrating on {spell}")

        # Replace any existing effect with same name
        ent["effects"] = [e for e in ent["effects"] if e["name"].lower() != spell.lower()]
        ent["effects"].append(effect)

        rem = _fmt_effect(effect)
        conc_tag = " [conc]" if is_conc else ""
        print(f"  + {entity_name}: {spell}{conc_tag} · {rem}{_fmt_modifier(effect)}")
        _save(campaign, state)

    elif action == "end":
        if not spell:
            print("  error: effect end requires <entity> <spell>")
            return
        before = len(ent["effects"])
        removed = [e for e in ent["effects"] if e["name"].lower() == spell.lower()]
        ent["effects"] = [e for e in ent["effects"] if e["name"].lower() != spell.lower()]
        if not removed:
            print(f"  ({entity_name} has no active effect '{spell}')")
            _save(campaign, state)
            return
        was_conc = any(e.get("concentration") for e in removed)
        if was_conc and (ent.get("concentration") or "").lower() == spell.lower():
            drop_concentration(state, ent)
            _send_announce(f"{entity_name} — concentration on {spell} ends")
            print(f"  - {entity_name}: {spell} ends (concentration broken, on every target)")
        else:
            _send_announce(f"{entity_name} — {spell} ends")
            print(f"  - {entity_name}: {spell} ends")
        _save(campaign, state)

    elif action == "tick":
        # One round passes for this entity: six seconds of in-game time, so a
        # round-counted effect loses a round and a minute effect 0.1 minute.
        me = entity_name.strip().lower()
        held = [e for e in ent["effects"] if e.get("until") and e["until"].lower() != me]
        ent["effects"] = [e for e in ent["effects"] if e not in held]
        all_expired = _run_down(ent, MINUTES_PER_ROUND)
        ent["effects"] += held
        kept = ent["effects"]
        values = ent.get("values", {})
        expired_conditions = []
        for cond, entry in values.items():
            if entry["decay"]:
                entry["value"] -= 1
                if entry["value"] == 0:
                    expired_conditions.append(cond)
        for cond in expired_conditions:
            del values[cond]
            ent["conditions"].remove(cond)
            print(f"  - {entity_name}: {cond} removed")
        if expired_conditions:
            _push_conditions(entity_name, ent["conditions"])

        # Effects other creatures carry that last until THIS entity's turn.
        for key, other in state.items():
            if key.startswith("_") or not isinstance(other, dict) or other is ent:
                continue
            mine = [e for e in other.get("effects", []) if (e.get("until") or "").lower() == me]
            if not mine:
                continue
            rest = [e for e in other["effects"] if e not in mine]
            other["effects"] = mine
            gone = _run_down(other, MINUTES_PER_ROUND)
            other["effects"] += rest
            if gone:
                _report_expired(other, gone, state)

        if not all_expired and not kept:
            # Nothing to report
            _save(campaign, state)
            return

        # Print tick summary
        if kept:
            lines = [f"⧗ {e['name']} · {_fmt_effect(e)}" for e in kept]
            print(f"  {entity_name} — effects: {', '.join(lines)}")

        _report_expired(ent, all_expired, state)
        _save(campaign, state)

    else:
        print(f"  error: unknown effect action '{action}' — use start / end / tick / advance")


def cmd_condition(campaign: str, entity_name: str, action: str, condition: str = "",
                  value: int | None = None, decay: bool = False, penalty_on: tuple = ()) -> None:
    state = _load(campaign)
    ent   = _entity(state, entity_name)
    conds = ent["conditions"]

    if action == "add" and condition.lower() in ("exhausted", "exhaustion"):
        # Exhaustion stacks in levels (6 is death), unlike every other
        # condition, so adding it again is another level rather than a no-op.
        ent["exhaustion"] = min(6, ent.get("exhaustion", 0) + 1)
        if "exhausted" not in conds:
            conds.append("exhausted")
            _push_conditions(entity_name, conds)
        _send_announce(f"{entity_name} → Exhaustion {ent['exhaustion']}")
        print(f"  + {entity_name}: exhaustion level {ent['exhaustion']}")
        if ent["exhaustion"] >= 6:
            print(f"  ✗ {entity_name}: exhaustion 6 — the character dies")

    elif action == "remove" and condition.lower() in ("exhausted", "exhaustion"):
        if ent.get("exhaustion", 0) <= 0:
            print(f"  ({entity_name} is not exhausted)")
        else:
            ent["exhaustion"] -= 1
            if ent["exhaustion"] == 0 and "exhausted" in conds:
                conds.remove("exhausted")
                _push_conditions(entity_name, conds)
            print(f"  - {entity_name}: exhaustion level {ent['exhaustion']}")

    elif action == "add":
        cond = condition.lower()
        if value is not None:
            entry = ent.setdefault("values", {}).setdefault(
                cond, {"value": value, "decay": False, "penalty_on": []})
            entry["value"] = max(entry["value"], value)
            entry["decay"] = entry["decay"] or decay
            entry["penalty_on"] = list(dict.fromkeys([*entry["penalty_on"], *penalty_on]))
        if cond not in conds:
            conds.append(cond)
            _push_conditions(entity_name, conds)
            _send_announce(f"{entity_name} → {cond.capitalize()}")
            print(f"  + {entity_name}: {cond}")
            if cond in ENDS_CONCENTRATION:
                spell = drop_concentration(state, ent)
                if spell:
                    _send_announce(f"{entity_name} — concentration on {spell} ends")
                    print(f"  - {entity_name}: concentration on {spell} ends ({cond})")
        else:
            print(f"  (already has {cond})")

    elif action == "remove":
        cond = condition.lower()
        ent.get("values", {}).pop(cond, None)
        if cond in conds:
            conds.remove(cond)
            _push_conditions(entity_name, conds)
            _send_announce(f"{entity_name} — {cond.capitalize()} ends")
            print(f"  - {entity_name}: {cond} removed")
        else:
            print(f"  ({entity_name} does not have {cond})")

    elif action == "clear":
        if conds:
            _send_announce(f"{entity_name} — all conditions cleared")
        conds.clear()
        ent.pop("values", None)
        ent["exhaustion"] = 0
        _push_conditions(entity_name, [])
        print(f"  {entity_name}: conditions cleared")

    ent["conditions"] = conds
    _save(campaign, state)


def cmd_concentrate(campaign: str, entity_name: str, spell_or_break: str) -> None:
    state = _load(campaign)
    ent   = _entity(state, entity_name)

    if spell_or_break.lower() == "break":
        old = drop_concentration(state, ent)
        if old:
            _send_announce(f"{entity_name} — concentration on {old} broken")
            print(f"  {entity_name}: concentration on '{old}' broken")
        else:
            print(f"  {entity_name}: was not concentrating")
    else:
        spell = spell_or_break
        old   = ent.get("concentration")
        if old and old.lower() != spell.lower():
            drop_concentration(state, ent)
        ent["concentration"] = spell
        if old and old != spell:
            _send_announce(f"{entity_name} — {old} ends, concentrating on {spell}")
            print(f"  {entity_name}: dropped '{old}', now concentrating on '{spell}'")
        else:
            _send_announce(f"{entity_name} — concentrating on {spell}")
            print(f"  {entity_name}: concentrating on '{spell}'")

    _save(campaign, state)


def cmd_saves(campaign: str, entity_name: str, action: str) -> None:
    state = _load(campaign)
    ent   = _entity(state, entity_name)
    saves = ent["death_saves"]

    if action == "success":
        saves["successes"] = min(3, saves["successes"] + 1)
        if saves["successes"] >= 3:
            saves["stable"] = True
            msg = f"{entity_name} is STABLE (3 successes)"
            _send_announce(f"☑ {msg}")
            print(f"  ☑ {msg}")
        else:
            print(f"  {entity_name}: {saves['successes']} success(es), {saves['failures']} failure(s)")

    elif action == "failure":
        saves["failures"] = min(3, saves["failures"] + 1)
        if saves["failures"] >= 3:
            msg = f"{entity_name} — 3 FAILURES: character is DEAD"
            _send_announce(f"✗ {msg}")
            print(f"  ✗ {msg}")
        else:
            print(f"  {entity_name}: {saves['successes']} success(es), {saves['failures']} failure(s)")

    elif action == "stable":
        saves["stable"] = True
        _send_announce(f"{entity_name} stabilised")
        print(f"  {entity_name}: marked stable")

    elif action == "reset":
        saves.update({"successes": 0, "failures": 0, "stable": False})
        print(f"  {entity_name}: death saves reset (regained consciousness)")

    ent["death_saves"] = saves
    _save(campaign, state)


def cmd_status(campaign: str, filter_name: str = "") -> None:
    state = _load(campaign)
    entities = [v for k, v in state.items() if not k.startswith("_") and isinstance(v, dict)]
    if not entities:
        print("  (no tracked entities)")
        return

    if filter_name:
        entities = [e for e in entities if filter_name.lower() in e["name"].lower()]

    for ent in entities:
        name   = ent["name"]
        conds  = ent.get("conditions", [])
        conc   = ent.get("concentration")
        saves  = ent.get("death_saves", {})

        effects = ent.get("effects", [])
        parts = []
        if conds:
            lvl = ent.get("exhaustion", 0)
            values = ent.get("values", {})
            labels = []
            for cond in conds:
                if cond == "exhausted" and lvl:
                    labels.append(f"Exhausted (level {lvl})")
                elif cond in values:
                    labels.append(f"{cond} {values[cond]['value']}")
                else:
                    labels.append(cond.capitalize())
            parts.append("Conditions: " + ", ".join(labels))
        if conc:
            parts.append(f"Concentrating: {conc}")
        if effects:
            eff_strs = []
            for e in effects:
                rem = _fmt_effect(e)
                tag = " [conc]" if e.get("concentration") else ""
                eff_strs.append(f"{e['name']}{tag} · {rem}{_fmt_modifier(e)}")
            parts.append("Effects: " + ", ".join(eff_strs))
        s = saves.get("successes", 0)
        f = saves.get("failures", 0)
        if s or f:
            stable = " (stable)" if saves.get("stable") else ""
            parts.append(f"Death saves: {s}✓ {f}✗{stable}")

        if parts:
            status = " DEAD" if _is_dead(ent) else (" unconscious" if "unconscious" in conds else "")
            print(f"  {name}:{status}")
            for p in parts:
                print(f"    {p}")
        else:
            print(f"  {name}: clean")


MAX_CHECK_DC = 30  # D&D 5e "Nearly Impossible" ceiling (DiceFrame rules-and-dice guard)


def cmd_check(
    campaign: str,
    action: str,
    entity: str = "",
    skill: str = "",
    dc: "int | None" = None,
    result: str = "",
) -> None:
    """Per-round check deduplication & DC ceiling guard."""
    state = _load(campaign)
    checks: list = state.setdefault("_round_checks", [])

    if action == "reset":
        count = len(checks)
        state["_round_checks"] = []
        _save(campaign, state)
        print(f"  Reset round check log ({count} cleared).")
        return

    if action == "list":
        if not checks:
            print("  (no checks logged this round)")
            return
        for c in checks:
            dc_s = f" DC {c['dc']}" if c.get("dc") is not None else ""
            res_s = f" → {c['result']}" if c.get("result") else ""
            print(f"  {c['entity']} — {c['skill']}{dc_s}{res_s}")
        return

    key_ent = entity.strip().lower()
    key_skl = skill.strip().lower()
    existing = [
        c for c in checks
        if c.get("entity", "").lower() == key_ent and c.get("skill", "").lower() == key_skl
    ]

    if action == "seen":
        if existing:
            c = existing[-1]
            print(f"  DUPLICATE: {c['entity']} already rolled {c['skill']} this round → {c.get('result', '?')}")
            sys.exit(1)
        print(f"  OK: {entity} has not rolled {skill} this round.")
        return

    if action == "log":
        if dc is not None and dc > MAX_CHECK_DC:
            print(f"  ⚠ DC {dc} exceeds 5e ceiling ({MAX_CHECK_DC}); clamping advisory.", file=sys.stderr)
        if existing:
            print(f"  ⚠ Duplicate check in same round: {entity} — {skill} (previous: {existing[-1].get('result', '?')})", file=sys.stderr)
        checks.append({
            "entity": entity.strip(),
            "skill": skill.strip(),
            "dc": dc,
            "result": result.strip(),
            "at": datetime.now(timezone.utc).isoformat(),
        })
        _save(campaign, state)
        dc_s = f" (DC {dc})" if dc is not None else ""
        res_s = f" → {result}" if result else ""
        print(f"  Logged check: {entity} — {skill}{dc_s}{res_s}")


ENEMY_ROLES = ("brute", "skirmisher", "ranged", "caster", "support")

#: Morale and Instinct (idea from Worlds Without Number, our own numbers).
#: Morale 2–12: roll 2d6 (+ situation), above the score = the creature breaks.
#: Instinct 0–10: roll d10, at or under the score = it acts on instinct this round.
DEFAULT_MORALE, DEFAULT_INSTINCT = 8, 3
GENERIC_INSTINCTS = {
    "brute":      ["charges whoever hurt it last, ignoring better targets",
                   "stands and bellows instead of pressing its advantage",
                   "goes for the biggest, most armoured foe"],
    "skirmisher": ["grabs something valuable and bolts",
                   "chases a fleeing or badly wounded target",
                   "breaks off to circle around and loses its turn"],
    "ranged":     ["shoots at whatever moved last, even a poor target",
                   "falls back to find a better angle",
                   "pours everything into one foe"],
    "caster":     ["throws its strongest power at once, even where it is wasted",
                   "shields itself and backs away",
                   "turns on whoever disrupted it"],
    "support":    ["rushes to a fallen ally",
                   "calls for help instead of fighting",
                   "throws itself in front of its leader"],
}


def _kit_monster(campaign: str, name: str) -> "dict | None":
    """The World Kit monster record, or None (missing kit, unknown name or a broken kit)."""
    try:
        import worldkit
        kit = worldkit.load(campaign)
        return worldkit.find(kit, "monsters", name) if kit else None
    except (OSError, ValueError, SystemExit):
        return None


def cmd_enemy(
    campaign: str,
    action: str,
    entity: str,
    role: "str | None" = None,
    slots_spec: str = "",
    recharge_spec: str = "",
    morale: "int | None" = None,
    spend_slot: "int | None" = None,
    ability: str = "",
    hp_pct: int = 100,
    distance_ft: int = 30,
    morale_score: "int | None" = None,
    instinct: "int | None" = None,
    instincts: str = "",
    kit_name: str = "",
    roll: "int | None" = None,
    mod: int = 0,
) -> None:
    """Role-aware enemy tactics, monster spell-slot / recharge tracker, morale and instinct."""
    state = _load(campaign)
    ent = _entity(state, entity)
    prof = ent.setdefault("enemy_profile", {
        "role": "brute",
        "slots": {},        # {"1": {"max": 2, "used": 0}}
        "recharges": {},    # {"Fire Breath": {"min": 5, "ready": True}}
        "morale_pct": 25,
    })

    if action == "set":
        # Only what was passed changes, so a later `set --slots …` keeps the rest.
        if kit_name:
            rec = _kit_monster(campaign, kit_name)
            if rec is None:
                print(f"  ERROR: no World Kit monster {kit_name!r} (or the kit has errors).", file=sys.stderr)
                sys.exit(1)
            if rec.get("role") in ENEMY_ROLES and role is None:
                prof["role"] = rec["role"]
            for key in ("morale", "instinct"):
                if key in rec:
                    prof["morale_score" if key == "morale" else "instinct"] = rec[key]
            if rec.get("instincts"):
                prof["instincts"] = list(rec["instincts"])
        if role is not None:
            prof["role"] = role
        if morale is not None:
            prof["morale_pct"] = max(0, min(100, int(morale)))
        if morale_score is not None:
            prof["morale_score"] = morale_score
        if instinct is not None:
            prof["instinct"] = instinct
        if instincts:
            prof["instincts"] = [x.strip() for x in instincts.split(";") if x.strip()]
        if slots_spec:
            slots = {}
            for part in slots_spec.split(","):
                if ":" in part:
                    lvl_s, cnt_s = part.split(":", 1)
                    lvl_k = lvl_s.strip()
                    cnt = int(cnt_s.strip())
                    slots[lvl_k] = {"max": cnt, "used": 0}
            prof["slots"] = slots
        if recharge_spec:
            rechs = {}
            for part in recharge_spec.split(","):
                if ":" in part:
                    ab, rng_s = part.split(":", 1)
                    min_roll = int(rng_s.strip().split("-")[0])
                    rechs[ab.strip()] = {"min": min_roll, "ready": True}
            prof["recharges"] = rechs
        _save(campaign, state)
        slot_note = f"slots={len(prof['slots'])} tier(s), " if prof["slots"] else ""
        nerve = (f"morale {prof['morale_score']}" if "morale_score" in prof else f"morale {DEFAULT_MORALE} (default)")
        nerve += f", instinct {prof.get('instinct', DEFAULT_INSTINCT)}"
        print(f"  Enemy profile set: {ent['name']} [role={prof['role']}, check morale at <={prof['morale_pct']}% HP, "
              f"{nerve}, {slot_note}recharges={list(prof['recharges'].keys())}]")
        return

    if action == "morale":
        score = prof.get("morale_score", DEFAULT_MORALE)
        label = "" if "morale_score" in prof else " (default)"
        if score >= 12:
            print(f"  {ent['name']} — morale {score}{label}: never breaks; it fights to the end.")
            return
        dice = [random.randint(1, 6), random.randint(1, 6)] if roll is None else None
        raw = sum(dice) if dice else roll
        total = raw + mod
        shown = f"2d6 {dice[0]}+{dice[1]}" if dice else f"2d6 {raw}"
        if mod:
            shown += f" {mod:+d}"
        if total > score:
            print(f"  {ent['name']} — {shown} = {total} vs morale {score}{label} → BREAKS: it flees, "
                  f"surrenders or begs to parley (pick what fits the creature).")
        else:
            print(f"  {ent['name']} — {shown} = {total} vs morale {score}{label} → HOLDS: it keeps fighting.")
        return

    if action == "instinct":
        score = prof.get("instinct", DEFAULT_INSTINCT)
        label = "" if "instinct" in prof else " (default)"
        raw = random.randint(1, 10) if roll is None else roll
        if raw <= score:
            pool = prof.get("instincts") or GENERIC_INSTINCTS.get(prof.get("role", "brute"), GENERIC_INSTINCTS["brute"])
            print(f"  {ent['name']} — d10 {raw} vs instinct {score}{label} → INSTINCT this round: "
                  f"{random.choice(pool)}.")
        else:
            print(f"  {ent['name']} — d10 {raw} vs instinct {score}{label} → acts with its full cunning "
                  f"(see `enemy advise`).")
        return

    if action == "spend":
        if spend_slot is not None:
            lk = str(spend_slot)
            if lk not in prof["slots"]:
                print(f"  ERROR: {ent['name']} has no level-{lk} spell slots.", file=sys.stderr)
                sys.exit(1)
            sl = prof["slots"][lk]
            if sl["used"] >= sl["max"]:
                print(f"  ERROR: {ent['name']} is out of level-{lk} slots ({sl['used']}/{sl['max']}).", file=sys.stderr)
                sys.exit(1)
            sl["used"] += 1
            _save(campaign, state)
            print(f"  {ent['name']} spent L{lk} slot ({sl['max'] - sl['used']}/{sl['max']} remaining).")
            return
        if ability:
            match_k = next((k for k in prof["recharges"] if k.lower() == ability.lower()), None)
            if not match_k:
                print(f"  ERROR: Ability '{ability}' not tracked for {ent['name']}.", file=sys.stderr)
                sys.exit(1)
            prof["recharges"][match_k]["ready"] = False
            _save(campaign, state)
            print(f"  {ent['name']} used '{match_k}' (now recharging on {prof['recharges'][match_k]['min']}-6).")
            return
        print("  Specify --slot <N> or --ability <NAME>.", file=sys.stderr)
        sys.exit(2)

    if action == "recharge":
        if not prof["recharges"]:
            print(f"  {ent['name']} has no recharge abilities.")
            return
        for ab, info in prof["recharges"].items():
            if ability and ab.lower() != ability.lower():
                continue
            if info.get("ready"):
                print(f"  {ent['name']} — {ab}: already READY.")
                continue
            roll = random.randint(1, 6)
            if roll >= int(info["min"]):
                info["ready"] = True
                print(f"  {ent['name']} — {ab}: d6 = {roll} (needs {info['min']}+) → RECHARGED!")
            else:
                print(f"  {ent['name']} — {ab}: d6 = {roll} (needs {info['min']}+) → still recharging.")
        _save(campaign, state)
        return

    if action == "advise":
        r = prof.get("role", "brute")
        conc = ent.get("concentration")
        slots_left = {k: v["max"] - v["used"] for k, v in prof.get("slots", {}).items() if v["max"] > v["used"]}
        ready_rechs = [k for k, v in prof.get("recharges", {}).items() if v.get("ready")]
        tips = []
        if prof.get("morale_score", DEFAULT_MORALE) >= 12:
            tips.append("FIGHTS TO THE END: morale 12, it never breaks or surrenders.")
        elif hp_pct <= prof.get("morale_pct", 25):
            tips.append(f"MORALE CHECK due: run `tracker.py enemy morale \"{ent['name']}\"`; on BREAKS it flees, "
                        "surrenders or parleys instead of fighting to 0 HP.")
        down = []
        for k, e in state.items():
            if k.startswith("_") or not isinstance(e, dict) or e.get("enemy_profile") or _is_dead(e):
                continue
            s = e.get("death_saves", {})
            if s.get("stable") or s.get("successes") or s.get("failures") or _sheet_hp(campaign, e["name"]) == 0:
                down.append(e["name"])
        if down:
            tips.append(f"DOWN AT 0 HP: {', '.join(down)} — out of the fight. Go for someone still standing; strike a "
                        "dying character only when its nature or orders demand it (a predator, a grudge, 'kill that "
                        "one'), and say so in the narration.")
        if conc:
            tips.append(f"CONCENTRATING on '{conc}': avoid casting another concentration spell; protect position / stay behind cover.")
        if ready_rechs:
            tips.append(f"RECHARGE READY ({', '.join(ready_rechs)}): prioritize lining up high-value target(s).")
        if r == "caster":
            if distance_ft <= 5:
                tips.append("CASTER IN MELEE: evaluate Disengage / Misty Step / defensive spell before casting ranged attacks at disadvantage.")
            elif slots_left:
                tips.append(f"CASTER AT RANGE ({distance_ft} ft): stay behind frontline; cast control/AoE using slots {slots_left}.")
            else:
                tips.append("CASTER OUT OF SLOTS: use ranged cantrips from cover — do NOT invent extra slots or charge into weak melee.")
        elif r == "support":
            tips.append("SUPPORT: check if a wounded frontline ally needs healing/buff more than dealing minor damage; stay protected.")
        elif r == "ranged":
            if distance_ft <= 5:
                tips.append("RANGED IN MELEE: disengage to regain firing lane or switch to backup melee weapon.")
            else:
                tips.append(f"RANGED ({distance_ft} ft): maintain distance, use partial cover, focus exposed casters/unarmored PCs.")
        elif r == "skirmisher":
            tips.append("SKIRMISHER: flank isolated targets, hit-and-run using mobility/stealth, avoid trading blows with heavy tanks.")
        else:
            tips.append("BRUTE: hold chokepoints, screen allied ranged and support creatures, pressure closest melee threat.")
        print(f"  Tactical Advisory — {ent['name']} [{r.upper()}, HP {hp_pct}%, dist {distance_ft}ft]:")
        for t in tips:
            print(f"    • {t}")
def _is_dead(ent: dict) -> bool:
    return ent.get("death_saves", {}).get("failures", 0) >= 3 or ent.get("exhaustion", 0) >= 6


def _sheet_hp(campaign: str, name: str):
    """Current HP from the character sheet, or None when there is no sheet."""
    try:
        from paths import find_character_file
        text = find_character_file(campaign, name).read_text(encoding="utf-8")
    except (OSError, ValueError, FileNotFoundError):
        return None
    m = re.search(r"\*\*HP:\*\*\s*(\d+)\s*/", text)
    return int(m.group(1)) if m else None


def _is_down(ent: dict, campaign: str | None = None) -> bool:
    """At 0 HP: dying, stable, unconscious — or a character sheet that reads 0 HP."""
    s = ent.get("death_saves", {})
    return bool(_is_dead(ent) or s.get("stable") or s.get("successes", 0) or s.get("failures", 0)
                or "unconscious" in ent.get("conditions", [])
                or (campaign and _sheet_hp(campaign, ent["name"]) == 0))


def cmd_clear(campaign: str, clear_all: bool = False) -> None:
    """End of encounter.

    This used to set effects=[] and drop every condition, and the rest
    procedures ran it too -- so a one-hour short rest deleted an eight-hour
    Mage Armor, and a long rest cleared exhaustion outright. It now ends what
    the encounter owned: conditions other than LASTING_CONDITIONS, effects
    counted in rounds, and concentration that no surviving effect holds.
    """
    state = _load(campaign)
    ent_count = 0
    for k, ent in list(state.items()):
        if k.startswith("_") or not isinstance(ent, dict):
            continue
        if "enemy_profile" in ent:
            del state[k]
            ent_count += 1
            continue
        _entity(state, ent["name"])
        saves = ent.get("death_saves", {})
        dying = (any(saves.get(k) for k in ("successes", "failures", "stable"))
                 or _sheet_hp(campaign, ent["name"]) == 0)   # at 0 HP before any death save
        ent["conditions"] = [c for c in ent["conditions"]
                             if c in LASTING_CONDITIONS or (c == "unconscious" and dying)]
        ent.pop("values", None)
        ent["effects"] = [e for e in ent["effects"] if e.get("duration_type") != "rounds"]
        held = {e["name"].lower() for e in ent["effects"] if e.get("concentration")}
        if (ent.get("concentration") or "").lower() not in held:
            ent["concentration"] = None
        _push_conditions(ent["name"], ent["conditions"])
        if clear_all and not (dying and "unconscious" in ent["conditions"]) and not _is_dead(ent):
            # A dead character's three failures are not encounter state.
            ent["death_saves"] = {"successes": 0, "failures": 0, "stable": False}
        ent_count += 1
    state["_round_checks"] = []
    _save(campaign, state)
    scope = "encounter state and death saves" if clear_all else "encounter state"
    print(f"  Cleared {scope} for {ent_count} entities "
          f"(minute/hour effects, exhaustion and petrification kept).")


REST_MINUTES = {"short": 60, "long": 480}


def cmd_rest(campaign: str, rest_type: str, advance_time: bool = True) -> None:
    """Rest bookkeeping for tracked entities. Time passes; nothing is wiped.

    Short: one hour passes. Long: eight hours pass, concentration ends
    (sleeping is unconsciousness), and exhaustion drops one level -- except
    for a creature at 0 HP, which gains no benefit from a long rest until it
    has at least 1 hit point.
    """
    if advance_time:
        advance(campaign, REST_MINUTES[rest_type])
    if rest_type != "long":
        print("  Short rest: 1 hour passed; effects kept running.")
        return
    state = _load(campaign)
    for k, ent in state.items():
        if k.startswith("_") or not isinstance(ent, dict):
            continue
        _entity(state, ent["name"])
        name = ent["name"]
        spell = drop_concentration(state, ent)
        if spell:
            print(f"  {name}: concentration on {spell} ends")
        if _is_dead(ent):
            continue
        if _is_down(ent, campaign):
            print(f"  {name}: at 0 HP — no long-rest benefit until they have at least 1 HP")
            continue
        if ent.get("exhaustion", 0) > 0:
            ent["exhaustion"] -= 1
            if ent["exhaustion"] == 0 and "exhausted" in ent["conditions"]:
                ent["conditions"].remove("exhausted")
                _push_conditions(name, ent["conditions"])
            print(f"  {name}: exhaustion {ent['exhaustion'] + 1} → {ent['exhaustion']}")
    _save(campaign, state)
    print("  Long rest: 8 hours passed.")


# ─── Main ────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(description="Session condition/death-save tracker.")
    p.add_argument("-c", "--campaign", required=True, metavar="NAME",
                   help="Campaign name (matches ~/.dne/campaigns/<name>/)")
    sub = p.add_subparsers(dest="cmd")

    # effect
    eff = sub.add_parser("effect", help="Track timed effects (rounds/minutes/hours/indefinite)")
    eff.add_argument("action", choices=["start", "end", "tick", "advance"])
    eff.add_argument("entity", help="Entity name, or the time for `advance` (90 / 90m / 8h / 10r)")
    eff.add_argument("spell", nargs="?", default="",
                     help="Spell or ability name")
    eff.add_argument("duration", nargs="?", default="",
                     help="Duration: 10r / 60m / 8h / indef")
    eff.add_argument("conc", nargs="?", default="",
                     help="Pass 'conc' to mark as concentration")
    eff.add_argument("--mod", default="",
                     help="Typed modifier the effect grants, e.g. +1d4 (Bless) or -1d4 (Bane)")
    eff.add_argument("--on", default="",
                     help=f"Roll types the modifier applies to: {', '.join(MODIFIER_TARGETS)}")
    eff.add_argument("--caster", default="",
                     help="Who holds the concentration (Bless on an ally: the cleric). When the caster's "
                          "concentration ends, the effect ends on every target")
    eff.add_argument("--until", default="",
                     help="Count the effect down on this creature's turn instead (e.g. the caster's, "
                          "for 'until the start of your next turn' effects placed on a target)")

    # rest
    rst = sub.add_parser("rest", help="Advance in-game time for a rest and apply its bookkeeping")
    rst.add_argument("type", choices=["short", "long"])

    # condition
    cond = sub.add_parser("condition", help="Add/remove/clear conditions")
    cond.add_argument("action", choices=["add", "remove", "clear"])
    cond.add_argument("entity")
    cond.add_argument("condition", nargs="?", default="")
    cond.add_argument("value", nargs="?", type=int, help="Positive condition value for add")
    cond.add_argument("--decay", action="store_true", help="Reduce value at the start of each turn")
    cond.add_argument("--penalty", help="Penalized rolls, comma-separated: attack,save,check")

    # concentrate
    conc = sub.add_parser("concentrate", help="Track spell concentration")
    conc.add_argument("entity")
    conc.add_argument("spell", help="Spell name, or 'break' to end concentration")

    # saves
    sav = sub.add_parser("saves", help="Track death saving throws")
    sav.add_argument("entity")
    sav.add_argument("action", choices=["success", "failure", "stable", "reset"])

    # check (per-round deduplication + DC ceiling)
    chk = sub.add_parser("check", help="Per-round check deduplication & DC guard")
    chk.add_argument("action", choices=["log", "seen", "list", "reset"])
    chk.add_argument("entity", nargs="?", default="")
    chk.add_argument("skill", nargs="?", default="")
    chk.add_argument("--dc", type=int, default=None)
    chk.add_argument("--result", default="")

    # enemy (role-aware tactics + spell/recharge resource tracker)
    enm = sub.add_parser("enemy", help="Enemy tactical role, spell slots, recharge & advisory")
    enm.add_argument("action", choices=["set", "spend", "recharge", "advise", "morale", "instinct"])
    enm.add_argument("entity")
    enm.add_argument("--role", choices=ENEMY_ROLES, default=None)
    enm.add_argument("--slots", default="", help='Spell slots e.g. "1:3,2:2"')
    enm.add_argument("--recharge", default="", help='Recharge abilities e.g. "Fire Breath:5-6"')
    enm.add_argument("--morale", type=int, default=None, help="HP%% at which a morale check is due (default 25)")
    enm.add_argument("--morale-score", type=int, default=None, help="2–12; 2d6 above it = breaks (12 = never)")
    enm.add_argument("--instinct", type=int, default=None, help="0–10; d10 at or under it = acts on instinct")
    enm.add_argument("--instincts", default="", help='its own instincts, ";"-separated')
    enm.add_argument("--kit", default="", help="take role/morale/instinct from this World Kit monster")
    enm.add_argument("--roll", type=int, default=None, help="a supplied roll (2d6 total for morale, d10 for instinct)")
    enm.add_argument("--mod", type=int, default=0, help="situation modifier added to the morale roll")
    enm.add_argument("--slot", type=int, default=None, help="Spell slot level to spend")
    enm.add_argument("--ability", default="", help="Recharge ability name")
    enm.add_argument("--hp-pct", type=int, default=100, help="Current HP percentage for advise")
    enm.add_argument("--distance-ft", type=int, default=30, help="Distance to nearest PC in feet")

    # status
    stat = sub.add_parser("status", help="Show current tracking state")
    stat.add_argument("entity", nargs="?", default="")

    # clear
    clr = sub.add_parser("clear", help="Clear encounter state")
    clr.add_argument("--all", action="store_true",
                     help="Also reset death saves (never a dead character's)")

    args = p.parse_args()
    if args.cmd in ("rest", "concentrate", "saves", "check", "enemy"):
        from paths import refuse_unless_d20
        refuse_unless_d20(["-c", args.campaign], f"tracker.py {args.cmd}")

    if args.cmd == "effect":
        cmd_effect(args.campaign, args.action, args.entity,
                   spell=args.spell, duration=args.duration,
                   is_conc=(args.conc.lower() == "conc"),
                   mod=args.mod, on=args.on, until=args.until, caster=args.caster)
    elif args.cmd == "rest":
        cmd_rest(args.campaign, args.type)
    elif args.cmd == "condition":
        penalty_on = tuple(t.strip().lower() for t in args.penalty.split(",")) if args.penalty is not None else ()
        if args.value is None and (args.decay or penalty_on):
            cond.error("--decay and --penalty require a condition value")
        if args.value is not None and (
            args.value < 1 or args.action != "add" or args.condition.lower() in ("exhausted", "exhaustion")
        ):
            cond.error("use a positive value with condition add for conditions other than exhaustion")
        if any(t not in CONDITION_PENALTY_TARGETS for t in penalty_on):
            cond.error("--penalty accepts attack,save,check")
        cmd_condition(args.campaign, args.entity, args.action, args.condition,
                      args.value, args.decay, penalty_on)
    elif args.cmd == "concentrate":
        cmd_concentrate(args.campaign, args.entity, args.spell)
    elif args.cmd == "saves":
        cmd_saves(args.campaign, args.entity, args.action)
    elif args.cmd == "check":
        cmd_check(args.campaign, args.action, args.entity, args.skill, dc=args.dc, result=args.result)
    elif args.cmd == "enemy":
        if args.morale_score is not None and not 2 <= args.morale_score <= 12:
            enm.error("--morale-score must be 2–12")
        if args.instinct is not None and not 0 <= args.instinct <= 10:
            enm.error("--instinct must be 0–10")
        if args.roll is not None and not (2 <= args.roll <= 12 if args.action == "morale" else 1 <= args.roll <= 10):
            enm.error("--roll must be 2–12 for morale, 1–10 for instinct")
        cmd_enemy(
            args.campaign, args.action, args.entity,
            role=args.role, slots_spec=args.slots, recharge_spec=args.recharge,
            morale=args.morale, spend_slot=args.slot, ability=args.ability,
            hp_pct=args.hp_pct, distance_ft=args.distance_ft,
            morale_score=args.morale_score, instinct=args.instinct, instincts=args.instincts,
            kit_name=args.kit, roll=args.roll, mod=args.mod,
        )
    elif args.cmd == "status":
        cmd_status(args.campaign, args.entity)
    elif args.cmd == "clear":
        cmd_clear(args.campaign, getattr(args, "all", False))
    else:
        p.print_help()


if __name__ == "__main__":
    main()
