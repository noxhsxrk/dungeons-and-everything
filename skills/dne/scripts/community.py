#!/usr/bin/env python3
"""
community.py — a settlement that keeps itself alive day by day, with or without the party.

One record per settlement (kind `settlement`, id = the place's map key) holds the five kinds of state this
moves, and nothing else:
  resources       stores {food, water, parts}, what the people use a day, what air housing and the grow-house need
  condition       assets: condition 0–100, wear per day in use, what each provides, what a repair takes, backups
  people, skills  workers: skills, duties, who is away, who learns from whom; offices: who holds them, who is next
  work            jobs in progress: hours done, who did them, what blocks them
  agreements      pacts with the neighbour, a rota once one is set, standing orders such as a parts buffer
A day (`community_day`, one event a day, no dice) goes: harvest, who holds each office, rounds (what the workers
*see* of each machine), wear and failures, requests from what they saw, the council's rulings, repairs, air,
water and food, the pact's own rhythm. Ordinary days write nothing. Every notable change writes one chronicle
row (kind `chronicle`, id "<place>|<day>"): who did it, why they could, what it left. The GM narrates from
those rows; Python moves the state.

Who does a job: someone with the skill it asks at full speed; else someone one level below at half speed,
chosen as the one whose own work matters least (that work goes undone that day, on record). An office goes to
the first person in its line who is present; with nobody, what needs it waits. A worker is away when marked so,
or when `routine.py` puts them elsewhere (an appointment, a schedule block, their last known place); `where`
answers for a worker routine knows nothing about with their settlement. The council rules by its
written rules unless the GM has ruled on that matter (`community_decide`); when the party is there it stops
the clock once to let them weigh in.

Engine actions:
  {"action": "settlement", "at": "The Ford", "template": "hollow-9"}          (start one from a template)
  {"action": "settlement", "at": "The Ford", "workers": {"Jonas": {"away": true}}, "stores": {"parts": 4}}
  {"action": "community", "at": "The Ford", "since_day": 1}                    (report + chronicle)
  {"action": "community_decide", "at": "The Ford", "matter": "service:filter-main", "decision": "approve",
   "why": "the party offered to air the grow-house by hand"}
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gm_guide  # noqa: E402
import scheduler  # noqa: E402
import trade  # noqa: E402
import turn  # noqa: E402
import routine  # noqa: E402  (after turn: its engine modules load in order)
import world_db as wdb  # noqa: E402

sys.modules.setdefault("community", sys.modules[__name__])

TEMPLATES = HERE.parent / "templates"
HOURS = 8                 # a worker's day
#: What leaving a duty for a day costs the settlement: the lower, the sooner that worker is pulled off it.
DUTY_WEIGHT = {"repair": 0, "rounds": 1, "market": 3, "haul": 5, "council": 6, "care": 7, "grow": 8, "pump": 9}


def _key(world, ref: str) -> str:
    """The place's map key; a world with no map yet keys the settlement by its name."""
    if not (world.json("world-map.json", {}) or {}).get("places") and ref.strip():
        return ref.strip().casefold()
    (key,) = trade._keys(world, [ref])
    return key


def _here(s: dict, name: str) -> bool:
    w = s["workers"].get(name)
    return w is not None and not w.get("away") and not w.get("elsewhere")


def _acting(s: dict, office: str) -> "str | None":
    return next((n for n in s["offices"][office].get("succession", []) if _here(s, n)), None)


def _in_use(s: dict, aid: str) -> bool:
    a = s["assets"][aid]
    if a.get("status") != "running":
        return False
    main = a.get("backup_of")
    return not main or s["assets"].get(main, {}).get("status") != "running"


def _merge(into: dict, patch: dict) -> dict:
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(into.get(k), dict):
            _merge(into[k], v)
        else:
            into[k] = v
    return into


