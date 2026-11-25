# Braid — the rules for a campaign with `**System:** core` (or `story`)

Read this whole file when state.md says `**System:** core` or `story`. It replaces the 5e rules for that campaign: no
levels, hit points, armour class, difficulty numbers, spell slots or rests by the clock. Everything else in SKILL.md
(narration, the display, saves, NPCs, the world engine) still applies. Braid is our own ruleset: one roll for every
genre; modules add tracks and tables, never a second way to roll. Numbers marked *(default)* are ours and adjustable;
they live in `data/braid.json`.

All Braid mechanics run on the world engine (`turn.py -c <campaign> resolve --intents '[...]'`; `turn.py help <action>`
prints each action's manual). Python keeps every number; you decide what it means in the story.

## 1. The roll

- **When:** only when the outcome is uncertain and both ways would be interesting. Otherwise say what happens.
- **How:** 2d6 + the approach the character uses (−1 to +3). A label that fits adds +1 (one label per roll). An
  unusually hard task is −1 or −2. There is no target number.
- **Before the dice**, say what is at stake and what a cost could be (`judge` with `risk`, `if_fails`, `cost`).
- **The ladder** (the same five steps the whole engine uses):

  | Total | Result | What you do |
  |---|---|---|
  | 3 or less | critical failure | a hard move (section 6), and it can be worse than the stakes said |
  | 4–6 | failure | a move: the stakes land |
  | 7–9 | success at a cost | it works; the player accepts the named cost or a worse position |
  | 10–11 | success | it works |
  | 12+ | critical success | it works and something extra: an opening, a clue, a step on a track |

  At +0 the odds are 8 / 33 / 42 / 14 / 3 %; at +2 they are 0 / 17 / 42 / 25 / 17 %. The middle result is the most
  common, so most rolls leave something to play.
- **Push:** before rolling, the player may push: +1, and they mark 1 stress. Not when stress is full.
- **Help:** a character with a bond (1 or more) to the roller adds +1 and shares whatever goes wrong.
- **Tokens:** each PC has a `tokens` pool, 1 at the start of each session, at most 3 *(default)*. Gain 1 when the
  character's flaw makes real trouble or they accept a hard bargain. Spend 1 right after a `roll` check (or a progress
  roll) to move it one step up the ladder; a `judge`, `flashback` or `bargain` settles its outcome at once, so push
  or get help before those instead. Engine: `{"action": "pool", "owner": "Mira", "id": "tokens", "max": 3, "set": 1, "cadence": "session"}`
  once, `{"action": "pool", "refill": "session"}` at each session start, `{"action": "pool", "owner": "Mira", "id":
  "tokens", "step_up": true}` to spend.
- **Engine:** `{"action": "roll", "actor": "Mira", "approach": "wits", "label": "pick the lock"}` rolls 2d6 + Mira's
  Wits from her sheet; conditions on that approach apply by themselves. Add `"push": true` or `"help": "Theo"`. With
  a label or a difficulty, send the whole modifier as a spec and keep the approach for its conditions
  (`"spec": "2d6+3", "approach": "wits"` = Wits +2 and a label). `judge`, `flashback`, `bargain` and `search` take
  the same `approach`, `push` and `help` (in the intent or its `roll`). With `roll_mode: players` the player sends the
  two dice added together.

## 2. Characters (the sheet)

One sheet for every genre, `characters/<name>.md`, made by `sheet.py new` (template `templates/sheets/core.md`):

- **Name and concept** — who they are, in one sentence.
- **Drive** — what they want. Acting on it when it costs them earns XP: this is how roleplay is rewarded.
- **Flaw** — what gets them in trouble. It earns XP (and a token) when it does.
- **Approaches** — how they act, not what they know. Give +2, +1, +1, 0, −1 in any order:
  - **Force**: strength, threat, endurance of the body
  - **Finesse**: speed, precision, stealth, a delicate hand
  - **Wits**: noticing, knowing, planning, improvising
  - **Heart**: charm, empathy, courage, reading people
  - **Grit**: holding on through pain, fear, cold and doubt
- **Labels** (2–3) — a profession, a past, a power: "Ex-navy pilot", "Hedge witch", "Knows every fence in town". A
  fitting label gives +1, or lets the character try what others simply can't.
- **Harm and stress** — kept by the engine (section 3), never written on the sheet.
- **Bonds** — who they are tied to. Write it on the sheet and record it in the engine (`{"action": "bond", "a":
  "Mira", "b": "Theo", "set": 1}`) so help works.
- **Gear** — what they carry, in the world's words. Gear makes an action possible; a fine tool can be a label's +1.

