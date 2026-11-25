Fear piles onto the **stress** track every character already has (the one a push marks). Panic adds no new
track and no new roll: it gives stress two more thresholds, and the script rolls what happens.

- **Mark stress** when fear bites, as a move after a miss or as a cost on 7–9:
  `{"action": "track", "owner": "Mira", "id": "stress", "mark": 1, "why": "the lights went out"}`.
  - A sudden shock, a friend hurt in front of them, being alone with the danger: 1 each.
  - The danger in the same room: 2 *(default)*.
  - A push still marks 1, as always. It is the same track.
- **Thresholds** *(default)*, rolled by the script when stress climbs past them; the reply's `crossed` (after a
  push, `stress_crossed`) has the entry:
  - **3 — Jitters:** a small slip from the table, played at once.
  - **5 — Panic:** the character loses control for a moment, played at once. The player plays it out; it lasts
    one beat, then they act again.
  - **6 — Breaking point** (Braid's own rule): no more pushes, a lasting scar, stress back to 0.
- Climbing past a threshold again after recovering fires it again; staying above it does not.
- **Calming down:** a moment of safety and someone steady with them clears 1 stress
  (`"mark": -1`); a night's sleep somewhere safe clears 2. Never in the middle of the danger.
- Players never roll for panic and never read the tables: tell them what their character does, then ask what
  they do next.
