A **vow** is a promise a character means to keep across many sessions: free a brother, find the heir, open a shop
of their own. It is a 10-box progress track that fills as the story moves toward it.

- **Swearing:** say it in the fiction, aloud, to someone. Pick how big it is: **easy** (a few scenes), **tough**,
  **hard**, **extreme**, **epic** (a whole campaign):
  `{"action": "vow", "owner": "Mira", "name": "Get my brother out", "rank": "hard", "why": "at the gate"}`.
  A party vow is `"owner": "party"`.
- **Progress:** when a scene brings it truly closer (a clue, an ally, an obstacle gone), mark it once:
  `{"action": "vow", "owner": "Mira", "name": "Get my brother out", "mark": 1, "why": "the warden's ledger"}`.
  One mark fills by rank *(default)*: easy 3 boxes, tough 2, hard 1, extreme half, epic a quarter.
- **Fulfilling:** when the moment comes, roll for it: `{"action": "vow", "owner": "Mira", "name": "…",
  "fulfil": true, "actor": "Mira"}`. It is the usual roll with the progress as its modifier (0–1 boxes −2 … 10
  boxes +3), no approach.
  - success or better: kept. XP by rank *(default)*: easy 1, tough 2, hard 3, extreme 4, epic 5. Run the
    `xp_command` in the reply.
  - success at a cost: kept, one XP less, and the GM names what it cost or what new trouble it opened.
  - a miss: not yet. Two boxes are lost *(default)*; something they believed was wrong. The vow stands.
  - The result lands at once: a token cannot step it up.
- **Forsaking:** giving up a vow marks stress by rank *(default)*: easy or tough 1, hard or extreme 2, epic 3:
  `{"action": "vow", "owner": "Mira", "name": "…", "forsake": true, "why": "…"}`.
- Keep one or two vows per character at a time. A vow that no longer matters can be forsaken without shame.
