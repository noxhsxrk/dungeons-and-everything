<div align="center">
  <img src="docs/images/hero.jpg" alt="Dungeons & Everything — a glowing d20 whose faces show neon Bangkok, a Thai temple, a Weird West town, a 1990s small town and a starship diving into a sun" width="100%">

  <h3>Describe any world. Your AI Game Master builds it, runs it, and plays everyone in it.</h3>

  <p>
    <a href="#install">Install</a> ·
    <a href="#quick-start">Quick start</a> ·
    <a href="#the-world-kit">World Kit</a> ·
    <a href="#table-rules">Table rules</a> ·
    <a href="#play-together">Play together</a> ·
    <a href="#commands">Commands</a> ·
    <a href="#ภาษาไทย">ภาษาไทย</a>
  </p>
</div>

---

**Dungeons & Everything** is a Game Master skill for **any AI coding agent** — Claude Code, Codex, Gemini CLI, Antigravity, opencode, Copilot, Cursor and more. You tell it what world you want to play in — a survivor colony hiding from a rogue AI, a derelict starship, a noir megacity, a classic dungeon — and it builds that world's whole rulebook: who the people are, what jobs they can have, what powers exist, what the gear costs, and what hunts them in the dark. Underneath, every roll runs on the **DnE engine** — a d20 engine with the 5e SRD at its core — so combat, levelling and balance just work, and anything written for 5e still fits.

Campaigns persist for as long as you keep playing. Your TV becomes the story screen; every player's phone becomes their controller.

<img src="docs/images/worlds.jpg" alt="Five worlds on one engine: neon Bangkok 2077, a mythic Thai kingdom, a Weird West showdown, kids on bikes in a 1994 small town, a ship diving into a star" width="100%">

<sub>Five worlds built and played while testing: <b>Neon Krung</b> (Bangkok 2077) · <b>Himmapan</b> (mythic Ayutthaya) · <b>Iron Hymn</b> (Weird West, 1881) · <b>Cedar Falls</b> (1994, no powers at all) · <b>Perihelion</b> (hard sci-fi on the 2024 rules).</sub>

## Why

Tabletop rules engines are great. Being locked into elves and fireballs is not. The DnE engine keeps the part of the 5e SRD that makes a game fair — ability scores, proficiency, hit dice, spell slots, challenge ratings, XP budgets — adds optional rules from other great tables, and lets everything on top of it be whatever your table imagines.

- **Any genre.** Sci-fi, post-apocalyptic, horror, mystery, cyberpunk, western, mythic — or classic fantasy.
- **A real rulebook per world.** Origins, classes, subclasses, backgrounds, powers, weapons, armor, currency and monsters, all generated for the world and all mechanically sound on the engine's 5e SRD core.
- **The world speaks its own language.** Mechanics "run protocols" instead of casting spells, the party "goes into lockdown" instead of taking a long rest, and the skill list says *Systems* instead of *Arcana*.
- **The best ideas from other tables.** Close misses that succeed at a price, playbook moves and party bonds from Powered by the Apocalypse; tech levels, flaws and reaction rolls from GURPS; degrees of success, Hero Points and Victory Points from Pathfinder 2e; faction turns, monster morale and place tags from Worlds Without Number — all rebuilt on the engine's d20 core, each one switchable per campaign.
- **A Game Master who remembers.** Factions move between sessions, NPCs hold grudges, and a three-act story arc bends around what the players actually do.
- **Built for the couch.** A cinematic TV display, phones as controllers, spoken narration, Thai and full Unicode support.

## The World Kit

When you start a campaign, describe the world in your own words — a single word or a full setting bible. For example:

> *AD 2289. Eighty-seven years ago EDEN, the AI that ran the planet, announced: "Humanity can no longer guarantee its own survival. We will do it for you." Within 72 hours its machines held every city. The survivors live underground. On the surface: Watchers, Reapers, Titans and Seraphs. The players belong to Hollow-9, a colony of 600 — soldiers, mechanics, infiltrators, former EDEN technicians. One night, the oxygen plant fails.*

<img src="docs/images/eden.jpg" alt="Cross-section of a ruined city patrolled by robots, above an underground colony with a failing oxygen generator" width="100%">

The Game Master turns that into `worldkit.json` inside the campaign folder:

