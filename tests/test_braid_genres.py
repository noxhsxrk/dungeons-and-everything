"""Braid PR 7: genre presets (data/genres), mixing (genres.py), the `modules` and `claims` dials, /dne new wiring.

Acceptance (plan §5 PR 7): a static check that takes any genre set and says what fits and what clashes; every single
genre, every pair and 50 seeded random sets of 3-5 genres each build a real campaign through campaign_init (the
preset's flags in the seed) that plays a first engine turn: modules applied to a PC from sheet.py, then a roll on the
ladder; a mystery thread's skeleton goes in as the engine's case. The campaigns are built in worker processes (one
temp root per campaign) so the ~220 builds stay within a few seconds of wall time."""
from __future__ import annotations

import concurrent.futures
import contextlib
import io
import itertools
import json
import multiprocessing
import os
import pathlib
import random
import re
import sys
import tempfile
import traceback
import unittest
import zlib

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
SCRIPTS = ROOT / "skills" / "dne" / "scripts"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(SCRIPTS))

import turn  # noqa: E402,F401  (the engine first, as the other Braid tests do)
import genres  # noqa: E402
import story_gen  # noqa: E402
from test_braid_modules import TRADE as TRADE_4  # noqa: E402
from test_braid_drama_modules import TRADE as TRADE_5  # noqa: E402

LADDER = ("critical failure", "failure", "success at a cost", "success", "critical success")
SEED = {"seed_version": 1, "campaign": "g", "system": "core", "flags": {"display": "none", "roll_mode": "auto"},
        "calendar": {"date": "1 Thaw 412", "time": "morning", "months": ["Thaw", "Bloom"], "month_length": 30}}
MIRA = ["new", "--name", "Mira Vale", "--concept", "A smuggler who owes everyone", "--drive", "Get her brother out",
        "--flaw", "Can't walk away from a bet", "--approaches", "wits=2,finesse=1,heart=1,force=0,grit=-1",
        "--labels", "Smuggler: knows every back door,Ex-navy pilot"]
MIXES = 50


def _drives(ids: list):
    plots = [g for g in ids if genres.load(g)["kind"] == "plot"]
    return plots[0] if len(plots) > 1 else None


def _sets() -> list:
    ids = sorted(genres.catalog())
    rng = random.Random(7)
    mixes = [rng.sample(ids, rng.randint(3, 5)) for _ in range(MIXES)]
    return [[g] for g in ids] + [list(p) for p in itertools.combinations(ids, 2)] + mixes


def play(ids: list) -> dict:
    """Worker: one campaign for this genre set, built and played in its own temp root. Returns what the test checks
    (or the traceback)."""
    try:
        with tempfile.TemporaryDirectory() as tmp:
            os.environ.update(DNE_CAMPAIGN_ROOT=tmp, DNE_RUNTIME_DIR=str(pathlib.Path(tmp) / "rt"),
                              DNE_DISPLAY_HOST="127.0.0.1:9", DNE_OUTBOX_LOG=str(pathlib.Path(tmp) / "out.jsonl"))
            os.environ.pop("DNE_NOTE_BUDGET", None)
            (pathlib.Path(tmp) / "rt").mkdir()
            import campaign_init
            import mechanics
            import modules
            import paths
            import sheet
            import world_db as wdb
            mix = genres.combine(ids, _drives(ids))
            if mix["errors"]:
                return {"ids": ids, "error": mix["errors"]}
            seed = genres.apply_to_seed(SEED, mix)["seed"]
            built = campaign_init.build(seed)
            if not built.get("ok"):
                return {"ids": ids, "error": built}
            camp = paths.find_campaign("g")
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                if sheet.main(["-c", "g", *MIRA]):
                    return {"ids": ids, "error": "sheet.py new failed"}
            skel = story_gen.generate(mix["story_axes"], seed=zlib.crc32(",".join(ids).encode()))
            (camp / "story-skeleton.json").write_text(json.dumps(skel, ensure_ascii=False), encoding="utf-8")
            intents = [{"action": "modules", "apply": True},
                       {"action": "roll", "actor": "Mira Vale", "approach": "wits", "label": "first look"}]
            if "mystery" in mix["story_axes"]:
                intents.insert(1, {"action": "case", "skeleton": True})
            turn.begin("g", "[Mira Vale]: I look around")
            r = turn.resolve("g", intents)
            turn.finish("g", "ok")
            datas = [x.get("data") or {} for x in r.get("results") or []]
            with wdb.reader("g") as db:
                tracks = {k for (k,) in db.execute("SELECT id FROM things WHERE kind = 'track'")}
            want = {mechanics.key_of("Mira Vale" if t["owner"] == "pc" else "party", t["id"])
                    for m in mix["modules"] for t in modules.load(m)["tracks"]}
            state = (camp / "state.md").read_text(encoding="utf-8")
            return {"ids": ids, "status": r.get("status"), "errors": [d["error"] for d in datas if d.get("error")],
                    "n": len(datas), "want": len(intents), "degree": datas[-1].get("degree") if datas else None,
                    "missing_tracks": sorted(want - tracks), "on": modules.enabled("g"), "modules": mix["modules"],
                    "flag_lines": len(re.findall(r"(?m)^- modules:", state)), "skeleton_ok": skel["checked"]["ok"]}
    except Exception:
        return {"ids": ids, "error": traceback.format_exc()}


