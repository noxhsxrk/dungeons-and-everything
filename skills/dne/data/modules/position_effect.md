Before any roll that could go wrong in an interesting way, say two things out loud, then roll as usual.

- **Position** — how bad a miss gets:
  - **controlled**: the character acts on their own terms; a miss costs little, they can back off or try again.
  - **risky** *(the usual)*: a miss hurts or complicates things.
  - **desperate**: they are reaching past what they can do; a miss is serious.
- **Effect** — how much a hit achieves: **limited**, **standard** *(the usual)* or **great**.
- Set them from the fiction: tools, help, the opposition's strength and scale. A player may trade one for the
  other ("I go in desperate for great effect"); agree before the dice.
- **Send it as one action**; the script rolls the usual check and reads the result through both:
  `{"action": "position", "actor": "Mira", "approach": "finesse", "position": "risky", "effect": "standard",
  "label": "crack the strongbox", "clock": "The vault"}`. Push and help work as on any roll.
- **What comes back** (`reading`):
  - `consequence`: what this degree means at this position. Pick the concrete form: harm, a complication,
    a worse position, a lost chance, or less done.
  - `harm_if_hurt`: the harm to mark if you choose harm *(default)*: controlled 1, risky 2, desperate 3; one less
    on a cost, one more on a critical failure (4 takes them out).
  - `ticks`: what a hit does to a clock *(default)*: limited 1, standard 2, great 3, +1 on a critical; 0 on a miss.
    Name the clock in the action and it is ticked at once.
- **The position carries**: leave `position` out and the last one named is used (an engagement roll sets the
  first). Set it without a roll: `{"action": "position", "set": "desperate", "why": "the alarm is up"}`.
- The reading lands at once, so a token cannot step this roll up afterwards.
- **Story mode:** the oracle answers (controlled likely, risky 50/50, desperate unlikely); the reading is the same.
