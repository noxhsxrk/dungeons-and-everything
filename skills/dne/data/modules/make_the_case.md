A mystery **with no hidden answer**. Clues are real things the players find, but nobody, not even you, knows what
they mean until the players argue a theory and it holds.

- **Tell the players at the start**, in these words or your own: "There is no answer written down. If your
  theory fits the clues and the roll goes your way, it is what happened."
- **Open the case:** `{"action": "case", "id": "the-lighthouse", "open": true, "complexity": 6, "clues": [...]}`.
  - The script marks it as having no hidden answer for good and tells the party. It refuses a `truth`.
  - `complexity` is how tangled it is *(default 6)*: 4 for a quick one, 8 for a whole-campaign one.
  - Clues are concrete and odd, with no meaning attached ("a wet umbrella in a dry house"). Write 12–20.
- **Finding clues:** `search` as usual. Only clues someone has actually found count later.
- **Making the case:** when the players agree on a theory, write it down as they say it and send
  `{"action": "make_the_case", "actor": "Mira", "case": "the-lighthouse", "theory": "…", "explains": ["c2", "c5", "c9"]}`.
  - `explains` lists the found clues the theory accounts for. Be fair: a clue counts only if the theory says
    why it is there. Clues nobody has found do not count; the script checks.
  - The roll is the usual check with Wits, + the clues it explains − the complexity (push and help as usual).
- **Results:**
  - **10+:** the theory is the truth. The script writes it into the case. Play the confrontation.
  - **7–9:** the theory is the truth, but there is a complication: the culprit runs, a cost, a second secret.
  - **6 or less:** the theory is wrong. Make a move (a new victim, a clue turns false, someone is angry). They
    can make another case later, with more clues.
- Once a theory holds, **you must play it as true**, even if you had another idea. That is the promise.
- Story mode: the oracle answers, its odds set by explained clues minus complexity.
