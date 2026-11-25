The war is bigger than the characters. Four party tracks *(defaults)*: **time** 0–12 (at 12 the war is lost or
the deadline passed), **pressure** 0–6 (how close the enemy is), **morale** 0–12 (starts 8), **supply** 0–6 (starts 3).

- **Time passes** (between missions, once): `{"action": "war", "pass": true}`. Time +1, pressure +1, supply −1;
  with no supply left, morale −2 instead.
- **The army moves on:** `{"action": "war", "advance": true}`. The script rolls dice equal to pressure and adds
  time by the highest: 1–3 +1, 4–5 +2, 6 +3, two sixes +5; then pressure goes back to 0. No pressure, no time lost.
- **Losses:** `{"action": "war", "losses": 2, "why": "the ford"}`: morale −1 each. At 0 morale every further loss
  is a desertion (the reply counts them).
- **Campaign actions** between missions, by morale: 3 or less none, 4–7 one, 8+ two. The reply's
  `campaign_actions` says how many (rest, recruit, forage, scout, repair: the table decides what each does).
  Rewards and penalties from missions move the tracks directly
  (`{"action": "track", "owner": "party", "id": "supply", "mark": 2, "why": "captured wagons"}`).
- **A unit is a character:** `{"action": "war", "unit": "Third Lantern Company", "quality": "trained"}`.
  - quality raw: +0, 1 harm box; trained: +1, 2 boxes; veteran: +2, 3 boxes.
  - The unit rolls the usual check with its rating: `{"action": "war", "unit": "Third Lantern Company",
    "roll": "hold the bridge"}`; push and help as on any roll.
  - It takes harm like a foe: `{"action": "war", "unit": "Third Lantern Company", "hit": 1}`. At full harm it
    breaks, and morale −1. That −1 already counts its dead: do not also send `losses` for the same casualties.
- **Read everything:** `{"action": "war"}`. Show the four tracks to the players; they are the commanders.
