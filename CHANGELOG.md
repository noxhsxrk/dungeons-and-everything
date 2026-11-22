# Changelog

All notable changes to Dungeons & Everything are documented here. The project follows [semantic versioning](https://semver.org/) — `MAJOR.MINOR.PATCH` where MAJOR breaks an existing campaign or workflow, MINOR adds significant new capability, and PATCH fixes bugs without changing behavior.

The installed version is in the `VERSION` file at the repo root. Run `/dne update --check` to compare your local copy against `origin/main`.

---

## [Unreleased]

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
