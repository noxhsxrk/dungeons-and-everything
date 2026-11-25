A **string** is a hold one character has on another: a secret they know, a promise owed, a moment the other cannot
forget. Strings run one way (Mira can hold three on Theo while he holds none on her) and live on the pair's bond.

- **Gaining one:** when someone shows a character their weak spot, owes them, wants them, or gives something away
  in a scene: `{"action": "string", "by": "Mira", "on": "Theo", "gain": 1, "why": "she saw him cry"}`.
  Say why every time; it is the story of the pair. A good roll to reach someone can earn one.
- **Spending one** (one string each, refused if there is none):
  - **plus**: +1 on the holder's next roll that has to do with the other *(default)*. Spend it right before.
  - **minus**: −1 on the other's next roll that goes against the holder *(default)*.
  - **tempt**: offer them something they want, in the fiction, to do what the holder wants:
    `"spend": "tempt", "offer": "skip the hearing and run away with me"`. If they go along,
    `{"action": "string", "on": "Theo", "accept": true}` gives them 1 XP *(default)*: run the `xp_command` it returns.
    If they refuse, send `"accept": false`; the string is gone either way.
  - **emotion**: give them an emotion (needs the emotions module): `"spend": "emotion", "emotion": "insecure"`.
- The +1 and −1 last for one roll: the script takes them off after that character's next check.
- Players can hold strings on NPCs and NPCs on players; play NPC strings as the GM's moves, never all at once.
- **The bond and the strings are different numbers.** The bond (0–5) is how close two people are and lets one help
  the other; strings are leverage. A pair can be close with no strings, or hold strings with no bond at all.
- A romance or rivalry arc is the strings changing hands until someone stops spending them and says the truth.