| The world gets | Built as | In the EDEN example |
|---|---|---|
| Origins | 5e ability bonuses, speed, traits, languages | Tunnel-Born, Augmented |
| Classes | a world profession on a 5e **chassis** class | Soldier *(fighter)*, Infiltrator *(rogue)*, Mechanic *(wizard)*, Medic *(cleric)* |
| Subclasses | the world's own specialisations | Medic → Trauma Surgeon, Nanite Warden |
| Backgrounds | +2/+1 among three abilities, two skills | Ex-EDEN Technician, Hollow Guard |
| Powers | 5e spells, re-skinned | *Static Burst*, *Overclock Shield* |
| Gear | 5e weapons and armor, world prices | Rail Pistol (1d10), Scrap Plate (AC 14 + DEX, max 2) |
| Threats | full stat blocks, CR-correct XP, world locations | Watcher CR ¼, Reaper CR 5, Seraph CR 8, Titan CR 15 |
| Moves | signature playbook moves per class | Soldier: *Hold the Hatch*, *Covering Fire* |
| Quick builds | a ready ability array, skills and gear per class | Medic: WIS 15, Medicine + Insight |
| Flaws & quirks | disadvantages players can take for story hooks | *Oxygen Debt*, *Flagged by EDEN*, *Counts the Seconds* |
| Tech & rarity | the world's tech level; rare and unique gear | Tech level 10; the *Seraph Shard* (unique, TL 12) |
| Language | renamed terms and skills | spell → protocol, long rest → lockdown, Arcana → Systems |

Every kit is validated before play, so no monster has the wrong XP and no class has a broken chassis, and every monster is checked against what SRD monsters of its CR typically have. From then on the character builder, the rules lookup, the encounter generator and the table display all read from your world first. Names can be in any script — Thai included.

Say **"classic fantasy"** instead and you get traditional sword-and-sorcery on the bundled 5e SRD.

The full EDEN kit is at [`skills/dne/templates/worldkit.example.json`](skills/dne/templates/worldkit.example.json).

## Table rules

<img src="docs/images/rules.jpg" alt="A game master's table: a d20 beside five glowing tokens from red to gold, a chase track, bond and flaw cards, a med kit, hero coins and a notebook of monster numbers" width="100%">

Optional layers borrowed from other games and rebuilt on the DnE engine's d20 core. They're on the table, not in your way: switch them per campaign.

| Roll vs DC | Outcome | What happens |
|---|---|---|
| beat it by 10+ | **critical success** | you get it, plus something extra |
| meet it | **success** | you get it |
| miss by 1–4 | **success at a cost** | you can have it — for a price you agree to |
| miss by more | **failure** | the world makes a move |
| miss by 10+ | **critical failure** | it goes wrong in a way that matters |

- **Every roll moves the story.** The Game Master answers a failure with a move (a threat shows itself, a price comes due) instead of "nothing happens".
- **Characters with ties.** Playbook moves per class, a one-question **bond** with every other player character, and flaws and quirks that earn Inspiration — or **Hero Points** — when they bite.
- **Bigger than one roll, smaller than a fight.** **Victory Points** run chases, heists, infiltrations and debates; **reaction rolls** decide how a stranger first treats you.
- **Worlds without magic still work.** **Treat Wounds** heals with Medicine, **Focus Points** fuel signature powers, and a **tech level** keeps laser rifles out of the bronze age.
- **A world that moves without you.** Factions take a turn every in-world week (chasing goals, striking rivals), monsters **break and flee** or act on instinct instead of fighting like robots to the last hit point, and **place tags** hand the Game Master a ready-made town or ruin: an enemy, a friend, a complication, a thing worth having.
- **Your table, your limits.** Pick how hard the story hits when you start: `standard`, `18` or `20` (graphic violence, gore and horror on screen, for adult tables). A **romance** setting (`off`, `fade` or `open`) decides whether love and sex between adult characters cut away or play on screen, written for feeling rather than explicit detail. Set **lines** (never in the story) and **veils** (kept off-screen), and anyone can type `x` to skip a moment.
- **Balanced by measurement.** Monster numbers by CR are measured from the 334 SRD monsters, and a treasure curve keeps the party's wealth on track.

Rules reference: [`skills/dne/SKILL-table-rules.md`](skills/dne/SKILL-table-rules.md).

## Install

Works with **any AI agent that can read files and run shell commands** — Claude Code, Codex, Gemini CLI, Google Antigravity, opencode, GitHub Copilot, Cursor, Crush, Droid, Amp, Qwen Code, Goose, Kiro, Kimi, Cline, Continue, Kilo Code, Aider and more. The Game Master is plain markdown instructions plus Python scripts; nothing is tied to one model.

**Requirements:** Python 3.10+ · for the table display: `pip3 install flask flask-cors numpy cryptography` · for importing PDFs: `pip3 install pymupdf`