class Presets(unittest.TestCase):
    def test_every_preset_is_valid_and_matches_story_axes(self):
        cat = genres.catalog()
        self.assertEqual(set(cat), set(story_gen.genre_ids()))
        for gid in cat:
            self.assertEqual(genres.validate(gid), [], gid)
        self.assertEqual({g for g, d in cat.items() if d["early"]},
                         {"wuxia", "litrpg", "analog-horror", "competition", "survival", "thai-ghost", "thriller", "spy",
                          "post-apoc", "superhero", "western", "kids-adventure", "court-intrigue", "pirates", "kaiju",
                          "mafia", "portal-fantasy", "road-trip", "abyss-delve", "urban-occult", "magic-academy"})
        self.assertTrue(all(d["system"] == "core" for d in cat.values()))
        for kind in genres.KINDS:
            self.assertTrue(any(d["kind"] == kind for d in cat.values()), kind)

    def test_kinds_agree_with_story_axes(self):
        for gid, d in genres.catalog().items():
            self.assertEqual(d["kind"], story_gen.load_genre(gid)["kind"], gid)

    def test_no_trade_names(self):
        for path in [*sorted(genres.DIR.glob("*.json")), *sorted(story_gen.axes_dir().glob("*.json"))]:
            text = path.read_text(encoding="utf-8")
            self.assertEqual([t for t in TRADE_4 + TRADE_5 + [r"(?i)kids on bikes", r"(?i)groundhog"]
                              if re.search(t, text)], [], path.name)

    def test_presets_never_write_content(self):
        for gid, d in genres.catalog().items():
            self.assertFalse({"content", "romance"} & set(d["dials"]), gid)
        mix = genres.combine(["horror"])
        self.assertEqual(mix["suggest"]["content"], "18")
        self.assertFalse(any(line.startswith("- content") for line in genres.flag_lines(mix)))


