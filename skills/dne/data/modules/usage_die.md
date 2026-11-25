A **usage die** stands for a supply nobody wants to count: torches, ammunition, fuel, rations, air, medicine. It is
a die size, d12 down to d4. Each time the supply is drawn on, the script rolls it; on a 1 or 2 it steps down one
size, and a 1 or 2 on a d4 means it is gone *(default)*.

- **Stocking:** `{"action": "upkeep", "dice": {"torches": "d8", "ammo": "d10", "fuel": "d6"}}` (party supplies).
  A fresh find or a purchase sets a new size the same way. This works whether or not `survival` is on.
- **Drawing on it:** `{"action": "use", "item": "torches"}`. When to roll:
  - once per scene where it is really used (a dark tunnel, a firefight, a long drive);
  - once per day of travel for rations, fuel or air;
  - never for a moment that would not change anything.
- The reply says the roll, the die before and after, and `gone` when it runs out. Say it in the fiction when it
  steps down ("the last few torches"), and make the empty moment a real problem, never a footnote.
- Counted stores (`upkeep` stores with a daily rate) still work alongside: count what makes decisions by the unit
  (coin, a few precious arrows) and roll a die for the rest.
- Usage dice show on the display as shrinking bars and in state.md as `party torches d8`.
