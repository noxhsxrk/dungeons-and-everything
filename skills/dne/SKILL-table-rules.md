# Table Rules — optional layers on top of 5e

Ideas borrowed from other games and rebuilt for 5e: the close-miss "success at a cost", GM moves,
playbook moves and bonds (Powered by the Apocalypse); tech levels, disadvantages and quirks, reaction
rolls, quick-build templates and social status (GURPS); degrees of success, monster stats by CR,
Victory Points, Hero Points, valued conditions, Treat Wounds, Focus Points, rarity and traits, and a
treasure curve (Pathfinder 2e); faction turns, enemy morale and instinct, and place tags (Worlds
Without Number). Only the ideas are used; every number and word here is our own.
Attacks, damage, spell slots and XP stay plain 5e; death saves too, unless `when_down: choices` (§12).

Read this file when a campaign uses any of these rules (see the flags below) or when the World Kit
has the fields in §8.

## 1. Flags (`state.md → ## Session Flags`)

| Flag | Values | Default | Effect |
|---|---|---|---|
| `success_at_cost` | on \| off | on | A check that misses the DC by 1–4 may still succeed, with a price (§2). |
| `degrees` | on \| off | on | Beating a DC by 10 or more is a critical success; missing by 10 or more is a critical failure (§2). |
| `hero_points` | on \| off | off | Hero Points replace Inspiration (§6). |
| `when_down` | saves \| choices | saves | `choices`: a character who would die picks how they fall instead (§12). |

Offer them at `/dne new` with the other Table Dials. Reaction rolls, Victory Points, Treat Wounds,
the treasure curve and the monster table are GM tools with no flag; use them when they help.

## 2. One roll, five outcomes

`dice.py d20+5 --vs check --dc 15` (or `--vs save`) prints PASS/FAIL and the outcome:

| Outcome | When | What you narrate |
|---|---|---|
| critical success | total ≥ DC + 10 | They get it and something extra: faster, quieter, a clue, an edge on the next roll. |
| success | total ≥ DC | They get what they wanted. |
| success at a cost | DC − 4 … DC − 1 | Offer it with a price; the player may take it or take the failure. |
| failure | otherwise | It doesn't work; the world moves (a soft move, §3). |
| critical failure | total ≤ DC − 10 | It goes wrong in a way that matters (a hard move). |

A natural 20 moves the outcome one step up, but a total below the DC rises no higher than success at
a cost. A natural 1 moves it one step down. Attack rolls and death saves are not on the ladder; they
keep their 5e crits.

**Prices for a success at a cost** — pick one that fits the fiction and say it plainly before they
accept: it takes much longer; it's loud and draws attention; they use up something (ammo, supplies, a
spell slot, a Hit Die); they take a little harm (1d6 or one level of a valued condition); they end up
in a worse position; someone they care about is exposed; they owe someone. Never make the price
"you fail anyway".

With `success_at_cost: off` the 1–4 band is an ordinary failure. With `degrees: off` the two critical
rows are ordinary successes and failures.

## 3. GM moves — how the world answers

Always on, alongside the DM Standards in SKILL.md.

- **Look for the move when the table goes quiet, on a failure, or on a critical failure.** Make it
  follow from the fiction; never from nowhere.
- **Soft moves** warn and set up: show signs of a threat coming; reveal an unwelcome truth; offer an
  opportunity with a cost; put someone in a spot; tell them the consequences and ask.
- **Hard moves** land with no chance to react: deal damage; take something away; separate them;
  use up their resources; turn their move back on them; make a threat real.
- Use a hard move only after a soft move went unanswered, or on a critical failure.
- **Principles:** address the characters, not the players; name every person and place; ask
  questions and build on the answers; make the world feel real and the stakes concrete; be a fan of
  the characters; think off-screen (Standard 11); sometimes give the decision back to the player.

## 4. Playbook moves (World Kit `moves`)

A world class may carry `moves`: short signature actions in that world's voice, each with a level,
a trigger and an effect. `lookup.py move <name> -c <campaign>` shows one. Level-up lists the moves
the new level opens; `character.py calc` lists the ones the character already has.

