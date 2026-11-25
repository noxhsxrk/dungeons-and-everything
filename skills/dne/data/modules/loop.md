One day plays again. The script keeps the day; you keep its meaning.

- **The first morning.** When the day the loop repeats begins, send `{"action": "loop", "start": true}`. The
  script copies the world as it stands: every scheduled event, every record (tracks, conditions, NPC places,
  clocks, markets) and the world files (calendar, tracker, map, factions). That copy is the seed.
- **Before the first loop,** schedule the day: what each NPC does and when (`schedule` events, routines,
  clocks). Each event rolls from the campaign seed and its own id, so every loop the day comes out the same.
- **Players change things.** Their changes hold for this loop only. Play them in full: the day bends.
- **Reset** (death, the bell at midnight, sleep, whatever ends the day): `{"action": "loop", "reset": true,
  "why": "..."}`. Events, records, the clock and the world files go back to the seed; the reply says the loop
  number, what was forgotten and what carries. Nothing the players did survives except:
  - **Knowledge**: facts, names, passwords, where the knife is. `{"action": "loop", "learn": "..."}`.
  - **Anchors**: up to 3 items *(default)* that wake up with them. `{"action": "loop", "anchor": "the silver
    key"}`. Character sheets are prose and the script does not rewind them: at a reset, strike from the sheets
    the gear gained this loop that is not an anchor, and put back what was lost.
  - Memories, roles and achievements, if those modules are on.
- **Breaking out.** `loop_break` is a party track 0–10 *(default)*. Mark it when they learn why the day repeats
  or undo a link in its chain (1 for a clue, 2-3 for a key truth): `{"action": "track", "owner": "party",
  "id": "loop_break", "mark": 1, "why": "..."}`. At 10 the loop is broken: reset is refused and tomorrow comes.
- **Fatigue.** Each reset marks 1 `loop_fatigue`. Every 3rd mark *(default)* the script picks one piece of
  knowledge and crosses it out: tell the players what slipped away. At 9 they are worn thin: play it.
- **Run the day as a clock.** The world does not wait: if they spend the morning on one lead, the noon event
  still happens. Let them see the same NPC say the same line; change only what their actions touched.
- **Never invent changes the seed did not have.** If you want the day to change, it is because of something a
  player did in this loop.
