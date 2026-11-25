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

**Pin every genre-defining ask.** The skeleton does not read prose: "a murder mystery" or "the Mayor's harvest
vault" does nothing unless you pin it (`mystery.crime=a killing`, `heist.target=...`, `cozy.season=...`).
`story_gen.py axes mystery,heist` lists every axis and its values, so you can pick the value closest to what the
players said. A pin may also be your own words. The only prose `check` catches is a fact that quotes another
value of an axis word for word ("it was a theft" when the skeleton rolled "a killing"): it then fails and names
the pin to add. A paraphrase is not caught.

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
    stand-in: flesh each clue with `--slot clue:<id>` (step 3) before the case reaches play, because `search`
    sends the text to the player's phone word for word.
  - **horror, slasher, analog-horror, war, competition, comedy:** a ladder of at least 3 steps that rise one
    after another. Play them in order. Do not jump to the top step.
  - **heist:** a plan with the target, two defences, the insider and what goes wrong.
  - **romance:** obstacles. One comes from a character, one from circumstance.
- **Setting genres keep their era.** wuxia, fantasy and historical leave out values that do not fit them (radios,
  guns, recordings, data…) in every genre in play; `axes` shows what each leaves out. A pin still wins.
- **In a campaign (`-c`).** A mystery's places become the campaign's map places (the party's place first, where
  the trail starts) and its suspects get the names of NPCs in npcs.md, as far as there are enough of each. Places
  the map lacks keep their generated names: add them to the map, or rename them with
  `story_gen.py -c <camp> name "<old place>" "<map place>"`. Name a suspect with `name s2 "<NPC name>"`; the name
  is on the suspect record, so `accuse` shows it to you. Run `skeleton` after the map and NPCs exist.
- **Re-rolling.** Rolling a new skeleton over one you never fleshed takes the old one out of the history, so a
  discarded roll does not weigh on later stories. Seed the pins first, then re-roll.
- **Replaying.** The output records `seed` and `history_at`. `skeleton --seed N --history-at K` replays it
  exactly and records nothing.

The skeleton is truth. Do not change the culprit, the method, the motive, where the clues are or what each
clue proves. If the players' seed facts forced something, it is already in the skeleton.

## 3. Flesh: you write five, the script picks

Do this for the prose that matters most: the premise, each core clue (`obvious: true`), the horror's first sign,
the insider. Hidden clues are cheaper: write 1 to 5 candidates for each, or run
`story_gen.py -c <camp> fill`, which gives every hidden clue you have not written a plain English line that does its
job ("Something here shows how it was done: …"). For a table in another language, write them yourself.

```
story_gen.py -c <camp> flesh --slot premise
```

This prints the givens, the facts and a `do_not_use` list (the genre's clichés plus recent picks). Then:

```
story_gen.py -c <camp> flesh --slot premise --candidates '[{"text": "...", "p": 0.06}, ... five ...]'
```

- **Clue slots.** With `--slot clue:<id>` the pick also becomes that clue's `text` in the case. The brief shows
  the clue's `job`: where it is, what it proves, where it points, whether it is core, and the suspects. **Every
  candidate must still prove what the clue proves and point where it leads: vary the detail, not the job.** The
  "(This points to …)" line is added by `search`; do not write it.
- **Write 5 candidates** (1 to 5 for a hidden clue). Give each a probability of at most 0.10, meaning each is one
  you would rarely write. Write from the unlikely tail, not the obvious middle.
- **Dropped candidates.** The script drops any that use a cliché or are close to a recent pick. The cliché list is
  English: it never matches text in another language, so keep clear of the `do_not_use` ideas yourself.
- **The pick.** It chooses one of the rest by its own rng, weighted by your probabilities. Use the one it picked,
  even if you liked another better. If every one is dropped, it refuses: write new ones.

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
re-rolls the case and keeps the axes, but only while no clue text has been written yet. A case with written
clues is never thrown away: fix the listed problems by hand.

**Other genres:**
- **horror and the other ladder genres:** at least 3 steps that rise one after another;
- **romance:** an obstacle that comes from a character, not only from luck;
- **heist:** a target, 2 or more defences, an insider and the thing that goes wrong;
- **every genre:** no empty axis, no pinned seed fact contradicted, and no prose fact that quotes another value
  of an axis.

Exit code 0 means ready to play, 1 means problems are listed, 2 means bad input.

## While playing

- **Prep situations, not plots.** The skeleton says what is true and what happens if nobody acts. It does not
  say what the players will do.
- **Core clues are never rolled.** A roll decides time, cost, danger and the extra `detail`.
- **When players stall.** Bring in a complication from the ladder that carries a clue.
- **Accusations.** Never reveal the truth. An accusation is recorded (`accuse`) and the world answers through
  what happens next.
