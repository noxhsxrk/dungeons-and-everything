An **emotion** is a feeling that stays with a character between scenes: −1 on one approach *(default)* until they
act on it. The script stores it as a condition, so every roll already counts it.

| Emotion | −1 on | Clears when they… |
|---|---|---|
| afraid | Force | admit the fear out loud to someone, or step back from a fight that matters |
| angry | Heart | say the cruel thing, or break something that belongs to whoever caused it |
| guilty | Wits | confess, or pay for it with something they value |
| hopeless | Grit | give up on something for an easy comfort tonight |
| insecure | Finesse | do something reckless, alone, to prove they can |

- **Marking one:** when a scene leaves a mark (a rejection, a betrayal, a close call), or on a miss when that fits
  better than harm: `{"action": "emotion", "owner": "Theo", "name": "guilty", "why": "he lied to her"}`.
  A character can carry several; the same one twice changes nothing.
- **Clearing one:** when the player has the character do what the feeling pushes them to, or when someone comforts
  them in a real scene: `{"action": "emotion", "owner": "Theo", "name": "guilty", "act": true, "why": "confessed"}`.
  Offer the clearing action as a choice, never force it. Acting on an emotion is good drama: say so.
- Knowing someone's emotion is leverage: with the strings module, a character who uses it gains a string.
- Players see their own emotions; the others see what the character lets show.
