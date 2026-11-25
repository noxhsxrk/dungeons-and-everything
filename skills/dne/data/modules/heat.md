The crew's jobs leave a trail. Two party tracks: **crew heat** 0–8 and **wanted** 0–4 *(defaults)*. They are the
crew's, not one character's. (This is not the `heat` action, which is one faction's attention in one area.)

- **After every job** say how loud it was, and send it once:
  `{"action": "crew_heat", "job": "loud", "high_profile": true, "killing": false}`.
  - quiet 0, contained 2, loud 4, wild 6 *(defaults)*;
  - +1 a high-profile target, +1 on hostile turf, +1 while at war, +2 if anyone was killed.
- **At 9 heat** the crew gains a wanted level and the heat starts again from what is left over (wanted stops at 4).
  Tell the players: their names are now known in places they were not.
- **Between jobs**, once: `{"action": "crew_heat", "entangle": true}`. The script rolls dice equal to the wanted
  level (none wanted: two dice, the lower counts) and reads the result in the column of the crew's heat
  (0–3, 4–5, 6+). Play the entanglement it gives before the next job; it arrives in full before they can dodge it.
- **Lowering heat:** a week lying low, a bribe, someone taking the blame: `{"action": "crew_heat", "add": -2,
  "why": "…"}`. Wanted only goes down when someone pays for it (a crew member serves time, a big favour is called
  in): `{"action": "track", "owner": "party", "id": "wanted", "mark": -1, "why": "…"}`.
- Heat and wanted show on the display like any track. The players see both numbers.
