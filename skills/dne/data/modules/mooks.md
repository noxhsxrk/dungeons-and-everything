Two kinds of foes. **Mooks** are nameless: guards, thugs, drones. **Named foes** have a name, a motive and a scene of
their own. The script holds the numbers; you hold the moves.

- **Mooks come as a group:** `{"action": "foe", "name": "Dock thugs", "threat": 1, "count": 5}`.
  - Every mook goes down in **one hit**, whatever their threat; a critical success drops one more *(default)*.
  - The group deals the harm of its threat, raised by its size as in the core rules (3–5 of them +1 threat,
    6–10 +2). The reply's `deals` says how much; it falls as they drop.
  - Mooks never roll. When a roll against them misses, they act: they hit, they grab, they raise the alarm.
- **Named foes:** `{"action": "foe", "name": "Captain Hale", "threat": 3}`. They take the harm boxes of their
  threat, at least 2 *(default)*: a named foe never falls to one blow. Each hit marks the harm the PC dealt.
- **A hit:** `{"action": "foe", "name": "Dock thugs", "hit": 1}` (mooks: a hit is a hit; send `"critical": true` on
  a critical success) or `{"action": "foe", "name": "Captain Hale", "hit": 2}` (named: the harm dealt, 1 +1 for a
  fitting weapon or label +1 critical, as usual). The reply says who is down and who is left.
- **Read:** `{"action": "foe", "name": "Dock thugs"}`. Foes are tracks: they show on the display.
- Let mooks scatter once half of them are down, and named foes bargain or run before the last box.