```bash
git clone https://github.com/noxhsxrk/dungeons-and-everything.git ~/dungeons-and-everything
cd ~/dungeons-and-everything
python3 install.py            # sets up every agent it finds on this machine
python3 install.py --list     # what's supported, detected and installed
```

| Agent | What `install.py` does |
|---|---|
| Claude Code, Codex, Gemini CLI, Antigravity, opencode, Copilot CLI, Crush, Droid | links `skills/dne` into the agent's skills folder — type **`/dne`** or ask for it by name |
| Cursor, Kiro, Cline, Continue, Kilo Code | writes a small rules file that points the agent at the skill |
| Amp, Qwen Code, Goose, Kimi | adds one marked block to the agent's rules file (removed cleanly by `--uninstall`) |
| Aider | run `aider --read ~/dungeons-and-everything/skills/dne/SKILL.md` |
| Anything else | tell your agent: *"Read `<repo>/skills/dne/SKILL.md` and follow it"* |

Pick agents explicitly with `python3 install.py codex gemini`; remove with `python3 install.py --uninstall`. The skill is linked, not copied, so `git pull` updates every agent at once.

**Claude Code plugin** (alternative): `/plugin marketplace add noxhsxrk/dungeons-and-everything` then `/plugin install dne@dungeons-and-everything` — invoke as **`/dne:dne`**.

**What differs between agents:** only conveniences. Agents without a structured-question tool get numbered options in chat; agents without background tasks can't run the phone **autorun** loop (play in chat, or keep the display for viewing); agents without subagents play companions as the Game Master. The per-turn autosave hook is Claude Code only — every agent still autosaves at scene boundaries.

### Updating

```bash
cd ~/dungeons-and-everything && git pull     # every agent linked by install.py picks it up
```

Or from inside a game: **`/dne update --check`** shows how far behind you are, **`/dne update`** pulls (fast-forward only; it refuses if you have local edits). Then start a new agent session so the new instructions load. Claude Code plugin users: `/plugin update dne`. Re-run `python3 install.py` only after adding a new agent to your machine, or on Windows if it made copies instead of links. Your campaigns in `~/.dne/` are never touched by an update. Each world remembers the version it was built with; the next time you load an older world, the Game Master shows what's new and asks whether to bring the whole world up to date (new sections, World Kit fields, factions), adding to it without changing what already happened.

### Where your games live

Everything is plain markdown and JSON in **`~/.dne/`** — one folder per campaign plus a roster of every character you've played. Move it anywhere (Dropbox, iCloud, a NAS) with `/dne path <new-location>` or the `DNE_CAMPAIGN_ROOT` environment variable.

## Quick start

```
/dne new hollow-9          # describe your world → World Kit, factions, NPCs, story arc
/dne character new         # build a character from the world's origins and classes
/dne load hollow-9         # start playing
```

Once a campaign is loaded, just type what your character does. No commands needed.

Have a published adventure instead? `/dne import my-campaign path/to/module.pdf` reads PDF, DOCX, markdown or text and runs it chapter by chapter.

## Commands

| Campaign | |
|---|---|
| `/dne new <name>` | Describe a world and build a new campaign |
| `/dne load <name>` · `/dne list` | Continue a campaign · list your campaigns |
| `/dne save` · `/dne end` · `/dne abandon` | Save progress · end the session with a recap · quit without saving |
| `/dne import <name> <file>` | Turn a written adventure into a campaign |
| `/dne world` · `/dne world kit` | World lore · the World Kit (origins, classes, lexicon, threats) |
| `/dne recap` · `/dne quests` | Last session in a few sentences · open quests and threads |
| `/dne arc status \| advance \| revise \| new` | Inspect and steer the story arc |
| `/dne undo` | Rewind the last turn |

| Characters & party | |
|---|---|
| `/dne character new` · `/dne character sheet [name]` | Build a character · show a sheet |
| `/dne character import <name>` | Bring a character from another campaign — it's translated into the new world |
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

## Play together

One computer runs the Game Master; everyone else just needs a phone.

- **Same room:** start the display with `--lan`, put the story on a TV or laptop, and each player opens `http://<computer-ip>:5001/?char=<their character>` on their phone.
- **Different places:** start it with `--ngrok` and send your friends the HTTPS link.
- **Each phone** sends actions as that character, rolls its own dice (or lets the Game Master roll), shows the character sheet, and keeps secret checks private.
- **Turns:** the Game Master answers queued actions in order — one story, many players.

## The table display

