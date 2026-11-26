"""Braid PR 9: one scripted scene per genre preset (plan §5 PR 9, "เล่นตามสคริปต์แนวละหนึ่งฉาก").

Each scene is a real campaign: the preset written into a seed by `genres.py apply`, built by campaign_init, two
characters made by sheet.py, the modules applied, then a genre-typical risky scene played through engine turns that
uses every switched-on module's own action at least once, and ends with the scene refill and a clean `sheet.py check`.
Three scenes add an optional module with `--set` (so every module in data/modules is played somewhere), and horror is
played in story mode. No 5e module may be touched and the GM text must not point at 5e rules. Dice are the engine's
own (roll_mode auto), so the checks hold for any roll."""
from __future__ import annotations

import contextlib
import io
import json
import os
import pathlib
import shlex
import subprocess
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _engine_case import SCRIPTS  # noqa: E402
from test_braid_rules import MIRA, THEO, leaks, no_5e  # noqa: E402

import turn  # noqa: E402,F401  (the engine first, as the other Braid tests do)
import genres  # noqa: E402
import modules  # noqa: E402
import story_gen  # noqa: E402

CAMP = "play"
LADDER = ("critical failure", "failure", "success at a cost", "success", "critical success")
SEED = {"seed_version": 1, "campaign": CAMP, "flags": {"display": "none", "roll_mode": "auto"},
        "calendar": {"date": "1 Thaw 412", "time": "morning", "months": ["Thaw", "Bloom"], "month_length": 30}}
#: Modules a scene adds with `--set` (all from the preset's own `optional` list), so every module is played once.
EXTRA = {"comedy": "labels", "cozy": "make_the_case", "timeloop": "memories"}
#: A module's own action where it is not the first of its `actions`: panic has none (its stress threshold is checked).
OWN = {"contest": "contest", "make_the_case": "make_the_case", "panic": "track"}