class Mixing(unittest.TestCase):
    def test_first_genre_wins_single_values_and_every_conflict_is_named(self):
        mix = genres.combine("mystery,horror,cozy")
        self.assertEqual(mix["errors"], [])
        self.assertEqual(mix["dials"]["storyteller"], "noir")
        c = next(c for c in mix["conflicts"] if c["field"] == "dials.storyteller")
        self.assertEqual((c["chosen"], c["from"], c["others"]), ("noir", "mystery", {"horror": "dread", "cozy": "banter"}))
        self.assertIn("suggest.content", [c["field"] for c in mix["conflicts"]])
        self.assertEqual(mix["modules"], ["clues", "gm_budget", "composure", "seasons", "strings"])   # union, in order
        self.assertNotIn("clues", mix["optional"])
        self.assertEqual(genres.combine("cozy,mystery")["dials"]["storyteller"], "banter")

    def test_clues_without_mystery_adds_the_mystery_thread(self):
        self.assertEqual(genres.combine("thai-ghost")["story_axes"], ["thai-ghost", "mystery"])
        self.assertEqual(genres.combine("mystery,thai-ghost")["story_axes"], ["mystery", "thai-ghost"])
        self.assertEqual(genres.combine("western")["story_axes"], ["western"])
        mix = genres.combine("thai-ghost")
        skel = story_gen.generate(mix["story_axes"], seed=4, record=False, drives=mix["story_drives"])
        self.assertTrue(next(t for t in skel["threads"] if t["genre"] == "mystery").get("case"))
        self.assertEqual(skel["drives"], "thai-ghost")                   # the ghost story leads; the case is inside it
        self.assertIn("--drives thai-ghost", genres._report(mix))
        self.assertNotIn("story_drives", genres.combine("thriller"))      # a plot genre already drives

    def test_list_survives_a_preset_without_fits(self):
        from contextlib import redirect_stdout
        from unittest import mock
        bad = {**genres.load("western")}
        bad.pop("fits")
        with mock.patch.object(genres, "catalog", return_value={"western": bad}), redirect_stdout(io.StringIO()) as out:
            self.assertEqual(genres.main(["list"]), 0)
        self.assertIn("fits ?", out.getvalue())
        with mock.patch.object(genres, "load", return_value={**bad, "fits": []}):
            self.assertTrue(any(p.startswith("fits:") for p in genres.validate("western")))

    def test_two_plot_genres_must_choose_a_driver(self):
        mix = genres.combine("horror,heist,war")
        self.assertTrue(any("only one drives" in e for e in mix["errors"]), mix["errors"])
        mix = genres.combine("horror,heist,war", drives="war")
        self.assertEqual(mix["errors"], [])
        # horror's clues bring a mystery thread to build the case
        self.assertEqual((mix["drives"], mix["story_axes"]), ("war", ["horror", "war", "heist", "mystery"]))
        skel = story_gen.generate(mix["story_axes"], seed=3, record=False)
        self.assertEqual(skel["drives"], "war")
        self.assertTrue(genres.combine("horror,heist,war", drives="horror")["errors"])     # not a plot genre

    def test_module_conflicts_and_requires_come_from_modules_py(self):
        mix = genres.combine("cozy", sets=["modules=make_the_case, clues"])
        self.assertIn("clues and make_the_case conflict: pick one", mix["errors"])
        mix = genres.combine("heist", sets=["modules=engagement,heat"])
        self.assertTrue(any("requires position_effect" in e for e in mix["errors"]), mix["errors"])
        big = genres.combine("slasher,heist,wuxia,romance,cozy")
        self.assertGreater(len(big["modules"]), 8)
        self.assertTrue(any("more than 8" in w for w in big["warnings"]), big["warnings"])
        self.assertTrue(any(w.startswith("wuxia: early") for w in big["warnings"]))

    def test_bad_input(self):
        for bad in ("", "mystery,mystery", "a,b,c,d,e,f", "nosuch", "../x"):
            with self.assertRaises(ValueError, msg=bad):
                genres.combine(bad)
        with self.assertRaises(ValueError):
            genres.combine("mystery", sets=["claims=sometimes"])

    def test_static_check_cli_names_what_clashes(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = genres.main(["combine", "horror,heist,war"])
        self.assertEqual(code, 1)
        self.assertIn("CONFLICT dials.storyteller: dread (from horror)", out.getvalue())
        self.assertIn("heist, war are plot genres", out.getvalue())
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(genres.main(["combine", "horror,heist,war", "--drives", "war"]), 0)
            self.assertEqual(genres.main(["combine", "cozy", "--set", "modules=clues,make_the_case"]), 1)
            self.assertEqual(genres.main(["combine", "nosuch"]), 2)

    def test_every_pair_and_mix_is_statically_compatible(self):
        for ids in _sets():
            mix = genres.combine(ids, _drives(ids))
            self.assertEqual(mix["errors"], [], ids)


class Apply(unittest.TestCase):
    def test_seed_gets_flags_system_and_kit_genre(self):
        seed = {**SEED, "flags": {**SEED["flags"], "pacing": "adventure"}, "worldkit": {"_meta": {"name": "x"}}}
        done = genres.apply_to_seed(seed, genres.combine("horror,mystery"))
        s = done["seed"]
        self.assertEqual(s["system"], "core")
        self.assertEqual(s["flags"]["modules"], "composure, clues, gm_budget")
        self.assertEqual((s["flags"]["claims"], s["flags"]["pacing"]), ("grounded", "adventure"))   # the table's answer stays
        self.assertEqual(done["kept"], {"pacing": "adventure"})
        over = genres.apply_to_seed(seed, genres.combine("horror,mystery", sets=["pacing=mixed"]))["seed"]
        self.assertEqual(over["flags"]["pacing"], "mixed")                          # unless the players changed it
        self.assertEqual(s["worldkit"]["_meta"]["genre"], ["horror", "mystery"])
        self.assertNotIn("content", s["flags"])
        self.assertEqual(seed["flags"]["pacing"], "adventure")                       # the input is not changed
        for five in ({**SEED, "system": "d20"}, {k: v for k, v in SEED.items() if k != "system"}):  # none = d20
            d20 = genres.apply_to_seed({**five, "ruleset": "2014"}, genres.combine("fantasy"))["seed"]
            self.assertNotIn("modules", d20["flags"])
            self.assertNotIn("when_down", d20["flags"])                 # death saves stay as in 5e
            self.assertEqual(d20["flags"]["storyteller"], "pulp")
            self.assertEqual(d20.get("system", "d20"), "d20")

    def test_cli_seed_file_and_existing_campaign(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "seed.json"
            path.write_text(json.dumps(SEED), encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(genres.main(["apply", "romance", "--set", "claims=open", "--seed", str(path)]), 0)
            flags = json.loads(path.read_text(encoding="utf-8"))["flags"]
            self.assertEqual((flags["modules"], flags["claims"]), ("strings, emotions", "open"))
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(genres.main(["apply", "heist,war", "--seed", str(path)]), 1)   # no driver: nothing written
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["flags"]["modules"], "strings, emotions")


class Flags(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)
        self._saved = {k: os.environ.get(k) for k in ("DNE_CAMPAIGN_ROOT", "DNE_RUNTIME_DIR", "DNE_DISPLAY_HOST", "DNE_OUTBOX_LOG")}
        os.environ.update(DNE_CAMPAIGN_ROOT=str(self.root), DNE_RUNTIME_DIR=str(self.root / "rt"),
                          DNE_DISPLAY_HOST="127.0.0.1:9", DNE_OUTBOX_LOG=str(self.root / "out.jsonl"))
        (self.root / "rt").mkdir()

    def tearDown(self):
        for k, v in self._saved.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        self._tmp.cleanup()

    def test_new_worlds_carry_both_dials_once_and_old_ones_are_told(self):
        import campaign_init
        import campaign_version
        import modules
        import paths
        self.assertEqual((campaign_version.FLAGS["modules"], campaign_version.FLAGS["claims"]), ("(none)", "grounded"))
        self.assertTrue({"modules", "claims"} <= campaign_init.KNOWN_FLAGS)
        for name, seed in (("five", {**SEED, "campaign": "five", "system": "d20"}),
                           ("braid", genres.apply_to_seed({**SEED, "campaign": "braid"}, genres.combine("heist"))["seed"])):
            built = campaign_init.build(seed)
            self.assertTrue(built["ok"], built)
            self.assertEqual(built["warnings"], [])
            state = (paths.find_campaign(name) / "state.md").read_text(encoding="utf-8")
            self.assertEqual(len(re.findall(r"(?m)^- modules:", state)), 1, name)
            self.assertEqual(len(re.findall(r"(?m)^- claims:", state)), 1, name)
            self.assertFalse([t for t in campaign_version.audit(name) if "Session Flags" in t], name)
        self.assertEqual(modules.enabled("five"), [])
        self.assertEqual(modules.enabled("braid"), ["position_effect", "engagement", "heat"])
        state = paths.find_campaign("five") / "state.md"
        state.write_text(re.sub(r"(?m)^- (claims|modules):.*\n", "", state.read_text(encoding="utf-8")), encoding="utf-8")
        todo = campaign_version.audit("five")
        self.assertIn("state.md Session Flags: add `- claims: grounded` (ask the table)", todo)
        self.assertIn("state.md Session Flags: add `- modules: (none)`", todo)

    def test_setup_page_lists_claims_and_never_a_genre_menu(self):
        page = (ROOT / "skills" / "dne" / "display" / "setup.html").read_text(encoding="utf-8")
        for v in genres.DIALS["claims"]:
            self.assertIn(f'["{v}", ', page)
        self.assertNotIn('name="genre"', page)                    # players describe the story; the GM matches presets
        self.assertIn('name="modules"', page)

    def test_worldkit_show_prints_a_braid_kit(self):
        import worldkit
        kit = {"_meta": {"name": "Ford", "genre": ["mystery"]},
               "labels": [{"name": "Smuggler", "description": "knows every back door"}],
               "equipment": [{"name": "Forged papers"}],
               "threats": [{"name": "Toll Guard", "threat": 2, "moves": ["blows the whistle"]}]}
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            worldkit.show(kit, "core")
        text = out.getvalue()
        for want in ("Smuggler: knows every back door", "Forged papers", "Toll Guard: threat 2; moves: blows the whistle"):
            self.assertIn(want, text)
        self.assertNotIn("Classes", text)


class SkeletonCase(Flags):
    def test_a_checked_skeleton_is_accepted_by_case(self):
        """story_gen `check` and table.py `case` run the same 1000 trials for a skeleton: seed 5036's case passes
        check at its own seed but would fail a re-check at other trials (94.5%), so `case` must use the skeleton's."""
        import campaign_init
        import copy
        import paths
        self.assertTrue(campaign_init.build(genres.apply_to_seed(SEED, genres.combine("mystery"))["seed"])["ok"])
        skel = story_gen.generate(["mystery"], seed=5036)
        self.assertTrue(skel["checked"]["ok"])
        case = skel["threads"][0]["case"]
        self.assertFalse(story_gen.check_case(copy.deepcopy(case), case["id"])["ok"])       # other trials: fragile
        (paths.find_campaign("g") / "story-skeleton.json").write_text(json.dumps(skel), encoding="utf-8")
        turn.begin("g", "setup")
        r = turn.resolve("g", [{"action": "case", "skeleton": True}])
        turn.finish("g", "ok")
        self.assertNotIn("error", r["results"][0]["data"], r["results"][0]["data"])


class GuardReadsStoryHistory(Flags):
    def test_flesh_picks_count_for_braid_only(self):
        import story
        from unittest import mock
        texts = ["The gulls wheel over the salt flats.", "Rain on the salt flats again.", "Nobody speaks."]
        picks = ["Wind over the salt flats at dusk.", "A dead lamp over the salt flats."]
        (self.root / "story-history.jsonl").write_text(
            "".join(json.dumps({"kind": "flesh", "text": p}) + "\n" for p in picks), encoding="utf-8")
        with mock.patch.object(story, "narrations", return_value=texts), \
                mock.patch.object(story, "_names", return_value=set()), \
                mock.patch.object(story, "_player_words", return_value=""):
            with mock.patch.object(story.paths, "campaign_system", return_value="core"):
                notes = " ".join(story.guard("x"))
                self.assertIn("\"the salt flats\"", notes)
                self.assertIn("earlier stories", notes)
            with mock.patch.object(story.paths, "campaign_system", return_value="d20"):
                self.assertNotIn("salt", " ".join(story.guard("x")))


class EveryMixPlays(unittest.TestCase):
    """The acceptance: every single genre, every pair and 50 random 3-5 mixes build and play a first turn."""

    def test_singles_pairs_and_random_mixes(self):
        jobs = _sets()
        n = len(genres.catalog())
        self.assertEqual(len(jobs), n + n * (n - 1) // 2 + MIXES)
        ctx = multiprocessing.get_context("spawn")
        with concurrent.futures.ProcessPoolExecutor(max_workers=min(8, os.cpu_count() or 2), mp_context=ctx) as pool:
            results = list(pool.map(play, jobs, chunksize=4))
        bad = [r for r in results if r.get("error") or r["errors"] or r["n"] != r["want"] or r["degree"] not in LADDER
               or r["missing_tracks"] or r["on"] != r["modules"] or r["flag_lines"] != 1 or not r["skeleton_ok"]]
        self.assertEqual(bad, [], json.dumps(bad[:3], indent=1, default=str))
        self.assertTrue(all(r["on"] for r in results))                       # every preset switches modules on
        self.assertGreater(sum(1 for r in results if "clues" in r["on"]), 20)


if __name__ == "__main__":
    unittest.main()
