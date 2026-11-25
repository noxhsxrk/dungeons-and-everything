One party track, **doom** 0–20 *(default)*, that rises with every risk. The script checks it; nobody rolls for it.

- **Every Braid check adds 1** (a `roll`, `judge`, `fright`, progress roll, any check with a result on the
  ladder), by itself. Then the script rolls a hidden d20: if it is **at or under doom, disaster strikes**.
  - The first risk has a 1-in-20 chance, the tenth 1-in-2, and at 20 it is certain: the first disaster
    tends to come around the fifth risk.
  - A risk that needs no roll (opening the sealed door, splitting up, a light left burning) adds by hand:
    `{"action": "doom", "add": 1, "why": "they split up"}`. `{"action": "doom"}` alone just reads it.
- **Disaster:** the reply carries `doom.disaster` with an entry the script rolled from the table. Play it at
  once and in full; it is a hard move that nobody can roll against.
  - Then doom drops back to its floor, and the floor rises by 1 *(default, up to 6)*: each disaster brings the
    next one sooner. The night only gets darker.
- **Show it.** Doom sits on the display's clock panel. Tell the players the number when it moves; the fear of
  the next check is the point.
- **Ending:** when the story's end comes (dawn, rescue, the last survivor), doom stops mattering. Remove it with
  `{"action": "track", "owner": "party", "id": "doom", "remove": true}`.
- Story mode: the oracle's answers count as checks too.
