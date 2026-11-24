#!/usr/bin/env python3
"""
trade.py — a road someone controls, a caravan that really travels, a market that can run out.

Records in the world store:
  route    "<a>|<b>"   {owner, access: open | toll | closed, toll, reason}        (a bridge is a route)
  market   "<place>"   {stock: {item: n}, base: {item: cp}, target: {item: n}, cash: cp, eats: {item: n per day}}
  caravan  "<id>"      {goods, budget, from, to, wants, owner, status, at, knows_closed, log}

Engine actions:
  {"action": "route", "between": ["Millbridge", "Market"], "access": "open", "owner": "Millers' Guild", "reason": "…"}
  {"action": "market", "at": "Market", "stock": {"flour": 3}, "base": {"flour": 5}, "target": {"flour": 20},
   "cash": 500, "eats": {"flour": 1}}
  {"action": "caravan", "id": "flour", "from": "Millbridge", "to": "Market", "goods": {"flour": 20},
   "budget": 200, "departs_in_minutes": 600, "owner": "Millers' Guild",
   "stops": [{"at": "The Ford", "sell": {"flour": 5}, "buy": {"salt": 2}}]}
  {"actor": "Mira", "action": "buy", "item": "flour", "qty": 1, "at": "Market"}     (and "sell")

PRICE  base × scarcity, where scarcity = target ÷ stock, kept between ½ and 3 (out of stock: 3, nothing to buy).
       Every quote carries its reason, e.g. "5 cp base × 2.0 (5 in stock, 10 wanted)".
A caravan routes by what it knows. Reaching a closed stretch it learns of it and takes another road if
there is one; otherwise it waits there and tries again. Its arrival sells its goods into the market's
stock, as far as the market's cash goes. What the party can see of all this is marked for them; the rest
is for the GM to bring in through what they notice.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import journey  # noqa: E402
import scheduler  # noqa: E402
import turn  # noqa: E402

RETRY_MINUTES = 360       # a held caravan looks again every six hours


def route_id(a: str, b: str) -> str:
    return "|".join(sorted((a, b)))


def _keys(world, names) -> tuple:
    data = world.json("world-map.json", {"places": {}, "edges": []})
    keys = [journey.place_key(data, str(n)) for n in names]
    if not all(keys):
        raise ValueError(f"unknown place in {list(names)}")
    return tuple(keys)


def price(market: dict, item: str) -> tuple:
    """(cp each, why) for one unit of `item` here, or (None, why) when the market does not deal in it."""
    base = (market.get("base") or {}).get(item)
    if base is None:
        return None, f"{item} is not traded here"
    stock = int((market.get("stock") or {}).get(item, 0))
    target = int((market.get("target") or {}).get(item, max(stock, 1)))
    scarcity = 3.0 if stock <= 0 else min(3.0, max(0.5, target / stock))
    carried = int((market.get("surcharge") or {}).get(item, 0))
    why = f"{base} cp base × {scarcity:.1f} ({stock} in stock, {target} wanted)"
    return max(1, round(base * scarcity) + carried), why + (f" + {carried} cp transport" if carried else "")


def _sees(world, place_key: str) -> str:
    """'party' when the party is standing there, else 'dm' (the GM decides how news of it reaches them)."""
    return "party" if world.json("world-map.json", {}).get("party_location") == place_key else "dm"


def _name(world, key: str) -> str:
    return world.json("world-map.json", {}).get("places", {}).get(key, {}).get("name", key)


# ── the market's own day ──────────────────────────────────────────────────────

@scheduler.effect("market_day")
def _market_day(world, row, eff):
    """What the town uses up in a day leaves the stock; the next day is queued."""
    key = eff["place"]
    market = world.get("market", key)
    if not market:
        return None
    out, stock = [], market.setdefault("stock", {})
    for item, n in (market.get("makes") or {}).items():        # what the town produces itself comes in first
        stock[item] = int(stock.get(item, 0)) + int(n)
        market.get("surcharge", {}).pop(item, None)             # local goods carry no transport cost
    day_no = int(eff.get("day", 0))
    for item, plan in (market.get("restock") or {}).items():    # a regular delivery from outside the map
        if int(plan.get("every_days", 0)) and day_no % int(plan["every_days"]) == 0:
            stock[item] = int(stock.get(item, 0)) + int(plan.get("amount", 0))
    for item, n in (market.get("eats") or {}).items():
        had = int(stock.get(item, 0))
        stock[item] = max(0, had - int(n))
        if had > 0 and stock[item] == 0:
            out.append({"type": "sold_out", "recipient": _sees(world, key),
                        "text": f"{_name(world, key)} has run out of {item}.", "place": key})
    world.put("market", key, market)
    day = int(eff.get("day", 0)) + 1
    scheduler.schedule(world.db, f"market-day-{key}-{day}", row["due_minute"] + 1440,
                       {"type": "market_day", "place": key, "day": day}, priority=-5)
    return out


# ── caravans ──────────────────────────────────────────────────────────────────

def _caravan_route(world, caravan: dict, start: str) -> "list | None":
    """The caravan's way from `start` to its destination, avoiding every stretch it knows to be closed."""
    data = world.json("world-map.json", {"places": {}, "edges": []})
    known = {tuple(pair) for pair in caravan.get("knows_closed", [])}
    open_edges = [e for e in data.get("edges", []) if tuple(sorted((e["a"], e["b"]))) not in known]
    if start == caravan["to"]:
        return []
    path = journey._shortest({**data, "edges": open_edges}, start, caravan["to"], caravan.get("mode", "wagon"), world)
    used = {tuple(sorted((a, b))) for a, b, _m, _x in path}
    real = {tuple(sorted((e["a"], e["b"]))) for e in open_edges}
    return path if used <= real else None        # a straight line across country is not a road for a wagon


