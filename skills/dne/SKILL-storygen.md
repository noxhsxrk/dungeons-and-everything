# Story generator — GM procedure

Load this file when starting a new Braid story (`/dne new`, or a new arc in a running campaign). It explains how
to use `scripts/story_gen.py`. The rule behind it: **Python rolls, the GM writes.** If you ask a model to "invent
something original", it drifts back to the same few plots. Here the script picks the bones of the story from
tables, and you dress them.

Every command takes `--file <path>` (or `-c <campaign>`, which uses `<campaign>/story-skeleton.json`). Every
campaign shares one history file, `<campaign root>/story-history.jsonl`. It is what keeps the next story
different from the last ones.

## 1. Seed: what the players said

```
story_gen.py -c <camp> seed "The town is called Saltmere" "mystery.culprit=the lighthouse keeper"
```

What a player says is true stays true. Write each thing as a fact:
- `genre.axis=value` (or `axis=value` for every genre that has that axis) pins that axis. The skeleton uses the
  pinned value, and `check` fails if anything later changes it.
- Any other text is kept as a fact. You must not contradict it when you write.

## 2. Skeleton: the script rolls

```
story_gen.py -c <camp> skeleton --genre war,mystery,horror [--seed N]
```

- **Genres.** Give 1–5, main genre first. Each genre has a kind:
  - **plot:** mystery, heist, war, competition
  - **mood:** horror, slasher, analog-horror, romance, cozy, comedy
  - **setting:** fantasy, sci-fi, space-opera, wuxia, litrpg, historical
  - **frame:** timeloop, traitor
- **Who drives.** The first plot genre drives the story. Every other genre is a sub-thread: in war + mystery the
  mission is the spine and the case is a thread inside it. With no plot genre, the first genre drives.
- **How each genre is rolled.** Each axis (culprit, motive, twist, obstacle…) is rolled on its own from
  `data/story_axes/<genre>.json`.
  - A value used in the last 20 stories of that genre counts for ×0.3 per use.
  - A new skeleton that shares more than 3 axes with any earlier one of its genre is rolled again.
  - "No twist" is exempt from the ×0.3, so it stays about 60% of mysteries.
- **What each genre builds:**
  - **mystery:** a case with suspects, places and clues. It goes straight to `table.py case` (`truth`, and
    clues with `id`, `text`, `where`, `obvious`), plus `proves` and `leads` for you. The clue `text` is a
    stand-in: write the real text (step 3) before the case reaches play, because `search` sends it to the
    player's phone word for word.
  - **horror, slasher, analog-horror, war, competition, comedy:** a ladder of at least 3 steps that rise one
    after another. Play them in order. Do not jump to the top step.
  - **heist:** a plan with the target, two defences, the insider and what goes wrong.
  - **romance:** obstacles. One comes from a character, one from circumstance.
- **Replaying.** The output records `seed` and `history_at`. `skeleton --seed N --history-at K` replays it
  exactly and records nothing.

The skeleton is truth. Do not change the culprit, the method, the motive, where the clues are or what each
clue proves. If the players' seed facts forced something, it is already in the skeleton.

## 3. Flesh: you write five, the script picks

Do this for every piece of prose that matters: the premise, each suspect's name and manner, each clue's text,
the horror's first sign, the insider.

```
story_gen.py -c <camp> flesh --slot premise
```

This prints the givens, the facts and a `do_not_use` list (the genre's clichés plus recent picks). Then:

```
story_gen.py -c <camp> flesh --slot premise --candidates '[{"text": "...", "p": 0.06}, ... five ...]'
```

- **Write exactly 5 candidates.** Give each a probability of at most 0.10, meaning each is one you would rarely
  write. Write from the unlikely tail, not the obvious middle.
- **Dropped candidates.** The script drops any that use a cliché or are close to a recent pick.
- **The pick.** It chooses one of the rest by its own rng, weighted by your probabilities. Use the one it picked,
  even if you liked another better. If all five are dropped, it refuses: write five new ones.

## 4. Check: before anything is played

```
story_gen.py -c <camp> check
```

`skeleton` already runs this. Run it again after you edit the file by hand. Each genre has its own validator.

**Mystery** (fixed answer):
- every place, and so every clue, can be reached from the first place by following leads;
- who, how and why each have 3 or more clues, in 2 or more places;
- every place has a core clue (`obvious: true`), found by anyone who looks, with no roll;
- exactly one suspect has means, motive and opportunity, and every other suspect has a clue that clears them;
- in 1000 trial games where a third of the clues are missed, the case is still solved at least 95% of the time.
  "Who" also counts as solved when every innocent is cleared.

When a mystery fails, `check` repairs it one step at a time: it adds a lead to a place that is hard to reach,
adds a clue to the weakest conclusion, or gives a second "full" suspect an alibi. If repair cannot fix it, it
re-rolls the case and keeps the axes.

**Other genres:**
- **horror and the other ladder genres:** at least 3 steps that rise one after another;
- **romance:** an obstacle that comes from a character, not only from luck;
- **heist:** a target, 2 or more defences, an insider and the thing that goes wrong;
- **every genre:** no empty axis, and no seed fact contradicted.

Exit code 0 means ready to play, 1 means problems are listed, 2 means bad input.

## While playing

- **Prep situations, not plots.** The skeleton says what is true and what happens if nobody acts. It does not
  say what the players will do.
- **Core clues are never rolled.** A roll decides time, cost, danger and the extra `detail`.
- **When players stall.** Bring in a complication from the ladder that carries a clue.
- **Accusations.** Never reveal the truth. An accusation is recorded (`accuse`) and the world answers through
  what happens next.