**Making a character** (`/dne character new`, or step 2 of `/dne new` for a Braid world): ask the player for the
concept, drive and flaw in their own words; offer the five approaches and let them place the array; agree on 2–3 labels
from their concept (the World Kit's `labels` are suggestions); pick a little gear and one bond with another PC or an
NPC. Then:

    sheet.py -c <campaign> new --name "Mira Vale" --concept "..." --drive "..." --flaw "..." \
        --approaches "wits=2,finesse=1,heart=1,force=0,grit=-1" --labels "Smuggler: knows every back door,Ex-navy pilot" \
        --gear "knife,forged papers" --bonds "Theo: he covered for her"
    sheet.py -c <campaign> check          every sheet against these rules (also at session start)
    sheet.py -c <campaign> show Mira      the sheet with harm, stress and conditions from the engine

## 3. Conflict and harm

A fight, a chase or a standoff is a scene of rolls, not rounds and initiative. Each player says what their character
does; you ask for the roll that matters; enemies never roll — they act through your moves when a roll misses or costs.

- **Harm** (track `harm`, 0–4 per character):
  | Harm | Means |
  |---|---|
  | 1 | Hurt: it shows, no penalty |
  | 2 | Wounded: −1 on Force and Finesse (the engine adds the condition) |
  | 3 | Badly hurt: also −1 on every roll |
  | 4 | Taken out: out of the scene. The player picks: knocked cold, captured, lost, or — only when the danger was deadly — dying unless someone helps before the scene ends |
- **Stress** (track `stress`, 0–6): fear, strain, exhaustion, pushing. At 6 the character hits a breaking point: no
  more pushes; they take a lasting **scar** (a condition, −1 on one approach, cleared at a milestone) and stress goes
  back to 0. Modules that bring fear or composure use this same track unless they say otherwise.
- **How much:** an enemy deals the harm of its threat (section 4): 1 from a nuisance, up to 3 from something
  overwhelming. Armour or cover that fits takes 1 off. Stress follows the same 1 / 2 / 3 for an unsettling, a
  distressing or a horrifying moment.
- **Engine:** `{"action": "track", "owner": "Mira", "id": "harm", "mark": 2, "why": "the guard's club"}`. The reply
  says what was crossed (Wounded, Badly hurt, Taken out); the conditions come and go with the track by themselves.
  `fight` may hold the objective and the zones; there is no HP and no `damage` in Braid.
- **Recovery** *(default)*: a night's rest (`wait`) clears 2 stress and 1 harm if the harm is below 2. Wounded or
  worse needs care: someone treats it (a roll, usually Wits or Heart with a fitting label) and each day of rest then
  clears 1 harm; a critical success on the treatment clears 1 at once. Send the recovery as `track` marks down
  (`"mark": -2`). A quiet scene spent on the character's drive or a vice clears 1 stress. A scene that ends sends
  `{"action": "pool", "refill": "scene"}`.

## 4. Enemies and threats

One line per enemy: **threat** (1–5), **harm boxes**, **harm it deals**, and two or three **moves** — what it does
when a roll against it misses. Named enemies also get a motive and a weakness.

| Threat | Harm boxes | Deals | For example |
|---|---|---|---|
| 1 | 1 | 1 | a nuisance: a thug, a guard dog |
| 2 | 2 | 1 | trained: a soldier, a cultist, a wolf |
| 3 | 3 | 2 | dangerous: a veteran, a beast, a gunman in cover |
| 4 | 4 | 2 | formidable: a champion, a monster |
| 5 | 6 | 3 | overwhelming: a dragon, a tank |

- **Mooks** run as a pack with one track: 3–5 of them are threat +1, 6–10 are threat +2. Each box of harm is one of them down or fleeing.
- **A PC's hit** (success, or success at a cost) deals 1 harm; +1 with a weapon or label that fits; +1 on a critical
  success. A threat 4–5 enemy is −1 to every roll against it unless the PCs found an edge (a weakness, a trap, help).
- **Taken out** at full harm — killed, routed, captured or yielding, as fits. Most enemies break before that: when
  the point of the scene is lost for them, they run or bargain.
- **Engine:** `{"action": "track", "owner": "Gate Guard", "id": "harm", "max": 2}` when it enters, `"mark": 1` per
  hit. NPC records: `npc.py add --threat <1-5>` writes the line. A World Kit lists `threats` (name, threat, moves).

## 5. Advancement

- **XP** *(default)*: 1 when the character acts on their drive and it costs them (once a session); 1 when their flaw
  makes real trouble (once a session); 1 for the first miss of a session that taught them something; 2 for each
  milestone — the party finished something that mattered (you name it). Mark it with
  `sheet.py -c <campaign> xp "<PC>" --why "<what they did>" --event <id>`; one id is paid once, so a retry is safe.
  Ask at session end which of these happened; the players answer, not you.
- **Every 5 XP buys one advance**, written by `sheet.py -c <campaign> advance "<PC>"` with one of:
  - `--raise <approach>`: +1 to one approach, never above +3;
  - `--label "<label>: <what it lets them do>"`: a new label;
  - `--move "<one narrow thing they do better than anyone>"`: a move, e.g. "When I talk my way past a guard, I never
    roll lower than 7".
- There are no levels. A veteran is a character with more labels, moves and a +3, not more hit points.

## 6. GM procedure

1. Describe the situation and ask "what do you do?". Follow the fiction; roll only by section 1.
2. Before a roll, name the stakes and the possible cost; on 7–9 make the player choose (`judge` asks them).
3. On a failure, make a move that follows from what is happening. Never "nothing happens"; the situation always
   changes. Moves:
   - inflict harm or stress, as established
   - separate them, or put someone in a spot
   - take away their stuff, or use it up (a usage die steps down)
   - show a danger coming, then make it arrive if they ignore it
   - advance a clock or a threat (`clock`, `progress`)
   - reveal an unwelcome truth
   - offer an opportunity, with or without a cost
   - turn their move back on them
   A critical failure gets a hard move now; a plain failure may get a soft one (a warning they can still answer).
4. When the players look to you for what happens next and no one rolled, make a soft move.
5. Give every enemy its moves and use them; let enemies run, surrender or change their minds.
6. Keep the numbers in the engine: harm, stress, tokens, bonds, clocks. Narrate what they mean.

## Story mode (`**System:** story`)

Braid without dice, for tables that want only the story. Same sheet, same tracks, same ladder; checks ask the
oracle instead: `{"action": "roll", "actor": "Mira", "likelihood": "likely"}` (likelihood from the situation and
the approach: a +2 approach where it fits makes it likely). yes-and = critical success, yes = success, yes-but =
success at a cost, no and no-but = failure, no-and = critical failure. There is no push or help: a token spent after
the answer moves it one step up, and helping is narrated and earns the helper's bond a mark. Harm, stress, XP and
advances work as above (an advance's `--raise` makes that approach count as one step more likely).
