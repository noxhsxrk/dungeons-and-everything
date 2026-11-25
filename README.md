<div align="center">
  <img src="docs/images/hero.jpg" alt="Dungeons & Everything — a glowing d20 whose faces show neon Bangkok, a Thai temple, a Weird West town, a 1990s small town and a starship diving into a sun" width="100%">

  <h3>Describe any world. Your AI Game Master builds it, runs it, and plays everyone in it.</h3>
  <p>Dungeons &amp; Everything is a Game Master skill for any AI coding agent, running on the <b>Unrolled Engine</b>:<br>a d20 engine with a 5e SRD core and a world that keeps moving when the party isn't looking.</p>

  <p>
    <a href="https://github.com/noxhsxrk/dungeons-and-everything/actions/workflows/tests.yml"><img src="https://github.com/noxhsxrk/dungeons-and-everything/actions/workflows/tests.yml/badge.svg" alt="tests"></a>
    <a href="https://github.com/noxhsxrk/dungeons-and-everything/releases/latest"><img src="https://img.shields.io/github/v/release/noxhsxrk/dungeons-and-everything" alt="latest release"></a>
    <a href="LICENSE"><img src="https://img.shields.io/github/license/noxhsxrk/dungeons-and-everything" alt="license: AGPL-3.0"></a>
    <img src="https://img.shields.io/badge/python-3.10%2B-blue" alt="Python 3.10+">
  </p>

  <p>
    <a href="#quick-start">Quick start</a> ·
    <a href="#what-the-engine-does">What the engine does</a> ·
    <a href="#play-any-genre-with-braid-alpha">Any genre</a> ·
    <a href="#play-together">Play together</a> ·
    <a href="#install">Install</a> ·
    <a href="README.th.md">ภาษาไทย</a>
  </p>
</div>

---

## Quick start

```bash
git clone https://github.com/noxhsxrk/dungeons-and-everything.git ~/dungeons-and-everything
cd ~/dungeons-and-everything && python3 install.py     # sets up every AI agent it finds
```

Then, in your agent (Claude Code, Codex, Gemini CLI, Antigravity, opencode, Copilot, Cursor …):

```
/dne new hollow-9          # describe your world
/dne character new         # build a character from that world's origins and classes
/dne load hollow-9         # play: type what your character does
```

Python 3.10+. For the TV and phone display: `pip3 install flask flask-cors numpy cryptography`.

<img src="docs/images/worlds.jpg" alt="Five worlds on one engine: neon Bangkok 2077, a mythic Thai kingdom, a Weird West showdown, kids on bikes in a 1994 small town, a ship diving into a star" width="100%">

<sub>Five worlds built and played while testing: <b>Neon Krung</b> (Bangkok 2077) · <b>Himmapan</b> (mythic Ayutthaya) · <b>Iron Hymn</b> (Weird West, 1881) · <b>Cedar Falls</b> (1994, no powers at all) · <b>Perihelion</b> (hard sci-fi on the 2024 rules).</sub>

## What the engine does

An AI that improvises everything forgets the rules, the prices and who owed whom by the third session. The Unrolled Engine keeps all of that in scripts the Game Master has to go through, so the AI tells the story and the engine keeps it honest. The name is a nod to the big game engines: a world that hasn't been rolled yet, unrolled one day at a time.

### 1. Rules that are computed, not guessed

- **Dice, attacks, damage, conditions, hit points, rests, XP and money** all come from scripts, with the math shown. A player can roll their own dice and type the result.
- **Every turn can be rewound** (`/dne undo`), files and all, and a late message from a rewound turn can't change the present.
- **2014 or 2024 rules** (SRD 5.1 or 5.2) per campaign.
- **Fights that make sense.** Encounters are balanced from the world's own bestiary; enemies see only what is in their line of sight, take cover, retreat when broken, and spend only the actions and resources they have. Areas (spheres, cubes, lines, cones) are sheltered by walls. A fight can end when its point is settled (the witness is safe), not when the last hit point is gone.

