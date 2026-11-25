A mind has room for only so much. Each character holds up to **5 memories** *(default)*; anything not held is
gone, and the character cannot act on it.

- **A memory** is one sentence the player writes, about a person, a place, a promise or a wound: "My brother
  laughed like a gull on the harbour wall." Not a list of facts; something that would hurt to lose.
- **Keeping one.** When something in play is worth holding (a name, a face, a vow, what the door hid), the player
  writes it and you send `{"action": "memories", "owner": "Mira", "keep": "..."}`.
  - If the slots are full, the action waits for the player: which memory fades? They answer with its number.
    Or name it at once: `"forget": 2`. Never choose for them.
- **Losing them.** Trauma, a curse, the loop, a long sleep: `{"action": "memories", "owner": "Mira", "lose": true}`
  and the script picks one. Tell the player which; it is gone from their notes too.
  - A player may also let one go (`"forget": 3`): it can make a beautiful scene.
- **Using them.** A memory that fits the moment is a label: +1 on the roll, or the right to know something.
  A character cannot recall what is not held: if Mira forgot the password, Mira does not know it, whatever
  the player remembers.
- **The mind grows or breaks.** `"slots": 6` for an immortal who learns to remember, `"slots": 3` for a mind
  that cracks (the oldest fade first).
- `{"action": "memories", "owner": "Mira"}` reads them, oldest first. Read them back to the player at the start
  of a session.
- With the loop module, memories carry across resets like knowledge; with roles, a forgotten role is still dealt.
