# Changelog

All notable changes to Dungeons & Everything are documented here. The project follows [semantic versioning](https://semver.org/) — `MAJOR.MINOR.PATCH` where MAJOR breaks an existing campaign or workflow, MINOR adds significant new capability, and PATCH fixes bugs without changing behavior.

The installed version is in the `VERSION` file at the repo root. Run `/dne update --check` to compare your local copy against `origin/main`.

---

## [Unreleased]

### Added
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