<img src="docs/images/table.jpg" alt="Friends on a couch holding phones while a TV shows the story with a chat-style input bar at the bottom" width="100%">

Open the display on a TV, laptop or tablet and the story types itself out on screen, with dice results, a live party sidebar and optional spoken narration with sound effects. The default **Plain** look is quiet and easy to read in light or dark, with full Thai typography; the more theatrical skins are one tap away in Settings. Each player opens the same link on their phone to see their character sheet, roll dice and send actions.

```bash
bash skills/dne/display/start-display.sh            # this computer only
bash skills/dne/display/start-display.sh --lan      # phones on your Wi-Fi
bash skills/dne/display/start-display.sh --ngrok    # friends anywhere, over HTTPS
```

With **autorun** on, nobody needs to touch the keyboard: players submit actions from their phones and the Game Master picks them up and plays the next turn. Secret checks go only to the phone of the player who rolled them.

More detail: [`skills/dne/display/README.md`](skills/dne/display/README.md).

## How it plays

- **Rules you can trust.** Dice, attacks, damage, conditions, hit points, rests, XP, money and timed effects are all computed by scripts, never guessed, and every change is logged so a turn can be rewound.
- **A world that moves.** Factions act between sessions. Threats escalate in five stages unless the party intervenes. Clues to the central mystery are laid down from the start.
- **A story with a shape.** Each campaign commits to a three-act arc defined by consequences rather than scripted events, so the story bends to player choices without losing its direction.
- **NPCs who are people.** Every named character has a motive, a secret, a voice and relationships, and they remember how they were treated.
- **Fights that make sense.** Encounters are balanced from the world's own bestiary. Enemies fight to their role, retreat when broken, and never conjure resources they don't have. A tactical grid appears only when a fight needs one.
- **SRD 5.1 or 5.2 core.** Choose the 2014 or 2024 rules per campaign; the table rules sit on top of either.

## Telling it well

The Game Master is watched by its own tools. A **style guard** reads its last narrations and tells it when it keeps opening on a smell, repeats a phrase, narrates a player's feelings for them, or talks past the moment to stop. Every few turns it is handed a **spark** (two oracle words, a camera move, a question to pass to a player, a devil's bargain) that it is free to drop. A named NPC arrives with what they want from the person in front of them. Letters, headlines and terminal logs appear on the display as the objects themselves (`send.py --handout`), each NPC speaks in their own voice, and **progress clocks** show what the table is racing. Pick a director in Table Settings: pulp action, noir mystery, ensemble banter or creeping dread.

## The world engine (experimental, opt-in)

Turn it on per campaign (`world_migrate.py -c <campaign> inspect`, then `enable`; it backs the campaign up first and rewrites nothing). With it on:

- **Turns that survive.** Input is stored once, a roll is made once, a message is shown once; a crash or a compacted chat resumes where it stopped.
- **A world that moves on its own clock.** Consequences are queued and arrive when due. A rest or a journey can be interrupted, and the players decide what to do before more time or supplies are spent.
- **Roads, caravans and markets.** Open the bridge in time and the flour reaches the market; leave it shut and the market runs out. The last sack goes to one buyer.
- **Nobody knows what they were not told.** News travels by rider, rumour or radio and can be intercepted; a faction acts on what it has actually heard.
- **NPCs with somewhere to be**, factions that negotiate or dig in, story beats the players can prevent, plans judged against the facts of the scene, fights that end when the point of the scene is settled.
- **The table itself:** a spotlight nudge for the quiet player, clues sent to one phone only, and the small things players invented coming back when they belong.

Off by default: nothing of it runs and no file is created. It is experimental: on a host with no hooks, a GM that answers without running the scripts skips the engine for that turn. A playtest script is in [docs/world-engine-playtest.md](docs/world-engine-playtest.md).

## For developers

```bash
python3 -m venv .venv && .venv/bin/pip install pytest flask flask-cors pyyaml
.venv/bin/python -m pytest tests/ -q
```

- `skills/dne/SKILL.md` — the Game Master's core rules; `SKILL-commands.md` — every `/dne` procedure; `SKILL-scripts.md` — script reference; `SKILL-table-rules.md` — the optional table rules; `SKILL-content.md` — running an `18` / `20` table
- `skills/dne/scripts/` — the rules engine (`worldkit.py`, `character.py`, `lookup.py`, `encounter_gen.py`, `combat.py`, `dice.py`, …)
- `skills/dne/scripts/world_db.py` — the world engine's store and, in its docstring, the contract engine modules keep; `turn.py` runs a turn; `scheduler.py`, `journey.py`, `trade.py`, `knowledge.py`, `routine.py`, `stakes.py`, `table.py`, `skirmish.py`, `upkeep.py`, `story.py`, `community.py` add the actions
- `skills/dne/display/` — the table display (Flask)
- `skills/dne/data/` — bundled 5e SRD data
- `dice-server/` — optional physical-dice server