def _leg_minutes(miles: float, mult: float, mode: str) -> int:
    import world_map
    return max(1, round(miles * mult / world_map.TRAVEL_SPEED_MPD.get(mode, 20.0) * 1440))


def _step(world, cid: str, caravan: dict, now: int, seq: int) -> list:
    """From where the caravan stands: sell if it has arrived, else take the next stretch or find it shut."""
    here, out = caravan["at"], []
    if here == caravan["to"]:
        return _arrive(world, cid, caravan)
    # Standing next to a stretch it thought was shut, it can see for itself whether that is still so.
    caravan["knows_closed"] = [pair for pair in caravan.get("knows_closed", [])
                               if here not in pair or journey.route_block(world, *pair)]
    route = _caravan_route(world, caravan, here)
    if not route:
        caravan["status"] = "held"
        world.put("caravan", cid, caravan)
        scheduler.schedule(world.db, f"caravan-{cid}-{seq}", now + RETRY_MINUTES, {"type": "caravan_move", "id": cid, "seq": seq})
        return [{"type": "caravan_held", "recipient": _sees(world, here), "place": here,
                 "text": f"The {cid} caravan waits at {_name(world, here)}: no open road to {_name(world, caravan['to'])}."}]
    a, b, miles, mult = route[0]
    block = journey.route_block(world, a, b)
    if block:                                     # it finds out by getting there
        pair = list(sorted((a, b)))
        if pair not in caravan.setdefault("knows_closed", []):
            caravan["knows_closed"].append(pair)
        caravan.setdefault("log", []).append({"minute": now, "found_closed": pair, "reason": block})
        world.put("caravan", cid, caravan)
        out.append({"type": "caravan_blocked", "recipient": _sees(world, here), "place": here,
                    "text": f"The {cid} caravan finds the way from {_name(world, a)} to {_name(world, b)} closed ({block})."})
        return out + _step(world, cid, caravan, now, seq)      # another road, or it waits
    caravan["status"] = "en_route"
    caravan["heading"] = b
    world.put("caravan", cid, caravan)
    scheduler.schedule(world.db, f"caravan-{cid}-{seq}", now + _leg_minutes(miles, mult, caravan.get("mode", "wagon")),
                       {"type": "caravan_move", "id": cid, "seq": seq, "reach": b})
    if len(caravan.get("knows_closed", [])) and not caravan.get("rerouted") and caravan.get("log"):
        caravan["rerouted"] = True
        world.put("caravan", cid, caravan)
        out.append({"type": "caravan_rerouted", "recipient": _sees(world, here), "place": here,
                    "text": f"The {cid} caravan turns toward {_name(world, b)} instead."})
    return out


