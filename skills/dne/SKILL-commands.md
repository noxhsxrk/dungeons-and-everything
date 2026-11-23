# Dungeons & Everything — Command Procedures

Full step-by-step procedures for all `/dne` slash commands. Load this file at `/dne load` or before executing any slash command.

> **Path note:** All helper scripts and templates are located in `${CLAUDE_SKILL_DIR}/` and can be invoked directly with the absolute commands shown below.

---

## `/dne new <campaign-name> [theme]`
1. **Session setup — call `AskUserQuestion`** with **three questions**:

   **Q1 *"Display & input mode?"***
   - `Display + autorun (ngrok) (Recommended / Default)` → `bash ${CLAUDE_SKILL_DIR}/display/start-display.sh --ngrok`, print public ngrok HTTPS URL, set `_display_running = true`, write `autorun: true` to `state.md → ## Session Flags`, then `python3 ${CLAUDE_SKILL_DIR}/display/push_stats.py --clear`. Always enter the autorun wait loop (`autorun_wait.py`) at the end of each turn.
   - `Display + autorun (LAN)` → `bash ${CLAUDE_SKILL_DIR}/display/start-display.sh --lan`, print both URLs, set `_display_running = true`, write `autorun: true` to `state.md → ## Session Flags`, then `--clear` as above.
   - `Display (local)` → `bash ${CLAUDE_SKILL_DIR}/display/start-display.sh`, print URL, set `_display_running = true`, then `--clear` as above.
   - `No display` → continue without display; write `display: none` and `autorun: false`.

   Record the choice as `display: ngrok|lan|local|none` in `state.md → ## Session Flags` (written in step 4). If the question is dismissed, use `Display + autorun (ngrok)`; an explicit `No display` always wins over that default.

   **Q2 *"Dice rolls?"*** — set how PC d20s are handled (see SKILL.md "Dice convention"):
   - `Players roll their own` (default) → write `roll_mode: players` to `state.md → ## Session Flags`. You will call for each PC roll and wait — never auto-roll a PC.
   - `DM rolls everything openly` → write `roll_mode: auto`. You resolve PC rolls yourself with full math shown.

   Default to `roll_mode: players` if the question is dismissed.

   **Q3 *"How much of the game runs on the rules engine?"*** — written to `state.md → ## Session Flags` in step 4; default `full` if dismissed.
   - `Full (Recommended)` → write `engine: full`. Every fight is tracked on the scripts (HP and AC for each enemy, each attack resolved) and XP comes from the tables.
   - `Light` → write `engine: light`. You judge fights and XP yourself and call for the rolls that matter; saves, NPC records and the in-world clock are still kept.
2. **Ruleset selection.** Ask: *"D&D 5e ruleset for this campaign? **2014** (SRD 5.1, default — full mechanics, classic Player's Handbook structure) or **2024** (SRD 5.2, weapon mastery + origin feats + background ASIs + revised exhaustion)?"* Default to `2014` if no answer or ambiguous. Write the chosen value to `state.md` header line as `**Ruleset:** 2014` or `**Ruleset:** 2024`.

   If 2024 was chosen: verify the dataset exists with `ls ${CLAUDE_SKILL_DIR}/data/dnd5e_srd_2024.json`. If missing, offer to run `python3 ${CLAUDE_SKILL_DIR}/scripts/build_srd.py --ruleset 2024` (one-time, ~3 min, needs network). Until it exists, `lookup.py` uses the 2014 SRD automatically (it prints a one-line notice) — World Kit content is unaffected.
3. `mkdir -p "${DNE_CAMPAIGN_ROOT:-$HOME/.dne}/campaigns/<name>/characters"`
4. Copy templates from `${CLAUDE_SKILL_DIR}/templates/` — state.md, world.md, npcs.md, npcs-full.md, session-log.md (worldkit.json is written in step 7) — and replace every `<campaign-name>`/`<date>` placeholder in them. The state.md header keeps the `**Ruleset:**` field from step 2 and the Session Flags from step 1. Template wording is fantasy-neutral but generic — rewrite any placeholder that doesn't fit the world once step 6 has defined it.
   Then stamp the engine version on the new world: `python3 ${CLAUDE_SKILL_DIR}/scripts/campaign_version.py -c <campaign> stamp` (writes `dne-version.json`, so later versions know what this world was built with).
5. Ask: **party size** and **starting level**. Write them to the state.md header (`**Party size:**`, `**Starting level:**`).
6. **World Wizard — the players define the world.** Ask one open question (prose, not a menu): *"What world are we playing in? Describe it however you like — genre, era, what happened to it, who the players are, how it starts. Or say **classic fantasy** for traditional D&D."* Accept anything from one word (*"cyberpunk"*) to a full setting document. If `[theme]` was supplied, treat it as the start of this description and ask only what's missing.

   Then, in one message, confirm or fill four dials (pre-fill everything the description already answers). Randomise a blank only if the player asks you to choose — roll with `dice.py` on the die given and log `"dN=X → [result]"` in world.md:
   - **Genre tags:** free-form, 1–4 (e.g. `sci-fi · post-apocalyptic · survival · mystery`)
   - **Tone:** `grimdark / dark / heroic / horror / political / swashbuckling / cosmic / noir / hopeful` (or the player's own word) — random: d10, 1–9 in that order, 10 = re-roll
   - **Power level:** how common and strong the world's supernatural or advanced powers are (magic, tech, psionics, mutation) — `none / low / medium / high` (random: d4 in that order). It shapes the kit in step 7: `none` → no casting chassis at all; `low` → at most 2 casting classes, spells to level 3; `medium` → up to half the classes cast; `high` → most classes may cast.
   - **Danger level:** `lethal / gritty / standard / heroic` (random: d4 in that order). Also set the matching Table Dial `difficulty` in Session Flags: lethal → `deadly`, gritty → `hard`, standard → `standard`, heroic → `easy`. Then ask about **content** in the same message: *"How hard should it hit? `standard`, `18` (everyone at the table is 18+) or `20` (everyone is 20+). Anything that must never appear (lines), or that should happen only off-screen (veils)?"* Choosing 18 or 20 is the players confirming their age; if anyone at the table is younger, use `standard`. Ask about **romance** in the same breath: *"Romance and sex in the story: `off`, `fade` (it happens, the scene cuts away) or `open` (intimate scenes on screen, 18+ only)?"* Romance only ever involves adult characters; in a school setting the students are under 18 and stay out of it. Write `content:`, `romance:`, `lines:` and `veils:` to Session Flags (SKILL.md → Table Dials). Ask about **pacing** too: *"How often should trouble come: `adventure` (constant pressure), `mixed` (default) or `slow` (slow burn, quiet turns, you drive the story)?"* Mention the other Table Dials (`spotlight`, `companions`, `rolls`, `show_dc`, `turn_end`, and the table rules `success_at_cost`, `degrees`, `hero_points` — SKILL.md, SKILL-table-rules.md) in the same message; leave them at their defaults unless the player picks. Offer the Table Settings page too, so they can tick everything at once instead of typing: `<display URL>/setup` when the display runs, otherwise the file `${CLAUDE_SKILL_DIR}/display/setup.html` (it takes the current values as a query string, e.g. `setup.html?pacing=slow&content=18`).

   **Classic fantasy** → skip step 7; the bundled SRD is the world's content (no `worldkit.json`). Continue at step 7b.

7. **World Kit — build the world's infrastructure (Strongest tier).** Everything a 5e table normally takes from the Player's Handbook and Monster Manual is re-imagined for *this* world and written to `<campaign>/worldkit.json` (schema: SKILL.md → *World Kit*; full example: `${CLAUDE_SKILL_DIR}/templates/worldkit.example.json`). Derive every entry from the player's description — reuse their names, factions, enemies and roles verbatim where they gave them.
   - **`_meta`** — `name`, `genre`, one-line `premise`, `power` (the step-6 power level: none/low/medium/high), `base_ruleset` (the step-2 ruleset), `srd_fallback: false`.
   - **`lexicon`** — 8–15 renames of 5e terms that would break immersion here (spell, spell slot, cantrip, magic, gold, long/short rest, temple, tavern, dungeon…). **`currency`** — the world's money.
   - **`skills`** — rename only the SRD skills whose names don't fit (Arcana, Religion, Nature, Animal Handling usually; keep the governing ability).
   - **`races`** — 3–6 origins/peoples/backgrounds-of-birth that exist in this world; each with legal 5e ability bonuses (total +3: +2/+1, or +1/+1/+1), speed, size, 2–3 traits on par with SRD racial traits, languages, and `skills` for any skill proficiency a trait grants (`character.py calc` adds them automatically). If the world has only humans, make origins out of upbringing or augmentation.
   - **`classes`** — 5–8 professions players would plausibly be (use the roles the player named — e.g. soldier, mechanic, infiltrator, ex-EDEN technician). Each picks the SRD **`chassis`** whose mechanics fit (armed fighter → `fighter`, stealth specialist → `rogue`, tech caster → `wizard`, healer → `cleric`, scout → `ranger`, unarmed brawler → `monk`, berserker → `barbarian`, face/charmer → `bard`, innate power → `sorcerer`, bargain-with-entity → `warlock`, nature/mutation → `druid`, crusader → `paladin`). Add `power_source` (`none`, `tech`, `psionic`, …) and a one-line `description`. If a chassis casts spells, the class's powers come from the kit's `spells`. A role the player named that is really a birth or people ("half-kinnaree", "tunnel-born") becomes an origin, not a class. In a `power: none` world only fighter, rogue, barbarian and monk qualify (ranger and paladin cast from level 2); a non-magical healer is a rogue or fighter whose description leans on Medicine plus the kit's healing gear. Chassis features that are plainly supernatural (a monk's Empty Body, a totem barbarian's rituals) are re-described as training or grit in the class `description`, or noted as "not available in this world" — never silently kept.
   - **`narrative_dna`** — how this world is told, so it does not sound like every other one: `sensory_palette` (the smells, sounds and light that belong here), `humor_style` (dry, dark, warm, none), `conflict_flavor` (court intrigue, scarcity, psychological, over-the-top action) and `taboo_cliches` (phrases and images that would break the tone; the style guard flags them). Optional: `climate` (seasons with `months`, `travel`, `light_hours`, `supplies`, `weather`) and `communication` (`{"phone": true, "radio": true}`) for the world engine.
   - **`backgrounds`** — 4–6, each with exactly 3 `ability_options` and 2 skills (SRD skill names or the kit's renamed ones). In a 2024 campaign also give each a `feat`: one SRD 5.2 origin feat (`lookup.py feat <name> --ruleset 2024` — Alert, Magic Initiate, Savage Attacker, Skilled …).
   - **Ability increases follow the ruleset, never both:** 2014 → the origin's `ability_bonuses` apply (`calc --race`) and background `ability_options` are ignored; 2024 → the background's +2/+1 or +1/+1/+1 applies (`calc --background … --background-asi …`) and origins grant traits only. Write both fields anyway so the kit works under either ruleset.
   - **`classes[*].subclass_label` + `subclasses`** — the world's own specialisations, 2–3 per class, each `{name, description}`. The first re-skins the chassis's SRD subclass (the only one the bundled data covers — e.g. Champion, Thief, Life Domain, Evocation); the others may re-skin any 5e subclass the table knows, and must then spell out their key features in the description because the engine has no data for them. `character.py levelup -c` offers these instead of the chassis's SRD subclasses.
   - **`class_options`** (warlock chassis only) — re-skin the invocations the world's warlock-type classes will meet (at least the level-2 ones): `{name, index, kind: "invocation", level, description … (chassis: <SRD invocation>)}`. Level-up then lists these instead of SRD invocation names.
   - **`spells`** — the world's powers, counted **per casting class**: cantrips for every chassis that has them (at least its starting count), at least 4 level-1 powers per class (6 for a wizard chassis — the starting spellbook), and 3+ per class at levels 2 and 3. One power may list several classes. Re-skin an SRD spell's exact mechanics and end the description with `(chassis: <SRD spell name>)`; the validator checks that name exists in the bundled SRD 5.1 (Hex, for example, does not — use Hellish Rebuke or Bane instead). In a world with no powers, use only non-casting chassis and omit `spells`: with `srd_fallback: false` no SRD spell or magic item is reachable in this campaign.
   - **`equipment`** — signature weapons (5e damage dice/properties; in 2024 a `mastery` property from `lookup.py mastery <name> --ruleset 2024`), 3–4 armors with valid `ac` strings, key gear and consumables, priced in the world currency. 1 world coin = 1 gp mechanically, so set prices on the 5e scale (a revolver ≈ a crossbow ≈ 25–50, plate-grade armor ≈ 1,500) and starting funds per the chassis's 5e starting gold; in a realistic modern world, say in the lexicon what one coin is ("1 = about $10"). A shield is an armor record with `ac: "AC +2"` and is worn with `calc --shield`.
   - **`monsters`** — 8–15 threats spanning CR 1/8 → the campaign's endgame CR, full 5e stat blocks (`cr`, `xp` matching the CR, `hp`, `hp_dice`, `ac`, six scores, `speed`, `type`, `description` with actions), `biomes` (the world's own location types, e.g. `tunnels`, `ruins`, `surface`) and a tactical `role` (`brute|skirmisher|ranged|caster|support`). Give every biome a spread of CRs (at least one low, one mid) so `encounter_gen.py` can fill a budget there. The player's named enemies are mandatory entries; scale "unbeatable" ones (a Titan) as set-piece CRs the party should avoid, not fight.

   - **Table-rules fields** (optional; `SKILL-table-rules.md` §8) — `_meta.tech_level` (0–12) and `status_levels` (social ranks, lowest first); 1–3 playbook `moves` per class in the world's voice (`{name, level, trigger, description}`); a `template` quick build on each class (`{abilities, skills, equipment}`); 4–8 `disadvantages` (mix of `disadvantage` and `quirk`) players can take; world `conditions` the setting needs (valued ones with `valued`, `decay`, `penalty_on`); `rarity`/`traits`/`tl` on gear (anything above the world's tech level is `rare` or `unique`); `focus: true` on signature powers; `morale` (2–12), `instinct` (0–10) and 1–3 `instincts` on monsters; 3–6 `place_tags` in the world's voice (`{name, description, enemies, friends, complications, things, places}`, §11). Before writing each monster, check `worldkit.py monster-stats --cr <CR>` and keep it near the typical numbers; `validate` warns when one is far off.

   **No dangling references:** every spell, power, item or creature that a class, subclass, `class_options` record or power description names must exist in this kit — with `srd_fallback: false` the SRD versions are unreachable. A subclass that grants extra spells lists them as kit powers; a feature that needs an item (a 300-coin component) has that item in `equipment`.

   **Validate before moving on:** `python3 ${CLAUDE_SKILL_DIR}/scripts/worldkit.py validate <campaign>`. Fix every error and re-run until it prints `OK`; treat its `warning:` lines as a checklist against the counts above. Then `worldkit.py show <campaign>` and give the player a short tour from its output (origins, classes and their specialisations, signature threats) — they can ask for changes now; re-validate after any edit.