class Day:
    """One day of one settlement: the record, the day number, and the chronicle rows it writes."""

    def __init__(self, s: dict, d: int, party_here: bool):
        self.s, self.d, self.party_here = s, d, party_here
        self.rows: list = []
        self.hours: dict = {}           # worker -> hours already spent today
        self.left_undone: dict = {}     # worker -> duties they could not do today
        self.interrupts: list = []

    def note(self, who: str, did: str, why: str, left: str = "", lasting: bool = False) -> None:
        self.rows.append({"day": self.d, "who": who, "did": did, "why": why, "left": left, "lasting": lasting})

    def free(self, name: str) -> int:
        return HOURS - self.hours.get(name, 0)

    def spend(self, name: str, hours: int, why: str, doing: str = "repair") -> None:
        self.hours[name] = self.hours.get(name, 0) + hours
        own = [d for d in self.s["workers"][name].get("duties", []) if d not in ("repair", "rounds", doing)]
        if own and self.free(name) < HOURS // 2 and name not in self.left_undone:
            self.left_undone[name] = own
            self.s.setdefault("backlog", {})[name] = self.s.get("backlog", {}).get(name, 0) + 1
            if self.streak(f"undone:{name}"):
                self.note(name, "left their own work undone: " + ", ".join(own), why,
                          left=f"{', '.join(own)} falls behind while this lasts")

    def streak(self, what: str) -> bool:
        """Mark `what` as happening today; True only on the first day of a run of days (the chronicle keeps that row)."""
        last = self.s.setdefault("streaks", {})
        first = last.get(what) != self.d - 1
        last[what] = self.d
        return first


# ── the steps of a day ────────────────────────────────────────────────────────

def _harvest(day: Day) -> None:
    s, g = day.s, day.s.get("grow")
    if not g or day.d < int(g.get("next_harvest", 0)):
        return
    every = int(g.get("every", 7))
    got = int(g.get("yield", 0)) * min(int(g.get("days", 0)), every) // every
    s["stores"]["food"] = int(s["stores"].get("food", 0)) + got
    grower = next((n for n, w in s["workers"].items() if "grow" in w.get("duties", [])), "the growers")
    day.note(grower, f"brought in the harvest: {got} food",
             f"{g.get('days', 0)} of {every} growing days had air and hands",
             left=f"food in store {s['stores']['food']}", lasting=got < int(g.get("yield", 0)))
    g["days"], g["next_harvest"] = 0, int(g["next_harvest"]) + every


def _offices(day: Day) -> None:
    for oid, o in day.s["offices"].items():
        now, first = _acting(day.s, oid), (o.get("succession") or [None])[0]
        if now != o.get("acting") and (now != first or o.get("acting") is not None):
            gone = [n for n in o.get("succession", []) if n != now and not _here(day.s, n)]
            day.note(now or "nobody", f"holds the {o.get('label', oid)}" if now else f"can use the {o.get('label', oid)}",
                     ("next in line; " if now else "") + (", ".join(gone) + " away" if gone else "back in place"),
                     left="" if now else "whatever needs it waits")
        o["acting"] = now


def _rounds(day: Day) -> None:
    """What the workers see: each one present updates what is known of the machines they watch."""
    for name, w in day.s["workers"].items():
        if _here(day.s, name):
            for aid in w.get("watches", []):
                if aid in day.s["assets"]:
                    day.s["assets"][aid]["known"] = day.s["assets"][aid]["condition"]


def _wear(day: Day) -> None:
    s = day.s
    for aid, a in s["assets"].items():
        if not _in_use(s, aid):
            continue
        a["condition"] = max(0, int(a["condition"]) - int(a.get("wear", 0)))
        if a["condition"] > 0:
            continue
        a["status"], a["known"] = "down", 0
        s.setdefault("disruptions", {})[aid] = s.get("disruptions", {}).get(aid, 0) + 1
        watchers = [n for n, w in s["workers"].items() if aid in w.get("watches", [])]
        seen = any(j.get("asset") == aid for j in s["jobs"].values())
        why = f"worn out ({a.get('wear')} a day)" + ("" if seen else "; nobody had seen it coming"
                                                     + (": " + ", ".join(n for n in watchers if not _here(s, n)) + " away"
                                                        if any(not _here(s, n) for n in watchers) else ""))
        backups = [b for b, x in s["assets"].items() if x.get("backup_of") == aid and x.get("status") == "running"]
        day.note(a["label"], "failed", why,
                 left=(f"the {s['assets'][backups[0]]['label']} carries the load" if backups else "nothing takes its place"))
        job = s["jobs"].setdefault(f"repair:{aid}", {"asset": aid, "opened": day.d})
        job["emergency"] = True