- A move works when its **trigger** happens in the fiction; the player doesn't spend an action to
  "activate" it unless the move says so.
- If the move calls for a roll, roll it on the ladder (§2).
- Write each character's moves on the sheet under `## Moves`.

## 5. Bonds, disadvantages and quirks — at character creation

**Bonds.** After the party is made, each player answers one question about each other PC, e.g.
*"Who here once saved your life?"*, *"Whose secret do you keep?"*, *"Who do you not trust yet?"*.
Write the answers under `## Bonds` on both sheets. Bring a bond into a scene at least once every
session or two.

**Disadvantages and quirks.** Each player may take up to two disadvantages (real trouble: a debt, an
enemy, a vow, an addiction, a wanted poster) and one quirk (colour: a habit, a fear, a phrase), from
the World Kit's `disadvantages` list or their own. Write them under `## Flaws & Quirks`.

- Use them as scene material, like faction moves.
- When a disadvantage costs the character something real in play, award Inspiration (or a Hero Point
  with `hero_points: on`), and say why.
- A quirk earns nothing; it's for character.

## 6. Hero Points (`hero_points: on`)

They replace Inspiration for the whole campaign.

- **Session start:** at `/dne load`, run `character.py hero reset --char <pc> -c <campaign>` for every
  PC (1 point, max 3).
- **Awarding:** whenever you would award Inspiration (Standard 12, a natural 20, bold play, a
  disadvantage that bit, a bond that drove a hard choice), run `character.py hero award`.
- **Spending one:** reroll any d20 the character just rolled and use the new result
  (`character.py hero use`).
- **Spending all:** when the character is dying, `character.py hero recover` spends every point;
  they are stable at 0 HP and their death saves reset.

## 7. GM tools

**Reaction roll.** The first time the party meets an NPC whose attitude isn't fixed by the story, roll
`reaction.py -c <campaign> --cha-mod <spokesperson CHA mod> [--status-diff N] [--mod ±1..2]`.

- Bands: hostile ≤2, unfriendly 3–5, indifferent 6–8, friendly 9–11, helpful 12+.
- `--status-diff` is the spokesperson's rank minus the NPC's in the World Kit `status_levels` (§8).
- Add `--npc <name> --apply` to write the result into `npcs.md`.
- Play the attitude, then let roleplay move it.

**Victory Points** handle chases, heists, infiltrations, persuading a council, research, and earning a
reputation: anything bigger than one roll and smaller than a combat.

- **Start:** `subsystem.py -c <campaign> start "<name>" --goal N [--limit M]`. Goal ≈ 2–3 per PC;
  limit = how many checks before time runs out.
- **Each attempt:** describe it, call the check, then run
  `subsystem.py -c <campaign> check "<name>" --total T --dc D`. A critical success adds 2, a success or
  success at a cost adds 1 (a cost still costs), a critical failure takes 1 away.
- **End:** narrate COMPLETE or OUT OF TIME. Decide the partial outcomes before you start.

**Treat Wounds.** Outside combat, a character with a healer's kit (or the world's equivalent) can spend
10 minutes treating one patient:

- Roll Medicine against DC 15, then `economy.py -c <campaign> treat --char <patient> --total T`.
- A critical success heals 4d8, a success 2d8, a success at a cost 2d8 plus a price, a critical
  failure deals 1d8.
- Each patient can be treated once per in-world hour; the script checks the calendar.
- Never at 0 HP; stabilise first. It does not replace Hit Dice; it is what non-magic worlds lean on.

**Focus Points.** A World Kit power marked `focus: true` costs a Focus Point instead of a slot.

- Pool = the character's number of focus powers, max 3. Set it with
  `character.py focus reset --max N --char <pc> -c <campaign>`.
- `character.py focus use` when a focus power is used.
- A short rest restores 1 Focus Point and a long rest restores all; `economy.py rest` handles both.

**Valued conditions** suit conditions that grow and fade: fear, static, bleeding, corruption.

