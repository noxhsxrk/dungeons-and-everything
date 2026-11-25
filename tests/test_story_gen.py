"""
test_story_gen.py — the story generator (plan §4, PR 8): axes, history, flesh, validators.

Run from repo root:
    python3 -m unittest tests.test_story_gen -v
"""
import contextlib
import io
import itertools
import json
import os
import pathlib
import random
import sys
import tempfile
import unittest
from collections import Counter

REPO = pathlib.Path(__file__).resolve().parent.parent
SKILL = REPO / "skills" / "dne" if (REPO / "skills" / "dne").is_dir() else REPO
sys.path.insert(0, str(SKILL / "scripts"))

import story_gen as sg  # noqa: E402


class _Root(unittest.TestCase):
    """Every test gets its own campaign root, so the real ~/.dne history is never read or written."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)
        self._old = os.environ.get("DNE_CAMPAIGN_ROOT")
        os.environ["DNE_CAMPAIGN_ROOT"] = str(self.root)

    def tearDown(self):
        if self._old is None:
            os.environ.pop("DNE_CAMPAIGN_ROOT", None)
        else:
            os.environ["DNE_CAMPAIGN_ROOT"] = self._old
        self._tmp.cleanup()

    def thread(self, skel, gid):
        return next(t for t in skel["threads"] if t["genre"] == gid)


class Acceptance(_Root):
    """The plan's 'ผ่านเมื่อ' line for PR 8."""

    def test_every_genre_has_a_real_table(self):
        ids = sg.genre_ids()
        for gid in ("mystery", "horror", "romance", "heist", "war", "competition", "cozy", "comedy", "fantasy",
                    "sci-fi", "space-opera", "wuxia", "litrpg", "historical", "timeloop", "traitor", "slasher",
                    "analog-horror"):
            self.assertIn(gid, ids)
        for gid in ids:
            table = sg.load_genre(gid)
            self.assertIn(table["kind"], sg.KINDS, gid)
            self.assertGreaterEqual(len(table["axes"]), 5, gid)   # fewer axes would make "≤3 shared" vacuous
            self.assertTrue(all(len(v) >= 6 for v in table["axes"].values()), gid)

    def test_hundred_seeds_no_pair_shares_more_than_three_axes(self):
        for gid in sg.genre_ids():
            skels = [sg.generate([gid], 7000 + s) for s in range(100)]
            axes = [self.thread(k, gid)["axes"] for k in skels]
            worst = max(sg.overlap(a, b) for a, b in itertools.combinations(axes, 2))
            self.assertLessEqual(worst, 3, gid)
            self.assertTrue(all(k["checked"]["ok"] for k in skels), gid)

    def test_every_generated_mystery_passes_the_validator(self):
        for s in range(100):
            skel = sg.generate(["mystery"], 300 + s)
            case = self.thread(skel, "mystery")["case"]
            report = sg.check_case(case, skel["seed"])          # independent re-check of the stored case
            self.assertTrue(report["ok"], (s, report["problems"]))
            self.assertGreaterEqual(report["solve_rate"], sg.SOLVE_RATE)
            for clue in case["clues"]:                          # table.py `case` can take it as is
                self.assertEqual({"id", "text", "where", "obvious"} - set(clue), set())
                self.assertIsInstance(clue["obvious"], bool)
                self.assertIn(clue["where"], case["places"])
                self.assertNotIn(clue["proves"], clue["text"])  # the player's text never says what it proves

    def test_mixed_genres_pass_every_validator(self):
        for s in range(30):
            skel = sg.generate(["war", "mystery", "horror"], 900 + s)
            self.assertEqual(skel["drives"], "war")
            self.assertEqual([t["role"] for t in skel["threads"]], ["drives", "sub-thread", "sub-thread"])
            self.assertEqual(set(skel["checked"]["threads"]), {"war", "mystery", "horror"})
            self.assertTrue(skel["checked"]["ok"], skel["checked"])
            self.assertGreaterEqual(len(self.thread(skel, "horror")["ladder"]), 3)
        rng = random.Random(5)
        for s in range(40):
            combo = rng.sample(sg.genre_ids(), rng.randint(3, 5))
            skel = sg.generate(combo, 2000 + s)
            self.assertTrue(skel["checked"]["ok"], (combo, skel["checked"]))
            plots = [g for g in combo if sg.load_genre(g)["kind"] == "plot"]
            self.assertEqual(skel["drives"], plots[0] if plots else combo[0])

    def test_same_seed_replays_identically(self):
        first = sg.generate(["mystery", "romance"], 42)
        for s in range(5):
            sg.generate(["mystery", "romance"], s)
        again = sg.generate(["mystery", "romance"], 42, history_at=first["history_at"], record=False)
        self.assertEqual(again, first)
        lines = (self.root / "story-history.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 6)                         # the replay recorded nothing
        self.assertEqual(json.loads(lines[0])["seed"], 42)

    def test_history_down_weighting_reduces_repeats(self):
        table = sg.load_genre("mystery")
        recent = [{"culprit": "the quiet servant"}] * 3
        fresh = Counter(sg.roll_axes(random.Random(i), table, [], {})["culprit"] for i in range(3000))
        tired = Counter(sg.roll_axes(random.Random(i), table, recent, {})["culprit"] for i in range(3000))
        self.assertLess(tired["the quiet servant"], fresh["the quiet servant"] * 0.2)   # 0.3³ ≈ 0.03 in theory
        twist = Counter(sg.roll_axes(random.Random(i), table, [{"twist": table["axes"]["twist"][0]["v"]}] * 10, {})["twist"]
                        for i in range(3000))
        self.assertGreater(twist[table["axes"]["twist"][0]["v"]] / 3000, 0.5)   # "no twist" is exempt, stays ~60%

        # end to end: decay and the >3-shared gate together (the roll_axes half above isolates decay)
        def repeats(record):
            seen, hits = [], 0
            for s in range(40):
                ax = self.thread(sg.generate(["heist"], 50 + s, record=record), "heist")["axes"]
                hits += sum(1 for prev in seen[-5:] for k, v in ax.items() if prev.get(k) == v)
                seen.append(ax)
            return hits
        without = repeats(False)
        with_history = repeats(True)
        self.assertLess(with_history, without * 0.8, (with_history, without))   # 103 vs 145 at these seeds


class MysteryValidator(_Root):
    def _case(self, seed=1):
        skel = sg.generate(["mystery"], seed, record=False)
        return skel, self.thread(skel, "mystery")["case"]

    def test_broken_case_fails_then_repairs(self):
        skel, case = self._case()
        culprit = case["culprit"]
        innocent = next(s for s in case["suspects"] if s["id"] != culprit)
        hows = [c for c in case["clues"] if c["proves"] == "how"]
        case["clues"] = [c for c in case["clues"] if c["proves"] != "how" or c is hows[0]]
        case["clues"] = [c for c in case["clues"] if c["proves"] != f"clears:{innocent['id']}"]
        for c in case["clues"]:
            if c["where"] == case["places"][-1]:
                c["obvious"] = False
                c.pop("leads", None)
        for c in case["clues"]:
            if c.get("leads") == case["places"][-1]:
                c.pop("leads")
        innocent.update(means=True, motive=True, opportunity=True)
        broken = sg.check_case(case, skel["seed"])
        kinds = {p[0] for p in broken["problems"]}
        self.assertFalse(broken["ok"])
        self.assertTrue({"thin", "unique", "uncleared", "no-core", "unreachable"} <= kinds, kinds)
        result = sg.check(skel)
        self.assertTrue(result["ok"], result)
        self.assertNotIn("rerolled", result["threads"]["mystery"])          # fixed by repair, not by a re-roll
        self.assertTrue(sg.check_case(case, skel["seed"])["ok"])
        self.assertEqual([s["id"] for s in case["suspects"] if s["means"] and s["motive"] and s["opportunity"]], [culprit])

    def test_fragile_case_is_shored_up(self):
        skel, case = self._case(3)
        case["clues"] = [c for c in case["clues"] if not (c.get("leads") and c["where"] != case["places"][0])]
        for c in case["clues"]:                      # one lead into each place, nothing more
            c.pop("leads", None)
        for place in case["places"][1:]:
            sg._add_clue(case, "lead", case["places"][0], leads=place)
        self.assertLess(sg.check_case(case, skel["seed"])["solve_rate"], sg.SOLVE_RATE)
        self.assertTrue(sg.check(skel)["ok"])
        self.assertGreaterEqual(sg.check_case(case, skel["seed"])["solve_rate"], sg.SOLVE_RATE)

    def test_written_case_is_never_rerolled(self):
        skel, case = self._case(6)
        cands = [{"text": f"A wax seal pressed with a thumb, version {i}.", "p": 0.05} for i in range(5)]
        got = sg.flesh(skel, f"clue:{case['clues'][0]['id']}", cands, record=False)
        self.assertEqual(case["clues"][0]["text"], got["text"])
        case["clues"][1]["where"] = "a place that is not in the case"
        result = sg.check(skel)
        self.assertFalse(result["ok"])
        self.assertNotIn("rerolled", result["threads"]["mystery"])
        self.assertEqual(self.thread(skel, "mystery")["case"]["clues"][0]["text"], got["text"])
        with self.assertRaises(ValueError):
            sg.flesh(skel, "clue:nope", cands, record=False)

    def test_unrepairable_case_is_rerolled(self):
        skel, _ = self._case(4)
        self.thread(skel, "mystery")["case"] = {"id": "case-4", "places": [], "clues": []}
        result = sg.check(skel)
        self.assertTrue(result["ok"], result)
        self.assertGreaterEqual(result["threads"]["mystery"]["rerolled"], 1)


class GenreValidators(_Root):
    def test_horror_needs_three_rising_steps(self):
        skel = sg.generate(["horror"], 1, record=False)
        self.thread(skel, "horror")["ladder"] = self.thread(skel, "horror")["ladder"][:2]
        self.assertFalse(sg.check(skel)["ok"])
        skel = sg.generate(["horror"], 1, record=False)
        ladder = self.thread(skel, "horror")["ladder"]
        ladder[0], ladder[1] = ladder[1], ladder[0]
        self.assertFalse(sg.check(skel)["ok"])

    def test_romance_needs_an_obstacle_from_a_character(self):
        skel = sg.generate(["romance"], 1, record=False)
        self.assertTrue(skel["checked"]["ok"])
        self.thread(skel, "romance")["obstacles"] = [o for o in self.thread(skel, "romance")["obstacles"]
                                                     if o["src"] != "character"]
        self.assertIn("no obstacle comes from a character", " ".join(sg.check(skel)["threads"]["romance"]["problems"]))

    def test_heist_needs_target_defences_insider_and_what_goes_wrong(self):
        skel = sg.generate(["heist"], 1, record=False)
        plan = self.thread(skel, "heist")["plan"]
        self.assertTrue(skel["checked"]["ok"])
        self.assertEqual(len(set(plan["defences"])), 2)
        plan["insider"], plan["defences"] = "", plan["defences"][:1]
        problems = sg.check(skel)["threads"]["heist"]["problems"]
        self.assertTrue(any("insider" in p for p in problems) and any("defences" in p for p in problems))

    def test_seed_facts_are_kept_and_guarded(self):
        skel = sg.generate(["mystery", "romance"], 8, facts=["mystery.culprit=the lighthouse keeper",
                                                             "obstacle=a vow to a dying mother",
                                                             "The town is called Saltmere"], record=False)
        self.assertEqual(self.thread(skel, "mystery")["axes"]["culprit"], "the lighthouse keeper")
        self.assertIn("the lighthouse keeper", self.thread(skel, "mystery")["case"]["truth"])
        self.assertEqual(self.thread(skel, "romance")["axes"]["obstacle"], "a vow to a dying mother")
        self.assertTrue(skel["checked"]["ok"])
        self.thread(skel, "mystery")["axes"]["culprit"] = "the mayor"
        self.assertFalse(sg.check(skel)["ok"])


class Flesh(_Root):
    def cands(self, *texts):
        return [{"text": t, "p": 0.05 + i * 0.01} for i, t in enumerate(texts)]

    def test_rejects_bad_candidates(self):
        skel = sg.generate(["mystery"], 1, record=False)
        with self.assertRaises(ValueError):
            sg.flesh(skel, "premise", self.cands("a", "b", "c", "d"))
        bad = self.cands("a", "b", "c", "d", "e")
        bad[0]["p"] = 0.3
        with self.assertRaises(ValueError):
            sg.flesh(skel, "premise", bad)

    def test_drops_cliches_and_recent_picks_and_picks_by_rng(self):
        skel = sg.generate(["mystery"], 1, record=False)
        texts = ["The butler did it, plainly.", "A beekeeper's ledger is missing a page.",
                 "The ferry clock was set back an hour.", "Two sisters share one alibi.", "A dog will not enter the chapel."]
        got = sg.flesh(skel, "premise", self.cands(*texts))
        self.assertIn("cliché: the butler did it", [d["why"] for d in got["dropped"]])
        self.assertIn(got["text"], texts[1:])
        again = sg.flesh(dict(skel, flesh={}), "premise", self.cands(*texts), record=False)
        self.assertNotEqual(again["text"], got["text"])        # the earlier pick is now a repeat
        self.assertTrue(any(d["why"].startswith("repeats:") for d in again["dropped"]))
        other = sg.generate(["mystery"], 1, record=False)      # same seed, fresh history → same pick
        os.remove(self.root / "story-history.jsonl")
        self.assertEqual(sg.flesh(other, "premise", self.cands(*texts), record=False)["text"], got["text"])

    def test_all_banned_is_an_error(self):
        skel = sg.generate(["horror"], 1, record=False)
        with self.assertRaises(ValueError):
            sg.flesh(skel, "premise", self.cands(*["Ancient evil awakens, part %d" % i for i in range(5)]))


class Cli(_Root):
    def run_cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = sg.main(list(argv))
        return code, out.getvalue()

    def test_four_steps_through_the_cli(self):
        f = str(self.root / "skel.json")
        self.assertEqual(self.run_cli("--file", f, "seed", "heist.target=the mayor's ledger")[0], 0)
        code, out = self.run_cli("--file", f, "skeleton", "--genre", "heist,romance", "--seed", "11")
        self.assertEqual(code, 0)
        skel = json.loads(out)
        self.assertEqual(self.thread(skel, "heist")["plan"]["target"], "the mayor's ledger")
        code, out = self.run_cli("--file", f, "flesh", "--slot", "insider")
        self.assertEqual(code, 0)
        self.assertIn("do_not_use", json.loads(out))
        cands = json.dumps([{"text": f"option {i} about a lantern", "p": 0.08} for i in range(5)])
        self.assertEqual(self.run_cli("--file", f, "flesh", "--slot", "insider", "--candidates", cands)[0], 0)
        self.assertEqual(self.run_cli("--file", f, "check")[0], 0)
        saved = json.loads(pathlib.Path(f).read_text(encoding="utf-8"))
        self.assertIn("insider", saved["flesh"])
        code, out = self.run_cli("--file", f, "skeleton", "--genre", "heist,romance", "--seed", "11",
                                 "--history-at", str(skel["history_at"]))
        self.assertEqual(json.loads(out)["threads"], skel["threads"])
        self.assertEqual(self.run_cli("--file", f, "skeleton", "--genre", "nonsense")[0], 2)


if __name__ == "__main__":
    unittest.main()