def _trade(world, caravan: dict, key: str, sell: dict, buy: dict) -> tuple:
    """Sell up to `sell` into the market at `key` while it has coin, then buy up to `buy` while the caravan has
    coin. Both sides' stock and coin change. Returns (sold, bought) with each price's reason."""
    market = world.get("market", key) or {"stock": {}, "base": {}, "target": {}, "cash": 0}
    sold, earned = {}, 0
    for item, want in sorted(sell.items()):
        qty = min(int(want), int((caravan.get("goods") or {}).get(item, 0)))
        each, why = price(market, item)
        if each is None or qty <= 0:
            continue
        carry = int(caravan.get("transport", 0))             # what it cost to bring each one here
        each += carry
        can = min(qty, int(market.get("cash", 0)) // each) if each else qty
        if can < qty and market.get("when_broke") == "credit":
            market["owes"] = int(market.get("owes", 0)) + (qty - can) * each     # the rest on account
            market["cash"] = int(market.get("cash", 0)) + (qty - can) * each
            can = qty
        if can <= 0:
            continue
        if carry:
            market.setdefault("surcharge", {})[item] = carry
        market["stock"][item] = int(market["stock"].get(item, 0)) + can
        market["cash"] = int(market.get("cash", 0)) - can * each
        caravan["goods"][item] = int(caravan["goods"][item]) - can
        sold[item] = {"qty": can, "each": each, "why": why}
        earned += can * each
    caravan["budget"] = int(caravan.get("budget", 0)) + earned
    bought = {}
    for item, qty in sorted(buy.items()):
        each, why = price(market, item)
        have = int(market["stock"].get(item, 0))
        can = min(int(qty), have, caravan["budget"] // each) if each else 0
        if can > 0:
            market["stock"][item] = have - can
            market["cash"] += can * each
            caravan["budget"] -= can * each
            caravan.setdefault("goods", {})[item] = int(caravan["goods"].get(item, 0)) + can
            bought[item] = {"qty": can, "each": each, "why": why}
    world.put("market", key, market)
    return sold, bought


def _stop(world, cid: str, caravan: dict, key: str) -> list:
    """A market on the way where the caravan was told to trade: it sells and buys what its plan for that stop says."""
    plan = next((s for s in caravan.get("stops") or [] if s.get("at") == key and not s.get("done")), None)
    if not plan or not world.get("market", key):
        return []
    sold, bought = _trade(world, caravan, key, plan.get("sell") or {}, plan.get("buy") or {})
    plan["done"] = True
    caravan.setdefault("log", []).append({"stopped": key, "sold": sold, "bought": bought})
    world.put("caravan", cid, caravan)
    what = ", ".join(f"{v['qty']} {k}" for k, v in sold.items()) or "nothing"
    got = ", ".join(f"{v['qty']} {k}" for k, v in bought.items())
    return [{"type": "caravan_stopped", "recipient": _sees(world, key), "place": key, "sold": sold, "bought": bought,
             "text": f"The {cid} caravan stops at {_name(world, key)}, sells {what}" + (f" and buys {got}" if got else "") + "."}]


def _arrive(world, cid: str, caravan: dict) -> list:
    key = caravan["to"]
    sold, bought = _trade(world, caravan, key, dict(caravan.get("goods") or {}), dict(caravan.get("wants") or {}))
    caravan["status"] = "arrived"
    caravan.setdefault("log", []).append({"arrived": key, "sold": sold, "bought": bought})
    world.put("caravan", cid, caravan)
    what = ", ".join(f"{v['qty']} {k}" for k, v in sold.items()) or "nothing the market could pay for"
    return [{"type": "caravan_arrived", "recipient": _sees(world, key), "place": key, "sold": sold, "bought": bought,
             "text": f"The {cid} caravan reaches {_name(world, key)} and sells {what}."}]


@scheduler.effect("caravan_move")
def _caravan_move(world, row, eff):
    """The caravan sets out, reaches the end of a stretch, or looks again at a road that was shut."""
    cid = eff["id"]
    caravan = world.get("caravan", cid)
    if not caravan or caravan.get("status") == "arrived":
        return None
    out = []
    if eff.get("reach"):
        caravan["at"] = eff["reach"]
        caravan.pop("heading", None)
        if eff["reach"] != caravan["to"]:
            out = _stop(world, cid, caravan, eff["reach"])
    return out + _step(world, cid, caravan, row["due_minute"], int(eff.get("seq", 0)) + 1)


# ── a faction's goal that changes the map ─────────────────────────────────────

def faction_outcomes(world) -> list:
    """Factions whose goal is complete and that wrote down what success does (`on_success` on the faction):

        {"type": "route", "between": ["Millbridge", "Market"], "owner": "Tollmen", "access": "toll", "toll": "2 sp",
         "requires": {"force": 3}, "cost": {"wealth": 1}}

    It is applied once, if the faction has the strength it requires and pays what it costs."""
    data = world.json("factions.json")
    out = []
    for name in sorted((data or {}).get("factions", {})):
        f = data["factions"][name]
        plan = f.get("on_success")
        if not plan or f.get("on_success_applied") or f.get("progress", 0) < f.get("clock", 1):
            continue
        short = [s for s, need in (plan.get("requires") or {}).items() if f.get(s, 0) < need]
        f["on_success_applied"] = True
        world.touch("factions.json")
        if short:
            f["on_success_result"] = "not carried out: lacks " + ", ".join(short)
            out.append({"type": "faction_goal", "recipient": "dm", "text": f"{name} reached its goal but {f['on_success_result']}."})
            continue
        for stat, n in (plan.get("cost") or {}).items():
            f[stat] = max(0, f.get(stat, 0) - int(n))
        if plan.get("type") == "route":
            a, b = _keys(world, plan["between"])
            record = world.get("route", route_id(a, b)) or {}
            record.update({k: plan[k] for k in ("owner", "access", "toll", "reason") if k in plan})
            record.setdefault("reason", f"held by {plan.get('owner', name)}")
            world.put("route", route_id(a, b), record)
            f["on_success_result"] = f"route {plan['between'][0]}–{plan['between'][1]} now {record.get('access')} under {record.get('owner')}"
            out.append({"type": "route_changed", "recipient": "dm", "place": a,
                        "text": f"{name} takes the road between {_name(world, a)} and {_name(world, b)}: {record.get('access')}"
                                + (f", toll {record['toll']}" if record.get("toll") else "") + "."})
    return out


_inner_week = scheduler.EFFECTS["faction_week"]


@scheduler.effect("faction_week")
def _faction_week(world, row, eff):
    """The scheduler's faction week, then whatever a completed goal changes on the map."""
    out = _inner_week(world, row, eff) or []
    return out + faction_outcomes(world)


# ── actions ───────────────────────────────────────────────────────────────────

@turn.handler("route")
def _route(ctx, intent: dict) -> dict:
    """route — who holds a road or a bridge, and whether it can be crossed.

    {"action": "route", "between": ["Millbridge", "Market"], "access": "open" | "toll" | "closed",
     "owner": "Tollmen", "toll": "2 sp a head", "reason": "the Tollmen hold the bridge"}
    A closed stretch stops the party and any caravan that reaches it; a toll stops the party to decide."""
    world = scheduler.World(ctx.campaign, ctx.db)
    try:
        a, b = _keys(world, intent["between"])
    except (ValueError, KeyError) as exc:
        return {"status": "done", "elapsed_minutes": 0, "data": {"error": str(exc)}}
    record = world.get("route", route_id(a, b)) or {}
    before = dict(record)
    record.update({k: intent[k] for k in ("access", "owner", "toll", "reason") if k in intent})
    world.put("route", route_id(a, b), record)
    return {"status": "done", "elapsed_minutes": 0, "data": {"route": route_id(a, b), "before": before, "now": record},
            "visible_events": scheduler.fire(world, "when")}


@turn.handler("market")
def _market(ctx, intent: dict) -> dict:
    """market — set up or adjust the market at a place.

    {"action": "market", "at": "Market", "stock": {"flour": 3}, "base": {"flour": 5}, "target": {"flour": 20},
     "cash": 500, "eats": {"flour": 1}}
    `base` is the fair price in copper, `target` how much the town likes to have, `eats` what it uses each day.
    Without the other fields, {"action": "market", "at": "Market"} just quotes today's prices and why."""
    world = scheduler.World(ctx.campaign, ctx.db)
    try:
        (key,) = _keys(world, [intent["at"]])
    except (ValueError, KeyError) as exc:
        return {"status": "done", "elapsed_minutes": 0, "data": {"error": str(exc)}}
    market = world.get("market", key) or {"stock": {}, "base": {}, "target": {}, "cash": 0, "eats": {}}
    for field in ("stock", "base", "target", "eats", "makes", "restock"):
        market.setdefault(field, {}).update(intent.get(field) or {})
    for field in ("when_out", "when_broke"):
        if field in intent:
            market[field] = str(intent[field])
    if "cash" in intent:
        market["cash"] = int(intent["cash"])
    world.put("market", key, market)
    if (market.get("eats") or market.get("makes") or market.get("restock")) and not ctx.db.execute(
            "SELECT 1 FROM events WHERE status='pending' AND event_id LIKE ?", (f"market-day-{key}-%",)).fetchone():
        scheduler.schedule(ctx.db, f"market-day-{key}-1", (world.minute or 0) + 1440,
                           {"type": "market_day", "place": key, "day": 1}, priority=-5)
    quotes = {item: dict(zip(("each", "why"), price(market, item))) | {"in_stock": int(market["stock"].get(item, 0))}
              for item in sorted(market["base"])}
    return {"status": "done", "elapsed_minutes": 0, "data": {"market": key, "cash": market["cash"], "prices": quotes}}


@turn.handler("caravan")
def _caravan(ctx, intent: dict) -> dict:
    """caravan — goods on the move.

    {"action": "caravan", "id": "flour", "from": "Millbridge", "to": "Market", "goods": {"flour": 20},
     "budget": 200, "wants": {"salt": 5}, "departs_in_minutes": 600, "owner": "Millers' Guild", "mode": "wagon"}
    It leaves when its time comes and travels the map's roads. A closed stretch is found by reaching it: the
    caravan takes another road if there is one, or waits and looks again every six hours. Arriving, it sells into
    the market's stock while the market has coin, then buys what it `wants`. `stops`: markets on its road where it
    trades on the way, e.g. [{"at": "The Ford", "sell": {"flour": 5}, "buy": {"salt": 2}}] (a stop off its road is
    not visited)."""
    world = scheduler.World(ctx.campaign, ctx.db)
    cid = str(intent.get("id") or f"caravan-{ctx.action_id}")
    try:
        src, dst = _keys(world, [intent["from"], intent["to"]])
    except (ValueError, KeyError) as exc:
        return {"status": "done", "elapsed_minutes": 0, "data": {"error": str(exc)}}
    departs = (world.minute or 0) + int(intent.get("departs_in_minutes", 0))
    caravan = {"goods": dict(intent.get("goods") or {}), "budget": int(intent.get("budget", 0)),
               "wants": dict(intent.get("wants") or {}), "from": src, "to": dst, "at": src,
               "owner": intent.get("owner", ""), "mode": intent.get("mode", "wagon"), "status": "waiting",
               "transport": int(intent.get("transport", 0)),
               "stops": [{**s, "at": _keys(world, [s["at"]])[0]} for s in intent.get("stops") or []],
               "departs": departs, "knows_closed": [list(sorted(_keys(world, pair))) for pair in intent.get("knows_closed", [])],
               "log": []}
    world.put("caravan", cid, caravan)
    scheduler.schedule(ctx.db, f"caravan-{cid}-0", departs, {"type": "caravan_move", "id": cid, "seq": 0})
    return {"status": "done", "elapsed_minutes": 0, "data": {"caravan": cid, "departs_minute": departs}}


def _deal(ctx, intent: dict, buying: bool) -> dict:
    import economy
    world = scheduler.World(ctx.campaign, ctx.db)
    item, qty, actor = str(intent.get("item", "")), max(1, int(intent.get("qty", 1))), str(intent.get("actor", ""))
    try:
        (key,) = _keys(world, [intent.get("at") or world.json("world-map.json", {}).get("party_location") or ""])
    except ValueError as exc:
        return {"status": "done", "elapsed_minutes": 0, "data": {"error": str(exc)}}
    market = world.get("market", key)
    sheets = journey._pc_sheets(world, [actor])
    if not market or not sheets:
        return {"status": "done", "elapsed_minutes": 0,
                "data": {"error": "no market here" if not market else f"no character sheet for {actor}"}}
    rel, (title, text) = next(iter(sheets.items()))
    each, why = price(market, item)
    if each is None:
        return {"status": "done", "elapsed_minutes": 0, "data": {"error": why}}
    coin, _m = economy._read_currency_cp(text)
    stock = int(market["stock"].get(item, 0))
    if buying:
        target = int((market.get("target") or {}).get(item, 0))
        if market.get("when_out") == "ration" and target and stock * 5 <= target and qty > 1:
            return {"status": "done", "elapsed_minutes": 0,
                    "data": {"bought": 0, "error": f"{item} is rationed here: one to a customer while stocks are this low"}}
        if stock < qty:
            return {"status": "done", "elapsed_minutes": 0,
                    "data": {"bought": 0, "error": f"sold out: {stock} {item} left" if stock else f"sold out: no {item} left"},
                    "visible_events": [{"type": "sold_out", "recipient": "party", "text": f"There is no {item} left for {title}."}]}
        cost = each * qty
        if coin < cost:
            return {"status": "done", "elapsed_minutes": 0,
                    "data": {"bought": 0, "error": f"{title} has {economy.format_cp(coin)}, needs {economy.format_cp(cost)}"}}
        market["stock"][item] = stock - qty
        market["cash"] = int(market.get("cash", 0)) + cost
        text = economy._write_currency_cp(text, coin - cost)
        for _ in range(qty):
            text = economy._add_inventory_item(text, item, "Adventuring Gear")
        data = {"bought": qty, "item": item, "each": each, "why": why, "paid": cost, "left_in_stock": stock - qty}
    else:
        new_text, had = text, 0
        for _ in range(qty):
            new_text, ok = economy._remove_inventory_item(new_text, item)
            had += 1 if ok else 0
        pays = max(1, each // 2)                  # a market buys at half what it sells for
        can = min(had, int(market.get("cash", 0)) // pays)
        if can < qty:
            return {"status": "done", "elapsed_minutes": 0,
                    "data": {"sold": 0, "error": f"{title} has {had} {item}" if had < qty else "the market cannot pay for that"}}
        market["stock"][item] = stock + qty
        market["cash"] -= pays * qty
        text = economy._write_currency_cp(new_text, coin + pays * qty)
        data = {"sold": qty, "item": item, "each": pays, "why": f"half of {each} cp ({why})", "earned": pays * qty}
    world.put("market", key, market)
    return {"status": "done", "elapsed_minutes": 0, "writes": {rel: text}, "data": {"actor": title, "at": key, **data}}


@turn.handler("buy")
def _buy(ctx, intent: dict) -> dict:
    """buy — a character buys from the market where the party is.

    {"actor": "Mira", "action": "buy", "item": "flour", "qty": 1, "at": "Market"}
    Needs the item in stock and the coin on the sheet. Two buyers for the last one: the first gets it."""
    return _deal(ctx, intent, True)


@turn.handler("sell")
def _sell(ctx, intent: dict) -> dict:
    """sell — a character sells to the market: {"actor": "Mira", "action": "sell", "item": "flour", "qty": 2}.

    The market pays half its selling price, while it has coin."""
    return _deal(ctx, intent, False)
