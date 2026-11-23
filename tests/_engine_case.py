"""Base class for engine tests: the old-campaign fixture with the world engine on and a small map."""
from __future__ import annotations

import json
import os
import pathlib
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
SCRIPTS = ROOT / "skills" / "dne" / "scripts"
DISPLAY = ROOT / "skills" / "dne" / "display"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(SCRIPTS))
import _old_campaign  # noqa: E402

PLACES = (("millbridge", "Millbridge", 0), ("ford", "The Ford", 12), ("market", "Market", 24))
EDGES = [{"a": "millbridge", "b": "ford", "road": True, "miles": 12.0},
         {"a": "ford", "b": "market", "road": True, "miles": 12.0}]


class EngineCase(unittest.TestCase):
    FLAGS = "- display: none\n- roll_mode: auto\n- world_engine: on\n"
    PARTY_AT = "millbridge"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)
        self.rt = self.root / "rt"
        self.rt.mkdir()
        self.camp = _old_campaign.make(self.root)
        self.flags(self.FLAGS)
        (self.camp / "world-map.json").write_text(json.dumps({
            "party_location": self.PARTY_AT,
            "places": {k: {"name": n, "x": x, "y": 0, "biome": "plains", "kind": "town", "desc": "", "secret": "",
                           "hidden": False, "visited": True, "danger": 1} for k, n, x in PLACES},
            "edges": EDGES}), encoding="utf-8")
        self._saved = {k: os.environ.get(k) for k in ("DNE_CAMPAIGN_ROOT", "DNE_RUNTIME_DIR", "DNE_OUTBOX_LOG", "DNE_NOTE_BUDGET")}
        os.environ.update(DNE_CAMPAIGN_ROOT=str(self.root), DNE_RUNTIME_DIR=str(self.rt),
                          DNE_OUTBOX_LOG=str(self.root / "out.jsonl"))
        os.environ.pop("DNE_NOTE_BUDGET", None)
        import scheduler
        import turn
        import world_db
        self.s, self.turn, self.wdb = scheduler, turn, world_db

    def tearDown(self):
        for k, v in self._saved.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        self._tmp.cleanup()

    def flags(self, block: str) -> None:
        state = self.camp / "state.md"
        state.write_text(state.read_text(encoding="utf-8").split("## Session Flags")[0] + "## Session Flags\n" + block,
                         encoding="utf-8")

    def do(self, text: str, *intents, campaign: str = "oldworld") -> dict:
        """One turn's worth of engine actions; returns the resolve result."""
        self.turn.begin(campaign, text)
        return self.turn.resolve(campaign, list(intents))

    def data(self, out: dict, i: int = -1) -> dict:
        return out["results"][i]["data"]

    def thing(self, kind: str, id: str, campaign: str = "oldworld"):
        with self.wdb.reader(campaign) as db:
            return self.wdb.get(db, kind, id)

    def event(self, event_id: str, campaign: str = "oldworld"):
        with self.wdb.reader(campaign) as db:
            return db.execute("SELECT * FROM events WHERE event_id=?", (event_id,)).fetchone()

    def read_json(self, rel: str):
        return json.loads((self.camp / rel).read_text(encoding="utf-8"))
