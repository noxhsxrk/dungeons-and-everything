"""One campaign that looks like a table mid-story: a PC, a companion, a graph, a faction, a calendar, an open quest.

Shared by the tests that must keep old saves working (undo, the turn runner, migrations).
"""
from __future__ import annotations

import json
import pathlib

COMPANION = """# Bren
- **Status:** active | **Mode:** agent

## What I know
- The party saved my shop.

## Journal
- Day 3: they paid my debt to the Tollmen.
"""


def make(root: pathlib.Path, name: str = "oldworld") -> pathlib.Path:
    """Create the campaign under <root>/campaigns/<name> and return its folder."""
    camp = root / "campaigns" / name
    (camp / "characters").mkdir(parents=True)
    (camp / "companions").mkdir()
    files = {
        "state.md": (f"# Campaign: {name}\n**Session count:** 3\n\n## Current Situation\n- Location: Millbridge\n\n"
                     "## Active Quests\n- [ ] Find out who is taxing the bridge\n\n"
                     "## Live State Flags\n**NPC dispositions:**\n- Bren: friendly\n\n"
                     "## Session Flags\n- autorun: false\n- roll_mode: players\n"),
        "world.md": "# World\n",
        "npcs.md": "# NPCs\n\n| Name | Role | Faction | Location | Attitude | Notes |\n|---|---|---|---|---|---|\n"
                   "| Bren | miller | independent | Millbridge | friendly | |\n",
        "npcs-full.md": "# NPCs (full entries)\n\n## Bren\n- **HP:** 9 | **AC:** 11\n",
        "session-log.md": "# Session log\n\n## Session 3\n- Reached Millbridge.\n",
        "graph.json": json.dumps({"nodes": {"npc_bren": {"type": "npc", "name": "Bren"}}, "edges": []}),
        "factions.json": json.dumps({"factions": [{"name": "Tollmen", "force": 3, "cunning": 2, "wealth": 4}]}),
        "calendar.json": json.dumps({"gregorian": True, "day": 15, "month": 5, "year": 2026, "hour": 9,
                                     "months": ["January", "February", "March", "April", "May", "June", "July",
                                                "August", "September", "October", "November", "December"]}),
        "characters/mira.md": "# Mira\n- **Class:** Medic | **Level:** 3\n- **XP:** 1150 / 2700\n- **HP:** 20 / 20\n",
        "companions/Bren.md": COMPANION,
    }
    for rel, body in files.items():
        (camp / rel).write_text(body, encoding="utf-8")
    return camp
