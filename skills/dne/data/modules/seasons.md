Time passes in **seasons**: spring, summer, autumn, winter *(default; a World Kit's `climate.seasons` names them
instead)*. The season comes from the campaign calendar's month, so it turns by itself as `wait` moves the days.
Nobody here has harm or a hit count: trouble is a problem to solve together, never a fight to win.

- **When the season turns**, the script notices on its own (after any action that moves the calendar), rolls one
  happening from that season's table, and gives every character 1 token *(default)*. Build the next sessions
  around the happening; it is the season's question, not a threat.
- `{"action": "season"}` reads the season and its happening (send it once at the start of play to set the first:
  that first read only notes where play starts, with no turn and no tokens).
- **Tokens** (pool `tokens`, per character, up to 5 *(default)*; the same tokens that step a result up in story
  mode). With seasons on, this module's tokens rule replaces the core one (max 5, gained as below, no session
  refill). `modules apply` makes the pool; if it already existed, send `{"action": "pool", "owner": "Pell",
  "id": "tokens", "max": 5}` once.
  - **gain 1** when the character puts themselves out for someone: gives up their afternoon, their place, a thing
    they love, or admits they were wrong: `{"action": "pool", "owner": "Pell", "id": "tokens", "gain": 1, "why": "…"}`.
  - **spend 1** to make a small good thing simply true (the cart is fixed by morning, the cat comes home), to ease
    someone's worry for real, or to step a roll or an oracle answer up one step
    (`{"action": "pool", "owner": "Pell", "id": "tokens", "step_up": true}`).
- **Rolls are rare.** Ask for one only when failing would be interesting and nobody would be hurt by it. In story
  mode the oracle answers instead.
- Use `bond` for friendships (0–5): a season's end is a good time for each pair to say how they changed.
