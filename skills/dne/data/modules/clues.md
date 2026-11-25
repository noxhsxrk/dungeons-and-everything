A case with one true answer, built so the players cannot get stuck: the answer is fixed before play, and it is
always findable.

- **Build it with the story generator** (`SKILL-storygen.md`): `story_gen.py -c <campaign> skeleton --genre
  mystery,…`, flesh every `clue:<id>`, then `check` (exit 0). That writes `story-skeleton.json`.
- **Load it into the engine:** `{"action": "case", "skeleton": true}`. The case keeps the truth, the places,
  the clues and where each leads; the culprit and the suspects stay with you. The validator runs on every
  `case` that carries places, and **refuses** a case that cannot be solved:
  - every place reachable from the first one by following clues;
  - who, how and why each backed by 3 clues in 2 places;
  - a core clue in every place, found without a roll;
  - one suspect with means, motive and opportunity, a clue that clears each other one;
  - still solvable in 95% of 1000 games where a third of the clues are missed.
  Fix what it lists (`story_gen.py check` repairs most of it). `"force": true` stores it anyway, with warnings.
- **Searching:** `{"action": "search", "actor": "Theo", "case": "<id>", "where": "<place>"}`.
  - Core clues are found by anyone who looks in the right place. **Never roll to find the clue that keeps the
    story moving.** A roll (`"roll": {"approach": "wits"}`) adds the hidden clues and the extra detail, and
    a miss costs time, not the clue.
  - A clue that points somewhere tells that player where. The players follow the trail; you do not lead them.
  - What a search finds goes to that player alone; sharing it is `tell`.
- **The answer:** `accuse` records what they claim and never says if it is right. Play what follows from it.
- **Stuck table:** offer a new place with a core clue, or let an NPC come to them. Never hand them the answer.
- Write clue text that is plain and concrete (what is seen, not what it means). Stand-in text (`[clue …]`)
  must be written before anyone can find it: the reply's `unwritten` lists those still left.
