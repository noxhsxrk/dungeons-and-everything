A **contest** is two sides trying for the same thing over several rounds. Each round, the side acting rolls the
usual check (the engine's `roll`), then the GM scores it with `subsystem.py`. Two kinds:

- **Race** (first to 3 *(default)*): a cooking match, a horse race, a card game.
  `subsystem.py -c <campaign> start "Harvest bake-off" --race 3 --sides "Mira,The baker"`
  - critical success: +2 for the side that rolled; success: +1; at a cost: +1 and the GM names the price
    (a twist, a burnt hand, a rule bent); failure: +1 to the other side; critical failure: +2 to the other side.
- **Countdown** (each side starts at a score and is worn down): a debate, a trial, a duel of nerves.
  `subsystem.py -c <campaign> start "The hearing" --countdown 6 --sides "Theo,The prosecutor"`
  - critical success: the other side −3; success: −2; at a cost: −1 to each side (unless that −1 already
    wins it); failure: the side that rolled −1; critical failure: −2 *(defaults)*.
  - The first side at 0 loses. The winner still owes a **concession** sized by what they lost on the way: none if
    untouched, small if they lost less than half, a real one if they lost half or more. The reply says which.
- **Scoring a round:** `subsystem.py -c <campaign> check "The hearing" --side Theo --total 9` (the 2d6 total of the
  roll), or `--degree success` in story mode. The NPC side scores when the GM's character acts: roll for them only if
  the table agrees, otherwise let a player's miss be the NPC's point (it already is).
- Every round must change the situation: describe each point as a moment the audience sees.
- `subsystem.py -c <campaign> status` shows every contest; `end "<name>"` removes one.