def _notice(day: Day) -> None:
    s = day.s
    for aid, a in s["assets"].items():
        if a.get("status") != "running" or int(a.get("known", a["condition"])) > int(a.get("notice_at", 0)) \
                or any(j.get("asset") == aid for j in s["jobs"].values()):
            continue
        who = next((n for n, w in s["workers"].items() if aid in w.get("watches", []) and _here(s, n)
                    and int(w.get("skills", {}).get("repair", 0)) >= 1), None)
        if not who:
            continue
        s["jobs"][f"repair:{aid}"] = {"asset": aid, "opened": day.d, "service": True, "noticed_by": who}
        day.note(who, f"asked to stop the {a['label']} for service",
                 f"on rounds {who} read it at {a['known']}% (repair {s['workers'][who]['skills']['repair']})",
                 left="waiting on the council")


def _ruling(day: Day, matter: str, rule_says: str, rule_why: str) -> "tuple | None":
    """(decision, who, why) for a matter today, or None while it waits."""
    s = day.s
    gm = s.get("decisions", {}).get(matter)
    if gm:
        return gm["decision"], _acting(s, "council") or "the council", "the GM's ruling" + (f": {gm['why']}" if gm.get("why") else "")
    chair = _acting(s, "council")
    if not chair:
        return None
    raised = s.setdefault("raised", {})
    if day.party_here and matter not in raised:
        raised[matter] = day.d
        day.interrupts.append(matter)
        return None
    return rule_says, chair, rule_why


def _council(day: Day) -> None:
    s, d = day.s, day.d
    for jid, job in list(s["jobs"].items()):
        if not job.get("service") or job.get("approved") or job.get("emergency"):
            continue
        a = s["assets"][job["asset"]]
        backup_air = sum(int(x.get("provides", {}).get("air", 0)) for x in s["assets"].values()
                         if x.get("backup_of") == job["asset"] and x.get("status") == "running")
        need_air = sum(int(n.get("air", 0)) for n in s["needs"].values())
        g = s.get("grow") or {}
        harvest_soon = g and int(g.get("next_harvest", 0)) - d <= 1 and "air" in a.get("provides", {})
        rules = s["offices"]["council"].get("rules", {})
        if rules.get("delay_shutdown_before_harvest") and harvest_soon and backup_air < need_air:
            says, why = "delay", (f"harvest is due on day {g['next_harvest']} and the backup gives {backup_air} air "
                                  f"of the {need_air} housing and the grow-house need")
        else:
            says, why = "approve", "nothing it serves is at stake today"
        r = _ruling(day, f"service:{job['asset']}", says, why)
        if r is None:
            if not _acting(s, "council") and job.get("waiting") != "seal":
                job["waiting"] = "seal"
                day.note("nobody", f"can rule on stopping the {a['label']}", "no one present holds the council seal",
                         left=f"the {a['label']} keeps running at {a['condition']}%")
            continue
        decision, who, why = r
        if decision == "approve":
            job["approved"] = True
            a["status"] = "service"
            day.note(who, f"approved stopping the {a['label']}", why, left=f"the {a['label']} is off for service")
        elif decision == "deny":
            del s["jobs"][jid]
            s.setdefault("decisions", {}).pop(f"service:{job['asset']}", None)
            day.note(who, f"refused to stop the {a['label']}", why, left=f"it runs on at {a['condition']}%")
        elif job.get("waiting") != "delay":
            job["waiting"] = "delay"
            day.note(who, f"delayed stopping the {a['label']}", why, left=f"it keeps running at {a['condition']}%")
    _offer(day)


