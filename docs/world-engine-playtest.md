# World engine playtest: the bridge at Millbridge

The plan's test of whether the engine is *fun*, not only correct. One town whose market is waiting for flour, one
caravan, one bridge, two factions that both want the bridge. Run it with real players through the table's normal way
in (display or chat); nobody should have to type a command to repair anything.

The engine's side of all three rounds is checked by script in `tests/test_playtest_bridge.py` (no model, no
players): what is left for a real table is the people, their answers below and the timings.

## Set up (once, then save: all three rounds start from this save)

Turn the engine on for a fresh campaign (`world_migrate.py -c <campaign> enable`), make a map with Millbridge, the
Ford and Market joined by roads, and resolve:

```json
[{"action": "route", "between": ["Millbridge", "Market"], "access": "closed", "owner": "Tollmen",
  "reason": "the Tollmen are deciding what to charge"},
 {"action": "market", "at": "Market", "stock": {"flour": 3}, "base": {"flour": 5}, "target": {"flour": 20},
  "cash": 500, "eats": {"flour": 1}},
 {"action": "caravan", "id": "flour", "from": "Millbridge", "to": "Market", "goods": {"flour": 20},
  "departs_in_minutes": 600, "owner": "Millers' Guild"},
 {"action": "fact", "id": "toll-talk", "text": "The Tollmen mean to charge a toll at the bridge.", "place": "Millbridge"},
 {"action": "remember", "id": "clerk-debt", "owner": "<PC 1>", "kind": "bond", "tone": "either",
  "text": "The toll clerk owes <PC 1> for getting his brother out of the cells.", "about": ["clerk", "toll"],
  "payoff": {"place": "Millbridge"}},
 {"action": "situation", "id": "the-bridge", "difficulty": "hard",
  "sides": [{"who": "Tollmen", "wants": "coin from every cart", "limit": "too few men to hold it against the Guild",
             "will_trade": "a quiet payment instead of a public toll"},
            {"who": "Millers' Guild", "wants": "the flour through today", "limit": "cannot be seen to pay",
             "will_trade": "a share of the mill's winter contract"}],
  "if_left_alone": "the bridge stays shut, the caravan waits, the market runs out in three days"}]
```

Give one PC the clerk's debt and tell another, alone (`notice`), that they can read a freight schedule. Open the first
scene with what each character really knows.

## Round A: the party rests for three days

`{"action": "rest", "type": "long"}` three times, or `{"action": "wait", "days": 3}`. Watch what the world did on its
own and what evidence of it is left for the party to find (the market's shelves, the caravan on the wrong side, what
Market has heard: `knows` for `place:Market`).

## Round B: the same save, and the players act

Let them bargain, lean on the clerk, or open the road before the caravan needs it. Then compare with round A: when
they got into town, the price of flour (`market`), who thinks what of whom, and what the townsfolk have heard.

## Round C: the players split up

One stalls at the bridge, another carries word ahead. Use `group` so each says what they do; the result should depend
on the one who decides last, and the turn should wait for them.

## Ask each player, separately

- What did *you* change in this world?
- Did you know the risk well enough before you chose?
- Was there a moment the game stopped you and gave you nothing to decide?

Keep the actual moments they name. Those tune the rules and the pacing.

## Numbers to write down

`turn.py -c <campaign> metrics` gives: turns, how many the GM closed through the runner and how many it narrated
around, questions put to players, background events that happened and events cancelled with a reason. Add by hand:
seconds from a player's action to the result on screen, and how often someone had to fix continuity themselves. Take
the same numbers from the same host and model with the engine off first: that is the baseline for speed.

## Ready to ship when

An old campaign still opens; an interrupted turn and an undo behave; one journey leaves effects that can be traced
back (`scheduler.py list`, the events' `cause`); and the party that opened the bridge in time lives in a visibly
different world from the party that let the days go by.
