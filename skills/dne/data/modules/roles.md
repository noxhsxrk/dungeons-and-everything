The script deals the roles and holds them. You cannot move the traitor once the deal is sealed, and neither can
anyone else: that is what makes the betrayal fair.

- **Deal at the start,** before anything is decided: `{"action": "roles", "deal": ["Mira", "Theo", "Vos",
  "Kell"], "roles": {"traitor": 1}}`. Names are player characters and NPCs. Roles not counted are `loyal`;
  with no counts, one traitor per 4 names *(default)*. Other roles are fine (`"cultist": 1, "spy": 1`).
  - The script shuffles, adds a secret salt, and sends the whole table the **seal**: a sha256 of the deal.
    Ask a player to copy it somewhere outside the game.
  - Each player character is told their role privately. Your reply does not show the deal.
- **NPCs play their role by the odds.** When an NPC with a role does something that matters (a vote, a claim,
  a watch, a choice), ask the script: `{"action": "roles", "act": "Vos", "why": "the vote"}`. Narrate what it
  returns. Traitors mostly look loyal; slips are rare and real. A role with no table needs
  `"options": ["...", "..."]` (an entry twice is twice as likely).
- **Players with roles** choose for themselves. Give a traitor player private chances: whisper an opening
  (send.py --to) and let them decide.
- **Evidence is public.** What the NPCs did, who was where, what went missing: say it to everyone, the same way.
  Never hint with tone; the players deduce from what happened.
- **Reveal at the end** (the vote, the climax, the last scene): `{"action": "roles", "reveal": true, "expect":
  "<the seal the player kept>"}`. The table sees the deal, the salt and whether it matches the seal. Anyone can
  check it: sha256 of `{"deal":{...},"salt":"..."}` (keys sorted, no spaces).
  - If `verified` is false, say so plainly. The game's truth was broken; do not narrate around it.
- A new deal is refused until the old one is revealed.