7b. **World Foundations** — geography/biome/climate, power system (how the world's magic/tech/psionics works and what it costs), beliefs (gods, ideologies, AIs, cults — whatever this world worships or fears), calendar. Write to `## World Foundations` in world.md. Seed `state.md → ## World State → In-world date`, then `python3 ${CLAUDE_SKILL_DIR}/scripts/calendar.py -c <campaign> init --date "<day month year>" --time <label>` — a real-world setting uses `--gregorian` (real month lengths and weekdays; add `--months` with 12 local month names and `--day-names` with 7 local day names starting Monday to show them in the table's language); an invented one adds `--months "<names>" --month-length <N> --day-names "<names>"`. Time labels: dawn, morning, midday, afternoon, dusk, evening, night, midnight (or `set … --hour N`). Timed effects and the in-game clock work from session 1.
8. **Three Truths** — one settlement, one nearby threat, one mystery (with clue trail). Write to respective sections in world.md.
9. **Threat Escalation Arc** — fill the five-stage table in world.md immediately after threat generation. Set current stage to 1. Write `Threat arc stage: 1 — Now` to `state.md → ## World State`.
10. **2 Factions** — archetype, all fields including current activity. Write to `## Factions` in world.md. Write one-line faction states to `state.md → ## World State`. Then track each one's numbers for off-screen turns: `python3 ${CLAUDE_SKILL_DIR}/scripts/faction.py -c <campaign> add "<name>" --force N --wealth N --influence N --goal "<current activity as a goal>" --clock 6 --goal-stat <stat> --rivals "<other>"` (1–5 each: Force = muscle, Wealth = money and goods, Influence = favours, secrets and reach). When you need a settlement, district or ruin later, `tags.py -c <campaign> roll` gives two place tags to build it from (SKILL-table-rules.md §11).
11. **3 NPCs with relationship web** — for each proposed name run `python3 ${CLAUDE_SKILL_DIR}/scripts/name_registry.py check "<name>"` and regenerate duplicates. Write full entries (aliases — every name the story will use for them, including the spelling in the table's language — role, stats, demeanor, motivation, secret, speech quirk, faction, current goal, schedule, personality axes) to **`npcs-full.md`**, one `## <Name>` section each; write one index row per NPC to **`npcs.md`**. Generate all three first, then fill Relationships (every NPC needs ≥2 links to others). Then `name_registry.py add --name "<name>" --type npc --campaign <campaign> --session 0` for each.
12. **3–5 Quest Seeds** from threat, factions, mystery, NPC motivations. Write to `## Quest Seed Bank` in world.md. Then turn the strongest 3 into `## Adventure Nodes` (situation, ways in, what happens if the party never arrives, connections).
13. **Dynamic Campaign Arc** — auto-generate the arc from all world data just created. Use the Strongest tier for this step. Ask: *"Generate a committed narrative arc? [y/n — recommended]"*

   **If yes:** Drawing from theme, threat arc stages, factions, Three Truths, NPC motivations, and quest seeds, derive:
   - **`theme`** — one sentence: what is this story ultimately about? Not the threat — its meaning.
   - **`resolution`** — the committed endpoint shape: if the party succeeds, what's the emotional truth? Keep specific events open; commit to the shape.
   - **Acts 1–3**, each with 2 beats. Each beat has:
     - `label` — a dramatic name
     - `what_changes` — before/after: what's fundamentally different once this lands? **CRITICAL: write this as a CONSEQUENCE, not an event.** A consequence is a state-of-the-world after the beat. An event is one specific thing that happens. Consequences survive when players pre-empt the obvious event delivery; events break and the beat goes stale. Example contrast for a 2b "All Is Lost" beat:
       - ❌ Event-shaped (fragile): *"Vedra's nomination succeeds and she takes the third seat."* If the party flips the clerk, this can't land — beat goes stale.
       - ✅ Consequence-shaped (robust): *"The party experiences a concrete cost from the Kept's escalation that they cannot reverse — a cover blown, an ally compromised, or a position they relied on no longer available."* This survives multiple delivery paths.
     - `world_pressure` — the specific faction or NPC move (naming actual entities from this world) that makes the beat feel inevitable. This MAY be event-shaped — but if the players pre-empt it, you're expected to revise per SKILL.md rule 8 (pre-emption is a revision trigger).
   - **`steering_notes`** — how to reach the first beat without forcing it

   Beat layout:
   - Act 1: **1a Inciting Incident** (the threat becomes personal for the party), **1b Complication** (the problem is bigger or stranger than it first appeared)
   - Act 2: **2a Midpoint Shift** (what the party *thought* they were doing changes), **2b All Is Lost** (a genuine setback — something fails, is lost, or collapses)
   - Act 3: **3a Final Confrontation** (the decisive moment the campaign turns on), **3b Resolution** (what's different about the world and the characters after)

   Write to `state.md → ## Campaign Arc` with `type: dynamic`. Deliver a one-paragraph arc summary to the DM.

   **If no:** Write `type: sandbox` to `## Campaign Arc`. The story remains open-ended with no arc tracking.

14. Write state.md with session count 0, starting location.
15. **Physical dice server check (only if installed).** Skip this step unless the optional dice server is set up: probe with `test -d ~/.dne-dice || test "$DNE_DICE_PHYSICAL" = "1"` and short-circuit out if the test fails. When it passes, run `curl -sf http://localhost:7777/health` (timeout 1s). If it returns OK, fetch the LAN IP with `python3 -c "import socket; s=socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect(('8.8.8.8', 80)); print(s.getsockname()[0]); s.close()"` and announce: *"Dice server is up. Once each player has made a character via `/dne character new`, they should open `http://<ip>:7777/?player=<pc-name>` on their phone (lowercase, hyphens for spaces) and tap **consecrate** before play starts. NPC/DM rolls auto-resolve on the host."* If unreachable, skip silently.
16. Confirm creation, offer `/dne character new`.

---

## `/dne load <campaign-name>`
0. **Pick the campaign if none was named.** If `<campaign-name>` was supplied (or the player clearly named one), use it. Otherwise `ls` the campaigns dir (`${DNE_CAMPAIGN_ROOT:-$HOME/.dne}/campaigns/` or `$DNE_CAMPAIGN_ROOT/campaigns/`) and **call `AskUserQuestion`**: *"Which campaign?"* with the existing campaign names as options (most-recently-played first — sort by `state.md` mtime). The player can pick "Other" to type a name. If there are no campaigns, tell them and offer `/dne new`.
1. **Session setup — call `AskUserQuestion`** with **two questions, or three when `engine` is not yet in Session Flags** (not typed y/n prompts):

   **Q1 *"Display & input mode?"***
   - `Display + autorun (ngrok) (Recommended / Default)` → `bash ${CLAUDE_SKILL_DIR}/display/start-display.sh --ngrok` (or `bash ${CLAUDE_SKILL_DIR}/display/start-ngrok.sh`), print public ngrok HTTPS URL, set `_display_running = true`, write `autorun: true` to `state.md → ## Session Flags`; enter the autorun wait (`autorun_wait.py`) after the recap and at the end of every turn.
   - `Display + autorun (LAN)` → `bash ${CLAUDE_SKILL_DIR}/display/start-display.sh --lan`, print both URLs, set `_display_running = true`, write `autorun: true` to `state.md → ## Session Flags`; enter the autorun wait.
   - `Display (local)` → `bash ${CLAUDE_SKILL_DIR}/display/start-display.sh`, print URL, set `_display_running = true`.
   - `No display` → continue without display; write `display: none` and `autorun: false` to `state.md → ## Session Flags` (other choices: write `display: ngrok|lan|local`).

   *(Standing rule: Default to `Display + autorun (ngrok)` so players can immediately play via phone over internet).*

   **Q2 *"Dice rolls?"*** — confirm how PC d20s are handled this session (see SKILL.md "Dice convention"). Pre-fill the recommended option from the existing `roll_mode` in `state.md` if present, else `players`:
   - `Players roll their own` → write `roll_mode: players`. Call for each PC roll and wait — never auto-roll a PC.
   - `DM rolls everything openly` → write `roll_mode: auto`. Resolve PC rolls yourself with full math shown.

   **Q3 *"How much of the game runs on the rules engine?"*** — ask only when `state.md → ## Session Flags` has no `engine:` line yet; otherwise keep the saved value (the table changes it from Table Settings).
   - `Full (Recommended)` → write `engine: full`. Every fight is tracked on the scripts (HP and AC for each enemy, each attack resolved) and XP comes from the tables.
   - `Light` → write `engine: light`. You judge fights and XP yourself and call for the rolls that matter; saves, NPC records and the in-world clock are still kept.

   - (Defaults if the player dismisses: no display, no autorun, `roll_mode: players`, `engine: full` — or the existing saved value.)
   - **Session tail replay:** before clearing the display, check if the campaign's `session_tail.json` exists. The campaign-side path is the authoritative one — `${DNE_CAMPAIGN_ROOT:-$HOME/.dne}/campaigns/<name>/session_tail.json`. **Do NOT read** the legacy/fallback at `${CLAUDE_SKILL_DIR}/display/session_tail.json`; that file may exist from older sessions or other campaigns and will mislead the replay. If the campaign-side file does not exist, skip replay (display starts blank). If it does, read it. After `--clear` and full stats push (step 4 below), replay the tail by sending each entry via the appropriate `send.py` flag. Entry type → flag mapping:
     - `player` key present → `send.py --player <name>` with text via stdin
     - `npc` key present → `send.py --npc <name>` with text via stdin
     - `dice` key present → `send.py --dice` with text via stdin
     - `xp_award` key present → `send.py --xp-award '<json of the xp_award sub-dict>'`
     - `inspiration_award` key present → `send.py --inspiration-award '<name>'`
     - none of the above (plain DM narration) → `send.py` with text via stdin
     This restores the last scene to the display before the recap. The tail is written continuously by `dne-display-app.py` — it always contains the last session's final exchanges regardless of how the session ended.
   - Clear previous transcript: `python3 ${CLAUDE_SKILL_DIR}/display/push_stats.py --clear`

     ⚠ **`--clear` wipes both text log AND stats** (player card, world time, factions, quests). It must always be paired with the full `--replace-players ... --world-time ... --factions ... --quests ...` push from step 4 — otherwise the sidebar card and sheet tab render empty. Same rule applies any time you `--clear` mid-session (e.g. restoring scene state after a re-replay): always re-push the full character JSON + world-time + factions + quests in the same bash burst as the clear.
   - Register the active campaign: `python3 ${CLAUDE_SKILL_DIR}/display/push_stats.py --set-campaign <campaign-name>`. It marks the session start and prints the `SESSION START` checklist (what to read and run before the recap).
   - If autorun **yes** → write `autorun: true` to `state.md → ## Session Flags`; enter the autorun wait after the recap paragraph.
   - If autorun **no** → continue without autorun; DM drives turns manually.
   - **Physical dice server check (only if installed).** Skip this step unless the optional dice server is set up: probe with `test -d ~/.dne-dice || test "$DNE_DICE_PHYSICAL" = "1"` and short-circuit out if the test fails. When it passes, run `curl -sf http://localhost:7777/health` (timeout 1s). If it returns OK, fetch the LAN IP with `python3 -c "import socket; s=socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect(('8.8.8.8', 80)); print(s.getsockname()[0]); s.close()"` and announce to the table: *"Dice server is up. Each player, open `http://<ip>:7777/?player=<your-pc-name>` on your phone (lowercase name, hyphens for spaces — same name I'll use when calling for rolls) and tap **consecrate** before we begin. NPC and DM rolls auto-resolve here."* Then list the PC short-names from `characters/` so players know what to type. If the server is unreachable, skip silently — `dice.py` falls back to local random.

2. **Backwards-compat: ruleset migration check.** Before reading state.md, run:

   ```bash
   python3 ${CLAUDE_SKILL_DIR}/scripts/migrate_ruleset.py <campaign-name> --check
   ```

   - Exit code `0` (`migrated`) → proceed to step 3.
   - Exit code `1` (`needs-migration`) → this is a legacy campaign predating the ruleset field. Surface to DM exactly once: *"Campaign predates ruleset versioning. Stamp as **2014** (recommended for legacy campaigns) or **2024**? state.md will be backed up to `state.md.backup-pre-ruleset-<timestamp>` before any write. [2014/2024/skip]"*. On answer, run:

     ```bash
     python3 ${CLAUDE_SKILL_DIR}/scripts/migrate_ruleset.py <campaign-name> --ruleset 2014 --yes
     # or --ruleset 2024
     ```

     Migrator is idempotent and creates a timestamped backup. On `skip`, do not migrate; `paths.campaign_ruleset()` will return `2014` as the safety default at read time, but the field stays unstamped (DM will be re-prompted next load).

   **Engine version check.** Then run `python3 ${CLAUDE_SKILL_DIR}/scripts/campaign_version.py -c <campaign-name> check`.
   - `World is up to date` or `the players chose not to update` → carry on.
   - `UPDATE AVAILABLE` → show the players the version gap and the "New since then" list it prints, in their language, and **call `AskUserQuestion`**: *"This world was built with an older DnE. Bring the whole world up to v<engine> now?"* — `Update the world (Recommended)` / `Keep it as it is`. Update → follow **Update a world to the engine version** below, then continue loading. Keep → `campaign_version.py -c <campaign-name> mark --declined` (they are asked again only when a newer version arrives).
   - `newer than the engine` → stop and tell them to run `/dne update` first.
   - Exit code `2` (`missing`) → state.md not found; do not proceed with /dne load. Surface error to DM.

   Future migrations (e.g. when 2026 ruleset arrives) follow the same pattern: a small migrator script under `scripts/migrate_<topic>.py` invoked here as a `--check` then `--yes` pair.

3. **Read campaign ruleset** for this session: `python3 ${CLAUDE_SKILL_DIR}/scripts/paths.py campaign-ruleset <name>` (or import `campaign_ruleset` directly). Stash the result; pass `--ruleset <value>` to `lookup.py`, `build_supplemental.py`, and `combat.py` mastery calls so they route to the correct dataset. The display companion picks up the same value automatically via `push_stats.py --set-campaign`.

4. Read SKILL-scripts.md (for script syntax this session)
5. **Mark this campaign active.** `push_stats.py --set-campaign <campaign-name>` (step 1) already did it and printed a `SESSION START` checklist: do every line of it. With `display: none`, run `python3 ${CLAUDE_SKILL_DIR}/scripts/gm_guide.py -c <campaign-name> start` instead. The marker (`active-campaign.json` in the runtime dir) names the campaign for the autosave hook and the autorun watchdog, dates the session for `save_check.py`, and records each sheet's XP as the session opens. Then read state.md, world.md, npcs.md (index only), and all characters/*.md
   - **state.md contains `## DM Style Notes`** — read and internalize before narrating anything. These are table-specific calibration patterns that override default DM instincts.
   - **state.md contains `## Glossary`** (tables playing in a language other than English) — use exactly these translations for game terms all session; add a line the first time a new term comes up.
   - **state.md contains `## Pinned Facts`** — read and keep hot for the whole session. These are stable soft facts the table has chosen never to forget (a promise made, a dead relative's name, a house rule, a running joke, a detail the player flagged as mattering). Unlike Live State Flags, they don't change turn-to-turn — they are standing canon. Weave them in when relevant and never contradict one; if a pinned fact is now wrong, correct it via `/dne pin` rather than silently overriding it. If the section reads *(none pinned yet)*, there's nothing to load.
   - **Table rules:** if `## Session Flags` has `hero_points: on`, run `character.py hero reset --char <pc> -c <campaign>` for every PC (each session starts with 1). If any table-rules flag is set or the kit has `moves`/`disadvantages`/`focus` powers, read `SKILL-table-rules.md`.
   - **Content level:** if Session Flags say `content: 18` or `content: 20`, or `romance: open`, read `${CLAUDE_SKILL_DIR}/SKILL-content.md` now and hold that level all session.
   - **Faction turn:** run `python3 ${CLAUDE_SKILL_DIR}/scripts/faction.py -c <campaign> turn`. It plays one turn per in-world week since the last one (at most 4) and says so when none is due or no factions are tracked. Write each printed line into `state.md → ## Faction Moves` as something the party may now see or hear about, and fold a `GOAL COMPLETE` or `COLLAPSED` into the world (then give the faction a new goal with `faction.py set`).
   - **worldkit.json** (if present): read `_meta`, `lexicon`, `currency`, `skills`, and the names of `races`/`classes`/`monsters` — narrate in the world's language from the first sentence. Pass `-c <campaign>` to `lookup.py`, `character.py` and `encounter_gen.py` all session. Full records are looked up on demand, not held in context.
   - **world.md:** Load in full — World Foundations, Three Truths, and factions inform narration and faction moves. Do NOT read `world-seeds.md` at load (generation artifact, not live reference).
   - **world-nodes.md (imported campaigns only):** Do **NOT** load at session start. It holds the full Quest Seed Bank and Adventure Nodes for the whole module; read only the current act's nodes on demand when a scene needs them. If the file is absent (dynamic/sandbox, or an older import), there is nothing to lazy-load — `world.md` already carries the nodes, unchanged from prior behavior.
   - **arc.md (imported campaigns only):** Do **NOT** load at session start. `state.md → ## Campaign Arc` already carries the current + next chapter window. Read `arc.md` only when advancing chapters or when a player asks about the broader arc. If absent, the arc lives inline in `state.md` (dynamic/sandbox) — read it there as before. **Sanity-check the pointer at load:** if `## Campaign Arc`'s `current_chapter` shows its `outstanding_beats` already cleared, or the last session plainly ended in the *next* chapter's location or situation, the pointer never advanced — surface it (*"the current chapter looks finished; pick up in `<next_chapter>`?"*) instead of opening another scene in a chapter that's already done. A pointer that never moves is exactly how a structured campaign quietly drifts off its own arc and starts improvising.
   - **source/<chapter-id>.md (imported campaigns only):** the full module text, one file per chapter. Never loaded at session start. Before running a scene in a chapter, read that chapter's `source/<id>.md` (the `source_ref` in the arc) — and only that chapter. This is the predefined-story equivalent of reading a single NPC's full entry on demand.
   - **npcs.md:** Index row only at load. **Before writing substantive dialogue or decisions for any named NPC, read their full entry in `npcs-full.md`.** Do not wait for an explicit `/dne npc [name]` call — do it proactively when a scene centers on that character. Index rows carry surface traits only; personality axes, relationships, and hidden goals are in the full entry.
   - **companions/*.md** (if the folder exists and any sheet is `**Status:** active`): read `${CLAUDE_SKILL_DIR}/SKILL-companions.md` and follow its *At load* step.
   - **Do NOT read session-log.md at load** — recent events are already in `state.md → ## Recent Events`. Only read session-log.md if the player explicitly requests a recap, or if DM Calibration from the last 1-2 sessions is needed and not already internalized.
6. Push full party stats to display sidebar. **CRITICAL:** use `--json` with a complete player object — **never** the `--player` shorthand here. `--player` only updates existing fields; it cannot populate the card or sheet tabs. The display shows "Full sheet not loaded" when `sheet` is absent.

   ```bash
   python3 ${CLAUDE_SKILL_DIR}/display/push_stats.py --replace-players --json '{
     "players": [
       {
         "name": "CharName",
         "race": "Race",
         "class": "Class (Background)",
         "level": N,
         "hp": {"current": N, "max": N, "temp": 0},
         "ac": N,
         "speed": 30,
         "hit_dice": {"max": N, "remaining": N, "die": "d8"},
         "xp": {"current": N, "next": N},
         "conditions": [],
         "concentration": null,
         "inspiration": 0,
         "spell_slots": {},
         "sheet": {
           "attacks": [{"name":"...","bonus":"+N","damage":"...","type":"...","notes":"..."}],
           "features": [{"name":"Feature 1","text":"Description of what it does."},{"name":"Feature 2","text":"Description."}],
           "inventory": ["Item 1", "Item 2"]
         }
       }
     ]
   }'
   ```

   For casters, add `"spells": {"cantrips":["..."],"level1":["..."]}` inside `sheet`. Omit for non-casters.

   **Inspiration:** read from `state.md → ## Current Situation → Party status`. Set `"inspiration": 1` (or `true`) if the character has it, `0` if not. Inspiration is NOT reset by a long rest — it persists until spent. Must be explicitly tracked in the party status line at `/dne save` (e.g., `Mara: Inspiration ✓`) and loaded at `/dne load`. Use `push_stats.py --player <name> --inspiration true/false` for mid-session updates.

   `--replace-players` clears stale characters from previous campaigns. Build the JSON from the character file — every field above is required for the card and sheet tabs to render correctly.

   Also push `--world-time`, `--factions`, and `--quests` in the **same** `push_stats.py` call as the player JSON to avoid race conditions where the display server receives a partial update. Combine all into one invocation:

   ```bash
   python3 ${CLAUDE_SKILL_DIR}/display/push_stats.py --replace-players \
     --json '{...players...}' \
     --world-time '{...}' \
     --factions '[...]' \
     --quests '[...]'
   ```

   Faction JSON structure — **`standing` is required**:
   ```json
   [{"name":"Pale Court","standing":"Allied"},{"name":"The Kept","standing":"Hostile"}]
   ```
   `standing` values: `Allied`, `Friendly`, `Neutral`, `Suspicious`, `Hostile`. If the field is omitted, `dne-display-app.py` defaults it to `"Neutral"` and logs a warning to stderr — but always include it explicitly. Map prose from `state.md` to exact values (e.g. "deep ally" → `"Allied"`, "active hostile" → `"Hostile"`). Use `[]` to clear.

   The faction panel only appears when at least one faction is present — do not skip this push.

   Quest JSON structure:
   ```json
   [{"name":"The Missing Shipment","status":"resolved"},{"name":"Keth the Collector","status":"threat"}]
   ```
   Quest `status` values: `active` (amber), `threat` (red), `resolved` (green), `failed` (muted). Use `[]` to clear all quests:
   ```bash
   python3 ${CLAUDE_SKILL_DIR}/display/push_stats.py --quests '[...]'
   ```
   The quest panel only appears when at least one quest is present — do not skip this push.
7. **Pull scene-context from the campaign graph.** Always run, even if you suspect `graph.json` doesn't exist — the script exits cleanly with a notice when uninitialized.
   ```bash
   python3 ${CLAUDE_SKILL_DIR}/scripts/campaign_graph.py scene-context \
     --campaign <campaign-name> \
     --place "<current-location-name-or-id>" \
     --present "<comma-separated-NPC-names-likely-present>" \
     --hops 2 \
     --at-session <current-session-N>
   ```
   Identify `<current-location>` from `state.md → ## World State → location` (or the most recent location in `## Recent Events`). Identify `<present>` from the NPCs likely on-scene per `state.md` / `session-log.md`. `<current-session-N>` is `state.md → ## Session Count`.

   Output is a focused subgraph (nodes by type + relationships block). **Internalize this subgraph before delivering the recap** — it is the authoritative source for who-relates-to-whom in the current scene. Do not re-read `npcs-full.md` for relationships you can answer from the subgraph.

   If output reads `# graph not initialized` — graph hasn't been seeded for this campaign yet. **Graph init is a hard requirement, not deferrable.** The continuity-archive compression rule (the graph-init steps below + `/dne save`) assumes graph.json is present and canonical for relational state; deferring init creates state-archive drift that compounds session-over-session. Run the init flow before delivering the recap:

   1. **Detect legacy.** A campaign is "legacy" if any of: `Session count > 1` in state.md header, OR `## Continuity Archive` has at least one `### Session N` entry, OR session-log.md is > 100 lines. A freshly-created campaign at `/dne new` time fails all three signals — do NOT classify it as legacy.

   2. **Backup the campaign directory** (always — both fresh and legacy):
      ```bash
      mkdir -p "${DNE_CAMPAIGN_ROOT:-$HOME/.dne}"/.backups && cp -R "${DNE_CAMPAIGN_ROOT:-$HOME/.dne}"/campaigns/<name> \
            "${DNE_CAMPAIGN_ROOT:-$HOME/.dne}"/.backups/<name>-$(date +%Y%m%d-%H%M%S)
      ```
      Tell the DM the backup path explicitly so they can revert if needed.

   3. **Run `/dne graph init <name>`** — first `campaign_graph.py init --campaign <name>`, which creates the empty `graph.json` (idempotent, and it refuses to overwrite a graph that already has nodes or edges); then propose seed nodes/edges from `npcs.md`, `world.md`, and `state.md` (Live State Flags + Active Quests + recent NPC dispositions). Show the DM a single approval block (counts by type + named entries) and ask for one go/no-go. After approval, batch-execute the `add-node` and `add-edge` calls. Use `--since N` matching when each node/edge first became canon (use `1` for foundational; the actual session number for newer NPCs/edges).

   4. **Validate** with a `scene-context` query at the current location to confirm the subgraph is reachable.

   5. **(Legacy only)** Offer the one-time Continuity Archive compression pass:

      > "This campaign is legacy ({session_count} sessions, {archive_count} archive entries). Now that `graph.json` is the canonical source for faction memberships, NPC dispositions, and typed-edge relationships, I can do a one-time pass to trim the existing `## Continuity Archive` entries of relational restatements that the graph now answers. Mechanical changes, plot beats, atmospheric/decision moments, and disclosed information stay in full. Estimated reduction: 5–30% of archive bytes (varies by how relational vs. content-heavy your existing entries are). Backup is already at `<backup-path>`. Proceed? [y/n]"

      - `y` → trim each archive entry surgically; keep the bullet structure; remove ONLY pure-relational restatements (e.g. "X is allied with Y", "Z saw the party's faces", "W is a member of faction F") that have a corresponding edge in the just-initialized graph. Preserve: XP/level/items/HP, plot beats ("Beat 2a sealed"), atmospheric moments, disclosed content, calibration material, off-screen world events. Add a one-line note at the top of `## Continuity Archive`: *"Compressed YYYY-MM-DD (graph init pass). Relational state is canonical in graph.json — entries below preserve mechanical changes, plot beats, disclosed content, atmospheric/decision moments, and calibration material."*
      - `n` → leave the archive untouched. The going-forward compression rule (per `/dne save`) still applies to NEW entries from this session forward.

      For fresh (non-legacy) campaigns: skip the offer entirely — there's nothing to compress yet, and the going-forward rule covers all future entries.

   6. Re-run scene-context (now populated; on a fresh campaign pass `--at-session 1` so the foundational `--since 1` edges show). Then proceed to the recap step.

8. Deliver one in-character paragraph recapping current situation — where the party is, what's at stake, what was last happening.
9. Enter active DM mode — no `/dne` prefix needed from this point.

---

## `/dne import <filepath> [campaign-name]`

Import a pre-written campaign from a source file (PDF, MD, TXT, DOCX) and create a playable campaign from it.

**Supported file types:** `.pdf` `.md` `.txt` `.markdown` `.docx`

### Step 1 — Extract source text
```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/import_campaign.py "<filepath>" --info
```
**PDF sources:** extraction uses PyMuPDF (column-aware) so multi-column modules de-column into reading order and segment into chapters correctly — without it, two-column books collapse into one chapter. If the script prints a `pip3 install pymupdf` notice on its stderr, tell the DM to install it and re-run; it falls back to `pdftotext` otherwise but segmentation is less reliable.

Print file info. If it reports more than one chunk, read it chunk by chunk (a chunk is ~4000 words of English or ~6000 characters of Chinese/Japanese/Korean, with the source's line breaks intact):
```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/import_campaign.py "<filepath>" --chunks  # total chunks
python3 ${CLAUDE_SKILL_DIR}/scripts/import_campaign.py "<filepath>" --chunk 0  # first chunk
```
For a single-chunk source, read in full:
```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/import_campaign.py "<filepath>"
```

### Step 2 — Analyse structure
Read the extracted text and identify:
- **Campaign title and system**
- **Structure type:** `linear` (scene chain A→B→C) | `hub-and-spoke` (central hub + spoke locations, player-driven order) | `faction-web` (multi-faction city/complex, overlapping arcs)
- **Acts and chapters** — numbered sections, chapter headings, or named scenes
- **Key beats** — required story events the DM must deliver (boss reveals, faction turns, mandatory encounters)
- **Locations** — distinct named places with descriptions
- **NPCs** — names, roles, motivations, relationships, stat blocks if present
- **Factions** — groups with agendas, relationships to party
- **Quest hooks and seeds** — explicit adventure hooks, side quests, optional encounters
- **Starting conditions** — where does the party begin, what level, what's the inciting event

For large sources, read all chunks before proceeding.

### Step 3 — Confirm campaign name
If `[campaign-name]` not supplied, suggest one from the title and ask to confirm.

### Step 4 — Display summary and confirm
Show a structured summary before writing any files:

```
Title:    <source title>
Type:     structured / <structure type>
Acts:     N  |  Chapters: N  |  Key beats: N
NPCs:     N named  |  Factions: N
Locations: N distinct

Campaign name: <name>
Campaign dir:  ${DNE_CAMPAIGN_ROOT:-$HOME/.dne}/campaigns/<name>/

Proceed? [y/n]
```

### Step 5 — Create campaign files
On confirmation:

1. `mkdir -p ${DNE_CAMPAIGN_ROOT:-$HOME/.dne}/campaigns/<name>/characters`
2. Copy templates from `${CLAUDE_SKILL_DIR}/templates/`, then `python3 ${CLAUDE_SKILL_DIR}/scripts/campaign_version.py -c <name> stamp`, and ask the table the **content** question from `/dne new` step 6 (`content`, `romance`, `lines`, `veils` → Session Flags).
3. Write **world.md** (load-time core — kept small so it can be read in full every load):
   - `## World Foundations` — setting, geography, tone, magic level, calendar if present
   - `## Three Truths` — one settlement, one threat, one mystery (drawn from source)
   - `## Threat Escalation Arc` — map source acts to the 5-stage table; set stage 1
   - `## Factions` — all factions with archetype, current activity, relationship to party

3a. Write **world-nodes.md** (lazy reference — NOT read at load, pulled per current act):
   - `## Quest Seed Bank` — all explicit hooks + 2–3 implied side threads
   - `## Adventure Nodes` — named locations with one-line descriptions, grouped by act/chapter

   For a small module the split is optional, but for any published adventure it is the
   single biggest load-time saving — the whole quest/location bank no longer sits in
   context every session. If you write `world-nodes.md`, do **not** duplicate its
   sections into `world.md`.

4. Write **npcs.md** index table (one row per NPC: name, role, location, one-line demeanor)

5. Write **npcs-full.md** — full entry for each named NPC:
   - Role, motivation, secret, speech quirk, faction affiliation
   - Relationships to other NPCs (min 2 per NPC)
   - Stat block summary if present in source

6. Write **arc.md** from `${CLAUDE_SKILL_DIR}/templates/arc.md` — the **full** act/chapter tree: every chapter's `id`, `title`, `location`, `source_ref` (its file in the lazy corpus, see step 6b), `key_beats`, `telegraph_scene`, `branching_notes`, plus `outstanding_beats` and `steering_notes`. This is the heavy structure; it lives here so it is read on demand, not at every load.

6a. Write **state.md** from template:
   - Populate `## Current Situation` — starting location and party placeholder
   - Populate `## World State` — in-world date if given, factions, threat arc stage 1
   - Populate `## Campaign Arc` with the **STRUCTURED ARC POINTER only** (see template): `type: structured`, `source`, `structure`, `arc_file: arc.md`, `current_act`, `current_chapter`, the `current_chapter_detail` block, `next_chapter`, `outstanding_beats`, `steering_notes`. **Delete the entire DYNAMIC ARC yaml block** from the template — do not leave both arc forms in the file. The full tree is in arc.md; state.md carries only the current + next chapter window.
   - Leave `## Active Quests`, `## Session Flags` (autosave defaults on), `## DM Style Notes` as template defaults

6b. Write the **lazy corpus** — the full source text, kept available but out of the hot path:
   - `mkdir -p ${DNE_CAMPAIGN_ROOT:-$HOME/.dne}/campaigns/<name>/source`
   - For each chapter in arc.md, write `source/<chapter-id>.md` (e.g. `source/1.1.md`) containing that chapter's source text from the extracted chunks. Use the same chapter ids as arc.md.
   - Write `source-index.md` — a table mapping `chapter-id → source/<id>.md → one-line scope`, plus source title and import date.
   - Validate the layout: `python3 ${CLAUDE_SKILL_DIR}/scripts/corpus_check.py --campaign <name>` (expects "lazy-corpus layout OK"). Fix any orphan/missing-file problems before finishing. If it prints an **oversized-chapter WARNING**, split that chapter into sub-chapters (e.g. `1.1a` / `1.1b` at natural scene breaks) across `arc.md`, `source-index.md`, and `source/`, then re-run — a single giant chapter is the one thing that still bloats a load, so keep each `source/<id>.md` comfortably under the limit.

7. Write **session-log.md** with Session 0 import record:
   ```
   ## Session 0 — Import — <date>
   Source: <filepath>
   Imported: <N> acts, <N> chapters, <N> NPCs, <N> locations
   ```

### Step 6 — Gap-fill wizard
After writing files, identify anything the source left ambiguous:
- If starting level not specified → ask
- If party size not specified → ask
- If calendar/in-world date absent → offer to generate or leave blank
- If tone/genre not clear from source → offer the World Wizard (`/dne new` step 6); if the module is not standard fantasy, also build a World Kit (step 7) from its content

### Step 7 — Confirm and offer next step
Print summary of files written. Offer:
```
Campaign "<name>" created from <source title>.
→ /dne character new      — create your character
→ /dne load <name>        — start playing immediately
```

---

## `/dne save`
**Start and finish with the checklist.** Run `python3 ${CLAUDE_SKILL_DIR}/scripts/save_check.py -c <campaign>` first: it lists every part of the save, ticks what was already written this session, and names the NPCs who appeared in this session's narration (relationships live in three places: the Attitude column in npcs.md, `NPC dispositions` in state.md → Live State Flags, and the graph). The relationship rows never tick themselves (file times can't show them): answer them NPC by NPC, including a romance or grudge that deepened. The players never have to say what to save. Work through every ☐, run it again, and in your save summary to the players list each file you changed and, for every ☐ left, why nothing changed. Never report "saved everything" with a ☐ unexplained.

Write session events to session-log.md, update state.md (location, active quests, party HP/resources, recent events), update any characters/*.md that changed. Mirror each updated character to the global roster (`<DNE_CAMPAIGN_ROOT>/characters/<file>.md`, default `~/.dne/characters/`).

**Header bookkeeping:** on the first save of a session, increment `**Session count:**` and set `**Last session:**` to today's real date in the state.md header (later saves in the same session leave them alone). **NPC attitudes:** when an NPC's attitude changed, update its row in `npcs.md` and its `**Attitude toward party:**` line in `npcs-full.md` (and `campaign_graph.py set-disposition` if the graph is initialised), using the one scale everywhere: hostile → suspicious → neutral → friendly → allied.

**Inspiration tracking:** On every save, record each PC's Inspiration state in `state.md → ## Current Situation → Party status`. Use explicit text: `Inspiration ✓` if held, omit or `No Inspiration` if not. Inspiration persists across sessions and is NOT cleared by long rests. Example: `Mara: HP 24/24. Inspiration ✓. Theo: HP 24/24.`

**Update `## Live State Flags` in state.md on every save.** This section is the compaction-resistant anchor — it holds facts that prose summaries flatten. After each session, review and update:
- **Cover:** each PC's active cover, its status (INTACT / BLOWN / PARTIAL), and the one-line reason. Remove covers that are no longer active.
- **Faction stances:** each faction with non-neutral standing toward the party. Format: `[Faction]: [Allied/Friendly/Neutral/Suspicious/Hostile] — [one-line reason]`. Remove factions that have returned to neutral.
- **NPC dispositions:** each NPC with changed or notable standing. Format: `[Name]: [disposition] — [one-line reason]`. Remove NPCs who have returned to baseline.

If nothing changed in a category this session, leave it as-is. If a fact was wrong in the previous save, correct it.

**Structured (imported) campaigns — keep the arc window and arc.md in sync.** Advancing the pointer is not optional bookkeeping — it is what keeps the campaign on its own rails, and a pointer that never moves is how an imported module quietly becomes an improvised one. Before you decide "no chapter advanced," check honestly: **if this session cleared the last of the current chapter's `outstanding_beats`, or the party has plainly moved into the next chapter's location or situation, the chapter advanced — treat it as such and move the pointer now.** When a chapter advances: mark the completed chapter `status: complete` in `arc.md`, set the new chapter `status: current`, and update `state.md → ## Campaign Arc` so its `current_chapter`, `current_chapter_detail`, `next_chapter`, and `outstanding_beats` reflect the new window. The full tree stays in `arc.md`; `state.md` carries only the current + next chapter so the load stays light. Only when the party is genuinely still mid-chapter, update `outstanding_beats`/`steering_notes` inline in `state.md` — no need to touch `arc.md`. (Dynamic/sandbox campaigns have no `arc.md`; update the inline arc in `state.md` as before.)

Then update `## Faction Moves` in state.md: for each active faction, answer *"what did they do while the party was occupied?"* One line per faction — even if nothing visible yet. For factions tracked in `factions.json`, the answer comes from `faction.py turn` (run at `/dne load`); first apply anything the party did to them this session with `faction.py adjust`. Confirm what was written.

**Session tail archive:** `dne-display-app.py` continuously writes `${DNE_CAMPAIGN_ROOT:-$HOME/.dne}/campaigns/<name>/session_tail.json` — campaign-specific path, atomic-write, skip-on-empty guarded (since 2026-05-01). At save time:

1. Verify the campaign-side file exists and is non-empty (with `display: none` there is no live tail — skip straight to writing the canonical one with `write_canonical_tail.py`):
   ```bash
   bash ${CLAUDE_SKILL_DIR}/display/verify_tail.sh <campaign-name>
   ```
   The script returns 0 if the tail is healthy (non-empty + valid JSON list), 1 if missing/empty/corrupt. If it returns 1, the tail is unsafe to rely on for next session's replay — **write a canonical replacement directly to the campaign path** with this session's 5–8 most important narrative beats as a JSON list of `{"text": "...", "_camp": "<name>"}` entries (no display call needed; the display may already be dead). Use the helper: `python3 ${CLAUDE_SKILL_DIR}/display/write_canonical_tail.py --campaign <name> --json '[{"text": "…", "_camp": "<name>"}]'` (or `--file <path>`).
2. Also write `<campaign dir>/session-tail.md` (human-readable snapshot — companion to the JSON, used as fallback during /dne load if JSON read fails).
3. **Keep world.md in step with state.md:** if the threat stage, a faction's attitude toward the party, or a settlement fact changed this session, update the matching lines in `world.md` (`**Current stage:**`, each faction's `**Attitude toward party:**`, `**Current activity:**`). `/dne load` reads world.md in full, so a stale value there contradicts state.md.

**Session log archival (run on every save after session count > 3):**
session-log.md keeps only the **2 most recent full session entries**. Older entries move to `session-log-archive.md` (append, never delete). Before archiving each entry, extract a 3–5 bullet continuity summary and write it to `## Continuity Archive` in state.md. Format:

```markdown
### Session N — [date] — [one-line location/event label]
- [Key fact that may resurface as a callback]
- [NPC revelation, exact wording of something important, decision that has consequences]
- [Roll outcome that changed the fiction]
- [Item acquired with story significance, plot beat, atmospheric/decision moment]
```

**Going-forward Continuity Archive compression rule (from 2026-05-07; applies when `graph.json` exists for the campaign):** When `graph.json` is present, the Continuity Archive bullets must NOT restate relational state that the graph holds canonically. Specifically, **omit** bullets/clauses that say:
- "X is allied with Y" / "X is hostile to Y" / "X is friendly with Y" — already a typed edge with `--since N` and source-anchor
- "X is a member of faction F" / "X works for Y" / "X reports to Y" — already a `member_of` / `works_for` / `reports_on` edge
- "Z saw the party's faces" / "K is now in the Kept profile" — already a `hostile_to` / `surveils` edge with `--since`
- Faction memberships and NPC dispositions that haven't changed this session
- Restated NPC profiles (job title, age, location) that already live as node tags + summary

**Keep** in archive bullets:
- Mechanical changes (XP awarded, level-ups, items gained/spent, slots burned, HP deltas at session end)
- Plot beats (arc beat completions, "Beat 2a sealed", "Beat 2b LANDED")
- Atmospheric / decision moments that have no graph edge ("Mira ate the bread — first food in 800 years", "Mara squeezed her hand")
- Disclosed content (the WHAT was learned — "fragment / anchor / host", "three acceleration factors") even when the relational fact is in graph
- Off-screen world events / faction moves
- Calibration / DM Notes
- Cliffhangers and pause-points

Treat each bullet as one sentence with one job. If the only job is "restate a graph edge", drop it. If it carries content + edge, keep the content half. The graph is queried at `/dne load` step 7; the archive is queried for chronological narrative + mechanical state — they should not overlap.

The continuity summary is what stays hot in context. The full verbose log is in the archive, readable on `/dne recap` or explicit request. When a past detail surfaces mid-scene, check `## Continuity Archive` first, then `/dne graph scene-context` for relational context, then read session-log-archive.md if more depth is needed.

**Campaign-graph relationship-shift sweep:** before completing the save, scan this session's narration for relationship shifts that weren't captured live via `/dne graph add-edge` / `close-edge`. Look for moments matching these patterns:

- New alliance, betrayal, or rivalry between named NPCs / factions ("Velkyn now serves the Pale Court")
- A shift in how the **party** stands toward an NPC or faction ("the Pale Court now reads the party as hostile", "Aldric came around and trusts them"). Draft these as `set-disposition --to <npc-or-faction> --level <allied/friendly/neutral/suspicious/hostile>` calls, matching the `standing` you push to the display and the NPC-disposition lines in `## Live State Flags`.
- An NPC moving into / out of a location ("Mira fled the Citadel for the Lowmarket")
- A faction taking control of (or losing) a place ("House Tarn lost the silver mine")
- A character learning a secret ("the party now knows Velkyn was the spy")
- A quest / thread ending or being blocked

For each candidate, draft an `add-edge` or `close-edge` call. Then **present the batch to the DM as a numbered list** and ask: *"Apply all? [y / pick / skip]"*

- `y` → run all proposed calls via `python3 ${CLAUDE_SKILL_DIR}/scripts/campaign_graph.py ...`
- `pick` → DM names the numbers to apply (e.g. `1, 3, 5`); skip the rest
- `skip` → don't apply any

Always supply `--since <current-session-N>` from state.md (use `1` for anything that was true before the first session — a fresh campaign's session count is 0). Never write proposed edges silently.

If `graph.json` doesn't exist yet for this campaign, skip the sweep entirely (no proposal block) — graph isn't seeded.

---

## `/dne end`
1. Run `/dne save`, then:
   a. Append **Session Recap** block to session-log.md with key events and open threads.
   b. Ask: *"Quick calibration — what worked this session, and what would you adjust next time?"* Write answers to `### DM Calibration`. If skipped, leave blank.
   c. Update `## World State` in state.md: check whether events advanced the threat arc stage, shifted faction states, or changed the in-world date. Update all three.
   d. If the calibration response reveals a new pattern (or confirms/contradicts an existing one), update `## DM Style Notes` in state.md. Add new bullets; refine existing ones if the pattern has sharpened. Do not log every session — only update when something genuinely new or changed is observed.
   e. **Arc check** (dynamic arcs only — skip for sandbox/structured): If `## Campaign Arc` has `type: dynamic`, do all of:

      i. Ask: *"Did any arc beats land this session? [beat id(s) like '1b 2a', or 'none']"*
      ii. If beats landed: run `/dne arc advance <beat-id>` for each.
      iii. **Pre-emption check (critical):** for each remaining outstanding beat whose `world_pressure` was visibly delivered this session (the world event named in the beat actually appeared in narration or Faction Moves), evaluate whether the beat's `what_changes` consequence ALSO landed. Three possible states:
        - **Landed cleanly** → mark beat complete (step ii).
        - **Did not land — pressure absorbed without consequence** → the beat is overdue and its current shape no longer fits. **Run `/dne arc revise` immediately**; do not just update `steering_notes`. The beat's `what_changes` was event-shaped (something specific happens) when it should be consequence-shaped (something fundamentally different is true) — revise both `what_changes` and `world_pressure` to fit a path that DOES land. The committed shape bends; it does not break.
        - **Pressure not yet delivered** → leave beat alone; expected to deliver next session.
      iv. Update `steering_notes` for the next outstanding beat with the *consequence shape* expected, not the specific event.
   e2. **Companions** (only if a companion subagent was spawned this session): run the *At end* step of `SKILL-companions.md`.
   f. **Tail verification** (display sessions; with `display: none` just write the canonical tail): before killing the display, verify the campaign-side `session_tail.json` is healthy:
      ```bash
      bash ${CLAUDE_SKILL_DIR}/display/verify_tail.sh <campaign-name>
      ```
      Exit 0 = healthy. Exit 1 = missing/empty/corrupt → write a canonical replacement to `<campaign dir>/session_tail.json` (`write_canonical_tail.py`) from session context (5–8 entries, each `{"text": "...", "_camp": "<name>"}`) BEFORE the display kill — once the display is dead, only the file matters. The display's own `_persist_tail` has skip-on-empty + atomic-write guards, but the backstop ensures a worst-case file state is impossible.
2. Stop the display — only when Session Flags say `display` is not `none` (or a display process is running):
   ```bash
   kill $(cat ${CLAUDE_SKILL_DIR}/display/app.pid 2>/dev/null) 2>/dev/null
   rm -f ${CLAUDE_SKILL_DIR}/display/app.pid
   ```
3. **Post-kill tail re-verification:** run `verify_tail.sh` once more after the kill. If it now reports unhealthy (file got truncated by a final write race), restore from the canonical version written in step 1f.

---

## `/dne abandon`

Exit the current session **without saving any state changes**. Use this when an error occurred and you want to discard everything since the last `/dne save` (or since load, if the session was never saved).

1. Confirm: *"Abandon session? All unsaved state changes will be lost. Type 'yes' to confirm."* — do not proceed until confirmed.
2. Do **NOT** write to state.md, world.md, npcs.md, session-log.md, or any character files.
3. Clear the autorun flag in memory (`autorun: false`) so the wait loop does not restart.
4. If `_display_running = true`, stop the display:
   ```bash
   kill $(cat ${CLAUDE_SKILL_DIR}/display/app.pid 2>/dev/null) 2>/dev/null
   rm -f ${CLAUDE_SKILL_DIR}/display/app.pid
   ```
5. Confirm: *"Session abandoned. No files were written. Run `/dne load <campaign>` to reload from the last saved state."*

---

## `/dne data [sync|status]`
- `sync` → `python3 ${CLAUDE_SKILL_DIR}/scripts/sync_srd.py` — checks upstream SHAs (5e-bits + FoundryVTT) and rebuilds `dnd5e_srd.json` only if either source has new commits
- `sync --force` → `python3 ${CLAUDE_SKILL_DIR}/scripts/sync_srd.py --force` — rebuild regardless
- `sync --check` → check upstream without rebuilding
- `status` → `python3 ${CLAUDE_SKILL_DIR}/scripts/build_srd.py --status` — show current dataset metadata

Dataset is bundled at `${CLAUDE_SKILL_DIR}/data/dnd5e_srd.json` (1467 records: spells, equipment, magic items, conditions, monsters, races, subraces, class features). No download required at runtime. Run `sync` only when you want to pull new upstream content.

---

## `/dne path [<new-path> | reset]`

View or configure where campaign and character data is stored. Wraps the
`DNE_CAMPAIGN_ROOT` env var.

- No args → `python3 ${CLAUDE_SKILL_DIR}/scripts/path_config.py` and show output.
- New path → `python3 ${CLAUDE_SKILL_DIR}/scripts/path_config.py set <path>`. Confirm to user, then remind them the change only takes effect in new shells (or after they `source` their rc on macOS/Linux).
- `reset` → `python3 ${CLAUDE_SKILL_DIR}/scripts/path_config.py reset`.

Persistence is via shell rc on macOS/Linux and via `setx` on Windows. Existing campaigns are not auto-migrated; `paths.find_campaign()` handles legacy fallback + copy-on-access.

---

## Update a world to the engine version

Bring an existing world fully in line with the current skill: every file a new campaign would get today, in this world's own voice. Canon never changes; the update only adds.

1. **Snapshot first:** `python3 ${CLAUDE_SKILL_DIR}/scripts/turn_snapshot.py -c <campaign> save --label "Before update to v<engine>"` (undo restores everything).
2. **List the work:** `python3 ${CLAUDE_SKILL_DIR}/scripts/campaign_version.py -c <campaign> audit`. It compares the campaign with the current templates (state.md, world.md, npcs, session log, every character sheet), Session Flags, the World Kit (validation errors, balance warnings and every optional field), factions, calendar and graph.
3. **Do every item.**
   - Missing sections: add them with the template's heading and fill them from what this campaign already established (state.md, session log, world.md). Leave a section empty with a one-line note rather than inventing history.
   - World Kit: write the new fields in the world's language and tone, fitting what already exists: playbook `moves` and a quick-build `template` per class, `disadvantages`, `place_tags`, `tech_level`, `status_levels`, `rarity`/`traits`/`tl` on special gear, `morale`/`instinct`/`instincts` on each monster. Fix any validation error; for a balance warning, adjust only monsters the party hasn't met yet, otherwise leave them and say so. Run `worldkit.py validate <campaign>` when done.
   - Factions: `faction.py add` every faction in world.md `## Factions` with numbers that match how strong the story says it is and its current activity as the goal.
   - Characters: add `## Moves` from their class, then ask each player their Bonds question (or leave Bonds for the next scene they share), and offer Flaws & Quirks.
   - Items marked *ask the table* (content level, lines and veils, Hero Points): ask in one message.
4. **Run `audit` again** until only items the table chose to skip remain.
5. **Mark it:** `python3 ${CLAUDE_SKILL_DIR}/scripts/campaign_version.py -c <campaign> mark`. Tell the players in a few lines what their world gained.

## `/dne update [--check]`

Pull the latest skill changes from `origin/main`.

- No args → `python3 ${CLAUDE_SKILL_DIR}/scripts/update_skill.py` and stream output (script prompts before pulling).
- `--check` → `python3 ${CLAUDE_SKILL_DIR}/scripts/update_skill.py --check` — report status without pulling.
- The script refuses to update if the working tree is dirty and uses `--ff-only` so it never silently merges divergent history.
- After a successful pull, remind the user to restart their agent session so the new `SKILL.md` and `SKILL-commands.md` are reloaded. Each campaign is offered **Update a world to the engine version** the next time it is loaded.

---

## `/dne display [start|stop|status]`
- `start` → ask LAN mode [y/n]; run `bash ${CLAUDE_SKILL_DIR}/display/start-display.sh [--lan]`; print URL(s)
- `stop` → `kill $(cat ${CLAUDE_SKILL_DIR}/display/app.pid) 2>/dev/null && rm -f ${CLAUDE_SKILL_DIR}/display/app.pid`
- `status` → `curl -sk $(cat ${CLAUDE_SKILL_DIR}/display/.scheme 2>/dev/null || echo http)://localhost:5001/ping` — reachable or unreachable
- No argument → print quick-start instructions

---

## `/dne list`
Read `${DNE_CAMPAIGN_ROOT:-$HOME/.dne}/campaigns/*/state.md`, print summary table: campaign name | last session date | session count.

---

## `/dne character new [campaign-name]`

**Read the campaign's ruleset first** — `python3 ${CLAUDE_SKILL_DIR}/scripts/paths.py campaign-ruleset <campaign>`, or inline:

```bash
python3 -c "import sys; sys.path.insert(0,'${CLAUDE_SKILL_DIR}/scripts'); from paths import campaign_ruleset; print(campaign_ruleset('<campaign>'))"
```

The result drives branching at steps 1 (ASI source), 4 (origin feat), and 5 (subclass timing). The default `2014` applies for legacy campaigns predating the ruleset field.

**World Kit campaigns:** if `<campaign>/worldkit.json` exists, every species/race, class and background offered below comes from it (`python3 ${CLAUDE_SKILL_DIR}/scripts/worldkit.py show <campaign>`), never from the SRD. Present them by world name with a one-line description; the class's `chassis` decides the 5e mechanics (hit die, saves, features by level, spell progression — re-skinned with the world's lexicon and the kit's `spells`). Pass `-c <campaign>` to every `character.py` call so it resolves origins, classes, backgrounds, armor and skill names from the kit.

**First, offer the two build paths — call `AskUserQuestion`:** *"How do you want to build [or: your character]?"*
- `Step by step` → the guided flow below (steps 1–10). Use this when the player wants to make each choice deliberately, or already knows the exact build.
- `Describe it` → the prose path (step 0 below). Use this when the player would rather say who the character is in a sentence and let you assemble a legal sheet.

Default to `Step by step` if the question is dismissed. Either path lands in the same sheet and runs the same validation, calc, and write steps — the only difference is how the choices are gathered.

0. **Describe-it path.** Ask one open question: *"In a sentence or two, describe your character — who they are, how they fight or solve problems, where they come from. I'll build a legal, level-appropriate 5e sheet from it and show you before anything's written."* Then:

   a. **Derive the build from the prose, model-side.** Map the description to a legal build for this campaign — from the World Kit if the campaign has one, otherwise the SRD: **class** (and, if the level warrants it, subclass per the ruleset's timing — see step 5), **species/race**, **background**, ability-score priorities (which two or three scores the concept leans on), skill/tool proficiencies the class+background grant, a fighting style or starting spells if the class has them, and a one-line **Character Pillar** (Bond / Flaw / Ideal / Goal — the same field step 2 fills). Read the description for what the player actually cares about — a "disgraced temple guard who talks their way out of fights" is a Paladin or Cleric with a Soldier/Acolyte background and CHA/CON priority, not a generic pick. Never invent a detail the prose contradicts; where the prose is silent, choose the most concept-fitting legal option and note it as a choice, not a fact.

   b. **Validate against 5e legality before showing anything.** The derived sheet must be legal for the campaign's ruleset and the agreed starting level: class/species/background all exist in this world (the World Kit if present, else 5e SRD or a source the table allows — look up anything you're unsure of via `lookup.py -c <campaign>`), ability scores come from a legal method (roll or point buy — step 3), ASI source matches the ruleset (race in 2014, background + one origin feat in 2024 — step 1), proficiencies are actually granted by the chosen class+background (no double-dipping, no out-of-list picks), and any spells/features are available at this level. If the concept implies something illegal (a level-1 character with a capstone feature, a subclass earlier than the ruleset grants it), pick the closest legal equivalent and say so.

   c. **Present the derived sheet for one confirmation.** Show the full build — species/race, class (+ subclass if any), background, ability array with the concept's priorities assigned, proficiencies, starting kit, and the derived Pillar with its source sentence — and ask: *"This is what I read from your description. Change anything, or shall I roll it up?"* Let the player adjust any field in prose; re-validate after any change.

   d. **Converge into the shared flow.** On confirmation, run the name-uniqueness check (step 1's `name_registry.py check`), then continue at **step 3** (finalize ability scores — reuse the derived priorities), **step 4** (racial/background bonuses + `character.py calc`), and steps 6–10 (equipment, write, roster mirror, supplemental builder). Do not re-ask the step-by-step questions the description already answered; only fill genuine gaps.

1. Ask: name, **species** (2024) or **race** (2014) — called *origin* in World Kit campaigns — class, background.

   **Name uniqueness check:** run `python3 ${CLAUDE_SKILL_DIR}/scripts/name_registry.py check "<name>"`. Exit 1 (duplicate) → surface prior use; player confirms or changes. After step 9 record it: `name_registry.py add --name "<name>" --type pc --campaign <campaign> --session <N>`.

   **2014 (race-as-ASI):** the species/race grants ability score increases (e.g. Wood Elf: +2 DEX, +1 WIS). Apply to abilities at step 4.
   **2024 (background-as-ASI):** the **background** grants the +2/+1 ability score increase OR three +1s, AND a free **Origin Feat** (SRD 5.2: Alert, Magic Initiate, Savage Attacker, Skilled — `lookup.py feat <name> --ruleset 2024`). Species grants traits but no ability scores. Players in 2024 must pick background BEFORE rolling abilities — the background's ASI pattern dictates which scores benefit.
2. Ask: *"In a sentence, what should the DM know about [Name]?"*
   - If answered: derive ONE pillar — **Bond**, **Flaw**, **Ideal**, or **Goal** (whichever fits best). Store both the raw sentence and derived pillar in `## Character Pillar`.
   - If skipped: leave `## Character Pillar` blank. Do not invent one. Do not re-prompt.
   - **Flaws & quirks:** offer up to two disadvantages and one quirk (World Kit `disadvantages` or the player's own); write them under `## Flaws & Quirks`. Optional; a player may take none.
   - **Quick build:** if the World Kit class has a `template`, offer it: its abilities replace step 3, its skills go to `--proficient`, its gear to step 6.
3. Ask: roll or point buy
   - Roll → `ability-scores.py roll`, present 3 arrays, player assigns
   - Point buy → `ability-scores.py pointbuy --check <scores>` to validate
4. Run `character.py calc -c <campaign> --class <class> …` with the BASE ability array; it applies the ability increases itself and prints base / increase / final plus every secondary stat (and a spellcasting block for casters) — never add increases by hand first. Which flags depends on the ruleset:
   - **2014:** `--race <origin/race> [--subrace <subrace>]` grants the increase (an unknown race exits non-zero, so a typo can't silently drop bonuses). A background is passed too — `--background <name>` — for its skills only; `--background-asi` is refused in 2014.
   - **2024:** `--background <name> --background-asi STR=2,CON=1` (or `+1/+1/+1`, checked against the background's three abilities) grants the increase; `--race <origin/species>` may still be given for its traits, and grants no increase. Note the background's origin feat (`lookup.py feat <name>`).
   Add `--armor <armor index> [--shield]` (or `--armor none`) for AC, `--proficient …` for chosen class skills (background and origin skills are added automatically), `--expertise …` for rogue/bard expertise, `--fighting-style <style>`, and `--subclass <name>` when one is owed at this level. `lookup.py race|origin <name>` shows the full entry. **Starting above level 1:** run `character.py levelup -c <campaign> --class <class> --from N` for each level from 1 up to the starting level and resolve every owed choice (subclass, ASIs, invocations, new powers); use maximum HP at level 1 and the listed average (or player rolls) after.
5. Ask: Fighting Style (fighter/paladin/ranger chassis — World Kit names from `class_options` kind `fighting_style` when the kit has them), powers/spells (if caster), and in 2024 the weapon masteries (fighter 3, barbarian/paladin/ranger/rogue 2) from `lookup.py mastery <property>`; record masteries on the sheet under `### Class Features → Weapon Mastery:`.
6. Assign starting equipment per class + background — in a World Kit campaign pick kit gear of the same kind and give starting money equal to the chassis's 5e starting gold (1 world coin = 1 gp), written in the world currency
7. Write to `characters/<file>.md` using `templates/character-sheet.md` — `<file>` is the name in lowercase with spaces as hyphens (`walt-brennan.md`; Thai names as written, `ทองดี.md`); scripts accept the display name or the file name. Set `## Campaign History → Origin campaign`
8. Add to `state.md` party line
8b. **Bonds — once the whole party exists:** ask each player one question about each other PC (*"Who here once saved your life?"*, *"Whose secret do you keep?"*, *"Who don't you trust yet?"*) and write the answers under `## Bonds` on both sheets. A World Kit class's playbook `moves` (`calc` lists them) go under `## Moves`; with `hero_points: on` run `character.py hero reset --char <name> -c <campaign>`; a character with `focus` powers gets `character.py focus reset --max <N>`.
9. Mirror to global roster: `cp characters/<name>.md ${DNE_CAMPAIGN_ROOT:-$HOME/.dne}/characters/<name>.md`
10. **Classic campaigns only** (no `worldkit.json` — the script skips World Kit campaigns on its own): run the supplemental builder to fetch any non-SRD spells/features the character uses:
    ```bash
    python3 ${CLAUDE_SKILL_DIR}/scripts/build_supplemental.py --character ${DNE_CAMPAIGN_ROOT:-$HOME/.dne}/campaigns/<name>/characters/<charname>.md
    ```
    This scans the character file for spells and features not in the SRD and fetches descriptions from dnd5e.wikidot.com into `dnd5e_supplemental.json`. Skips any entries already present. Safe to re-run.

---

## `/dne character sheet [name]`
Read `characters/<name>.md`, display cleanly. If name omitted and one character exists, show that one.

---

## `/dne character import <name> [from:<campaign>]`
1. Find character sheet: `from:<campaign>` specified → that campaign's characters/; otherwise check global roster `${DNE_CAMPAIGN_ROOT:-$HOME/.dne}/characters/<name>.md`; if neither → search all campaigns, list matches, ask.
2. Show summary (level, XP, HP, key inventory) and ask: *"Import at current level [X], or level up before starting?"*
   - As-is → copy directly; Level up first → run `/dne level up` on source sheet
3. Copy to current campaign's `characters/<name>.md`. Update: Campaign, Last Updated, Previous campaigns, Death Saves (reset).
4. **Crossing worlds:** if the target campaign has a `worldkit.json` (or the source did and the target doesn't), translate the character into the target world: map their origin and class to the closest kit entries **with the same chassis**, swap gear for world equivalents of equal mechanics, and rename powers to kit `spells` of the same level. Keep level, XP, HP and ability scores. Show the mapping and confirm with the player.
5. Add to `state.md` party line. Update global roster.
6. Run supplemental builder for any non-SRD entries:
    ```bash
    python3 ${CLAUDE_SKILL_DIR}/scripts/build_supplemental.py --character ${DNE_CAMPAIGN_ROOT:-$HOME/.dne}/campaigns/<name>/characters/<charname>.md
    ```
7. Deliver one-paragraph in-character aside — how does it feel to step into a new world?

---

## `/dne level up [name]`
1. **XP gate — check first:**

   | Level | XP required | Level | XP required |
   |-------|-------------|-------|-------------|
   | 2 | 300 | 11 | 85,000 |
   | 3 | 900 | 12 | 100,000 |
   | 4 | 2,700 | 13 | 120,000 |
   | 5 | 6,500 | 14 | 140,000 |
   | 6 | 14,000 | 15 | 165,000 |
   | 7 | 23,000 | 16 | 195,000 |
   | 8 | 34,000 | 17 | 225,000 |
   | 9 | 48,000 | 18 | 265,000 |
   | 10 | 64,000 | 19 | 305,000 |
   |    |         | 20 | 355,000 |

   Insufficient XP → report deficit and stop. Only continue on explicit DM override.
2. Read sheet. Update the sheet's XP line to the next level's threshold (`**XP:** <xp> / <next>`). Run `character.py levelup --class <c> --from <n> --con-mod <m> [--con-mod-before <old>] [--subclass <s>] -c <campaign> --char <name>` (`--char` keeps powers already on the sheet out of the list to learn). It lists the **choices the new level owes** — an Ability Score Improvement, the subclass, Eldritch Invocations (by the SRD table), a Pact Boon, a Fighting Style — and the retroactive HP when the CON modifier rose; resolve every one with the player before writing the sheet. Apply class features. Ask for HP roll or average. Update sheet + global roster. Narrate the growth.

   **Ruleset-aware subclass timing:** read campaign ruleset via `paths.campaign_ruleset(<campaign>)`.
   - **2014:** Subclass selection happens at the class's specified level (Cleric/Sorcerer/Warlock at 1; Druid/Wizard at 2; most others at 3).
   - **2024:** Subclass selection unifies at **level 3** for ALL classes. If the player is hitting level 3 in a 2024 campaign and hasn't picked a subclass yet, prompt for it. Class features that 2014 placed at level 1 (e.g. Cleric Domain) shift to level 3 in 2024.

   **Weapon Mastery (2024 only):** Fighter/Barbarian/Paladin/Ranger/Rogue gain Weapon Mastery at level 1 (Fighter knows 3 mastery properties; others know 2). Track which properties the character knows on the sheet under `### Class Features → Weapon Mastery: <list>`. Properties are picked from the eight in `data/dnd5e_srd_2024.json → weapon_mastery_properties`. The character can use mastery only with weapons that have the matching property (`lookup.py item <weapon> -c <campaign>` shows its `Mastery:`).

---

## `/dne npc [name]`
- Existing → read full entry from npcs-full.md (search by name), portray in character with voice/quirk
- New → `python3 ${CLAUDE_SKILL_DIR}/scripts/npc.py -c <campaign> add --name "<Name>" --role "<role>" --cr <CR> --aliases "<names used in play>" [--faction F] [--location L] [--attitude neutral] [--notes "<one line>"]` writes the `npcs.md` row and the `npcs-full.md` entry with fair stats for that CR. Then write every `<fill: …>` part of the entry: main attack and abilities, demeanor, motivation, secret, speech quirk, current goal, schedule, all four personality axes, ≥2 relationships to existing NPCs, and `### History` (background, how they met the party). Do this the turn a named character first appears, without waiting for `/dne npc`.
- Growing → `npc.py -c <campaign> check` lists who is due (the `npc_growth` dial); `npc.py -c <campaign> advance "<Name>" --what "<what they did meanwhile>" [--levels N]` raises CR/Level, HP and AC (never lowers them) and adds the History line. Raise the Attack line by what it prints (it only ever names increases), and update goal, location and relationships.

  **Name uniqueness check:** before generating, run `python3 ${CLAUDE_SKILL_DIR}/scripts/name_registry.py check "<proposed-name>"`. If duplicate (exit 1), surface the prior use to the DM and offer either: (a) proceed with the duplicate (some scenarios want recurring names — a Voss reference can be deliberate); or (b) regenerate with a different name. Whichever path is chosen, after the NPC is added to npcs.md / npcs-full.md, call `name_registry.py add --name "<name>" --type npc --campaign <name> --session <current>` to record the entry.

  When **/dne new** generates a batch of NPCs during world-gen, run the check on each generated name in the same loop: if duplicate, regenerate that name (re-prompt the LLM with the prior name added to a "do-not-pick" exclusion list). After world-gen completes, batch-call `name_registry.py add` for every accepted NPC.

## `/dne npc attitude <name> <shift>`
Find NPC in npcs.md, shift attitude one step (hostile → suspicious → neutral → friendly → allied — the same scale as the graph and Live State Flags), update `npcs.md` and `npcs-full.md`, log reason and date; if the graph is initialised also run `campaign_graph.py set-disposition`.

## `/dne companion <add|leave|mode|status|ask|on|off> [name] [...]`
Opt-in NPC companions played by their own subagent. Full procedure: read `${CLAUDE_SKILL_DIR}/SKILL-companions.md`.

## `/dne npc rename "Old Name" <"New Name" | random> [flags]`
Rename a character across an entire campaign — `npcs.md`, `npcs-full.md`, `state.md` (every section), `session-log.md`, `graph.json` (node + edges preserved), and `characters/<slug>.md` if `--type pc`. Backs up the campaign first.

Maps to: `python3 ${CLAUDE_SKILL_DIR}/scripts/npc_rename.py --campaign <current> --old "..." --new "..." [flags]`. Use the currently loaded campaign by default; for explicit-campaign use, pass `--campaign <name>` directly.

Flags:
- `--random` — pick a name from the bundled fantasy-name corpus (~4800 unique combinations) that isn't already in `${DNE_CAMPAIGN_ROOT:-$HOME/.dne}/.name_registry.json`. Mutually exclusive with explicit "New Name".
- `--type npc | pc` (default `npc`) — `pc` also moves the character file and updates the global roster.
- `--dry-run` — show all hits across files without writing. Always run first for sanity.
- `--yes` — skip the confirmation prompt.
- `--include-archive` — also rename in `session-log-archive.md`. **Default is to leave the archive untouched** for historical accuracy and add a one-line audit note at the top: *"`<old>` renamed to `<new>` at S<N>; historical entries below preserve the original name."*

The script always backs up the campaign to `<name>.backup-rename-<old-slug>-YYYYMMDD-HHMMSS/` before any writes. Revert command is printed at the end.

After rename, the name registry is updated: old name marked `retired_from` this campaign with `replaced_by` pointing at the new slug; new name added with this campaign's current session as `first_session`.

## `/dne registry <subcommand>`
View and manage the cross-campaign name registry at `<DNE_CAMPAIGN_ROOT>/.name_registry.json` (default `~/.dne/`). Used by `/dne npc rename --random` to never reuse a name, and by `/dne new` step 11 and `/dne character new` / `/dne npc <new>` to flag duplicates at creation time.

Maps to: `python3 ${CLAUDE_SKILL_DIR}/scripts/name_registry.py <subcommand> [args]`.

- `/dne registry rebuild [--include-prose]` — scan every campaign's `npcs.md`, `npcs-full.md`, `characters/*.md`, and `graph.json` (node names); rebuild the registry from canonical sources. Preserves any existing `retired_from` history. Run once on install, then ad hoc when desired.

  **`--include-prose` (opt-in):** also scan `session-log.md` and `session-log-archive.md` for capitalized 2–3-word sequences (likely-name patterns) in any cased script — accented Latin, Cyrillic and Greek included — and, for Chinese, Japanese and Korean, which have no capitals, for a name directly followed by an honorific (田中さん, 李明先生, 민수씨). Filtered against a stopword list (places, factions, mechanic words like "Theo Stealth", sentence starts) but **regex-based extraction is inherently noisy** — typically 5–15× more entries than canonical, with maybe 10–20% real catches. Tagged `source: prose` to distinguish; query with `/dne registry list --source prose` to manually review and prune. For high-quality prose extraction, the future move is LLM-backed (similar to `/dne graph extract`).

- `/dne registry list [--campaign C] [--type npc|pc] [--source canonical|prose]` — print all registry entries; filter by campaign-currently-active, type, or source.
- `/dne registry lookup <name>` — case-insensitive lookup; prints the full entry as JSON.
- `/dne registry check <name> [--json]` — check whether a proposed name collides with the registry. Exit 0 if unique, 1 if duplicate. A name whose first name (titles like Lady / Sir / Captain stripped) matches a player character's is also flagged — "Lady Willa Torne" beside a PC "Willa Finch" — as a warning, exit 0; rename the NPC unless the echo is deliberate.
- `/dne registry clashes [--campaign C]` — list every NPC that shares a first name with a player character; exit 1 if any. Severity (`warn` default, `strict` opt-in via `<DNE_CAMPAIGN_ROOT>/.name_registry_config.json`) controls whether duplicates are reported as warnings or hard refusals. Used by `/dne new`, `/dne character new`, `/dne npc <new>` procedures.
- `/dne registry add --name N --type npc|pc --campaign C --session N` — record a new entry manually (auto-called by `/dne npc rename` and the creation-time uniqueness hooks).
- `/dne registry retire --name N --campaign C [--replaced-by NEW]` — mark a name as no longer active in a campaign (auto-called by `/dne npc rename`).

The registry by default captures **canonical** characters (those in `npcs.md` / `npcs-full.md` / `characters/` / graph.json node names). Names that appear only in session-log prose (one-off mentions, throwaway NPCs, skill-check labels) are NOT registered by default — that's deliberate, to avoid banning common names because of incidental use. The `--include-prose` flag is opt-in for users who want the broader (noisier) view.

**Severity config:** create `${DNE_CAMPAIGN_ROOT:-$HOME/.dne}/.name_registry_config.json` with `{"severity": "strict"}` to make all duplicate detections refuse-by-default rather than warn-and-allow. Set to `"none"` to disable checks entirely (registry rebuild and rename still work).

---

## `/dne characters`
List all characters in global roster (`${DNE_CAMPAIGN_ROOT:-$HOME/.dne}/characters/`). Display: name, race/class/level, origin campaign, previous campaigns, last updated.

---

## `/dne roll <notation>`
Run `scripts/dice.py <notation>`. Display output verbatim. Examples: `d20`, `2d6+3`, `d20 adv`, `4d6kh3`. For a d20, say what it is for with `--vs check|save|attack|death` (only an attack crits or fumbles) and add `--dc N` for a PASS/FAIL verdict.

---

## `/dne combat start`
1. Identify combatants; collect name, DEX mod, HP, AC, type (pc/npc) for each.
2. Run `combat.py init '<JSON>'` — under `roll_mode: players` collect each player's d20 and add `"roll": N` to that PC's entry (`"init_bonus"` for Alert-style bonuses, `"max_hp"` when a PC starts wounded); everyone else is rolled by the script. Display tracker and per-combatant roll breakdown.
3. Send initiative to display:
   ```bash
   python3 ${CLAUDE_SKILL_DIR}/display/send.py << 'DNDEND'
   ⚔️ Initiative — Round 1
   [Name]: d20(N) + DEX = total
   Turn order: [Name] → [Name] → ...
   DNDEND
   ```
4. Push turn order to stats sidebar:
   ```bash
   python3 ${CLAUDE_SKILL_DIR}/display/push_stats.py --turn-order '{"order":[...],"current":"FirstName","round":1}'
   ```
5. Save STATE_JSON to `state.md` under `## Active Combat`.
6. Step through turns using the per-turn sequence (in SKILL.md Active DM Mode).
7. On combat end: update HP in character sheets, clear `## Active Combat`, `push_stats.py --turn-clear`, narrate aftermath, send XP summary, run `tracker.py -c <campaign> clear` (ends encounter conditions and round-long effects; minute/hour effects, exhaustion and petrification stay).

**XP awards:** first `python3 ${CLAUDE_SKILL_DIR}/scripts/xp.py award --campaign <name> --characters "<PCs>" --monsters "<name>:<CR>:<count>,…"` (or `--difficulty … --type noncombat` for an objective). It works the amounts out from the tables, writes each sheet and updates the display; XP typed onto the display or into a sheet by hand is flagged on the next turn (`XP NOT AWARDED BY THE ENGINE`). Then announce its numbers in the final display send:
```bash
python3 ${CLAUDE_SKILL_DIR}/display/send.py << 'DNDEND'
[combat aftermath narration]

⭐ XP Awarded
- [Enemy] defeated: N XP
- [Objective] completed: N XP
- Total: N XP ÷ [players] = N XP each
- [Name]: N / 300 XP | [Name]: N / 300 XP
DNDEND
```

---

## `/dne rest <short|long>`
Three scripts, one job each: **`economy.py rest`** writes the rest to the character sheets, **`character.py`** only computes (hit-die rolls, previews), **`calendar.py rest`** moves the clock and the tracker's timed effects. Neither wipes effects — do not run `tracker.py clear` for a rest; it is for the end of an encounter.

**Short (1 hour):**
1. Ask how many Hit Dice each player spends. The player rolls them (`dice.py <K>d<N>+<K×CON> --player <pc> --label "Hit Dice"`), or use `character.py hitdie --die d<N> --con-mod <M> --hp <cur> --max-hp <max> --remaining <R> --count <K> -c <campaign>` (refuses at 0 HP or with no dice left).
2. Apply per character: `economy.py -c <campaign> rest --type short --char "<Name>" --hit-dice <K> --heal <total>` — updates HP (capped at max), Hit Dice remaining, and restores a warlock-chassis character's pact slots.
3. Note class features that recharge (e.g. Second Wind → `push_stats.py --player NAME --second-wind true`).
4. Advance time: `calendar.py -c <campaign> rest short`.

**Long (8 hours):**
1. **Life-state gate first.** A character at 0 HP — dying, stable or dead — gains **nothing** from a long rest; RAW it needs at least 1 HP. `economy.py` leaves such a sheet untouched and says so; resolve how they regain consciousness first (a stable creature regains 1 HP after 1d4 hours).
2. `economy.py -c <campaign> rest --type long --char all` — for everyone else: full HP, Temp HP 0, Hit Dice regained equal to **half the character's total, rounded down, minimum 1** (2014) or **all spent dice** (2024), spell slots restored, death saves reset. Exhaustion drops **one level lower** when `calendar.py rest long` runs (step 4; 2014 also requires food and drink). `character.py rest long … -c <campaign>` previews these numbers if needed.
3. Push: `push_stats.py --player NAME --hp <max> <max>`, `--hit-dice-restore <n>`, and `--second-wind true`.
4. Advance time: `calendar.py -c <campaign> rest long` — ends every concentration, lowers tracked exhaustion by one for anyone above 0 HP, runs effects down by eight hours. Reset a dying character's death saves with `tracker.py saves <name> reset` only once they have regained HP.
5. Update `state.md` in-world date to match calendar output.

---

## `/dne recap`
Read session-log.md. Deliver 3–5 sentence in-character narrator recap of the most recent session entry.

## `/dne pin [<fact> | list | remove <fact-or-number>]`

Manage the campaign's **Pinned Facts** — the soft, stable canon the table never wants forgotten. Pinned facts live in `state.md → ## Pinned Facts` and are read at every `/dne load` alongside `## DM Style Notes`, then kept hot for the whole session. They are the DM's long-term memory: things that don't fit Live State Flags (which track shifting state) because they don't change — a promise made, a dead sibling's name, an in-joke, a house rule, a detail the player has said matters.

- **`/dne pin <fact>`** — append `<fact>` as a new bullet under `## Pinned Facts` (replacing the *(none pinned yet)* placeholder if present). Confirm what was pinned. Keep each fact to one line; pin the fact, not a paragraph.
- **`/dne pin`** *(no args, mid-scene)* — when the player says "remember this" / "don't forget X" / "pin that", capture the fact they mean in one line and pin it as above, then acknowledge briefly in the fiction and move on.
- **`/dne pin list`** — read and print the current `## Pinned Facts` bullets.
- **`/dne pin remove <fact-or-number>`** — remove the matching bullet (by its text or its position in the list). If it leaves the section empty, restore the *(none pinned yet)* placeholder. Confirm the removal.

Pinned facts are never rewritten wholesale at `/dne save` the way Live State Flags are — they only change when the player pins or unpins one, or when one is corrected because it became wrong. A running account of *what happened* already lives in `session-log.md`, `## Recent Events`, and `## Continuity Archive` (queried via `/dne recap`); Pinned Facts is the separate, deliberately small set of things to always carry, not a second event log.

## `/dne world [kit]`
Read and display world.md. `/dne world kit` → `python3 ${CLAUDE_SKILL_DIR}/scripts/worldkit.py show <campaign>` (origins, classes → chassis, lexicon, threats). After any hand edit of `worldkit.json`, run `worldkit.py validate <campaign>`.

## `/dne quests`
Read `state.md` → display Active Quests and Open Threads sections.

---

## `/dne arc [status|advance|revise|view]`

Manage the dynamic campaign arc. The `advance`/`revise`/`new` subcommands are active only when `state.md → ## Campaign Arc` has `type: dynamic` — no-op for sandbox campaigns. For **structured (imported)** campaigns, `status` and `view` read from `arc.md` (chapter advancement happens at `/dne save`, not here); `advance`/`revise`/`new` are no-ops.

- **`/dne arc`** or **`/dne arc status`** — print current act, current beat label, `what_changes` for the current beat, and `steering_notes`. Quick reference, one screen. (Structured: print `current_act`, `current_chapter`, current chapter's `key_beats`, and `outstanding_beats` from `state.md`; read `arc.md` only if more detail is asked for.)
- **`/dne arc advance [beat-id]`** — mark the named beat complete (current beat if omitted). Remove from `outstanding_beats`. Advance `current_beat` to the next pending beat. If all beats in an act are complete, advance `current_act`. Update `steering_notes` to describe how to reach the newly current beat without forcing it.

  **When the final beat (3b) is marked complete — arc continuation:**
  `outstanding_beats` is now empty. Ask: *"The arc is complete. Continue the campaign with a new arc? [y/n]"*
  - **Yes** → run `/dne arc new` (see below).
  - **No** → set `type: sandbox` and clear `outstanding_beats`. The campaign continues open-ended from the resolution state.

- **`/dne arc new`** — generate a new arc for a campaign that has completed its previous arc. Use the Strongest tier for this step.

  The new arc must be **intentionally distinct** — not a continuation of the same conflict, but a new chapter that grows from the changed world. The resolution of arc N is the status quo of arc N+1.

  Procedure:
  1. Read the completed arc's `resolution` field — this is now the world's baseline.
  2. Read `## DM Notes`, `## World State`, `## Faction Moves`, and any `## Continuity Archive` entries to understand what the world looks like post-resolution.
  3. Derive the new arc from **the consequences** of what just resolved. Ask: *what problem did solving the last arc create? What power vacuum formed? What did the party's victory cost that now has to be reckoned with? What was ignored because the last arc demanded all attention?*
  4. Generate a new full arc (theme, resolution, acts 1–3, 6 beats) using the same format as the initial arc. The new theme must be meaningfully different from the previous one — same world, new lens.
  5. Archive the completed arc: move the current `acts` block, `theme`, and `resolution` into a new `## Arc History` section in state.md under `arc_N` (numbered), with a one-line summary of how it resolved.
  6. Write the new arc to `## Campaign Arc`, incrementing `arc_number`. Set `current_act: 1`, `current_beat: "1a"`, `outstanding_beats` to all 6 beat ids.
  7. Append to `revision_log`: `"<date>: Arc N complete. New arc N+1 generated. [one-line premise of the new arc]"`
  8. Deliver a one-paragraph summary of the new arc's premise and how it differs from the previous one.

- **`/dne arc view`** — show full arc: theme, resolution, all acts and beats with completion status (current / complete / pending). If `## Arc History` exists, show a one-line summary of each completed arc above the current one.
- **`/dne arc revise`** — open revision flow for when the story has taken a major unexpected turn OR when the auto-trigger from /dne end's pre-emption check fires (most common case):
  1. Show all outstanding beats with their current `what_changes` and `world_pressure`.
  2. Ask: *"What's changed in the story that the arc doesn't reflect?"* — or, when auto-triggered by pre-emption, name the pre-empted beat directly: *"Beat 2b's pressure delivered but the consequence didn't land. Picking a revision path…"*
  3. **Apply one of three landing-path templates** (per SKILL.md rule 8) to the affected outstanding beat:
     - **Cost path** — `what_changes` becomes "the party paid a concrete cost for moving fast"; `world_pressure` becomes the specific cost (cover blown, ally compromised, position lost). Best when the party pre-empted cleanly.
     - **Secondary consequence path** — `what_changes` becomes "the world responded to being pre-empted in a way the party didn't anticipate"; `world_pressure` becomes the new escalation (the antagonist reads the disruption as a signal and does something WORSE). Best when the antagonist is intelligent and adaptive.
     - **Deferred path** — keep the original `what_changes` shape; rewrite `world_pressure` to a NEW pressure pointing at the same consequence, scheduled for the next 1–2 sessions. Best when the original consequence is still narratively essential and only the timing slipped.
  4. Rewrite `what_changes` (consequence-shaped per the rule in /dne new step 13) and `world_pressure` (event-shaped is fine) for the affected beat. Do NOT modify completed beats.
  5. Append to `revision_log`: `"<date>: <beat-id> — <path: cost/secondary/deferred> — <what changed and why — one sentence>"`
  6. Update `steering_notes` to describe the next session's expected delivery.
  7. Confirm what was revised. Show before/after for `what_changes` and `world_pressure`.

---

## `/dne graph <subcommand>` — campaign relationship graph

Local-only typed-edge relationship graph supplementing markdown. Stored at `${DNE_CAMPAIGN_ROOT:-$HOME/.dne}/campaigns/<name>/graph.json`. Supplements `npcs-full.md` / `session-log.md` — does not replace them. Edges are time-stamped (`since_session` / `until_session`), so historical state is recoverable.

**Auto-pulled at `/dne load` step 7** (scene-context) and **swept at `/dne save`** (relationship-shift extraction). The DM also uses `/dne graph scene-context` on demand mid-session, especially before heavy social or political scenes.


All subcommands invoke `python3 ${CLAUDE_SKILL_DIR}/scripts/campaign_graph.py <subcommand> --campaign <name> [args]`.

### `/dne graph init [campaign-name]`
First-time bootstrap. Run `campaign_graph.py init --campaign <name>` to create the empty `graph.json` — idempotent on an empty graph, and it refuses to overwrite one that already holds nodes or edges. Then read existing `npcs.md` / `world.md` / `state.md` for the campaign. Propose a node list (NPCs as `npc_*`, factions as `faction_*`, key locations as `place_*`) and a starter edge list (faction membership from npcs.md tables, NPC location from "Lives in / Based at" fields, faction relationships from world.md). Display the proposed list to the DM and **ask for approval** before writing — do not silently extract. After approval, run `add-node` and `add-edge` for each. Use `--since 1` for everything already true before play (a fresh campaign's session count is 0), and the current session number for anything newer.

For existing campaigns being initialized for the first time, the `/dne load` flow offers to back the campaign directory up first; honour that flow rather than running init from a cold prompt.

### `/dne graph add-node --type T --name N [--tags ...] [--summary ...]`
Add a single node. Type is open vocab; suggested: `npc`, `faction`, `place`, `item`, `thread`. Default id is `<type>_<name-slug>`.

### `/dne graph add-edge --from <id> --to <id> --type T [--since N] [--note ...]`
Add a typed edge between two existing nodes. Edge type is open vocab; common: `loyal_to`, `opposes`, `allied_with`, `member_of`, `lives_in`, `controls`, `knows_about`, `friends_with`, `lover_of`, `owes`, `rules`, `related_by_blood`, `advances_thread`, `blocks_thread`. Always supply `--since` (the current session number from state.md) so historical replay works.

### `/dne graph set-disposition --to <npc-or-faction> --level <L> [--since N] [--note ...]`
Type how the **party** stands toward an NPC or faction on the normalized scale `allied | friendly | neutral | suspicious | hostile` — the same five values the display's faction panel uses, so the graph and the sidebar speak one language. The edge runs from the shared `party` node (auto-created on first use) to the target; its type is inferred from the target — `disposition` for an NPC, `standing` for a faction — and it carries the `level`.

Single-valued and current: setting a new stance **closes** any prior active party→target stance edge at `--since` (its arc stays queryable with `--at-session <old N>`) and adds the new level, so `scene-context` only ever surfaces the party's *current* stance. `scene-context` renders it as `The Party --[disposition:suspicious]--> Aldric` so the stance reads at a glance. Always pass `--since <current-session-N>`.

Use it whenever the fiction shifts the party's standing — an NPC turns on them, a faction they wronged goes hostile, an alliance is earned. It is the graph-side counterpart to the `standing` values pushed to the display via `push_stats.py --factions` and to the NPC-disposition lines in `state.md → ## Live State Flags`; keep the three consistent when a stance changes.

### `/dne graph close-edge --id <edge-id> --at-session N`
Mark an edge as ended at session N (e.g. when an alliance breaks). Original edge is preserved with `until_session` set; it remains visible in historical queries but is excluded from "active at session ≥ N" results.

### `/dne graph list [--type T] [--at-session N]`
Print a compact node table grouped by type. With `--at-session`, also reports active edge count at that session.

### `/dne graph show --id <node-id>`
Print one node with all incoming and outgoing edges.

### `/dne graph scene-context --place <id> [--present id1,id2] [--threads id1,id2] [--hops H] [--at-session N]`
**Primary query for in-session use.** Returns a focused subgraph from the current scene (place + present NPCs + active threads) bounded by hop count, optionally filtered to edges active at a given session. Output is grouped: nodes by type, then a relationships block. Default `--hops 2`. Use this when you need to recall who-relates-to-whom in the current scene without re-reading `npcs-full.md` or session-log archives.

### `/dne graph subgraph --seed <id> [--seed <id>] [--hops H] [--at-session N]`
Lower-level traversal — same as `scene-context` but with arbitrary seed nodes. Use when the scene framing doesn't fit (e.g. tracing faction politics independent of any specific place).

### `/dne graph extract [campaign-name] [--last-session-only]`
Run a Haiku pass over the campaign's session-log to propose new edges with verbatim source-anchors. Outputs a proposal JSON to `${DNE_CAMPAIGN_ROOT:-$HOME/.dne}/campaigns/<name>/graph-proposals-<date>.json` for human review. Does **not** write to graph.json — that's the apply step.

### `/dne graph extract --deterministic [--last-session-only] [--write FILE]`
**Zero-LLM alternative.** Pattern-matches session-log sentences against the bundled verb-table seed (`data/graph/verb_table_seed.yaml`) and emits the same proposal shape as the Haiku pass — no Claude API call, no cost, fully portable. Trades recall (~50%, clean subject-verb-object only) for precision (~95%) and determinism. Prints proposals to stdout, or writes them with `--write`.

### `/dne graph extract --deterministic --apply [--min-confidence low|medium|high] [--no-auto-nodes]`
One-shot auto-apply: run deterministic extraction and write proposals at/above `--min-confidence` (default `high`) straight into `graph.json` — deduped against existing edges and **idempotent** (re-running adds nothing new). Missing nodes are auto-created as `npc_*` placeholders unless `--no-auto-nodes` is set. Use this for a hands-off relationship sweep at `/dne save`; use the review path below when you want a human in the loop.

### `/dne graph extract-apply --proposals <file> [--pick N1,N2,...] [--review]`
Apply previously-extracted proposals (from either the Haiku or deterministic pass). Without `--pick`/`--review`, applies all. With `--pick`, applies only the listed proposal indices. With `--review`, walks proposals one at a time with y/n/q prompts.

### Suggested DM workflow

1. **First session after install:** `/dne load` will offer to initialize the graph (with a backup-first prompt). Accept; review the proposed seed; approve.
2. **During session:** when a relationship shifts in narration, run `/dne graph add-edge` (or `close-edge`) with `--since` set to the current session number. Don't batch this — record at the moment of the narrative change so you don't forget.
3. **Before a heavy social/political scene:** run `/dne graph scene-context --place <current-place> --present <key-NPCs>` to refresh which relationships matter right now.
4. **At `/dne save`:** review the session log and add any edges you missed during play (the save flow runs an automatic sweep and presents proposals for approval).

---

## `/dne oracle <subcommand>` — solo/improv oracle tools

Dice-driven oracles for improvised play — they keep pacing transparent and rollable instead of letting the DM invent every beat. All subcommands invoke `python3 ${CLAUDE_SKILL_DIR}/scripts/oracle.py <subcommand>`. Rolls are stdlib-random and seedable (`--seed N`) for reproducibility. Zero LLM calls.

### `/dne oracle chaos [--campaign N]`
Show the campaign's current **chaos factor** (Mythic-style, 1–9). 1 = the PCs are firmly in control; 9 = the world is spinning out from under them. Stored in `state.md → ## Session Flags` as `chaos_factor: N` (default 5).

### `/dne oracle chaos set --campaign N --value V`
Set the chaos factor to V (clamped 1–9) and persist it to `state.md`.

### `/dne oracle chaos adjust --campaign N (--pc-won | --pc-lost)`
Move the factor one step the standard Mythic direction: `--pc-won` (PC achieved the scene goal) → −1; `--pc-lost` (PC was reactive or failed) → +1. Adjust once per scene.

### `/dne oracle ask [--likelihood L] [--campaign N | --chaos C] [--seed S]`
Ironsworn-shaped **yes/no** oracle. Likelihood ∈ {`sure-thing`, `likely`, `50/50`, `unlikely`, `no-way`} (default `50/50`); the chaos factor (read from the campaign, or `--chaos`) shifts the odds. Returns a verdict — `yes`/`no` optionally suffixed `-and` (extreme, on doubles) or `-but` (qualified, near the threshold) — plus the d100. Use when the fiction poses a question the prep doesn't answer.

### `/dne oracle event [--seed S]`
Mythic **Random Event Focus** (d100). Returns a direction label (`new NPC`, `NPC action`, `move toward thread`, `PC negative`, etc.) — interpret it against the campaign's current threads, NPCs, and locations. Use when a scene needs an unexpected turn.

### `/dne oracle scene [--seed S]`
Two-word **scene-meaning** generator (action verb + subject noun, One Page Solo Engine). Use as a spark when narration runs dry or an event focus rolls. Interpret loosely.

---

## `/dne recap` — precomputed party state-diff

Deterministic state-diff between two character snapshots — `python3 ${CLAUDE_SKILL_DIR}/scripts/session_recap.py`. Recaps are the #1 thing an LLM hallucinates (wrong HP, dropped facts); this computes the change set from data so narration never has to. Reads the character sheets at `${DNE_CAMPAIGN_ROOT:-$HOME/.dne}/campaigns/<name>/characters/*.md` and merges live `tracker.json` conditions/concentration. Zero LLM calls.

### `/dne recap snapshot --campaign N`
Snapshot the party's current state (HP/temp/level/hit dice/death saves/conditions/concentration/exhaustion/inspiration/spell slots) to `${DNE_CAMPAIGN_ROOT:-$HOME/.dne}/campaigns/<name>/.recap/`. Rolls the previous `last.json` to `prev.json` so the next diff has a baseline. **Take a snapshot at `/dne end`** so the next session's load can diff against it.

### `/dne recap diff --campaign N [--before FILE] [--after FILE]`
Diff the prior snapshot against the current state and print a one-paragraph plain-English summary (e.g. *"Aldric: took 18 damage (30→12 HP); gained Poisoned; spent 2 level 1 slots."*). With no `--before`, uses the stored `prev`/`last` snapshot; with no `--after`, snapshots live state on the fly. **Inject this line at `/dne load`** as the mechanical half of the recap. `--json` emits the structured change list.

---

## `/dne tutor on` / `/dne tutor off`
Toggle tutor/learning mode. Write `tutor_mode: true/false` to `state.md` under `## Session Flags`. Session-scoped — does not persist to next `/dne load` unless explicitly set again. (Full tutor mode behavior is in SKILL.md.)

---

## `/dne autorun on` / `/dne autorun off`

Toggle autorun (taxi) mode — Antigravity drives the turn loop automatically when players submit via the display companion (`http://localhost:5001` or ngrok).

**On:**
1. Write `autorun: true` to `state.md → ## Session Flags`.
2. Confirm to the DM: *"Autorun enabled. Players submit via the display; I'll pick up each action automatically. Send me a message at any time to take control of a turn."*
3. If the user specified an interval (e.g. `/dne autorun on 45`), write `autorun_interval: 45` to `state.md → ## Session Flags`. Default is 60 if omitted.
4. Launch `autorun_wait.py` as a background task (Antigravity: `run_command` with `WaitMsBeforeAsync: 500`; Claude Code: Bash with `run_in_background: true`):
   ```bash
   python3 ${CLAUDE_SKILL_DIR}/display/autorun_wait.py
   ```
   When the player submits on the web, the host wakes you with the background task's completion containing the player's action.
   Every turn after that ends by relaunching it, including turns where you decline a request (SKILL.md → Autorun, step 3).
5. Launch the watchdog once, as a second background task the same way: `python3 ${CLAUDE_SKILL_DIR}/display/autorun_watchdog.py`. It stays silent while the game runs and wakes you with `AUTORUN STALLED` if a player action waits 90 seconds with no wait loop; follow its message, then start it again.

The display shows a pie-clock countdown draining from full to empty over the interval. Green pulse = actively waiting. Configurable via `autorun_interval: N` in state.md (default 60 seconds).

**Off:**
1. Write `autorun: false` (or remove the line) to `state.md → ## Session Flags`.
2. Confirm: *"Autorun disabled. Back to manual mode."*
3. Do NOT start the autorun wait after this response.

**Check on `/dne load`:** If `autorun: true` is present in state.md, tell the DM autorun is active and begin the background wait loop (and the watchdog, `autorun_watchdog.py`) after the recap paragraph.

**When NOT to run the autorun wait (even if flag is set):**
- Mid-combat, resolving a specific combatant's turn
- Waiting on a player dice roll result
- The DM just sent a message (they're driving this turn)
- During `/dne save`, `/dne end`, or any command response

---

## `/dne autosave on` / `/dne autosave off`

Toggle the behind-the-scenes continuity checkpoint. Writes `autosave: on|off` to `state.md → ## Session Flags`. **Default is on.** Applies to every campaign type (structured, dynamic, sandbox) — it only ever writes the same continuity anchors a normal save writes, just more often, and never changes narration.

**What autosave does when on:**
1. **In-model micro-saves** (always available, no setup): the DM silently flushes continuity at scene boundaries and on a turn cadence — see the *Continuity micro-save* rule in SKILL.md. This keeps unsaved state near zero so a context compaction costs nothing.
2. **Deterministic Stop-hook checkpoint** (optional, opt-in): if the user has installed the hook, `autosave_checkpoint.py` snapshots `state.md` every turn and prompts a micro-save every N turns. Install once with:
   ```bash
   python3 ${CLAUDE_SKILL_DIR}/scripts/install_autosave_hook.py        # enable
   python3 ${CLAUDE_SKILL_DIR}/scripts/install_autosave_hook.py --uninstall
   ```
   The hook reads this same `autosave` flag, so `/dne autosave off` silences it without uninstalling.

**On:** write `autosave: on`. Confirm: *"Autosave on — I'll checkpoint continuity behind the scenes so a context compaction never loses your place."*

**Off:** write `autosave: off`. Confirm: *"Autosave off — I'll only persist on /dne save and /dne end."*

**Why turn-count, not a context percentage:** the model cannot see its own context-usage level, so there is no reliable "save at 80% full" trigger from inside the skill. The cadence is keyed on turns instead, tuned to fire well before auto-compaction.

---

## Table UX Commands

## `/dne undo [turn-number]`

Atomically roll back the campaign to the previous turn snapshot (or a specific turn number). Restores every campaign file the snapshot tracked — `state.md`, `world.md`, `world-nodes.md`, `world-map.json`, `npcs*.md`, `arc.md`, `session-log.md`, `graph.json`, `tracker.json`, `lorebook.json`, `entropy.json`, `battlemap.json`, `events.jsonl`, `.economy_ledger.json`, `calendar.json`, `xp-ledger.jsonl`, `worldkit.json`, the session tail, `npc-timeline.json`, all `characters/*.md` and the whole `companions/` folder (sheets created after the snapshot are removed, and come back on `redo`), plus the display's own stats and feed — and refreshes connected display browsers. `redo` re-applies what the last undo rolled back. **Every undo and redo starts a new timeline:** player actions and dice requests queued before it are dropped, and a message or roll that still arrives for them is refused (the phone tells the player to read the latest text and send again), so nothing from the undone turns can change the story. Ask again for any roll you still need. **Companion agents:** the script names the restored sheets; stop every running companion agent and start it again from its sheet (SKILL-companions.md → After an undo). A snapshot taken before companions were tracked leaves the sheets as they are. The global roster (`<root>/characters/`) is not part of a campaign snapshot: re-mirror any restored character after an undo.

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/turn_snapshot.py -c <campaign> list
python3 ${CLAUDE_SKILL_DIR}/scripts/turn_snapshot.py -c <campaign> undo [--to N]
python3 ${CLAUDE_SKILL_DIR}/scripts/turn_snapshot.py -c <campaign> redo
```

## `/dne shop <buy|sell|gold>`

Execute atomic currency and inventory transactions via `economy.py` (refuses negative balances, logs receipts to `.economy_ledger.json`):

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/economy.py -c <campaign> buy --char "<Name>" --item "<Item>" --cost 50
python3 ${CLAUDE_SKILL_DIR}/scripts/economy.py -c <campaign> sell --char "<Name>" --item "<Item>" --value 5
python3 ${CLAUDE_SKILL_DIR}/scripts/economy.py -c <campaign> gold --char "<Name>" --delta -10 --reason "Inn room"
```
Amounts are gp-equivalent: in a World Kit campaign use plain numbers or the kit currency (`50 sc`, `12.5`); classic campaigns may also write `50gp 5sp`. Loot that costs nothing is `buy --cost 0`. `--char` accepts the character's name or file name.

## `/dne lorebook <scan|add|import|export>`

Manage campaign lorebooks and Character Card v3 (`chara_card_v3`) / Lorebook v3 (`lorebook_v3`) files:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/lorebook.py -c <campaign> add --name "Lantern Bridge" --keys "bridge,lantern" --content "..." [--dm-only]
python3 ${CLAUDE_SKILL_DIR}/scripts/lorebook.py -c <campaign> import-lorebook <file.json>
python3 ${CLAUDE_SKILL_DIR}/scripts/lorebook.py -c <campaign> export-lorebook <out.json>
python3 ${CLAUDE_SKILL_DIR}/scripts/lorebook.py -c <campaign> import-card <card.json>
python3 ${CLAUDE_SKILL_DIR}/scripts/lorebook.py -c <campaign> export-card --char "<Name>" <out.json>
```

## `/dne chain <new-campaign-name>`

Chain a completed campaign into a sequel chapter in the same world — carries forward `world.md`, `npcs*.md`, `graph.json`, `lorebook.json`, faction standings, and party characters (healed via Long Rest by default):

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/campaign_chain.py --from <old-campaign> --to <new-campaign> [--title "Book II"]
```

---

## Tactics, World & Tension Commands

## `/dne encounter <biome> [difficulty]`
Generate a balanced 5e XP-budget encounter for the current biome and party:
```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/encounter_gen.py -c <campaign> --biome <biome> [--party-level <L>] [--party-size <N>] --difficulty <easy|medium|hard|deadly>
```
With `-c`, a World Kit campaign draws only its own monsters (biomes are the kit's), and party size/level default to the state.md header. Without a World Kit, biomes are the SRD set (forest, crypt, cave, …).

## `/dne map <init|place|move|terrain|clear>`
Open and control the on-demand 2D tactical battlemap on the Display Companion (5ft squares, difficult terrain, walls, cover, diagonal costs):
```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/battlemap.py -c <campaign> init --width 12 --height 10 --title "<Encounter>"
python3 ${CLAUDE_SKILL_DIR}/scripts/battlemap.py -c <campaign> place --name "<Name>" --x 2 --y 5 --kind pc|enemy --hp 20/20
python3 ${CLAUDE_SKILL_DIR}/scripts/battlemap.py -c <campaign> move --name "<Name>" --x 5 --y 5 --speed 30
python3 ${CLAUDE_SKILL_DIR}/scripts/battlemap.py -c <campaign> clear
```

## `/dne travel <destination> [foot|horse|wagon|ship]`
Compute deterministic distance, travel days, biome crossings, and encounter checks via `world_map.py`:
```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/world_map.py -c <campaign> route --to "<Place>" --mode foot
python3 ${CLAUDE_SKILL_DIR}/scripts/world_map.py -c <campaign> travel --to "<Place>" --mode foot
```

## `/dne entropy <+N|-N|status|reset>`
Adjust or inspect the dungeon/world Tension & Noise Meter (`0–100`) and push updates to the Display Companion:
```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/entropy.py -c <campaign> add --delta 15 --reason "Loud combat"
python3 ${CLAUDE_SKILL_DIR}/scripts/entropy.py -c <campaign> status
```