### 2. A rulebook for any world (the World Kit)

Describe the world in a line or a full setting bible:

> *AD 2289. EDEN, the AI that ran the planet, decided humanity could no longer be trusted with its own survival. The survivors live underground. The players belong to Hollow-9, a colony of 600. One night, the oxygen plant fails.*

<img src="docs/images/eden.jpg" alt="Cross-section of a ruined city patrolled by robots, above an underground colony with a failing oxygen generator" width="100%">

The engine turns that into the world's own rulebook, `worldkit.json`, and checks it before play:

| The world gets | Built as | In the EDEN example |
|---|---|---|
| Origins and classes | 5e traits; a world profession on a 5e **chassis** class | Tunnel-Born; Soldier *(fighter)*, Mechanic *(wizard)*, Medic *(cleric)* |
| Subclasses and backgrounds | the world's own specialisations | Medic → Trauma Surgeon; Ex-EDEN Technician |
| Powers and gear | 5e spells and items, re-skinned and priced | *Static Burst*; Rail Pistol (1d10) |
| Threats | full stat blocks, CR-correct XP | Watcher CR ¼, Reaper CR 5, Titan CR 15 |
| Language | renamed terms and skills | spell → protocol, long rest → lockdown, Arcana → Systems |

The character builder, rules lookup, encounter generator and display all read from your world first. Say **"classic fantasy"** to play on the bundled 5e SRD. Example kit: [`worldkit.example.json`](skills/dne/templates/worldkit.example.json).

### 3. Table rules from other great games, switch by switch

<img src="docs/images/rules.jpg" alt="A game master's table: a d20 beside five glowing tokens from red to gold, a chase track, bond and flaw cards, a med kit, hero coins and a notebook of monster numbers" width="100%">

Success at a cost and five degrees of success, playbook moves and bonds (PbtA), flaws, reaction rolls and tech levels (GURPS), Hero Points and Victory Points for chases and heists (PF2e), faction turns, monster morale and place tags (WWN). Each one is rebuilt on the d20 core and switched per campaign. Reference: [`SKILL-table-rules.md`](skills/dne/SKILL-table-rules.md).

### 4. A world that lives on its own (opt-in)

Answer *yes* to "should the world live on its own?" at `/dne new` (or enable it on an existing campaign; it is backed up first). Then:

- **One clock for everything.** In-world time passes only through the engine. What was set in motion arrives when it is due, a rest or a journey stops for the players to decide when something comes up, and a month skipped at once ends in exactly the same world as thirty single days.
- **Turns that survive.** Input is stored once, a roll is made once, a message is shown once. A crash or a compacted chat picks up where it stopped. When a turn finishes, the engine records what the narration stands on and keeps a block in `state.md` that any agent can read.
- **Roads, caravans and markets.** Who holds a bridge, what it costs to cross, whether the flour arrives. Prices state their reason; the last sack goes to one buyer.
- **Nobody knows what they weren't told.** News travels by rider, rumour or radio and can be intercepted. NPCs keep appointments and turn back at a closed road; factions plan from what they have actually heard.
- **Each world declares its own work.** A forge that needs coal, a ferry that can't land in a flood, a heist crew: tasks wait for what they lack, reserve their materials, and are cancelled when the world changes under them.
- **Communities that keep themselves alive.** Machines wear and fail; whoever is there with the skill takes over; the council rules; a shortage brings a rota, a neighbour offers a pact, and what the trouble made stays. Every day writes who did what, why they could, and what it left.
- **New worlds ready on turn one.** `/dne new` can collect the whole world into one seed that the engine checks (every problem comes back with where to fix it) and builds in one go.

It is experimental. The contract every engine module keeps is in [`world_db.py`](skills/dne/scripts/world_db.py); a playtest script is in [`docs/world-engine-playtest.md`](docs/world-engine-playtest.md).

