# Changelog

All notable changes to Dungeons & Everything are documented here. The project follows [semantic versioning](https://semver.org/) — `MAJOR.MINOR.PATCH` where MAJOR breaks an existing campaign or workflow, MINOR adds significant new capability, and PATCH fixes bugs without changing behavior.

The installed version is in the `VERSION` file at the repo root. Run `/dne update --check` to compare your local copy against `origin/main`.

---

## [Unreleased]

### Added
- **Supplies, season and weather; a fuller market (world plan PR 12).** `scripts/upkeep.py`, on only with `survival: on`: the table chooses what to track (`upkeep`: food, water, fuel, coin for wages, anything with a daily rate; things spent by the piece go through `use`). Stores fall exactly as in-world time passes, the same for one long skip as for the days taken singly, and a journey or rest stops with a decision when a store reaches `warn_days` of supply and again when it is gone. `worldkit.json → climate` gives seasons, daylight and daily weather that lengthen journeys, shorten sight in a fight and change how fast supplies go (`conditions`); an overloaded party travels half as slow again. Markets can produce (`makes`), receive regular deliveries (`restock`), carry a transport surcharge on goods a caravan brought (shown in the price's reason), ration when stock is low and buy on credit when short of coin. Campaigns that never turn survival on are unchanged.
- **Fights that use the map and end when the scene is settled (world plan PR 11).** `scripts/skirmish.py`: a `fight` states its objective and what ends it (`end_when`: someone reaches a square or zone, goes down, a side is beaten, a round passes); it is over when that is true, whatever HP is left. Line of sight and cover come from the grid, or from named zones for a fight told in words. `advise` lists what an enemy can really see and reach (an attack that needs sight never picks someone behind a wall) with moves its orders and the objective suggest. `move` checks the path and speed and gives a reaction to whoever's reach is left, asking the player when it is theirs; `spend` enforces one action, bonus action and reaction a round and limited resources; `damage` applies immunity, resistance and vulnerability to HP and reports the concentration save and the morale check; `area` finds who is caught and who a wall shelters. Set pieces: `props` that work once and `round_triggers` that fire as rounds pass. `cover_rule: off` turns cover off.
- **Spotlight, cases and what the players gave meaning to (world plan PR 10).** `scripts/table.py`: the engine notes who drove each action and tells the GM when a character has gone several turns without one; `group` collects what each member does and waits for anyone who has not said. A `case` holds the truth and its clues: `search` finds what is plainly there without a roll (a roll changes how long it takes and how much more turns up) and sends it to that player alone, `tell` shares it, `accuse` records a theory without making it true. `notice` sends each character the detail their own expertise would catch, each to their own phone. `remember` keeps a promise, gift, in-joke, habit or personal goal with its owner, who knows it and where it belongs; when its person, place or time is in the scene the GM is offered it as an opening (warm ones are never clues), and `payoff` rests it so it is not worn out. Nothing is forced: an opening left alone stays open.
- **Preparation and prevention change the story (world plan PR 9).** `scripts/stakes.py`: story beats can be registered with the conditions they need (`beat`); when the players remove one (`set`, or anything else that changes the world, time included) the beat closes with its cause on record: `prevented` under `beat_policy: players_can_prevent`, `needs_revision` under `must_land`. `situation` records what each side wants, what limits them, what they would trade and what happens if nobody acts; `judge` rules on a plan against those facts: no risk left means success with no roll, a remaining risk must name what changes on failure (and what a failure opens up), and "success at a cost" stops the turn until the player accepts or refuses the price. `reward` pays table XP once per encounter for the whole plan. New dial `beat_policy`.
- **NPC routines and factions that decide (world plan PR 8).** `scripts/routine.py`: an NPC can have a structured day (`npc_schedule`, with exceptions; the prose Schedule stays until the GM sets one) and appointments (`appointment`): they leave in time to arrive, cannot be booked into two places they could not travel between, follow their `otherwise` plan when they know the road is shut, and walk into the closure and turn back when they do not. Arriving, they meet who is there: news passes and a relationship is written to the graph. `where` answers where an NPC is at any minute. A faction's week is chosen from its own brief (`faction_brief`): rest, defend, negotiate a truce, postpone or carry on, by rule or by a submitted `faction_intent` that the engine checks for legality; the choice and its reasons are stored and replayed. A route's state is now news: both ends know at once, everyone else has to hear of it.
- **Witnesses, news and belief (world plan PR 7).** `scripts/knowledge.py` separates what happened (`fact`) from what each holder thinks happened (`belief`: holder, claim, source, when learned, confidence, and what they believed before). Only witnesses know a fact; `news` carries it to someone else by messenger, rumour, phone or radio (the last two only in a world whose kit has them), each line its own event that `intercept` can stop or delay without touching the others. `heat` is one faction's attention in one area and rises only on a fact that faction has heard of; it says when they may question people or seek an arrest. `knows` lists what a holder actually knows, with sources. The scene context shows what the place the party stands in has heard.
- **A bridge, a caravan and a market (world plan PR 6).** `scripts/trade.py`: a route has an owner and is open, tolled or closed (`route`); a market has stock, a fair price, a target and what the town uses each day (`market`), with a price that states its reason (`5 cp base × 2.0 (5 in stock, 10 wanted)`); a caravan (`caravan`) leaves on time, travels the map's roads, learns of a closed stretch by reaching it, reroutes or waits and tries again, and sells into the market on arrival. Characters `buy` and `sell` against real stock and coin: the last item goes to one buyer. A faction's finished goal can change who holds a road (`on_success`), if it has the strength and pays the cost. What the party can see is addressed to them; the rest goes to the GM.
- **Rests and journeys the world can interrupt (world plan PR 5).** `scripts/journey.py` adds the engine actions `rest` and `travel`. Time passes once, through the world clock. An event queued with `"interrupt": true` or a closed road stops the party at that minute and the turn waits for a decision (rest: continue / restart / stop; travel: continue / back / stop), then the rest of the plan is worked out again. A rest grants its benefit only when complete (2014: an abandoned long rest gives nothing; 2024: an hour or more counts as a short rest); who rests and who keeps watch is explicit. A journey is walked leg by leg: a place is marked visited and becomes the party's location only on arrival, and events waiting at a place fire when the party enters.
- **In-world time and a consequence queue (world plan PR 4).** `scripts/scheduler.py`: `advance` is the one way time passes in an engine campaign. Events carry a stable id, a due minute or a trigger (the party enters a place, a state becomes true), preconditions, a cause and an audience; a failed precondition cancels the event with the reason on record. Same-minute events run by priority then id and read the state the minute began with. Work is batched with nothing skipped. Faction weeks and timed effects ride the same clock, each event with its own seeded dice, so crossing 70 days in one step or in 70 gives the same world and no catch-up cap applies. `calendar.py advance` goes through it; `calendar.py set` is a correction that runs nothing. New actions: `wait`, `schedule`.
- **Scene context at the start of every engine turn (world plan PR 3).** `scripts/scene_context.py` gathers who the turn waits on, conditions in force, the place and who is present, who the input names (a nickname in any script finds the same record as the full name; "him again" resolves to the last person named, or the GM is told to ask), what just happened, the table's rules, then graph relationships and lore while the budget lasts. A player's view holds only what that character was told (another player's whisper is absent, not shortened); companions see public events. The whole `[[GM note]]` now has a length cap: what is due is never cut.
- **World engine, opt-in (`world_engine: on`; world plan PR 2).** `scripts/turn.py` runs a turn as begin → resolve → wait → finish over a per-campaign SQLite store (`world.db`): the same input never opens a second turn, a roll is made once, a message reaches the display once (stable message ids), and `status` / `resume` pick up a turn after a crash or a compaction. The display's own scripts carry the lifecycle (`autorun_wait.py` and `check_input.py` begin the turn, a plain `send.py` narration closes it); chat mode waits on no background process. First actions: `roll` and `ask`. Off by default: nothing runs and no file is created.
- **Undo covers companions, and an undone turn cannot come back (world plan, PR 1).** `turn_snapshot.py` now captures, fingerprints and restores the whole `companions/` folder (a companion who joined after the snapshot is removed and returns on `redo`), `npc-timeline.json` and the session-log archive. Every undo and redo starts a new timeline (`timeline.json` in the runtime dir): queued player actions and open dice requests are dropped, and a late message or roll for them is refused with "The story was rewound". The script tells the GM which companion agents to restart. Snapshots from older versions still open and leave the table's companion sheets alone.
- **NPCs are created for real and grow with time.** `scripts/npc.py add` gives a character a full record the turn they appear: the `npcs.md` row and an `npcs-full.md` entry with fair stats for their CR, aliases, and a `### History` (background, how they met); the GM writes the prose. `npc.py advance` grows an NPC who has been away: CR/Level, HP and AC go up (never down) and History gets a line about what they did. `npc.py check` lists records that are unfinished, incomplete or due to grow; `save_check.py` and the session-start checklist run it.
- **Two new dials** (Table Settings, Session Flags): `engine: full|light` (how much of play runs on the rules scripts) and `npc_growth: off|slow|normal|fast` (a step every 120 / 60 / 30 in-world days).
- **The in-world clock is checked.** `IN-WORLD CLOCK OUT OF STEP` when the date on the display is not the calendar's, with the command for each side: NPC growth and faction turns count from `calendar.json`.

### Fixed
- **Undo left the display on the undone turn.** Snapshots listed the display's files as `.stats.json` and `.log.json`, which never existed; they are `stats.json` and `text_log.json`, so the sidebar and feed are now restored with the turn.
- **A GM that reads no docs played without the engine.** In one session a GM ran 30 turns with only `send.py`, `push_stats.py` and `autorun_wait.py`: fights won by narration, XP typed onto the display, nothing written to disk, `/dne load` done from memory. The rules now travel in the output of those scripts (`scripts/gm_guide.py`), with real paths and line numbers:
  - **Fights:** every player action comes with how a fight is run (`combat.py init` so each enemy has HP and AC, `combat.py attack` per attack, a typed d20 passed as `--roll`).
  - **XP:** `XP NOT AWARDED BY THE ENGINE` when a PC's XP on the display or sheet is above what the sheet held at session start plus this session's `xp.py award` rows, with the command that fixes it.
  - **Saves:** `SAVE DUE` once 10 player turns (`DNE_AUTOSAVE_EVERY`) passed without `state.md` being written, repeated until it is. Agents without a Stop hook had no autosave at all.
  - **Load:** `push_stats.py --set-campaign` marks the campaign active itself (the marker was left stale, so `save_check.py` dated the session wrong) and prints a `SESSION START` checklist: what to read again and which scripts to run.

## [1.6.4] — 2026-11-24 — The game keeps going

### Fixed
- **Autorun froze after a declined or blocked reply on agents without hooks (Antigravity).** A turn that ended in a chat-only reply left no wait loop, and only Claude Code had a backstop (the Stop hook). New `display/autorun_watchdog.py` runs as a second background task and wakes the GM with `AUTORUN STALLED` when a player action has waited 90 seconds (`DNE_AUTORUN_STALL_S`) with nothing listening. `autorun_wait.py` now ends its output with a `[[GM note …]]`: how to end the turn, and to start the watchdog when it isn't running.
- **`/dne save` skipped relationships unless the players asked.** `save_check.py` ticked the relationship rows as soon as `npcs.md` was touched for any reason. Those rows now never tick themselves: the GM answers them NPC by NPC, with each NPC's current attitude shown.
- **Display jumped to the start of the story after switching tabs on a phone.** Each reconnect appended the replayed log under the transcript already on screen and smooth-scrolled across it. A replay now replaces the transcript and lands on the latest text in one step (or where the reader had scrolled to).
- **Rules a GM never read.** An agent that read only the top of `SKILL.md` never saw the `/dne save` procedure, the relaunch rule or the adults-only rule. `SKILL.md` now opens with four rules for the whole session: read every file to the end, read a command's section before running it (`save_check.py` for saves), never end an autorun turn without the wait loop, and romance only between clearly adult characters.

## [1.6.3] — 2026-11-23 — Narration always reaches the display

### Fixed
- **Narration that never reached the display.** When the GM answered player actions only in its chat (no `send.py`), the players saw nothing. `autorun_wait.py` now notices, on its next launch, that no narration arrived since it handed out the last actions, and tells the GM at once to send it (`NOT ON THE DISPLAY`). It warns once per turn; the Status panel's `/doctor` reports `last_narration_at`.

## [1.6.2] — 2026-11-23 — Examples in Table Settings

### Changed
- **Table Settings shows an example for each choice:** one scene per setting, and what the GM does with it at the option you picked.

## [1.6.1] — 2026-11-23 — Table Settings in English

### Changed
- **Table Settings page is in English**, matching the rest of the display.

## [1.6.0] — 2026-11-23 — Set the table your way

### Added
- **Table Settings page.** `display/setup.html` (at `/setup` when the display runs, and under Settings → Table Settings): tick every dial, press copy and paste the text to the GM, who writes it to Session Flags. It works on phones and as a plain file, and takes current values as a query string.
- **Four new dials:** `companions` (quiet/normal/chatty), `rolls` (few/normal/many), `show_dc` (on/off) and `turn_end` (open/options).

### Changed
- **Pacing you can feel.** The `pacing` dial is now `adventure` | `mixed` | `slow` (old `downtime` = `slow`), with a concrete limit on how often unasked trouble arrives: every scene, once per scene, or at most once per in-world day. Standard 6 says outright that a turn which just answers the player is a complete turn. `/dne new` asks about pacing, players can say "slow down" mid-game, and the world update audit adds `pacing:` to old worlds.
- **Romance is for adult characters.** Romance and intimacy at every `romance` setting need characters who are clearly adults and characters of unclear age count as under 18. No romance between family members. The GM cuts away and keeps playing.

## [1.5.0] — 2026-11-23 — A table that keeps playing

### Changed
- **CI is quick on every push** (ubuntu + the ASCII-locale job, about a minute). macOS, Windows and
  Python 3.10 run on release tags (`v*`) and on manual runs, so every release is still tested on all
  of them.

- **Display text is faster, with a "Show all" button.** Typing runs at 14 ms a character by default
  (was 36); Settings → Type Speed cycles Normal / Fast / Instant / Slow and is remembered per browser.
  While a long passage is still typing, a **Show all** button above the input shows the rest at once.
- **Display, Plain look:** Codex and Bubbles are a quiet toolbar at the top of the reading column
  instead of boxed buttons floating across the sidebar's edge.
- **New icon set.** Every display icon (block badges, the 13 class icons, sheet sections, HP/XP, the
  corner logo, favicons and app icons) is redrawn as one family of thin-line SVGs in a slate tone that
  reads on light and dark; the old PNG artwork is gone (4 MB lighter).
- **Display on a phone (Plain):** the top bar is one row of icon buttons (party, Codex, Bubbles | dice,
  settings, DM help, phone) with the scene name below it; Settings and Dice open as solid bottom
  sheets; settings rows share one style. The desktop rail uses the same icons.
- **Suggested-action chips are gone**; they took room from the story and the input.
- **The Codex reads like a page, not a markdown file.** Entries render their markdown (lists, bold,
  `code`, tables) instead of showing `**` and `-`; NPCs show a name with the role beneath; empty tabs
  say what will appear there. In the Plain look it is a calm reading panel with underline tabs.

### Fixed
- `autorun_wait.py` on Windows left `.autorun-waiter.json` behind (deleted the file while it was
  still open), so the Status panel could report the GM as listening after the loop ended.
- **Running the tests no longer touches a live game.** Tests posted to the display at
  `localhost:5001` and wrote the runtime `stats.json`, so a test run during play put test characters
  (Aldric, Bob, Reaper…) into the real party, and a phone that picked one got "error 403". Scripts
  now take the display address from `DNE_DISPLAY_HOST`, and `tests/conftest.py` points it, the runtime
  dir and the data dir at a throwaway sandbox.
- A phone whose character isn't in the current party now says so instead of "error 403".
- **iPhone: text and buttons no longer run past the screen edge.** Closed drawers were parked just off
  the right edge, and iOS widened the page to include them; on phones they are now clipped in place.
- The input field re-measures once the Thai webfont loads, so it no longer keeps a blank extra line.
- **`/dne save` works from a checklist.** `save_check.py` lists every part of a save, ticks what was
  already written this session (file times since `/dne load`) and names the NPCs who appeared in this
  session's narration, so relationships (npcs.md Attitude, state.md NPC dispositions, the graph) are no
  longer the part that gets skipped. The save procedure runs it at the start and the end, and the save
  summary must explain every unticked item. NPC entries gain `**Aliases:**` (the names used in play,
  e.g. a Thai spelling) so the check recognises them.
- **The Codex updates live** while it is open (every few seconds, without losing your scroll), and the
  Game Master now writes relationship changes and new NPCs during play rather than only at save.
- **The game doesn't stop.** `autorun_wait.py` registers itself while it waits
  (`.autorun-waiter.json`). In Claude Code the Stop hook now refuses to end an autorun turn while the
  display is up and nothing is waiting for players, and tells the Game Master to relaunch the loop.
  On every agent, the display has a **Status** panel (Settings → Status; on a phone ⚙ → Status) that
  checks the display, campaign, party and whether the GM is listening, explains what to do, and
  **resends** actions that got stuck (`GET /doctor`, `POST /doctor/retry`). A phone whose sent action
  isn't being picked up now says so ("the GM isn't listening right now — tap for Status") instead of
  "sit tight" forever.
- **Autorun no longer stalls after a declined request.** The Game Master is told that every autorun
  turn ends by relaunching `autorun_wait.py`, and that a refusal or redirect goes to the display as one
  short out-of-character line (`send.py --tutor`) before the scene continues, never only to the chat
  the players can't see.
- Codex NPCs: a table's header and `| --- |` separator rows were listed as people (`------ — ------`),
  and player characters appeared among the NPCs. Long entries are cut at a line break, not mid-word.

## [1.4.0] — 2026-11-23 — Living worlds, table limits, world versions

### Added
- **Ideas from Worlds Without Number** (our own numbers and text; `SKILL-table-rules.md` §9–11):
  - **Faction turns** — `faction.py`: Force, Wealth and Influence (1–5), Stability, a goal on a 4/6/8
    clock and rivals. `faction.py turn` at `/dne load` plays one turn per in-world week since the last
    (at most 4): each faction regroups, strikes a rival or works on its goal, and the printed lines go
    into `## Faction Moves`. `adjust` applies what the party did; `factions.json` is snapshotted with
    the other campaign files.
  - **Morale and Instinct** — `tracker.py enemy morale` (2d6 above the creature's morale = it flees,
    surrenders or parleys; 12 never breaks) and `enemy instinct` (d10 at or under instinct = it acts on
    its nature this round). World Kit monsters can carry `morale`, `instinct` and `instincts`;
    `enemy set --kit` copies them. `enemy advise` now points at the morale roll.
  - **Place tags** — `tags.py roll`: two tags for a town, district, ruin or court, each with an enemy,
    a friend, a complication, a thing and a place. 20 generic tags ship in `data/place_tags.json`; a
    World Kit's own `place_tags` come first.

- **Every world knows its version.** `/dne new` writes `dne-version.json` with the engine version the
  world was built with. At `/dne load`, `campaign_version.py check` compares it with the running engine
  and, when the world is older, shows what's new and asks the players whether to update the whole world.
  `campaign_version.py audit` lists everything to bring it in line: missing sections in state.md,
  world.md and character sheets, new Session Flags, World Kit errors, warnings and new optional fields,
  untracked factions, calendar and graph. Worlds made before this release count as older. Saying no
  is remembered until a newer version arrives.
- **Content level and safety tools.** A `content` Table Dial chosen at `/dne new`: `standard`, `18` or
  `20` (graphic violence, gore, horror and dark themes on screen; the table confirms its age). Sex stays
  off-screen at every level and hard limits never move. `lines` (never appears) and `veils` (off-screen
  only) are asked at the same time, and any player can stop a scene with `x`. `SKILL-content.md`
  tells the Game Master how to run `18` and `20` at full strength: concrete, consequential violence and
  horror with no disclaimers or softening, and an in-fiction cut-away for any single detail it won't
  write instead of stopping the game.
- **Romance dial.** `romance: off | fade | open` (asked at `/dne new` with the content level). Romance,
  attraction, jealousy and relationships become story threads; with `fade` a sexual scene cuts away
  and picks up after, with `open` (18/20 tables only) it plays on screen in sensual, non-explicit
  terms. Adults only, every partner willing, and a player character is involved only when its player
  steers there.

### Changed
- **Display, Plain look: a chat-style input box.** On the shared screen the input is docked under the
  story and always open (no Party drawer). On a phone (`?char=`) the tabs sit at the top and the input at
  the bottom, like a messaging app. Character chips and suggested actions are one scrollable row each; the
  text field grows as you type; the round button sends. On a keyboard, Enter sends and Shift+Enter starts a
  new line (Ctrl/Cmd+Enter still works); on a touch screen Enter is a new line. Sending, retrying, waiting
  for approval and errors now show as a line under the field instead of replacing the button's label.
- Shared screen on a phone: the side buttons become a row of icons at the top right, so the story uses
  the full width and the scene name no longer hides behind Codex/Bubbles.

### Fixed
- **Autosave hook only in game sessions.** The Stop hook now checks this session's transcript for a
  real `/dne` command or dne skill call; a coding session no longer gets "continuity checkpoint"
  prompts because an old game left its campaign marker behind. `install_autosave_hook.py` replaces an
  entry whose path no longer exists (e.g. after the skill folder became a link) instead of saying
  "already installed".
- **Chained sequels keep their world.** `campaign_chain.py` now carries `worldkit.json`,
  `factions.json`, `calendar.json` and `dne-version.json` into the new campaign; before, a sequel in a
  custom world lost its classes, powers, gear and monsters.
- `tracker.py enemy set` reset the role to brute and the morale threshold to 25% whenever it was
  called again (e.g. to add spell slots); it now changes only the options passed.
- Phone controller in the Plain look filled only the bottom half of the screen.
- Phone controller, every look: the "Who are you playing?" picker and the settings button were hidden
  behind the input panel; Codex/Bubbles covered the tabs.
- The last lines of the story could sit under the input panel on phones (the space reserved for the
  panel was overridden).
- On a desktop, the Codex button sat on top of the corner logo; text scrolled under the top buttons.

## [1.3.0] — 2026-11-23 — Table rules and the DnE engine

**The DnE engine.** From this release the rules engine is our own: a d20 engine whose core is the 5e
SRD (5.1 and 5.2, still fully compatible — every new rule is optional and switched per campaign), with
table rules layered on top that come from other games' ideas and our own numbers.

### Added — Table rules (ideas from PbtA, GURPS and Pathfinder 2e, rebuilt on the 5e SRD core)
- **One roll, five outcomes.** `dice.py --dc` on a check or save now prints critical success · success ·
  **success at a cost** (1–4 short) · failure · critical failure; a natural 20/1 shifts it a step.
  Attacks and death saves keep their 5e rules. New DM Standard 15, *Every Roll Moves the Story*:
  soft and hard GM moves, prices for a close miss. Flags `success_at_cost` and `degrees` (on).
- **World Kit gets richer** (all optional, all validated): `_meta.tech_level` (0–12) and
  `status_levels`; `rarity`, `traits` and `tl` on gear (buying rare/unique needs `--force`);
  playbook **`moves`** per class (listed at creation and level-up, `lookup.py move`); a **`template`**
  quick build per class; **`disadvantages`** and quirks (`lookup.py disadvantage`); world
  **conditions** with values; **`focus`** powers. The example kit shows every field.
- **Monster stats by CR**, measured from the 334 SRD monsters (`data/monster_stats_by_cr.json`,
  `build_monster_table.py`): `worldkit.py monster-stats --cr 3` prints typical AC/HP/attack/DC/damage,
  and `validate` warns when a kit monster is far outside them.
- **Character creation:** Flaws & Quirks, a Quick build from the class template, and party **Bonds**
  (one question per other PC). New sheet sections: Moves, Bonds, Flaws & Quirks.
- **Hero Points** (`hero_points: on`, replaces Inspiration): `character.py hero reset|award|use|recover`.
  **Focus Points**: `character.py focus reset|use|refocus`; short rests restore 1, long rests all.
- **GM tools:** `reaction.py` (2d6 NPC reaction, writes the attitude to `npcs.md` with `--apply`),
  `subsystem.py` (Victory Points for chases, heists, influence; undo-safe), `economy.py treat`
  (Treat Wounds, once per patient per in-world hour), `economy.py treasure` (house treasure curve),
  valued conditions in `tracker.py` (`condition add X static 2 --decay --penalty check,save`).
- Rules reference: `skills/dne/SKILL-table-rules.md`. No rules text from those games is copied.

### Changed
- **Wording: the DnE engine.** The README now describes the rules as the DnE engine — a d20 engine
  with the 5e SRD at its core — instead of "plain D&D 5e"; the cover reads *Any world. One d20 engine.*
  The SRD credit (CC BY 4.0) is unchanged.
- **README:** new Table rules and Play together sections, World Kit rows for moves, quick builds,
  flaws and tech level, the Plain display, and five new images (the five play-tested worlds on the cover
  and in the strip, the Plain table display, a table-rules spread).
- **The display is plain by default.** A new **Plain** skin (Settings → Skin) is the default for new
  devices: quiet grey colours with a muted slate accent, one sans face (Noto Sans / Noto Sans Thai), no
  capitals, letter-spacing, shadows, background art or particles, in light and dark. Vellum and
  Editorial are still in the skin menu, and a device that already chose a skin keeps it. On phones the
  input stays a compact bottom bar; the controller textarea no longer runs past the panel edge.

### Fixed
- **`install.py` on Windows and non-UTF-8 consoles** no longer crashes printing `→` (cp1252 / ASCII);
  it writes UTF-8 like the skill's scripts. On Windows the rules block it writes now uses native paths
  (`D:\\…\\skills\\dne\\SKILL.md`) instead of mixing `\\` and `/`. CI: tests that need Thai file names or arguments skip only
  where the OS can't represent them (the ASCII-locale job); the rest still run there.
- **Thai on the display:** vowels and tone marks no longer float or sink. The fantasy faces (Cinzel,
  IM Fell, Syne, Newsreader) have no Thai, so every font stack now carries Noto Serif Thai / Noto Sans Thai
  for Thai text only (English keeps its fantasy face), and once Thai text appears the page turns
  `lang="th"` and drops letter-spacing, which broke Thai mark placement.

## [1.2.0] — 2026-11-23 — Any agent, Thai tables, polish

### Added
- **Thai tables, end to end:** `calendar.py init --lang th` prints the time of day in Thai
  (`กลางคืน (22:00 น.)`) and accepts Thai time words; the relationship graph's deterministic extractor
  reads Thai session logs (new Thai verb table: พบกับ, จับตาดู, ทรยศ, ทำงานให้ …) and Thai NPC/place names.
- `lookup.py subclass <name>` now finds SRD subclasses too (Champion, Life Domain …), with their features by level.
- Origin skills are automatic: `character.py calc` adds a skill an origin grants — from the origin's
  `skills` list or a trait that names one ("ชำนาญทักษะ Sleight of Hand", Elf Keen Senses, Half-Orc Menacing).
- `character.py levelup … --char <name>` leaves powers the character already knows out of the list to learn.
- **Works with any AI agent**, not just Claude: `python3 install.py` links the skill into every agent it finds
  (Claude Code, Codex, Gemini CLI, Antigravity, opencode, Copilot, Crush, Droid, dsh) or writes a pointer
  into rules-file agents (Cursor, Kiro, Cline, Continue, Kilo Code, Amp, Qwen, Goose, Kimi); `--list`,
  `--uninstall`. SKILL.md maps the host-specific bits (skill dir placeholder, question tool, background
  tasks, subagents) to whatever the host has, with plain fallbacks.

### Fixed
- 2024 campaigns: XP awards and `xp.py calc` use 2024 budgets with no group multiplier (`calc -c/--ruleset`);
  mixed-level parties sum each character's encounter budget; level-up lists 2024 features (Tactical Mind,
  Magical Cunning …); rogue weapon mastery; fighting styles and invocations look up inside a 2024 World Kit
  campaign.
- Level-up lists only the chosen subclass's features (a world subclass that re-skins a non-SRD subclass
  leaks none) and never option sub-features like Pact of the Chain.
- A character at 0 HP can't spend Hit Dice on a short rest; `tracker status` shows DEAD after three failed
  death saves; `scene-context` shows the party's stance toward factions it lists; `graph show` prints levels.
- Thai titles อาจารย์, แม่หมอ, พ่อหมอ, หมอ are stripped for duplicate checks; origin ability bonuses are labelled
  as 2014-only.
- Any-agent docs: procedures write the data root as `${DNE_CAMPAIGN_ROOT:-$HOME/.dne}` instead of a literal
  `~/.dne/`, and SKILL.md tells agents where campaign files live and to read rules data only via the scripts
  (found by an Antigravity CLI play-through, which otherwise ran with zero errors).
- Final replays: 2024 fighting styles look up their 2024 (feat) text; 2024 level-up owes Expertise at rogue 6 /
  bard 9; 2024 encounters and XP use Low/Moderate/High bands (the budget is a ceiling; no Deadly tier);
  a character at 0 HP gets nothing from any rest; a short rest can't heal past the Hit Dice left;
  `calendar.py init --gregorian` takes local month/day names (Thai); items written `- หอก (×2)` can be sold.
- Re-verification polish: sell `- 2× item` and `- item (note)` lines; characters resolve by any word of their
  name or without a Thai title (จ่า, สารวัตร, ผู้หมวด, ผู้การ added); the economy ledger records the sheet's own
  name; `lookup.py subclass <name> -c` shows a world subclass; long-rest reports count restored slots and
  cleared Temp HP; 0-HP characters stay down at combat end and gain nothing from `calendar.py rest long`;
  2024 exhaustion applies to death saves.
- `redo` refuses once play has continued after an undo (it used to roll the whole later session back);
  its message now says what it re-applied. Encounters label mixed-level parties by level (L4+L3).
- Display: Thai character names open their sheet on phone/TV; the player codex no longer shows DM prep
  (world.md's mystery answer and truths, Faction Moves, dm_only nodes) — locations and factions come from
  non-secret graph nodes; no SRD reference links in a World Kit campaign.
- Docs: tick effects at the start of a creature's turn; `--since 1` for pre-campaign graph facts; fixed step
  references; level-up updates the sheet's next-XP threshold; World Kit starting money.

## [1.1.0] — 2026-11-23 — Played, fixed, 2024-ready

### Added
- **Bundled 2024 (SRD 5.2) dataset** — feats, weapon mastery properties (on every weapon), species and
  backgrounds. `lookup.py feat|mastery|species`; 2024 lookups fall back to 2014 for invocations, pact
  boons and fighting styles.
- **2024 rules in play:** weapon mastery owed at level-up, origin feat on the sheet (Alert adds to
  initiative), −2 per exhaustion level on d20 tests, all Hit Dice back on a long rest, 2024 encounter
  budgets (per character, no group multiplier), `combat.py attack --mastery` with SRD 5.2 text.
- **Players roll their own dice:** `combat.py init` takes each player's `"roll"` (plus `init_bonus`,
  `max_hp`); `combat.py attack --roll N`, `--adv/--dis` with both naturals, `--crit-range 19`, compound
  damage (`1d6+5+1d4 piercing`); `character.py hitdie --roll`; `dice.py --player` marks local rolls.
- `turn_snapshot.py redo`; undo now covers the calendar, XP ledger, World Kit and session tail.
- `tracker.py effect start … --until <caster>` for "until your next turn" effects.
- `calendar.py init --gregorian` (real month lengths and weekdays), `advance N minutes`, `set --hour N`.
- `character.py calc`: spellcasting block (DC, attack, slots), `--expertise`, Passive Perception, owed
  subclass at creation; `levelup` lists new chassis features, spell/pact/cantrip progression, eligible
  kit powers, world pact boons and invocations.
- World Kit: world subclasses, `class_options` re-skins, `_meta.power`; much deeper `worldkit.py
  validate` (origin +3, background skills, chassis spell exists at the same level, casting classes have
  powers, monster role/biomes/hp, 2024 mastery/feat fields) plus warnings for step-7 counts;
  `worldkit.py show` is a readable tour. The example kit is a complete, warning-free world.

### Fixed
- `tracker.py clear` / `check reset` no longer corrupt the tracker; `check log` no longer crashes;
  `clear` keeps a dying PC unconscious and drops encounter enemies.
- XP: each PC gets raw monster XP ÷ party size (the multiplier only rates difficulty), per-character
  thresholds for mixed levels, small/large party multiplier steps; sheets found by display name.
- Economy: World Kit currency (`100 sc`, decimals); selling only touches the inventory; quantities
  instead of duplicate lines; weapons and armour filed under their own labels; rests follow the rules
  (0-HP gate, Temp HP cleared, warlock pact slots on a short rest).
- No SRD content leaks into a World Kit campaign (spells, magic items, monsters, classes) unless
  `srd_fallback` is on; rules (conditions, features) still merge.
- Thai: names keep vowels and tone marks in the name registry and graph ids; Thai and Ayutthaya-era
  titles are stripped for duplicate checks; readable Thai in lookup output and combat state.
- Calendar: bad dates and time labels are refused, weekdays run across months, display pushes work.
- 2014 class features in the bundled data are 2014 text again (and include the SRD subclass features).
- Encounters: an unknown world biome is an error, budgets are actually used, party size/level come from
  the character sheets, the difficulty label matches what was built.
- Session tail scripts honour `DNE_CAMPAIGN_ROOT`; `session_recap` no longer calls a level-up healing.

### Changed
- One rest procedure (`economy.py rest` writes sheets, `calendar.py rest` moves time), one NPC attitude
  scale (hostile → suspicious → neutral → friendly → allied), backups go to `<root>/.backups/`.
- The display/autorun choice made at `/dne new` or `/dne load` is respected (`display: none` works);
  `state.md` defaults to `roll_mode: players`.
- In a 2014 campaign a background grants skills only; `--background-asi` is a 2024 rule.

## [1.0.0] — 2026-11-22 — First release

### Any world, 5e rules
- **World Wizard.** `/dne new` asks the players to describe any world — sci-fi, post-apocalyptic, horror,
  cyberpunk, mystery, or classic fantasy — in their own words.
- **World Kit** (`<campaign>/worldkit.json`). The AI builds the world's infrastructure as legal D&D 5e content:
  origins (races), professions (classes on a 5e `chassis`) with their own subclasses, backgrounds, powers
  (re-skinned spells), gear, currency, a lexicon of renamed terms, renamed skills, and a bestiary of full 5e stat
  blocks with CR-correct XP and world biomes. Names may be in any script (Thai included).
- `scripts/worldkit.py validate | show` — every kit is checked before play.
- `lookup.py --campaign`, `character.py calc|levelup -c`, `encounter_gen.py -c` and the display's lookup read the
  kit ahead of the bundled SRD. World categories replace the SRD's; rules categories (conditions, features,
  class options) always merge. A campaign without a kit runs classic fantasy on the SRD.

### Game Master engine
- Persistent campaigns in plain markdown under `~/.dne/` (override with `DNE_CAMPAIGN_ROOT`): state, world,
  NPCs, session log, characters, and a global character roster.
- Improvised campaigns with a committed three-act dynamic arc, or structured campaigns imported from PDF,
  markdown, DOCX or text (`/dne import`).
- D&D 5e 2014 (SRD 5.1) and 2024 (SRD 5.2) rulesets, chosen per campaign.
- Scripts for dice, combat, initiative, conditions, character creation and level-up, XP, economy and rests,
  in-game calendar and timed effects, per-turn rollback, encounter generation, role-aware enemy tactics,
  tension meter, world map and travel, tactical battlemap, event ledger, relationship graph, lorebook,
  name registry, autosave checkpoints, and autonomous companions played by their own subagent.
- Cinematic display companion: typewriter narration, dice, live party sheets, TTS, SFX, private whispers,
  codex drawer, phone input, ngrok or LAN remote play, autorun turn loop, full Thai/Unicode support.
- Optional physical dice server.
- Runs in Google Antigravity (`/dne`) and Claude Code (plugin `dne`).