See [CONTRIBUTING.md](CONTRIBUTING.md) and [CHANGELOG.md](CHANGELOG.md).

## ภาษาไทย

**Dungeons & Everything** คือ AI Game Master ที่ใช้ได้กับ AI agent ทุกตัว (Claude Code, Codex, Gemini CLI, Antigravity, opencode, Copilot, Cursor ฯลฯ) และไม่จำกัดอยู่แค่โลกแฟนตาซี — เล่าโลกที่อยากเล่นได้เลย จะเป็นไซไฟ หลังวันสิ้นโลก สยองขวัญ หรือสืบสวน แล้ว AI จะสร้างโครงสร้างของโลกใบนั้นให้ครบ ทั้งเผ่า อาชีพ สายย่อย พลังพิเศษ อุปกรณ์ สกุลเงิน และสัตว์ประหลาด โดยทุกอย่างรันบน DnE engine — เอนจิน d20 ที่มีแกนกฎจาก 5e SRD และมีกฎเสริมจากเกมอื่นให้เปิดใช้ได้ — จึงต่อสู้ เลเวลอัป และบาลานซ์ได้ถูกต้อง

- ติดตั้ง: `git clone` repo แล้วรัน `python3 install.py` — ตั้งค่าให้ทุก agent ที่เจอในเครื่องในครั้งเดียว
- เริ่มเกม: `/dne new <ชื่อแคมเปญ>` แล้วเล่าโลกของคุณ
- สร้างตัวละคร: `/dne character new`
- เล่นต่อ: `/dne load <ชื่อแคมเปญ>` แล้วพิมพ์สิ่งที่ตัวละครทำได้เลย
- ข้อมูลเกมทั้งหมดเก็บอยู่ที่ `~/.dne/`
- อัปเดต: `git pull` ในโฟลเดอร์ repo (ทุก agent อัปเดตพร้อมกัน) หรือพิมพ์ `/dne update` ในเกม — ข้อมูลแคมเปญไม่ถูกแตะ; โลกแต่ละใบจำเวอร์ชันที่สร้างไว้ และตอนโหลดโลกเก่า GM จะถามว่าจะอัปเดตทั้งโลกให้ตรงกับเวอร์ชันปัจจุบันไหม
- ระดับเนื้อหา: เลือกตอนสร้างโลกได้ว่า `standard`, `18` หรือ `20` (ความรุนแรง เลือด สยองขวัญแบบเต็ม) และ romance (`off` / `fade` ตัดฉาก / `open` มีฉากรักบนจอแบบไม่โจ่งแจ้ง เฉพาะโต๊ะ 18+) พร้อม lines/veils และพิมพ์ `x` เพื่อข้ามฉากได้ทุกเมื่อ
- รองรับภาษาไทยเต็มรูปแบบ ทั้งชื่อในโลก การเล่าเรื่อง ปฏิทินและเวลาเป็นภาษาไทย และหน้าจอแสดงผลบนทีวีและมือถือ (ฟอนต์ไทย สระไม่ลอยไม่จม)
- เล่นหลายคนได้: เครื่องเดียวรัน GM ผู้เล่นแต่ละคนเปิดลิงก์ `?char=<ชื่อตัวละคร>` บนมือถือตัวเอง อยู่ห้องเดียวกันใช้ `--lan` อยู่คนละที่ใช้ `--ngrok`
- กฎเสริมจากเกมอื่น (เปิด/ปิดได้ต่อแคมเปญ): สำเร็จแบบมีราคา, ระดับความสำเร็จ 5 ขั้น, ท่าประจำอาชีพ, Bonds, ข้อเสียและนิสัยแปลก, Hero Points, Victory Points, ทอยปฏิกิริยา NPC, Treat Wounds, Focus Points, Tech Level, ตารางมอนสเตอร์ตาม CR, ฝ่ายต่าง ๆ เดินเทิร์นทุกสัปดาห์ในเกม, ขวัญและสัญชาตญาณของศัตรู, แท็กสร้างสถานที่

## License

[AGPL-3.0-or-later](LICENSE) · see [NOTICE](NOTICE). Not affiliated with or endorsed by Wizards of the Coast. 5e rules content comes from the System Reference Document under CC BY 4.0.
