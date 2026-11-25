Five **identity labels** say who a young hero is right now, in their own eyes and everyone else's. They are not the
sheet's labels (job, background, power): those stay as they are. Each runs −2 to +3 *(default)*.

| Label | It is about |
|---|---|
| fierce | fighting, standing your ground, being the one people fear |
| uncanny | the strange part of you: powers, the thing that makes you not normal |
| guardian | protecting, putting others first, being the one people lean on |
| proud | being right, being the best, seeing through people |
| grounded | the ordinary life: friends, family, school, being a person |

- **At the start** each hero puts +2, +1, +1, 0, −1 on the five *(default)*:
  `{"action": "identity", "owner": "Kit", "set": {"fierce": 2, "uncanny": 1, "guardian": 1, "proud": 0, "grounded": -1}}`.
  Send `{"action": "modules", "apply": true}` first so every PC has the five tracks.
- **Rolling with a label:** when the roll is about who the hero is (stand between a friend and danger, let the
  power loose, prove you are the smartest), roll the usual 2d6 with the label instead of an approach:
  `{"action": "identity", "owner": "Kit", "roll": "guardian", "label": "shield the bus"}`. Push and help work;
  conditions count as for the label's approach (fierce Force, uncanny Finesse, guardian Grit, proud Wits,
  grounded Heart), so an insecure hero rolls uncanny at −1. Story mode: the label sets the oracle's odds.
- **Shifting:** when someone the hero cares about tells them who they are ("you are a danger to everyone"), and the
  player accepts it, one label goes up and another goes down, always together:
  `{"action": "identity", "owner": "Kit", "up": "uncanny", "down": "grounded", "by": "Coach Reyes", "why": "…"}`.
  If the player rejects it, they roll Heart as usual; on a miss the shift happens anyway.
- **Past the edge:** a label already at +3 cannot go up and one at −2 cannot go down. That half of the shift does
  not happen; the hero becomes insecure instead (with the emotions module; otherwise name a condition).
- Players see all five numbers; ask them often which one they think is true.
