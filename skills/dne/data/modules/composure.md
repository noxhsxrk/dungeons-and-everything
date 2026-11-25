The mind is a track: **composure** 0–10 *(default)*, every character starts full. It only goes down in play.

- **A frightening sight.** When a character meets something that should not be (a body that moves, a voice from
  the wall, the thing itself), rate it and send one action; the script rolls the usual check with Heart:
  `{"action": "fright", "actor": "Mira", "rating": "serious", "what": "the drowned man stands up"}`.
  - **minor** (blood, a corpse, a trick of the dark): lose 1 on a miss *(default, as all numbers here)*.
  - **serious** (a monster at a distance, a friend's death): lose 2.
  - **overwhelming** (the thing up close, a truth too large): lose 3.
  - A critical failure loses one more. On 7–9 the character holds, and you name a small cost as usual.
  - Push and help work as on any roll; send them in the same action. A token cannot undo a loss afterwards.
  - Rate the same horror once per scene. Seeing it again later, once it is known, is a step down (or no roll).
- **Thresholds** (the script rolls the table and tells you; narrate it, never list it to the players):
  - **6 — Rattled:** a reaction from the table grips them for the rest of the scene.
  - **3 — Haunted:** a lasting fear from the table, and −1 on Wits and Heart while composure is 3 or less.
  - **0 — Broken:** out of the player's hands for the scene. Next scene the player picks: the character leaves
    the story, or comes back at 1 with a fear for good.
- **Recovery** (`{"action": "track", "owner": "Mira", "id": "composure", "mark": 1, "why": "…"}`):
  - +1 for a quiet scene with someone they have a bond with (once per session);
  - +2 when the horror is driven back or the case is closed;
  - never above the maximum. Haunted lifts by itself once composure climbs above 3.
- **Story mode:** the oracle answers instead of dice (minor = likely, serious = 50/50, overwhelming = unlikely).
- Show composure on the display like any track. Tell the players the number; never tell them the tables.
