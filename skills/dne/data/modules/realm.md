Power comes in realms, a track per character: **realm** 0–8 *(default)*, from Tempered Flesh to Ascendant (the
names are the module's; rename them to fit the world). Realm is not a bonus to rolls. It is what a character
can do at all: fly at Spirit Apart, shrug off steel at Bright Core. A lower realm wins only with a trick, a
treasure, a sacrifice, or numbers.

- **Breakthrough.** When a character has earned the chance (seclusion, a pill, an insight in play, a master's
  word), they try: `{"action": "realm", "actor": "Lin", "breakthrough": true}`. The usual check with Heart
  (send `approach` or a `spec` instead), -1 from realm 3 and -2 from realm 6 *(default)*. Push and help work.
  - Passed (7+): one realm up. On 7–9 name a cost as usual: a meridian scar, a rival who felt it, a debt.
  - Missed: no realm, and **Qi Deviation**: -1 on every roll until a rest clears it (`pool refill rest`).
    A critical miss also marks 1 harm. Nobody falls a realm.
  - Do not allow another try until the story gives a new chance (a new pill, a new insight, a new place).
- **Tribulation.** Into realms 3 and 6 *(default)* heaven answers. A passed breakthrough starts a tribulation of
  2 + realm/3 waves (3, then 4) instead of the realm. Send one action per wave, in order, so each is its own roll:
  `{"action": "realm", "actor": "Lin", "wave": 1}`, then 2, 3 … The usual check with Grit, same difficulty.
  - A missed wave marks 1 harm (2 on a critical miss). Friends may help a wave, and share the harm.
  - After the last wave: half or more passed = the realm. Fewer = Qi Deviation and no realm this time.
  - Describe each wave bigger than the last. The sky is watching.
- `{"action": "realm", "actor": "Lin"}` reads the realm, its name and any tribulation under way.
- Story mode: the oracle answers breakthroughs (likely, 50/50 from realm 3, unlikely from realm 6).