class GenreScene(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)
        self._saved = {k: os.environ.get(k) for k in ("DNE_CAMPAIGN_ROOT", "DNE_RUNTIME_DIR", "DNE_DISPLAY_HOST",
                                                       "DNE_OUTBOX_LOG", "DNE_NOTE_BUDGET")}
        os.environ.update(DNE_CAMPAIGN_ROOT=str(self.root), DNE_RUNTIME_DIR=str(self.root / "rt"),
                          DNE_DISPLAY_HOST="127.0.0.1:9", DNE_OUTBOX_LOG=str(self.root / "out.jsonl"))
        os.environ.pop("DNE_NOTE_BUDGET", None)
        (self.root / "rt").mkdir()
        self.out, self.played = [], set()

    def tearDown(self):
        for k, v in self._saved.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        self._tmp.cleanup()

    # ── the harness ──────────────────────────────────────────────────────────

    def run_main(self, module, argv) -> int:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            code = module.main(argv)
        self.out.append(buf.getvalue())
        return code

    @contextlib.contextmanager
    def scene(self, gid: str, system: str = "core"):
        """Build the genre's campaign, play the scene (the `with` body), end it, then check what every scene owes."""
        import campaign_init
        import paths
        import sheet
        with no_5e() as used:
            seed = self.root / "seed.json"
            seed.write_text(json.dumps({**SEED, "system": system}), encoding="utf-8")
            sets = ["--set", f"modules={','.join(genres.load(gid)['modules'] + [EXTRA[gid]])}"] if gid in EXTRA else []
            self.assertEqual(self.run_main(genres, ["apply", gid, "--seed", str(seed), *sets]), 0, self.out[-1])
            built = campaign_init.build(json.loads(seed.read_text(encoding="utf-8")))
            self.assertTrue(built.get("ok"), built)
            self.camp = paths.find_campaign(CAMP)
            self.assertEqual(paths.campaign_system(CAMP), system)
            self.assertEqual(self.sheet(*MIRA), 0, self.out[-1])
            self.assertEqual(self.sheet(*THEO), 0, self.out[-1])
            want = genres.load(gid)["modules"] + ([EXTRA[gid]] if gid in EXTRA else [])
            self.assertEqual(modules.enabled(CAMP), want)
            applied = self.one("[GM]: the scene opens", {"action": "modules", "apply": True})
            self.assertEqual(applied["modules"], want)
            yield
            done = self.one("[GM]: the scene ends", {"action": "pool", "refill": "scene"})
            self.assertEqual(done["cadence"], "scene")
            self.assertEqual(self.sheet("check"), 0, self.out[-1])
        self.assertEqual(used, [])
        self.assertEqual(leaks("\n".join(self.out)), [])
        for mod in want:                                    # every switched-on module's own action was played
            own = OWN.get(mod) or modules.load(mod)["actions"][0]
            self.assertIn(own, self.played, f"{gid}: {mod}")

    def sheet(self, *argv) -> int:
        import sheet
        return self.run_main(sheet, ["-c", CAMP, *argv])

    def turn_with(self, text: str, *intents) -> dict:
        import gm_guide
        turn.begin(CAMP, text)
        r = turn.resolve(CAMP, list(intents))
        self.assertEqual(r["status"], "open", r)
        self.out += gm_guide.engine_lines(CAMP, r) + [line for _p, line in gm_guide.turn_parts(CAMP, False, text, r)]
        self.out.append(json.dumps(r, ensure_ascii=False))
        turn.finish(CAMP, "ok")
        for x in r["results"]:
            self.assertNotIn("error", x.get("data") or {}, x)
        self.played |= {i["action"] for i in intents}
        return r

    def one(self, text: str, intent: dict) -> dict:
        return self.turn_with(text, intent)["results"][-1]["data"]

    def thing(self, kind: str, key: str):
        import world_db as wdb
        with wdb.reader(CAMP) as db:
            return wdb.get(db, kind, key)

    def value(self, owner: str, track: str) -> int:
        return self.thing("track", f"{owner.lower()}/{track}")["value"]

    def check(self, d: dict) -> dict:
        self.assertIn(d["degree"], LADDER, d)
        return d

    def system_lines(self) -> list:
        path = self.root / "out.jsonl"
        sent = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []
        return [line for m in sent if m.get("kind") == "system" for line in m["body"].splitlines()]

    def doom(self, before: int, d: dict) -> int:
        """One more doom, or a disaster that drops it to the floor; the track agrees. Returns the new doom."""
        self.assertEqual(d["doom"], d["floor"] if d["disaster"] else before + 1, d)
        self.assertEqual(self.value("party", "doom"), d["doom"])
        return d["doom"]

    def contest(self, *argv) -> subprocess.CompletedProcess:
        p = subprocess.run([sys.executable, str(SCRIPTS / "subsystem.py"), "-c", CAMP, *argv],
                           capture_output=True, text=True, encoding="utf-8")
        self.out.append(p.stdout + p.stderr)
        self.played.add("contest")
        return p

    # ── mood ─────────────────────────────────────────────────────────────────

    def test_analog_horror_a_tape_that_should_not_exist(self):
        with self.scene("analog-horror"):
            d = self.check(self.one("[Theo]: I watch the tape to the end", {"action": "fright", "actor": "Theo",
                                                                            "rating": "serious"}))
            self.assertEqual(self.value("Theo", "composure"), 10 - d["lost"])
            doom = self.doom(0, d["doom"])                               # every graded check feeds the doom
            d = self.check(self.one("[Mira Vale]: I rewind to the frame", {"action": "roll", "actor": "Mira Vale",
                                                                           "approach": "wits", "label": "the hidden frame"}))
            doom = self.doom(doom, d["doom"])
            self.doom(doom, self.one("[GM]: the signal comes back", {"action": "doom", "add": 1, "why": "the signal"}))

    def test_comedy_the_wedding_caterers(self):
        with self.scene("comedy"):
            self.one("[GM]: the caterers want their cake back", {"action": "foe", "name": "Caterers", "threat": 1,
                                                                 "count": 4})
            d = self.check(self.one("[Mira Vale]: I bluff, loudly", {"action": "identity", "owner": "Mira Vale",
                                                                    "roll": "proud", "label": "the best man's speech"}))
            d = self.one("[Theo]: I throw the cake", {"action": "foe", "name": "Caterers", "hit": 2})
            self.assertEqual((d["left"], d["down"]), (2, False))

    def test_cozy_who_ate_the_pie(self):
        clues = [{"id": "crumbs", "text": "crumbs on the porch", "where": "the bakery", "obvious": True},
                 {"id": "dog", "text": "the dog looks guilty", "where": "the bakery", "obvious": True}]
        with self.scene("cozy"):
            d = self.one("[GM]: the village wakes", {"action": "season"})
            self.assertIn(d["happening"], modules.load("seasons")["tables"][d["season"]])
            self.assertEqual(self.thing("season", "party")["name"], d["season"])
            self.one("[Mira Vale]: I bring Theo jam", {"action": "string", "by": "Mira Vale", "on": "Theo",
                                                        "gain": 1, "why": "she remembered his jam"})
            self.one("[Mira Vale]: I lean on that", {"action": "string", "by": "Mira Vale", "on": "Theo", "spend": "plus"})
            self.one("[GM]: the pie is gone", {"action": "case", "id": "pie", "open": True, "complexity": 3, "clues": clues})
            found = self.one("[Theo]: I look around the bakery", {"action": "search", "actor": "Theo", "case": "pie",
                                                                  "where": "the bakery"})["found"]
            self.assertEqual(len(found), 2)
            d = self.check(self.one("[Mira Vale]: it was the dog", {"action": "make_the_case", "actor": "Mira Vale",
                                                                    "case": "pie", "theory": "The dog, fed by Theo.",
                                                                    "explains": ["crumbs", "dog"]}))
            self.assertIn("Mira Vale's hold on Theo +1", d["edges"])     # the string spent on the next roll
            self.assertEqual(self.thing("case", "pie")["truth"], "The dog, fed by Theo." if d["holds"] else "")

    def test_horror_story_mode_the_lighthouse(self):
        with self.scene("horror", system="story"):
            self.one("[GM]: the lamp room", {"action": "case", "id": "lighthouse", "truth": "the keeper drowned his brother",
                                             "clues": [{"id": "c1", "text": "wet boots upstairs", "where": "the lamp room",
                                                        "obvious": True}]})
            found = self.one("[Mira Vale]: I search", {"action": "search", "actor": "Mira Vale", "case": "lighthouse",
                                                       "where": "the lamp room"})["found"]
            self.assertEqual([f["id"] for f in found], ["c1"])
            d = self.check(self.one("[Mira Vale]: I look in the water", {"action": "fright", "actor": "Mira Vale",
                                                                         "rating": "overwhelming"}))
            self.assertEqual(len(d["dice"]), 1)                          # story mode: the oracle's d100, not 2d6
            self.assertEqual(d["likelihood"], "unlikely")
            self.assertEqual(self.value("Mira Vale", "composure"), 10 - d["lost"])
            self.check(self.one("[Theo]: does the door hold?", {"action": "roll", "actor": "Theo", "likelihood": "likely",
                                                                "label": "the door holds"}))

    def test_romance_the_letter(self):
        with self.scene("romance"):
            self.one("[GM]: he read her letter", {"action": "emotion", "owner": "Theo", "name": "guilty", "why": "the letter"})
            self.assertEqual(self.thing("condition", "theo/guilty")["mod"], -1)
            self.one("[Theo]: I keep it", {"action": "string", "by": "Theo", "on": "Mira Vale", "gain": 1})
            self.check(self.one("[Theo]: I tell her", {"action": "roll", "actor": "Theo", "approach": "heart",
                                                       "label": "confess"}))
            self.assertTrue(self.one("[Theo]: it is out", {"action": "emotion", "owner": "Theo", "name": "guilty",
                                                           "act": True})["cleared"])
            self.assertIsNone(self.thing("condition", "theo/guilty"))

    def test_slasher_the_cabin(self):
        with self.scene("slasher"):
            self.one("[GM]: one flashlight", {"action": "upkeep", "dice": {"flashlight": "d6"}})
            d = self.one("[GM]: the mask in the window", {"action": "track", "owner": "Theo", "id": "stress", "mark": 3,
                                                          "why": "the mask"})
            jitters = [c for c in d["crossed"] if c["at"] == 3]          # panic's threshold on Braid's own stress
            self.assertEqual(len(jitters), 1)
            d = self.check(self.one("[Theo]: I hide under the bed", {"action": "roll", "actor": "Theo",
                                                                     "approach": "finesse", "label": "hide"}))
            doom = self.doom(0, d["doom"])
            d = self.one("[Mira Vale]: I switch the light on", {"action": "use", "item": "flashlight"})
            self.assertEqual(d["die"], "d4" if d["rolled"] <= 2 else "d6")              # 1-2: one size down
            self.doom(doom, self.one("[GM]: the phone line is cut", {"action": "doom", "add": 1}))

    # ── plot ─────────────────────────────────────────────────────────────────

    def test_competition_the_bake_off(self):
        with self.scene("competition"):
            self.assertEqual(self.contest("start", "Bake-off", "--race", "3", "--sides", "Mira Vale,The rival").returncode, 0)
            d = self.check(self.one("[Mira Vale]: my soufflé", {"action": "roll", "actor": "Mira Vale",
                                                               "approach": "finesse", "label": "the soufflé"}))
            p = self.contest("check", "Bake-off", "--side", "Mira Vale", "--total", str(d["total"]))
            self.assertEqual(p.returncode, 0, p.stderr)
            mira, rival = {"critical success": (2, 0), "success": (1, 0), "success at a cost": (1, 0),
                           "failure": (0, 1), "critical failure": (0, 2)}[d["degree"]]
            self.assertIn(f"Mira Vale {mira} · The rival {rival}", p.stdout)

    def test_heist_the_vault(self):
        with self.scene("heist"):
            d = self.check(self.one("[GM]: the plan", {"action": "engagement", "actor": "Mira Vale", "plan": "social",
                                                       "detail": "a cousin in the vault"}))
            self.assertEqual(self.thing("position", "party")["position"], d["position"])
            self.one("[GM]: the guards", {"action": "clock", "name": "Vault guards", "size": 4})
            d = self.check(self.one("[Mira Vale]: I crack the vault", {"action": "position", "actor": "Mira Vale",
                                                                       "approach": "finesse", "label": "crack the vault"}))
            self.assertIn("harm_if_hurt", d["reading"])
            d = self.one("[GM]: the job was loud", {"action": "crew_heat", "job": "loud", "high_profile": True})
            self.assertEqual((d["added"], self.value("party", "crew_heat")), (5, 5))

    def test_mystery_the_story_generator_case(self):
        with self.scene("mystery"):
            skel = story_gen.generate(["mystery"], seed=1926)
            self.assertTrue(skel["checked"]["ok"])
            (self.camp / "story-skeleton.json").write_text(json.dumps(skel, ensure_ascii=False), encoding="utf-8")
            case = skel["threads"][0]["case"]
            self.one("[GM]: the case", {"action": "case", "skeleton": True})
            start = case["places"][0]
            found = self.one("[Theo]: I go through the first room", {"action": "search", "actor": "Theo",
                                                                     "case": case["id"], "where": start})["found"]
            self.assertTrue(found)
            d = self.one("[GM]: someone walks in", {"action": "complicate", "what": "the clerk walks in", "cost": 1})
            self.assertEqual((d["left"], self.thing("pool", "party/complications")["value"]), (2, 2))
            culprit = next(s for s in case["suspects"] if s["id"] == case["culprit"])
            d = self.one("[Theo]: it was them", {"action": "accuse", "actor": "Theo", "case": case["id"],
                                                 "claim": f"The {culprit['role']} did it."})
            self.assertEqual(d["culprit_for_the_gm"]["role"], culprit["role"])

    def test_war_holding_the_ford(self):
        with self.scene("war"):
            self.one("[GM]: the company", {"action": "war", "unit": "Third Lantern", "quality": "trained"})
            d = self.one("[GM]: a day's march", {"action": "war", "pass": True, "why": "the march"})
            self.assertEqual((d["war_time"], d["war_pressure"], d["supply"]), (1, 1, 2))
            self.one("[GM]: the last rations", {"action": "upkeep", "dice": {"rations": "d8"}})
            self.one("[Theo]: we eat", {"action": "use", "item": "rations"})
            d = self.check(self.one("[Mira Vale]: hold the ford", {"action": "position", "actor": "Mira Vale",
                                                                   "approach": "force", "label": "hold the ford"}))
            self.assertEqual(d["reading"]["position"], "risky")
            d = self.one("[GM]: the ford costs us", {"action": "war", "losses": 2, "why": "the ford"})
            self.assertEqual((d["morale"], self.value("party", "morale")), (6, 6))

    # ── setting ──────────────────────────────────────────────────────────────

    def test_fantasy_the_dark_road(self):
        with self.scene("fantasy"):
            self.one("[Mira Vale]: I swear it", {"action": "vow", "owner": "Mira Vale", "name": "Free my brother",
                                                 "rank": "easy"})
            self.one("[GM]: into the tunnels", {"action": "upkeep", "dice": {"torches": "d6"}})
            self.one("[Theo]: torches", {"action": "use", "item": "torches"})
            self.one("[GM]: the gate is open", {"action": "vow", "owner": "Mira Vale", "name": "Free my brother", "mark": 3})
            d = self.check(self.one("[Mira Vale]: I bring him out", {"action": "vow", "owner": "Mira Vale",
                                                                     "name": "Free my brother", "fulfil": True}))
            if d["passed"]:                                              # the XP goes on the sheet through sheet.py
                argv = shlex.split(d["xp_command"])
                self.assertEqual(argv[:4], ["sheet.py", "-c", CAMP, "xp"])
                self.assertEqual(self.sheet(*argv[3:]), 0, self.out[-1])
                self.assertIn(f"XP {d['xp']}", self.out[-1] + self.sheet_text("Mira Vale"))

    def sheet_text(self, name: str) -> str:
        self.sheet("show", name)
        return self.out[-1]

    def test_historical_the_winter_siege(self):
        with self.scene("historical"):
            self.one("[GM]: lamp oil", {"action": "upkeep", "dice": {"lamp oil": "d8"}})
            d = self.one("[Theo]: we light the lamps", {"action": "use", "item": "lamp oil"})
            self.assertEqual(d["was"], "d8")
            self.check(self.one("[Mira Vale]: I talk the sentry round", {"action": "roll", "actor": "Mira Vale",
                                                                         "approach": "heart", "label": "the sentry"}))

    def test_litrpg_the_first_dungeon(self):
        with self.scene("litrpg"):
            self.one("[GM]: slimes", {"action": "foe", "name": "Cave slimes", "threat": 1, "count": 3})
            self.one("[GM]: a slime hits", {"action": "track", "owner": "Mira Vale", "id": "harm", "mark": 1, "why": "slime"})
            self.assertIn("[System] Mira Vale — harm: new (1/4)", self.system_lines())
            self.assertTrue(self.one("[Theo]: I sweep them", {"action": "foe", "name": "Cave slimes", "hit": 3})["down"])
            d = self.one("[GM]: a chest", {"action": "status", "loot": "bronze", "to": "Mira Vale"})
            self.assertIn(d["item"], modules.load("status_window")["tables"][f"loot_{d['tier']}"])
            self.assertIn("harm: 1/4", self.one("[Mira Vale]: status", {"action": "status", "show": "Mira Vale"})["window"])

    def test_sci_fi_the_dead_station(self):
        with self.scene("sci-fi"):
            self.one("[GM]: air", {"action": "upkeep", "dice": {"oxygen": "d8"}})
            self.one("[Theo]: we breathe", {"action": "use", "item": "oxygen"})
            self.one("[Mira Vale]: I will find the crew", {"action": "vow", "owner": "Mira Vale", "name": "Find the crew",
                                                           "rank": "tough"})
            d = self.one("[GM]: the logs", {"action": "vow", "owner": "Mira Vale", "name": "Find the crew", "mark": 1})
            self.assertEqual((d["ticks"], d["boxes"]), (8, 2))
            self.check(self.one("[Mira Vale]: I hack the door", {"action": "roll", "actor": "Mira Vale",
                                                                 "approach": "wits", "label": "the door"}))

    def test_space_opera_the_blockade(self):
        with self.scene("space-opera"):
            self.one("[GM]: drones", {"action": "foe", "name": "Boarding drones", "threat": 1, "count": 3})
            self.one("[GM]: the hull breaks", {"action": "position", "set": "desperate", "why": "hull breach"})
            d = self.check(self.one("[Mira Vale]: through the debris", {"action": "position", "actor": "Mira Vale",
                                                                        "approach": "finesse", "label": "the debris"}))
            self.assertEqual(d["reading"]["position"], "desperate")
            self.assertEqual(self.one("[Theo]: I shoot", {"action": "foe", "name": "Boarding drones", "hit": 1})["left"], 2)
            d = self.one("[GM]: the blockade noticed", {"action": "crew_heat", "job": "contained", "hostile_turf": True})
            self.assertEqual(self.value("party", "crew_heat"), d["added"])

    def test_wuxia_the_sect_gate(self):
        with self.scene("wuxia"):
            d = self.check(self.one("[Mira Vale]: I break through", {"action": "realm", "actor": "Mira Vale",
                                                                     "breakthrough": True}))
            if d["passed"]:
                self.assertEqual(self.value("Mira Vale", "realm"), 1)
            else:
                self.assertEqual(self.value("Mira Vale", "realm"), 0)
                self.assertIsNotNone(self.thing("condition", "mira vale/qi deviation"))
            self.one("[GM]: disciples", {"action": "foe", "name": "Iron Fist disciples", "threat": 2, "count": 3})
            self.assertEqual(self.one("[Theo]: palm strike", {"action": "foe", "name": "Iron Fist disciples",
                                                              "hit": 1})["left"], 2)
            self.one("[Mira Vale]: for my master", {"action": "vow", "owner": "Mira Vale", "name": "Avenge my master",
                                                    "rank": "hard"})

    # ── frame ────────────────────────────────────────────────────────────────

    def test_timeloop_the_same_day(self):
        with self.scene("timeloop"):
            self.assertTrue(self.one("[GM]: the day begins", {"action": "loop", "start": True})["started"])
            self.turn_with("[Mira Vale]: I fall from the tower",
                           {"action": "loop", "learn": "the ferryman lies"},
                           {"action": "memories", "owner": "Mira Vale", "keep": "the bell rings wrong"},
                           {"action": "track", "owner": "Mira Vale", "id": "harm", "mark": 2, "why": "fell"},
                           {"action": "wait", "minutes": 600})
            self.assertEqual(self.value("Mira Vale", "harm"), 2)
            d = self.one("[GM]: midnight", {"action": "loop", "reset": True, "why": "midnight"})
            self.assertEqual((d["loop"], d["fatigue"], d["knowledge"]), (2, 1, ["the ferryman lies"]))
            self.assertIsNone(self.thing("track", "mira vale/harm"))     # the fall is undone
            self.assertEqual(self.thing("memory", "mira vale")["held"], ["the bell rings wrong"])

    def test_traitor_the_sealed_deal(self):
        with self.scene("traitor"):
            d = self.one("[GM]: roles", {"action": "roles", "deal": ["Mira Vale", "Theo", "Ada", "Kell"]})
            seal = d["seal"]
            self.assertIn(self.one("[GM]: Ada acts", {"action": "roles", "act": "Ada"})["act"],
                          sum(modules.load("roles")["tables"].values(), []))
            self.check(self.one("[Theo]: I watch Ada", {"action": "roll", "actor": "Theo", "approach": "wits",
                                                        "label": "read the room"}))
            d = self.one("[GM]: the reveal", {"action": "roles", "reveal": True, "expect": seal})
            self.assertTrue(d["verified"], d)
            self.assertEqual(sorted(d["deal"].values()), ["loyal", "loyal", "loyal", "traitor"])

    # ── the 2.0 additions (all early) ────────────────────────────────────────

    def test_survival_the_washed_out_road(self):
        with self.scene("survival"):
            self.one("[GM]: what we carried", {"action": "upkeep", "dice": {"water": "d6"}})
            d = self.one("[Theo]: we drink", {"action": "use", "item": "water"})
            self.assertEqual(d["was"], "d6")
            self.one("[Mira Vale]: everyone gets home", {"action": "vow", "owner": "Mira Vale", "name": "Everyone gets home",
                                                         "rank": "tough"})
            d = self.check(self.one("[Mira Vale]: I ford the river", {"action": "roll", "actor": "Mira Vale",
                                                                      "approach": "grit", "label": "the ford"}))
            doom = self.doom(0, d["doom"])
            self.doom(doom, self.one("[GM]: the rain comes back", {"action": "doom", "add": 1, "why": "the rain"}))

    def test_thai_the_spirit_house(self):
        with self.scene("thai-ghost"):
            self.one("[GM]: the old shrine", {"action": "case", "id": "shrine", "truth": "the land was taken with a forged deed",
                                              "clues": [{"id": "deed", "text": "a deed with a dead man's seal",
                                                         "where": "the shrine", "obvious": True}]})
            found = self.one("[Theo]: I look behind the shrine", {"action": "search", "actor": "Theo", "case": "shrine",
                                                                 "where": "the shrine"})["found"]
            self.assertEqual([f["id"] for f in found], ["deed"])
            d = self.check(self.one("[Mira Vale]: her face in the window", {"action": "fright", "actor": "Mira Vale",
                                                                            "rating": "serious"}))
            self.assertEqual(self.value("Mira Vale", "composure"), 10 - d["lost"])

    def test_thriller_the_missing_night(self):
        with self.scene("thriller"):
            self.one("[Mira Vale]: what I hold on to", {"action": "memories", "owner": "Mira Vale",
                                                        "keep": "the text I don't remember sending"})
            self.assertEqual(self.thing("memory", "mira vale")["held"], ["the text I don't remember sending"])
            self.one("[GM]: that night", {"action": "case", "id": "night", "truth": "her husband sent the text",
                                          "clues": [{"id": "phone", "text": "his phone was at home all night",
                                                     "where": "the flat", "obvious": True}]})
            self.assertTrue(self.one("[Theo]: I check the flat", {"action": "search", "actor": "Theo", "case": "night",
                                                                  "where": "the flat"})["found"])
            d = self.one("[GM]: he comes home early", {"action": "complicate", "what": "he comes home early", "cost": 1})
            self.assertEqual(d["left"], 2)

    def test_spy_the_hotel_ledger(self):
        with self.scene("spy"):
            d = self.one("[GM]: the cell", {"action": "roles", "deal": ["Mira Vale", "Theo", "Ada", "Kell"]})
            seal = d["seal"]
            d = self.check(self.one("[Mira Vale]: I lift the ledger", {"action": "position", "actor": "Mira Vale",
                                                                       "approach": "finesse", "label": "the ledger"}))
            self.assertIn("position", d["reading"])
            d = self.one("[GM]: the minister noticed", {"action": "crew_heat", "job": "contained", "hostile_turf": True})
            self.assertEqual(self.value("party", "crew_heat"), d["added"])
            self.assertTrue(self.one("[GM]: the double agent", {"action": "roles", "reveal": True,
                                                                "expect": seal})["verified"])

    def test_post_the_flooded_school(self):
        with self.scene("post-apoc"):
            d = self.one("[GM]: the year turns", {"action": "season"})
            self.assertEqual(self.thing("season", "party")["name"], d["season"])
            self.one("[GM]: the medicine", {"action": "upkeep", "dice": {"medicine": "d8"}})
            self.assertEqual(self.one("[Theo]: we treat the fever", {"action": "use", "item": "medicine"})["was"], "d8")
            self.one("[Mira Vale]: we rebuild the well", {"action": "vow", "owner": "Mira Vale", "name": "Rebuild the well",
                                                          "rank": "easy"})

    def test_superhero_the_flood_blame(self):
        with self.scene("superhero"):
            self.one("[GM]: looters", {"action": "foe", "name": "Looters", "threat": 1, "count": 3})
            self.check(self.one("[Mira Vale]: I save the bus", {"action": "identity", "owner": "Mira Vale", "roll": "proud",
                                                               "label": "in front of the cameras"}))
            self.assertEqual(self.one("[Theo]: I knock one down", {"action": "foe", "name": "Looters", "hit": 1})["left"], 2)
            self.one("[Theo]: she knows who I am", {"action": "string", "by": "Mira Vale", "on": "Theo", "gain": 1,
                                                    "why": "she saw him unmasked"})

    def test_western_the_water_rights(self):
        with self.scene("western"):
            self.one("[GM]: the last cartridges", {"action": "upkeep", "dice": {"cartridges": "d6"}})
            self.one("[Theo]: I fire", {"action": "use", "item": "cartridges"})
            self.one("[Mira Vale]: the water stays free", {"action": "vow", "owner": "Mira Vale",
                                                           "name": "Keep the creek free", "rank": "tough"})
            d = self.one("[GM]: the baron's men saw it", {"action": "crew_heat", "job": "loud"})
            self.assertEqual(self.value("party", "crew_heat"), d["added"])

    def test_kids_the_thing_in_the_woods(self):
        with self.scene("kids-adventure"):
            self.check(self.one("[Theo]: I go in first", {"action": "identity", "owner": "Theo", "roll": "proud",
                                                         "label": "nobody calls me a baby"}))
            self.one("[Mira Vale]: I kept his secret", {"action": "string", "by": "Mira Vale", "on": "Theo", "gain": 1})
            self.one("[GM]: the woods", {"action": "case", "id": "woods", "truth": "the mill owner buried the dog there",
                                         "clues": [{"id": "collar", "text": "a dog collar under the leaves",
                                                    "where": "the woods", "obvious": True}]})
            self.assertTrue(self.one("[Theo]: I dig", {"action": "search", "actor": "Theo", "case": "woods",
                                                       "where": "the woods"})["found"])

    def test_court_the_coronation(self):
        with self.scene("court-intrigue"):
            d = self.one("[GM]: the heirs' people", {"action": "roles", "deal": ["Mira Vale", "Theo", "Ada", "Kell"]})
            seal = d["seal"]
            self.one("[Mira Vale]: the chancellor owes me", {"action": "string", "by": "Mira Vale", "on": "Theo", "gain": 1,
                                                             "why": "the forged letter"})
            self.assertEqual(self.one("[GM]: the queen falls ill", {"action": "complicate", "what": "the queen falls ill",
                                                                    "cost": 1})["left"], 2)
            self.assertTrue(self.one("[GM]: coronation day", {"action": "roles", "reveal": True,
                                                              "expect": seal})["verified"])

    def test_pirates_the_frigate_behind(self):
        with self.scene("pirates"):
            self.one("[GM]: casks of water", {"action": "upkeep", "dice": {"fresh water": "d8"}})
            self.one("[Theo]: we drink", {"action": "use", "item": "fresh water"})
            self.one("[GM]: boarders", {"action": "foe", "name": "Navy boarders", "threat": 2, "count": 3})
            self.assertEqual(self.one("[Mira Vale]: I cut the rope", {"action": "foe", "name": "Navy boarders",
                                                                     "hit": 1})["left"], 2)
            self.one("[Mira Vale]: the treasure is ours", {"action": "vow", "owner": "Mira Vale", "name": "Find the treasure",
                                                           "rank": "hard"})

    def test_kaiju_the_gulf_rises(self):
        with self.scene("kaiju"):
            self.one("[GM]: the defence corps", {"action": "war", "unit": "Gulf Wardens", "quality": "trained"})
            d = self.one("[GM]: a week between attacks", {"action": "war", "pass": True, "why": "the week"})
            self.assertEqual((d["war_time"], d["war_pressure"]), (1, 1))
            self.one("[GM]: the spawn", {"action": "foe", "name": "Spawn", "threat": 1, "count": 4})
            self.assertEqual(self.one("[Theo]: cannon", {"action": "foe", "name": "Spawn", "hit": 2})["left"], 2)
            self.doom(0, self.one("[GM]: it surfaces again", {"action": "doom", "add": 1, "why": "the tide"}))

    def test_mafia_the_docks(self):
        with self.scene("mafia"):
            d = self.one("[GM]: the family", {"action": "roles", "deal": ["Mira Vale", "Theo", "Ada", "Kell"]})
            seal = d["seal"]
            self.one("[Theo]: I owe the old man", {"action": "string", "by": "Theo", "on": "Mira Vale", "gain": 1,
                                                   "why": "he paid my debt"})
            d = self.one("[GM]: the shooting at the market", {"action": "crew_heat", "job": "loud", "high_profile": True})
            self.assertEqual((d["added"], self.value("party", "crew_heat")), (5, 5))
            self.assertTrue(self.one("[GM]: who talked", {"action": "roles", "reveal": True, "expect": seal})["verified"])