### 5. A Game Master that is held to account

- **NPCs are real records** the moment they appear: stats, aliases, voice, history. They grow while the party is away.
- **A note with every player action** tells the GM what is due (a save, an XP award, a clock out of step) and which rules apply right now.
- **A style guard** catches repeated phrases, feelings narrated for the players and talking past the moment to stop; a **spark** every few turns offers an idea the GM may drop.
- **Your table's limits.** Content `standard`, `18` or `20`; romance `off`, `fade` or `open` (adults only); lines and veils; anyone can type `x` to skip a moment.

## Play any genre with Braid (alpha)

Not every story wants hit points and spell slots. From 2.0 a campaign can run on **Braid**, our own light rules for any genre, instead of 5e:

- **One roll.** 2d6 plus one of five approaches (Force, Finesse, Wits, Heart, Grit). 10+ you do it, 7–9 you do it at a cost named before the dice, 6 or less it goes wrong. Harm and stress instead of hit points; an enemy is a threat from 1 to 5. Or play **story mode**: no numbers on the sheet, the oracle answers every risk.
- **Pick your genres.** Run `/dne new`, describe the world and pick one to five of 18 genres, the main one first: mystery, heist, war, competition, cosmic horror, slasher, analog horror, romance, cozy, comedy, fantasy, hard sci-fi, space opera, wuxia, LitRPG, historical, time loop, traitor among us. Each genre switches on the small rules it needs (a mind that frays in horror, heat after a loud job, seasons in a cozy village, a day that resets in a time loop, sealed secret roles in a traitor game), and the table can add or drop any of them. When mixed genres disagree, the engine says where, and the table picks.
- **A story that holds together.** The story generator rolls the skeleton of the story so it does not repeat the last one, and checks that a mystery stays solvable even when the players miss a third of the clues.
- **Your 5e campaigns are untouched.** Say "D&D" or "5e" at `/dne new` to play on the 5e rules as before.

It is an alpha: the numbers are our starting values and will change with play, and wuxia, LitRPG, analog horror and competition are marked *early*. The rules are in [`SKILL-core.md`](skills/dne/SKILL-core.md), the genres in [`data/genres/`](skills/dne/data/genres/), and what changed in the [changelog](CHANGELOG.md).

## Play together

<img src="docs/images/table.jpg" alt="Friends on a couch holding phones while a TV shows the story with a chat-style input bar at the bottom" width="100%">

One computer runs the Game Master; everyone else needs a phone.

```bash
bash skills/dne/display/start-display.sh --lan      # same room: phones on your Wi-Fi
bash skills/dne/display/start-display.sh --ngrok    # friends anywhere, over HTTPS
```

The story types itself out on the TV with dice, a party sidebar, handouts, progress clocks and optional narration in a voice per NPC. Each player opens `…/?char=<their character>` to see their sheet, roll and send actions; secret checks go to that phone only. With **autorun**, the Game Master picks up each action and plays the next turn on its own. More: [`display/README.md`](skills/dne/display/README.md).

## Install

Works with **any AI agent that can read files and run shell commands**. `python3 install.py` sets up every agent it finds; `--list` shows what is supported, `python3 install.py codex gemini` picks agents, `--uninstall` removes it. The skill is linked, not copied, so `git pull` updates every agent at once.

<details>
<summary>What <code>install.py</code> does per agent</summary>

| Agent | What it does |
|---|---|
| Claude Code, Codex, Gemini CLI, Antigravity, opencode, Copilot CLI, Crush, Droid | links `skills/dne` into the agent's skills folder: type **`/dne`** |
| Cursor, Kiro, Cline, Continue, Kilo Code | writes a small rules file that points the agent at the skill |
| Amp, Qwen Code, Goose, Kimi | adds one marked block to the agent's rules file (removed cleanly by `--uninstall`) |
| Aider | run `aider --read ~/dungeons-and-everything/skills/dne/SKILL.md` |
| Anything else | tell your agent: *"Read `<repo>/skills/dne/SKILL.md` and follow it"* |

