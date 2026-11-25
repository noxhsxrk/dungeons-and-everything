The GM gets a **budget of complications** per session: 3 *(default)*. A complication is trouble the GM brings in on
their own, with no roll that called for it: reinforcements arrive, the bridge is out, the rival shows up early.

- **What costs nothing:** the moves a roll gives you. A miss, a cost on 7–9, a threshold, a doom disaster, a clock
  filling: those are the dice speaking. The budget is only for what you add with no roll asking for it.
- **Spending:** say it in the fiction, then send it in the same turn:
  `{"action": "complicate", "what": "the guard's relief comes early", "cost": 1}`. A small twist costs 1, a big one
  2, a scene-changing one 3. Refused when the budget is short: then it does not happen, find another way.
- **Every spend is written down** with its turn. `{"action": "complicate"}` reads what is left and every spend so
  far, so anyone at the table can check the GM kept to it.
- **A new session** refills the budget: `{"action": "pool", "refill": "session"}`. Unspent points do not carry over.
- Tell the players the number. They should know how much trouble is still in your pocket.