class EveryGenreAndModuleHasAScene(unittest.TestCase):
    def test_coverage(self):
        names = {n[len("test_"):].split("_")[0] for n in dir(GenreScene) if n.startswith("test_")}
        ids = {g.split("-")[0] for g in genres.catalog()}
        self.assertEqual(names, ids)
        played = {m for g in genres.catalog() for m in genres.load(g)["modules"]} | set(EXTRA.values())
        self.assertEqual(played, set(modules.catalog()))



class ReleaseVersionOrder(unittest.TestCase):
    """2.0.0-alpha follows the unpublished 2.0.0-alpha.1 groundwork; semver still sorts it first (alpha < alpha.1)."""

    def test_alpha_sorts_as_semver(self):
        import campaign_version
        import update_skill
        order = ["1.8.6", "2.0.0-alpha", "2.0.0-alpha.1", "2.0.0-alpha.2", "2.0.0-beta", "2.0.0"]
        self.assertEqual(sorted(reversed(order), key=campaign_version.vkey), order)
        self.assertTrue(update_skill._is_newer("2.0.0-alpha", "1.8.6"))
        self.assertFalse(update_skill._is_newer("2.0.0-alpha", "2.0.0-alpha.1"))
        self.assertTrue(update_skill._is_newer("2.0.0", "2.0.0-alpha"))
        self.assertFalse(update_skill._is_newer("2.0.0-alpha", "2.0.0-alpha"))


if __name__ == "__main__":
    unittest.main()