def _offer(day: Day) -> None:
    s, n = day.s, day.s.get("neighbour")
    if not n or n.get("pact") or n.get("refused"):
        return
    stuck = [j for j in s["jobs"].values() if j.get("blocked") == "parts" and int(j.get("blocked_days", 0)) >= int(n.get("offers_after_days", 3))]
    if not stuck:
        return
    a = s["assets"][stuck[0]["asset"]]
    if not n.get("offered"):
        n["offered"] = day.d
        day.note(n["name"], f"offered {n['has'].get('parts', 0)} parts for {n['wants']}",
                 f"word reached them that the {a['label']} has stood {stuck[0]['blocked_days']} days for parts",
                 left="the council must answer")
    says = "approve" if s["offices"]["council"].get("rules", {}).get("accept_pact_when_down") and a.get("status") != "running" else "deny"
    r = _ruling(day, f"pact:{n['name']}", says, f"the {a['label']} is down and nobody else has parts")
    if r is None:
        return
    decision, who, why = r
    if decision != "approve":
        n["refused"] = day.d
        day.note(who, f"turned down {n['name']}'s offer", why, left="the parts must come from somewhere else", lasting=True)
        return
    got = int(n["has"].get("parts", 0))
    s["stores"]["parts"] = int(s["stores"].get("parts", 0)) + got
    n["has"]["parts"] = 0
    n["pact"] = {"since": day.d, "until": day.d + int(n.get("pact_days", 90)), "gives": n["wants"], "gets": {"parts": got}}
    s.setdefault("pacts", {})[n["name"]] = n["pact"]
    day.note(who, f"agreed a pact with {n['name']}: {n['wants']}, for {got} parts now", why,
             left=f"the pact holds until day {n['pact']['until']}", lasting=True)


def _pick(day: Day, need: int) -> "tuple | None":
    """(worker, full_speed) for a repair needing skill `need`: full skill first, then the least missed of those
    one level below; within that, whoever's own work matters least."""
    s, best = day.s, None
    for i, (name, w) in enumerate(s["workers"].items()):
        lvl = int(w.get("skills", {}).get("repair", 0))
        if not _here(s, name) or day.free(name) <= 0 or lvl < need - 1 or lvl < 1:
            continue
        cost = max([DUTY_WEIGHT.get(x, 5) for x in w.get("duties", []) if x not in ("repair", "rounds")] or [0])
        rank = (lvl < need, cost, i)
        if best is None or rank < best[0]:
            best = (rank, name, lvl >= need)
    return best and (best[1], best[2])


def _salvage(day: Day, aid: str, need: int, who: str) -> bool:
    s, a = day.s, day.s["assets"][aid]
    for did, donor in s["assets"].items():
        if donor.get("status") == "running" and int(donor.get("salvage", {}).get("parts", 0)) >= need \
                and int(donor.get("priority", 9)) > int(a.get("priority", 9)):
            donor["status"], donor["stripped"] = "down", True
            s["jobs"].setdefault(f"repair:{did}", {"asset": did, "opened": day.d})["emergency"] = True
            s["salvaged"] = s.get("salvaged", 0) + 1
            day.note(who, f"pulled {need} parts from the {donor['label']} to fix the {a['label']}",
                     f"the {a['label']} is down, the store has no parts, and it comes before the {donor['label']}",
                     left=f"the {donor['label']} is stopped", lasting=True)
            return True
    return False


