Plans are short. The crew picks **one plan** and supplies its **one detail**; everything else is found out in play
(flashbacks cover what they "had prepared").

| Plan | Its detail |
|---|---|
| assault | the point of attack |
| deception | the lie, and who it is told to |
| stealth | the way in |
| uncanny | the strange means (magic, tech, the impossible) |
| social | the contact who opens the door |
| transport | the route and the ride |

- **The engagement roll** is the usual 2d6 with no approach (it is the crew's luck), plus +1 or −1 for each factor
  *(defaults)*: **bold** (simple, daring) or **complex** (too many moving parts); **weakness** (the detail hits the
  target's weak spot) or **strength** (the target is strongest exactly there); **help** (friends lend a hand) or
  **interfere** (enemies get in the way); **other** −2..+2 for anything else.
- Send: `{"action": "engagement", "actor": "Mira", "plan": "stealth", "detail": "the laundry chute",
  "bold": true, "weakness": true, "job": "the Gilded Vault"}`.
- **Where play starts** (stored as the party's position, read by `position`):
  - critical success: controlled, and the first obstacle is already behind them;
  - success: controlled; success at a cost: risky; failure or worse: desperate.
- **Then cut straight to the first obstacle.** Never narrate the walk in. Put a clock on each defence and let the
  `position` rolls tick them.
- Needs the position_effect module switched on too.
