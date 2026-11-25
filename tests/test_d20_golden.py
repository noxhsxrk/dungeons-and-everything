"""Braid (2.0) must leave 5e campaigns byte-identical: the d20 checks of roll, judge, flashback and search give
the same results as 1.8.6 for the same seed. GOLDEN was recorded from 1.8.6 before any 2.0 change."""
from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _engine_case import EngineCase  # noqa: E402

GOLDEN = json.loads('[{"actor":"Mira","dice":[1],"modifier":0,"total":1,"label":"Stealth","dc":12,"degree":"critical failure","passed":false},[{"situation":"gate","actor":"Mira","plan":"p0","outcome":"failure","dice":5,"total":5,"dc":14,"degree":"failure","if_fails":"f","opens":""}],{"by":"Mira","claim":"I hid a key","cost":"","worked":false,"dice":1,"total":1,"dc":13,"passed":false,"advantage":false,"note":"It was tried and something about it went wrong: say what, and let that be the new problem."},{"actor":"Theo","found":[{"id":"mud","text":"Mud on the floor."}],"took_minutes":20,"roll_helped":false},{"actor":"Mira","dice":[13],"modifier":1,"total":14,"label":"Stealth","dc":12,"degree":"success","passed":true},[{"dice":11,"total":12,"dc":14,"degree":"success at a cost"}],{"by":"Mira","claim":"I hid a key","cost":"","worked":false,"dice":7,"total":8,"dc":13,"passed":false,"advantage":false,"note":"It was tried and something about it went wrong: say what, and let that be the new problem."},{"actor":"Theo","found":[{"id":"mud","text":"Mud on the floor."}],"took_minutes":20,"roll_helped":false},{"actor":"Mira","dice":[20],"modifier":2,"total":22,"label":"Stealth","dc":12,"degree":"critical success","passed":true},[{"situation":"gate","actor":"Mira","plan":"p2","outcome":"failure","dice":3,"total":5,"dc":14,"degree":"failure","if_fails":"f","opens":""}],{"by":"Mira","claim":"I hid a key","cost":"","worked":false,"dice":8,"total":10,"dc":13,"passed":false,"advantage":false,"note":"It was tried and something about it went wrong: say what, and let that be the new problem."},{"actor":"Theo","found":[{"id":"mud","text":"Mud on the floor."}],"took_minutes":20,"roll_helped":false},{"actor":"Mira","dice":[12],"modifier":3,"total":15,"label":"Stealth","dc":12,"degree":"success","passed":true},[{"situation":"gate","actor":"Mira","plan":"p3","outcome":"failure","dice":6,"total":9,"dc":14,"degree":"failure","if_fails":"f","opens":""}],{"by":"Mira","claim":"I hid a key","cost":"","worked":true,"dice":20,"total":23,"dc":13,"passed":true,"advantage":false,"note":"It happened as told."},{"actor":"Theo","found":[{"id":"ink","text":"Ink on the sill. Blue ink."},{"id":"mud","text":"Mud on the floor."}],"took_minutes":10,"roll_helped":true},{"actor":"Mira","dice":[11],"modifier":4,"total":15,"label":"Stealth","dc":12,"degree":"success","passed":true},[{"situation":"gate","actor":"Mira","plan":"p4","outcome":"failure","dice":5,"total":9,"dc":14,"degree":"failure","if_fails":"f","opens":""}],{"by":"Mira","claim":"I hid a key","cost":"","worked":true,"dice":19,"total":23,"dc":13,"passed":true,"advantage":false,"note":"It happened as told."},{"actor":"Theo","found":[{"id":"mud","text":"Mud on the floor."}],"took_minutes":20,"roll_helped":false},{"actor":"Mira","dice":[15],"modifier":5,"total":20,"label":"Stealth","dc":12,"degree":"success","passed":true},[{"situation":"gate","actor":"Mira","plan":"p5","outcome":"success","dice":14,"total":19,"dc":14,"degree":"success"}],{"by":"Mira","claim":"I hid a key","cost":"","worked":true,"dice":9,"total":14,"dc":13,"passed":true,"advantage":false,"note":"It happened as told."},{"actor":"Theo","found":[{"id":"ink","text":"Ink on the sill. Blue ink."},{"id":"mud","text":"Mud on the floor."}],"took_minutes":10,"roll_helped":true}]')

SITUATION = {"action": "situation", "id": "gate", "difficulty": "hard",
             "sides": [{"who": "a", "wants": "b", "limit": "c", "will_trade": "d"}], "if_left_alone": "e", "facts": []}
CASE = {"action": "case", "id": "ledger", "question": "who took the ledger?", "answer": "the clerk",
        "clues": [{"id": "ink", "text": "Ink on the sill.", "where": "office", "obvious": False, "detail": "Blue ink."},
                  {"id": "mud", "text": "Mud on the floor.", "where": "office"}]}


def _turn(case: EngineCase, text: str, *intents) -> dict:
    r = case.do(text, *intents)
    if r["status"] == "waiting_for_player":             # a price offered: take it, so the next turn starts clean
        first = r["results"][-1].get("data")
        r = case.turn.answer("oldworld", r["next_input"]["request_id"], "accept")
        r["results"] = [{"data": first}, {"data": (r.get("results") or [{}])[-1].get("data")}]
    case.turn.finish("oldworld", "ok")
    return r


def run(case: EngineCase) -> list:
    with case.wdb.writer("oldworld") as db:            # the store's seed is clock-made: pin it so rolls repeat
        case.wdb.set_meta(db, "seed", "braid-golden")
    out = []
    for n in range(6):
        r = _turn(case, f"roll {n}", {"actor": "Mira", "action": "roll", "spec": f"1d20+{n}", "dc": 12, "label": "Stealth"})
        out.append(case.data(r))
        r = _turn(case, f"judge {n}", SITUATION if n == 0 else {"action": "ask"},
                    {"action": "judge", "situation": "gate", "actor": "Mira", "plan": f"p{n}", "risk": "r", "if_fails": "f",
                     "cost": "c", "roll": {"spec": f"1d20+{n}", "dc": 14, "label": "Athletics"}})
        out.append([d.get("data") for d in r["results"][-2:] if "dice" in (d.get("data") or {})])
        r = _turn(case, f"flashback {n}", {"actor": "Mira", "action": "flashback", "claim": "I hid a key",
                                       "roll": {"spec": f"1d20+{n}", "dc": 13}})
        d = dict(case.data(r))
        d.pop("minute", None)
        out.append(d)
        r = _turn(case, f"search {n}", CASE if n == 0 else {"action": "ask"},
                    {"actor": "Theo", "action": "search", "case": "ledger", "where": "office",
                     "roll": {"spec": f"1d20+{n}", "dc": 13}})
        out.append(case.data(r))
    return json.loads(json.dumps(out))


class D20Golden(EngineCase):
    def test_seeded_d20_checks_are_unchanged(self):
        got = run(self)
        self.assertEqual(got, GOLDEN)