def _work(day: Day) -> None:
    s = day.s
    order = sorted(s["jobs"].items(), key=lambda kv: (not kv[1].get("emergency"), int(s["assets"][kv[1]["asset"]].get("priority", 9)), kv[0]))
    for jid, job in order:
        if not (job.get("emergency") or job.get("approved")):
            continue
        a = s["assets"][job["asset"]]
        rep = a.get("repair", {})
        need, hours, parts = int(rep.get("skill", 1)), int(rep.get("hours", 4)), int(rep.get("parts", 0))
        pick = _pick(day, need)
        if not pick:
            if job.get("blocked") != "hands":
                day.note("nobody", f"could start on the {a['label']}", f"no one present has repair {need - 1} or better",
                         left=f"the {a['label']} stays {a['status']}")
            job["blocked"] = "hands"
            continue
        who, full = pick
        if not job.get("parts_in"):
            keys = _acting(s, "workshop")
            if parts and int(s["stores"].get("parts", 0)) >= parts and keys:
                s["stores"]["parts"] = int(s["stores"]["parts"]) - parts
                job["parts_in"] = f"{parts} from the store" + ("" if keys == who else f", released by {keys}")
            elif parts and job.get("emergency") and _salvage(day, job["asset"], parts, who):
                job["parts_in"] = f"{parts} pulled from another machine"
            elif parts:
                why = "the store has no parts" if keys else "no one present holds the workshop keys"
                if job.get("blocked") != "parts":
                    day.note("nobody", f"could repair the {a['label']}", why + " and nothing less vital to take them from",
                             left=f"the {a['label']} stays {a['status']}")
                job["blocked"] = "parts"
                job["blocked_days"] = int(job.get("blocked_days", 0)) + 1
                continue
        job.pop("blocked", None)
        left = hours - int(job.get("done", 0))
        spent = min(day.free(who), left if full else 2 * left)
        job["done"] = int(job.get("done", 0)) + (spent if full else spent // 2)
        job.setdefault("by", [])
        if who not in job["by"]:
            job["by"].append(who)
        first = s["offices"]["workshop"].get("succession", [None])[0]
        day.spend(who, spent, f"the {a['label']} could not wait" + ("" if _here(s, first or "") or who == first else f" and {first} is away"))
        lvl = s["workers"][who]["skills"]["repair"]
        _learn(day, who, full, spent)
        if job["done"] >= hours:
            a.update(condition=100, known=100, status="running", stripped=False, wear=rep.get("wear_after", a.get("wear", 0)))
            del s["jobs"][jid]
            s["last_repair_day"] = day.d
            day.note(who, f"repaired the {a['label']}",
                     f"repair {lvl}" + ("" if full else ", one level short, at half speed")
                     + f"; parts: {job.get('parts_in') or 'none needed'}",
                     left=f"the {a['label']} runs again")


def _learn(day: Day, who: str, full: bool, spent: int) -> None:
    """An apprentice learns beside their teacher, or by doing the work themselves when the teacher is gone."""
    for name, w in day.s["workers"].items():
        plan = w.get("learns")
        if not plan or plan.get("skill") != "repair" or not _here(day.s, name):
            continue
        if name == who or (who == plan.get("from") and full):
            plan["done"] = int(plan.get("done", 0)) + spent
            if plan["done"] >= int(plan.get("hours", 12)):
                w["skills"]["repair"] = int(w["skills"].get("repair", 0)) + 1
                how = f"{plan['done']} hours beside {plan['from']}" if name != who else f"{plan['done']} hours doing the work"
                del w["learns"]
                day.note(name, f"can now repair at level {w['skills']['repair']}", how,
                         left=f"{day.s['name']} has another mechanic", lasting=True)


def _air(day: Day) -> None:
    s = day.s
    have = sum(int(a.get("provides", {}).get("air", 0)) for aid, a in s["assets"].items() if _in_use(s, aid))
    was = s.get("aired", {})
    aired = {}
    for need, n in sorted(s["needs"].items(), key=lambda kv: int(kv[1].get("priority", 9))):
        aired[need] = have >= int(n.get("air", 0))
        if aired[need]:
            have -= int(n.get("air", 0))
        if was.get(need, True) != aired[need]:
            day.note(need, "has air again" if aired[need] else "lost its air",
                     "the machines give enough again" if aired[need] else
                     f"what still runs cannot serve it after what comes first", left="")
    s["aired"] = aired
    g = s.get("grow")
    if g and aired.get(g.get("need"), True) and any(_here(s, n) and "grow" in w.get("skills", {}) for n, w in s["workers"].items()):
        g["days"] = int(g.get("days", 0)) + 1


def _supplies(day: Day) -> None:
    s = day.s
    makes: dict = {}
    for aid, a in s["assets"].items():
        if _in_use(s, aid):
            for k, v in (a.get("makes") or {}).items():
                makes[k] = makes.get(k, 0) + int(v)
    rota = s.setdefault("rota", {})
    for res, use in s["use"].items():
        use = int(use) * int(rota[res]["pct"]) // 100 if res in rota else int(use)
        have = int(s["stores"].get(res, 0)) + makes.get(res, 0)
        plan = s.get("short", {}).get(res, {})
        if have < use and plan.get("carry"):
            for name, w in s["workers"].items():
                lvl = int(w.get("skills", {}).get("haul", 0))
                if have >= use or not lvl or not _here(s, name) or day.free(name) < HOURS // 2:
                    continue
                got = int(plan["carry"]) * lvl
                have += got
                if day.streak(f"carry:{name}"):
                    day.note(name, f"began carrying {res} from {(s.get('neighbour') or {}).get('name', 'outside')}, {got} a day",
                             f"{res} is short and {name} can haul ({lvl})",
                             left="the market gets its goods late" if "market" in w.get("duties", []) else "")
                day.spend(name, day.free(name), f"carrying {res}", doing="haul")
        if have < use and plan.get("ration_pct") and res not in rota:
            chair = _acting(s, "council") or "the people"
            rota[res] = {"since": day.d, "pct": int(plan["ration_pct"])}
            use = int(s["use"][res]) * rota[res]["pct"] // 100
            day.note(chair, f"set a {res} rota", f"{res} ran short on day {day.d}",
                     left=f"everyone draws {rota[res]['pct']}% of the old share, in turns", lasting=True)
            if plan.get("households_move") and not s.get("moved"):
                s["moved"] = int(plan["households_move"])
                day.note(f"{s['moved']} households", "moved in with relatives",
                         f"no {res} reaches the end of the pipe", left="crowded homes nearer the tanks", lasting=True)
        if have < use and day.streak(f"short:{res}"):
            day.note("everyone", f"began going without enough {res}", f"{have} for a need of {use}", left="")
        s["stores"][res] = max(0, have - use)
        for name in s["workers"]:
            if s.get("streaks", {}).get(f"carry:{name}") == day.d - 1 and res in s.get("short", {}) and plan.get("carry"):
                day.note(name, "went back to their own work", f"the {res} holds without carrying")


def _standing(day: Day) -> None:
    """Agreements and orders that keep acting after the trouble that made them."""
    s = day.s
    if s.get("salvaged") and not s.get("buffer", {}).get("parts"):
        biggest = max(int(a.get("repair", {}).get("parts", 0)) for a in s["assets"].values())
        s.setdefault("buffer", {})["parts"] = biggest
        day.note(_acting(s, "council") or "the people", f"made it a rule to keep {biggest} parts in the store",
                 "a machine was stripped to save another", left="a standing order", lasting=True)
    for name, pact in (s.get("pacts") or {}).items():
        if day.d > int(pact["until"]) or (day.d - int(pact["since"])) % 7 or day.d == int(pact["since"]):
            continue
        hauler = next((n for n, w in s["workers"].items() if "market" in w.get("duties", []) and _here(s, n)), None)
        if not hauler:
            continue
        day.hours[hauler] = HOURS
        brought = int(s.get("buffer", {}).get("parts", 0)) > int(s["stores"].get("parts", 0))
        if brought:
            s["stores"]["parts"] = int(s["stores"].get("parts", 0)) + 1
        day.note(hauler, f"ran the cart for {name}", f"the pact: {pact['gives']}",
                 left="1 part back for the store" if brought else "no market run today")


@scheduler.effect("community_day")
def _community_day(world, row, eff):
    """One day of a settlement. Queues the next."""
    key = eff["place"]
    s = world.get("settlement", key)
    if not s:
        return None
    d = int(eff.get("day", s.get("day", 0) + 1))
    day = Day(s, d, trade._sees(world, key) == "party")
    for name, w in s["workers"].items():          # an NPC whose appointment or schedule puts them elsewhere is away
        found = _routine_where(world, name)
        gone = found.get("why") != "unknown" and found.get("place") != key and (found.get("place") or found.get("between"))
        was = w.pop("elsewhere", None)
        if gone:
            w["elsewhere"] = found.get("place") or "on the road"
            if not was:
                day.note(name, f"is away: {found.get('activity') or w['elsewhere']}", found.get("why", ""),
                         left="their work here waits or passes to someone else")
    for step in (_harvest, _offices, _rounds, _wear, _notice, _council, _work, _air, _supplies, _standing):
        step(day)
    s["day"] = d
    if day.party_here:
        s["seen_day"] = d
    world.put("settlement", key, s)
    if day.rows:
        world.put("chronicle", f"{key}|{d:03d}", {"day": d, "rows": day.rows})
    scheduler.schedule(world.db, f"community-day-{key}-{d + 1}", row["due_minute"] + 1440,
                       {"type": "community_day", "place": key, "day": d + 1}, priority=-6)
    out = []
    if day.rows:
        out.append({"type": "community", "recipient": "party" if day.party_here else "dm", "place": key, "day": d,
                    "text": f"{s['name']}, day {d}: " + "; ".join(f"{r['who']} {r['did']}" for r in day.rows)})
    for matter in day.interrupts:
        out.append({"type": "community_matter", "recipient": "party", "place": key, "interrupt": True, "matter": matter,
                    "text": f"{s['name']}'s council must rule on {matter}. The party is here: let them weigh in, then "
                            f"record the ruling with community_decide (or wait and the council's own rule decides tomorrow)."})
    return out


# ── where the workers are, for routine.where ────────────────────────────────────

_routine_where = routine.where


def _where(world, npc: str, minute: "int | None" = None) -> dict:
    """routine.where, and for a settlement's worker nothing else accounts for: at work in their settlement."""
    found = _routine_where(world, npc, minute)
    if found.get("why") != "unknown":
        return found
    for key, s in sorted(world.all("settlement").items()):
        w = (s.get("workers") or {}).get(npc)
        if w and not w.get("away"):
            return {"place": key, "activity": f"{w.get('role') or 'working'} in {s['name']}", "why": f"works in {s['name']}"}
    return found


routine.where = _where


# ── reading it back ───────────────────────────────────────────────────────────

def chronicle(db, key: str, since: int = 0) -> list:
    rows = []
    for cid, c in sorted(wdb.all_of(db, "chronicle").items()):
        if cid.startswith(key + "|") and int(c["day"]) >= since:
            rows += c["rows"]
    return rows


def report(s: dict) -> dict:
    return {"name": s["name"], "day": s.get("day", 0), "stores": s["stores"],
            "assets": {k: {"label": a["label"], "condition": a["condition"], "known": a.get("known", a["condition"]),
                           "status": a["status"]} for k, a in s["assets"].items()},
            "offices": {k: o.get("acting") for k, o in s["offices"].items()},
            "away": [n for n, w in s["workers"].items() if w.get("away")],
            "skills": {n: w.get("skills", {}) for n, w in s["workers"].items()},
            "jobs": s["jobs"], "pacts": s.get("pacts", {}), "rota": s.get("rota", {}), "buffer": s.get("buffer", {}),
            "moved_households": s.get("moved", 0), "backlog": s.get("backlog", {}),
            "open_matters": [f"service:{j['asset']}" for j in s["jobs"].values() if j.get("service") and not j.get("approved")
                             and not j.get("emergency")]}


# ── actions ───────────────────────────────────────────────────────────────────

def _err(msg: str) -> dict:
    return {"status": "done", "elapsed_minutes": 0, "data": {"error": msg}}


@turn.handler("settlement")
def _settlement(ctx, intent: dict) -> dict:
    """settlement — start or change a community that lives on its own, one day at a time.

    {"action": "settlement", "at": "The Ford", "template": "hollow-9"}
    {"action": "settlement", "at": "The Ford", "workers": {"Jonas": {"away": true}}, "stores": {"parts": 4}}
    Any field merges into the record: stores, use, needs, assets, workers (skills, duties, watches, away,
    learns), offices (succession, rules), grow, short, neighbour. Its days run with the world clock."""
    world = scheduler.World(ctx.campaign, ctx.db)
    try:
        key = _key(world, str(intent.get("at", "")))
    except ValueError as exc:
        return _err(str(exc))
    s = world.get("settlement", key)
    if intent.get("template"):
        path = TEMPLATES / f"community-{intent['template']}.json"
        if not path.is_file():
            return _err(f"no template {path.name}")
        s = json.loads(path.read_text(encoding="utf-8"))
    if not s:
        return _err("no settlement here yet: start one with a template or the full record")
    patch = {k: v for k, v in intent.items() if k not in ("action", "at", "template", "actor", "action_id")}
    _merge(s, patch)
    s.setdefault("jobs", {})
    for a in s["assets"].values():
        a.setdefault("status", "running")
        a.setdefault("known", a["condition"])
    for o in s["offices"].values():
        o.setdefault("acting", (o.get("succession") or [None])[0])
    world.put("settlement", key, s)
    if not ctx.db.execute("SELECT 1 FROM events WHERE status='pending' AND event_id LIKE ?",
                          (f"community-day-{key}-%",)).fetchone():
        d = int(s.get("day", 0)) + 1
        scheduler.schedule(ctx.db, f"community-day-{key}-{d}", (world.minute or 0) + 1440,
                           {"type": "community_day", "place": key, "day": d}, priority=-6)
    return {"status": "done", "elapsed_minutes": 0, "data": {"settlement": key, **report(s)}}


@turn.handler("community")
def _community(ctx, intent: dict) -> dict:
    """community — how a settlement stands and what happened there: {"action": "community", "at": "The Ford",
    "since_day": 1}. The chronicle rows say who did what, why they could, and what it left."""
    world = scheduler.World(ctx.campaign, ctx.db)
    try:
        key = _key(world, str(intent.get("at", "")))
    except ValueError as exc:
        return _err(str(exc))
    s = world.get("settlement", key)
    if not s:
        return _err("no settlement here")
    since = int(intent.get("since_day", max(0, int(s.get("day", 0)) - 6)))
    return {"status": "done", "elapsed_minutes": 0, "data": {**report(s), "chronicle": chronicle(ctx.db, key, since)}}


@turn.handler("community_decide")
def _decide(ctx, intent: dict) -> dict:
    """community_decide — rule on a settlement's matter instead of its council's written rule.

    {"action": "community_decide", "at": "The Ford", "matter": "service:filter-main" | "pact:Deepwell",
     "decision": "approve" | "deny" | "delay", "why": "…"}
    Kept on record; it takes effect on the settlement's next day."""
    world = scheduler.World(ctx.campaign, ctx.db)
    try:
        key = _key(world, str(intent.get("at", "")))
    except ValueError as exc:
        return _err(str(exc))
    s = world.get("settlement", key)
    decision = str(intent.get("decision", ""))
    if not s or decision not in ("approve", "deny", "delay") or not intent.get("matter"):
        return _err("needs a settlement, a matter and a decision of approve, deny or delay")
    s.setdefault("decisions", {})[str(intent["matter"])] = {"decision": decision, "why": str(intent.get("why", ""))}
    day = Day(s, int(s.get("day", 0)), False)
    _council(day)                                 # the ruling takes effect now, not after tomorrow's wear
    world.put("settlement", key, s)
    if day.rows:
        cid = f"{key}|{day.d:03d}"
        rows = (world.get("chronicle", cid) or {"day": day.d, "rows": []})
        rows["rows"] += day.rows
        world.put("chronicle", cid, rows)
    return {"status": "done", "elapsed_minutes": 0,
            "data": {"settlement": key, "matter": intent["matter"], "decision": decision, "chronicle": day.rows}}


def _provider(campaign: str, text: str, turn_view) -> list:
    """Arriving at a settlement: what changed there that is still visible, since the party was last there."""
    if not wdb.enabled(campaign):
        return []
    with wdb.reader(campaign) as db:
        if db is None:
            return []
        here = (scheduler.World(campaign, db).json("world-map.json", {}) or {}).get("party_location")
        s = wdb.get(db, "settlement", here) if here else None
        if not s:
            return []
        rows = [r for r in chronicle(db, here, int(s.get("seen_day", 0)) + 1) if r.get("lasting")]
    if not rows:
        return []
    since = f"since the party was last here (day {s['seen_day']})" if s.get("seen_day") else "before the party came"
    told = "; ".join(f"day {r['day']}: {r['who']} {r['did']} ({r['left'] or r['why']})" for r in rows[-4:])
    return [(gm_guide.DEPTH, f"{s['name'].upper()} CHANGED {since.upper()}: {told}. Show it through what is there to "
                             "see and who mentions it; the full record is the `community` action.")]


gm_guide.PROVIDERS.append(_provider)