- Define them in the World Kit's `conditions` with `valued`, `decay` and `penalty_on`.
- Apply one with `tracker.py -c <campaign> condition add <who> <condition> <N> --decay --penalty check,save`.
- The value comes off d20 rolls of those kinds (`dice.py --effects <who>`) and drops by 1 each time
  that creature's turn ticks.
- SRD conditions keep their 5e meaning; don't put a value on "frightened" unless the kit defines its
  own version.

**Monster stats by CR.** Before writing or adjusting a monster, run
`worldkit.py monster-stats --cr <CR>` for the typical AC, HP, attack bonus, save DC and damage of SRD
monsters at that CR. `worldkit.py warnings` flags kit monsters far outside those bands.

**Treasure.** `economy.py -c <campaign> treasure --level L --party N` gives a house budget per
encounter in the world's currency. Spend it as coin, gear or favours that fit the world. Rare and
unique items cost more than money.

## 8. World Kit fields (all optional)

| Field | Where | Meaning |
|---|---|---|
| `tech_level` 0–12 | `_meta` | What the world can build. Gear with a higher `tl` must be `rare` or `unique` (a relic). |
| `status_levels` | `_meta` | Social ranks, lowest first (for reaction rolls and NPC framing). |
| `rarity` | any record | common · uncommon · rare · unique. Buying rare/unique gear needs `economy.py buy --force`: the GM decides it's available. |
| `traits` | gear, powers, monsters | Short tags (loud, cursed, illegal, sacred …) for rulings and lookups. (On origins, `traits` stays the list of racial traits.) |
| `tl` | equipment | The item's tech level. |
| `moves` | classes | Playbook moves: `{name, level, trigger, description}` (§4). |
| `template` | classes | Quick build: `{abilities, skills, equipment}`; offer it at character creation for a fast start. |
| `disadvantages` | top level | `{name, kind: disadvantage\|quirk, description}` (§5). |
| `conditions` | top level | World conditions; `valued`, `decay`, `penalty_on` for valued ones (§7). |
| `focus` | spells/powers | A Focus-Point power (§7). |
| `morale` 2–12 · `instinct` 0–10 · `instincts` | monsters | Morale and Instinct (§10). 12 morale = never breaks (machines, the mindless, the fanatical). |
| `place_tags` | top level | `{name, description, enemies, friends, complications, things, places}`: this world's own place tags (§11). |

Tech levels (our labels): 0 stone tools · 1 bronze · 2 iron and early empires · 3 medieval ·
4 gunpowder and sail · 5 steam and industry · 6 electricity and the early 1900s · 7 mid-1900s ·
8 computers and the late 1900s · 9 today and the near future · 10 advanced near-future ·
11 interplanetary · 12 interstellar and beyond.

## 9. Faction turns (`faction.py`)

The world moves on a clock: every in-world week, each tracked faction does one thing off-screen.
world.md still says who a faction is and state.md how it feels about the party; `factions.json`
holds only its numbers.

- **Numbers.** Force (muscle), Wealth (money, goods), Influence (favours, secrets, reach), 1–5 each.
  Stability = 4 + the three; at 0 the faction has COLLAPSED and stops acting.
- **Goal.** One goal on a clock of 4, 6 or 8 segments, tied to the stat it is pursued with. Make it
  concrete and visible when it lands: *take the docks*, *buy the council vote*, *finish the
  machine*. A completed goal raises that stat by 1 (max 5); narrate it and set a new goal.
- **A turn** (`faction.py turn`, run at `/dne load`; it plays one turn per week since the last, at most
  4, and refuses when none is due). Each faction: regroups if Stability is at half or less; otherwise
  about one turn in three it strikes a rival (d10 + Force or Influence against the rival's d10 + the
  same; ties go to the defender; the loser loses 1 Stability, 2 if beaten by 5 or more); otherwise it
  works on its goal (d10 + the goal's stat: 8+ one segment, 12+ two, 3 or less backfires for −1
  Stability). A faction with no goal only regroups.
- **Telling it.** Each line `turn` prints becomes one line under `## Faction Moves` as something the
  party can notice: a rumour, a new face at the gate, a burned warehouse. Bring the biggest one in as
  a bang (Standard 13).
