The world has a system, and the system talks. The script writes its messages from the state; you never type a
number into one.

- **System messages come by themselves.** After every action the script compares every track, pool, progress
  track and condition with what it saw last, and sends the table one line per change:
  `[System] Mira — harm: 1/4 → 2/4`, `[System] Mira — Wounded: gained (-1)`. Read them out as they are, in the
  system's voice if you like (dry, cheerful, a little cruel). Do not add numbers they do not have.
  - The first time a module is switched on the script only takes note; announcements start with the next change.
- **The status window.** When a player asks to see it: `{"action": "status", "show": "Mira"}`. It lists Mira's
  numbers and achievements from the store, nothing else.
- **Achievements.** The first critical success and the first critical failure of each character earn one by
  themselves (the script picks the title). Award others when a player does something the system would notice
  (a first kill, a ridiculous plan that worked, a door kicked that should not have been):
  `{"action": "status", "achievement": "Bridge Burner", "to": "Mira", "why": "burned the only way back"}`. Each
  one is awarded once; a repeat says nothing.
- **Loot boxes.** As a reward, not as a shop: `{"action": "status", "loot": "silver", "to": "Mira"}`. The script
  rolls d100 for the tier and then the item. Box odds *(default)*: bronze 80/18/2, silver 50/40/10, gold 15/55/30
  (common/rare/epic). An item's effect in brackets is a suggestion; write the item onto the sheet.
  - Give a bronze box for a scene well played, silver for a goal, gold for a floor, boss or arc.
- **What the system does not say:** secret roles, a hidden truth, an enemy's plan. It shows numbers, not minds.
- Players will try to game the system. Let them; it is part of the genre. The system has rules, and it keeps them.