**Claude Code plugin** (alternative): `/plugin marketplace add noxhsxrk/dungeons-and-everything`, then `/plugin install dne@dungeons-and-everything`, and invoke it as **`/dne:dne`**.

Only conveniences differ between agents: without a question tool you get numbered options in chat; without background tasks there is no phone **autorun** loop; without subagents the Game Master plays companions itself.
</details>

**Updating:** `git pull` in the repo, or `/dne update` in a game. Campaigns are never touched; an older world is offered an upgrade the next time you load it.
**Your games** are plain markdown and JSON in `~/.dne/`; move them with `/dne path <dir>` or `DNE_CAMPAIGN_ROOT`.
**Importing:** `/dne import <name> module.pdf` runs a published adventure (PDF, DOCX, markdown or text; PDFs need `pip3 install pymupdf`).

<details>
<summary>All commands</summary>

| Campaign | |
|---|---|
| `/dne new <name>` | Describe a world and build a new campaign |
| `/dne load <name>` · `/dne list` | Continue a campaign · list your campaigns |
| `/dne save` · `/dne end` · `/dne abandon` | Save progress · end the session with a recap · quit without saving |
| `/dne import <name> <file>` | Turn a written adventure into a campaign |
| `/dne world` · `/dne world kit` | World lore · the World Kit |
| `/dne recap` · `/dne quests` | Last session in a few sentences · open quests and threads |
| `/dne arc status \| advance \| revise \| new` | Inspect and steer the story arc |
| `/dne undo` | Rewind the last turn |

| Characters & party | |
|---|---|
| `/dne character new` · `/dne character sheet [name]` | Build a character · show a sheet |
| `/dne character import <name>` | Bring a character from another campaign, translated into the new world |
| `/dne level up [name]` | Level up, with every choice the level grants |
| `/dne rest short` · `/dne rest long` | Rests, with exact hit dice and slot recovery |
| `/dne npc <name>` · `/dne npc attitude <name> <level>` | Talk to or create an NPC · shift their attitude |
| `/dne companion add \| leave \| mode \| status` | NPCs who travel with the party and think for themselves |

| Table | |
|---|---|
| `/dne display start \| stop \| status` | The TV display and phone controllers |
| `/dne autorun on \| off` | Players act from their phones; the Game Master answers automatically |
| `/dne tutor on \| off` | Gentle rules hints for new players |
| `/dne path [<dir> \| reset]` · `/dne update [--check]` | Move your data · update the skill |
</details>

## Contributing

```bash
python3 -m venv .venv && .venv/bin/pip install pytest flask flask-cors pyyaml
.venv/bin/python -m pytest tests/ -q
```

The Game Master is [`SKILL.md`](skills/dne/SKILL.md) (core rules), [`SKILL-commands.md`](skills/dne/SKILL-commands.md) (every `/dne` procedure) and [`SKILL-scripts.md`](skills/dne/SKILL-scripts.md) (script reference); the engine is in [`skills/dne/scripts/`](skills/dne/scripts/), the display in [`skills/dne/display/`](skills/dne/display/). Read [CONTRIBUTING.md](CONTRIBUTING.md) before a pull request, and [CHANGELOG.md](CHANGELOG.md) for what changed.

## Support

- **Questions, bugs, ideas:** [open an issue](https://github.com/noxhsxrk/dungeons-and-everything/issues).
- **Security:** see [SECURITY.md](SECURITY.md); please don't report vulnerabilities in a public issue.
- **Releases:** [what's new](https://github.com/noxhsxrk/dungeons-and-everything/releases).

## License

[AGPL-3.0-or-later](LICENSE) · see [NOTICE](NOTICE). Not affiliated with or endorsed by Wizards of the Coast. 5e rules content comes from the System Reference Document under CC BY 4.0.