- **The party's hand.** When the party helps or hurts a faction, `faction.py adjust` its Stability or
  goal progress (sabotaging a plan: progress −1 or −2; a raid that guts them: Stability −2 to −4).
  `faction.py act` forces one chosen action when the fiction demands it.

## 10. Morale and Instinct (`tracker.py enemy`)

Creatures in 5e fight to the last hit point unless the GM decides otherwise. These two rolls decide
it for you, so the AI's monsters behave like living things rather than perfect tacticians.

- **Morale 2–12** (default 8). Roll `tracker.py enemy morale <name>` the first time any of these
  happens: the first of them falls; half of them are down; their leader falls; they see something
  overwhelming. Add `--mod 1` or `2` when things are especially bad, `--mod -1` when they have
  somewhere to fall back to. 2d6 above the score = BREAKS: they flee, surrender or beg to parley,
  whichever fits. Roll once per trigger for a group. 12 never breaks.
  Rough guide: cowards and conscripts 5–6, ordinary fighters 7–8, veterans and zealots 9–10, the
  mindless, machines and the undead 12.
- **Instinct 0–10** (default 3). Each round a creature might act on instinct, roll
  `tracker.py enemy instinct <name>`: d10 at or under the score means this round it follows its
  nature instead of the best move. It uses the monster's `instincts` if the World Kit gives any,
  otherwise one that fits its role. Animals and swarms 6–8, ordinary people 3–4, trained soldiers 1–2,
  machines 0–2. Roll for the ones that matter, not every goblin every round.
- **Someone at 0 HP is out of the fight.** Enemies turn to whoever is still standing. A creature hits a
  dying character only when its nature or orders demand it (a predator dragging off prey, a zealot with a
  grudge, "kill that one"); show it coming so the party can answer. `enemy advise` names who is down.
- `enemy set <name> --kit "<monster>"` copies role, morale, instinct and instincts from the World Kit.

## 11. Place tags (`tags.py`)

When the party reaches a town, district, ruin or court you haven't built, roll
`tags.py -c <campaign> roll`: two tags, each with an enemy, a friend, a complication, a thing and a
place drawn at random. `--all` shows every entry to choose from.

- Join the two tags: let an enemy of one be tied to a friend of the other, and make the
  complication something the party has to choose about.
- Name everyone and everything you use, and write the place into world.md like any other.
- The World Kit's `place_tags` (written in this world's voice) are drawn first; the 20 generic tags
  in `data/place_tags.json` fill in.

## 12. When a character goes down (`when_down: choices`)

With `saves` (the default) 0 HP is plain 5e: death saves, and three failures is death. With
`choices` a loss can be a turn in the story instead of the end of it.

- **When it applies:** a character's third death-save failure, a blow that would kill them outright,
  or a fight the party has lost with everyone down. Stop before narrating death and offer the choice.
- **Who chooses:** the fallen character's player, with the host agreeing. In a party, ask the player
  first; the host only steps in when the choice would undo what the rest of the table just did.
- **The choices** (each costs something real; name the cost before they pick):
  1. **Hold on.** They stay where they fell, stable at 0 HP (`tracker.py saves <name> stable`), and
     carry a lasting mark: a level of exhaustion, a scar that becomes a disadvantage, or something
     they carried is lost or broken.
  2. **Dragged clear.** An ally, a stranger or plain luck gets them out. They wake later at 1 HP
     somewhere safe for now, and the enemy got what it came for (the prisoner, the relic, the
     ground). Advance any clock it was racing.
  3. **Wake elsewhere.** They come to after the worst has already happened: captured, robbed and
     left for dead, or carried off by the enemy. Start the next scene from there.
  4. **Die.** Always on the table, and always the player's call; play it with the weight it deserves.
- **What stays the same:** death saves are still rolled; a natural 20 still brings them back at 1 HP.
  A creature that chooses to strike someone who is down (§10) is a threat to show and answer, and
  `choices` still applies if it lands.
- Write what happened to the character's sheet (`## Notes` or `## Flaws & Quirks` for a new mark)
  and to `session-log.md`.
