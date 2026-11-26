"""
test_braid_pr10_storygen.py — PR 10 story generator fixes from the AI-GM playtests: `axes`, prose facts in `check`,
campaign places and NPC names in the case, the clue brief and cheaper fleshing, setting bans, re-rolls and history.

Run from repo root:
    python3 -m unittest tests.test_braid_pr10_storygen -v
"""
import contextlib
import io
import json
import os
import pathlib
import sys
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "skills" / "dne" / "scripts"))

import story_gen as sg  # noqa: E402


class _Root(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)
        self._old = os.environ.get("DNE_CAMPAIGN_ROOT")
        os.environ["DNE_CAMPAIGN_ROOT"] = str(self.root)
        self.file = str(self.root / "s.json")

    def tearDown(self):
        if self._old is None:
            os.environ.pop("DNE_CAMPAIGN_ROOT", None)
        else:
            os.environ["DNE_CAMPAIGN_ROOT"] = self._old
        self._tmp.cleanup()

    def cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            rc = sg.main(list(argv))
        return rc, out.getvalue()

    def history(self):
        path = self.root / "story-history.jsonl"
        return path.read_text(encoding="utf-8").splitlines() if path.is_file() else []


class Axes(_Root):
    def test_lists_pinnable_axes_and_values(self):
        rc, out = self.cli("axes", "mystery,wuxia")
        self.assertEqual(rc, 0)
        self.assertIn("mystery.crime: a killing | a theft", out)
        self.assertIn("wuxia.sect:", out)
        self.assertIn("leaves out: radio", out)


class ProseFacts(_Root):
    def test_a_fact_quoting_another_axis_value_fails_check(self):
        skel = sg.generate(["mystery"], 5, facts=["mystery.crime=a killing"], record=False)
        self.assertTrue(skel["checked"]["ok"])
        skel["facts"].append("It was a theft, everyone says so")
        self.assertTrue(sg.check(skel)["ok"])                       # pinned: the prose does not override a pin
        skel["facts"] = ["It was a theft, everyone says so"]
        rep = sg.check(skel)
        self.assertFalse(rep["ok"])
        self.assertIn('pin it with "mystery.crime=a theft"', " ".join(rep["threads"]["mystery"]["problems"]))
        skel["facts"] = ["The town is called Saltmere", "a killing, some say a theft"]   # the rolled value is named too
        self.assertTrue(sg.check(skel)["ok"])


class Campaign(_Root):
    def camp(self, places, npcs):
        camp = self.root / "campaigns" / "lom"
        camp.mkdir(parents=True)
        keys = {f"p{i}": {"name": n} for i, n in enumerate(places)}
        (camp / "world-map.json").write_text(json.dumps({"party_location": "p0", "places": keys}), encoding="utf-8")
        rows = "".join(f"| {n} | fisher | | | | |\n" for n in npcs)
        (camp / "npcs.md").write_text("| Name | Role | Faction | Location | Attitude | Notes |\n|--|--|--|--|--|--|\n"
                                      + rows, encoding="utf-8")
        return camp

    def test_places_come_from_the_map_and_suspects_from_the_npcs(self):
        places = ["Pier", "Boat shed", "Shrine", "Ice factory", "Headman's house", "Market"]
        npcs = ["Lung Chuan", "Mae Noi", "Bang Sak", "Headman Thong", "Uncle Pom"]
        camp = self.camp(places, npcs)
        rc, _ = self.cli("-c", "lom", "skeleton", "--genre", "mystery", "--seed", "11")
        self.assertEqual(rc, 0)
        case = json.loads((camp / "story-skeleton.json").read_text(encoding="utf-8"))["threads"][0]["case"]
        self.assertEqual(case["places"][0], "Pier")                 # the trail starts where the party is
        self.assertTrue(set(case["places"]) <= set(places))
        for c in case["clues"]:
            self.assertIn(c["where"], case["places"])
            if c.get("leads"):
                self.assertIn(c["leads"], case["places"])
            self.assertIn(f" at {c['where']}:", c["text"])           # the stand-in names the new place
        self.assertTrue(all(s.get("name") in npcs for s in case["suspects"]))
        culprit = next(s for s in case["suspects"] if s["id"] == case["culprit"])
        self.assertIn(f"({culprit['id']}, {culprit['name']})", case["truth"])
        self.assertTrue(sg.check_case(case, case["id"])["ok"])

    def test_a_small_map_maps_what_it_can_and_name_fixes_the_rest(self):
        camp = self.camp(["The Ford"], ["Jonas"])
        self.assertEqual(self.cli("-c", "lom", "skeleton", "--genre", "mystery", "--seed", "3")[0], 0)
        path = camp / "story-skeleton.json"
        case = json.loads(path.read_text(encoding="utf-8"))["threads"][0]["case"]
        self.assertEqual(case["places"][0], "The Ford")
        self.assertEqual([s.get("name") for s in case["suspects"]].count("Jonas"), 1)
        other = case["places"][1]
        unnamed = next(s["id"] for s in case["suspects"] if not s.get("name"))
        self.assertEqual(self.cli("-c", "lom", "name", other, "Boat shed")[0], 0)
        self.assertEqual(self.cli("-c", "lom", "name", unnamed, "Mae Noi")[0], 0)
        case = json.loads(path.read_text(encoding="utf-8"))["threads"][0]["case"]
        self.assertIn("Boat shed", case["places"])
        self.assertNotIn(other, [c["where"] for c in case["clues"]] + [c.get("leads") for c in case["clues"]])
        self.assertEqual(next(s for s in case["suspects"] if s["id"] == unnamed)["name"], "Mae Noi")
        self.assertEqual(self.cli("-c", "lom", "check")[0], 0)
        self.assertEqual(self.cli("-c", "lom", "name", "s99", "X")[0], 2)


class FleshFlow(_Root):
    def test_clue_brief_says_the_job_and_hidden_clues_take_fewer_candidates(self):
        self.assertEqual(self.cli("--file", self.file, "skeleton", "--genre", "mystery", "--seed", "5")[0], 0)
        case = json.loads(pathlib.Path(self.file).read_text(encoding="utf-8"))["threads"][0]["case"]
        core = next(c for c in case["clues"] if c["obvious"])
        hidden = next(c for c in case["clues"] if not c["obvious"])
        brief = json.loads(self.cli("--file", self.file, "flesh", "--slot", f"clue:{core['id']}")[1])
        self.assertEqual(brief["clue"]["proves"], core["proves"])
        self.assertIn(f"Found at {core['where']}", brief["job"])
        self.assertIn("vary the detail, not the job", brief["job"])
        self.assertEqual(len(brief["suspects"]), len(case["suspects"]))
        self.assertTrue(brief["write"].startswith("exactly 5"))
        self.assertTrue(json.loads(self.cli("--file", self.file, "flesh", "--slot",
                                            f"clue:{hidden['id']}")[1])["write"].startswith("1 to 5"))
        skel = json.loads(pathlib.Path(self.file).read_text(encoding="utf-8"))
        sg.flesh(skel, f"clue:{hidden['id']}", [{"text": "A wet rope coiled the wrong way.", "p": 0.05}], record=False)
        with self.assertRaises(ValueError):
            sg.flesh(skel, f"clue:{core['id']}", [{"text": "One is not enough here.", "p": 0.05}], record=False)

    def test_fill_writes_every_hidden_clue_and_leaves_core_ones(self):
        self.cli("--file", self.file, "skeleton", "--genre", "mystery", "--seed", "8")
        rc, out = self.cli("--file", self.file, "fill")
        self.assertEqual(rc, 0)
        got = json.loads(out)
        skel = json.loads(pathlib.Path(self.file).read_text(encoding="utf-8"))
        case = skel["threads"][0]["case"]
        self.assertEqual(sorted(got["still_unwritten"]), sorted(c["id"] for c in case["clues"] if c["obvious"]))
        culprit = next(s for s in case["suspects"] if s["id"] == case["culprit"])
        for c in case["clues"]:
            if c["id"] in got["filled"] and c["proves"] == "who":
                self.assertIn(culprit["role"], c["text"])
            if c["id"] in got["filled"] and c["proves"].startswith("clears:"):
                self.assertNotIn(culprit["role"], c["text"])
        self.assertEqual(self.cli("--file", self.file, "check")[0], 0)


class SettingBans(_Root):
    def test_era_bans_share_one_vocabulary_and_can_be_mixed(self):
        mixed = sg.tables_for(["western", "analog-horror"])
        flat = json.dumps(mixed["analog-horror"])
        for word in ("unlabelled tapes", "voicemail inbox", "the recording addresses"):
            self.assertNotIn(word, flat)
        self.assertIn("unlabelled tapes", json.dumps(sg.tables_for(["western", "analog-horror"], mix_eras=True)))
        kept = json.dumps(sg.tables_for(["pirates", "magic-academy", "abyss-delve"]))
        for word in ("train war-casters", "ancient engine", "electric eels"):   # verbs and natural words survive
            self.assertIn(word, kept)
        self.assertTrue(sg._mentions("two cars", ["car"]) and not sg._mentions("a cart", ["car"]))
        skel = sg.generate(["pirates", "analog-horror"], 7, record=False, mix_eras=True)
        self.assertTrue(skel["mix_eras"])

    def test_a_wuxia_siege_never_rolls_a_radio(self):
        for seed in range(150):
            skel = sg.generate(["war", "wuxia", "traitor"], seed, record=False)
            text = json.dumps(skel["threads"]).casefold()
            for word in ("radio", "guns", "data on a machine"):
                self.assertNotIn(word, text, seed)
        hits = sum("radio" in json.dumps(sg.generate(["war", "traitor"], s, record=False)["threads"]) for s in range(150))
        self.assertGreater(hits, 0)                                 # without the setting the radio can come up

    def test_a_pin_still_wins_and_mystery_pools_are_filtered(self):
        skel = sg.generate(["traitor", "fantasy"], 1, facts=["traitor.channel=a radio frequency"], record=False)
        self.assertEqual(skel["threads"][0]["axes"]["channel"], "a radio frequency")
        for seed in range(60):
            case = sg.generate(["mystery", "wuxia"], seed, record=False)["threads"][0]["case"]
            self.assertNotIn("the stables or garage", case["places"])


class Rerolls(_Root):
    def test_a_reroll_before_flesh_replaces_the_discarded_line(self):
        self.cli("--file", self.file, "skeleton", "--genre", "heist", "--seed", "1")
        self.cli("--file", self.file, "skeleton", "--genre", "heist", "--seed", "2")
        self.cli("--file", self.file, "skeleton", "--genre", "heist", "--seed", "3")
        lines = [json.loads(ln) for ln in self.history()]
        self.assertEqual([r["seed"] for r in lines], [3])
        self.cli("--file", self.file, "flesh", "--slot", "premise", "--candidates",
                 json.dumps([{"text": f"An odd premise number {i}", "p": 0.05} for i in range(5)]))
        self.cli("--file", self.file, "skeleton", "--genre", "heist", "--seed", "4")   # fleshed: the old one stays
        self.assertEqual([json.loads(ln).get("seed") for ln in self.history()], [3, 3, 4])

    def test_an_older_line_is_never_removed(self):
        self.cli("--file", self.file, "skeleton", "--genre", "heist", "--seed", "1")
        other = str(self.root / "other.json")
        self.cli("--file", other, "skeleton", "--genre", "heist", "--seed", "9")   # another campaign rolled since
        self.cli("--file", self.file, "skeleton", "--genre", "heist", "--seed", "2")
        self.assertEqual([json.loads(ln)["seed"] for ln in self.history()], [1, 9, 2])


if __name__ == "__main__":
    unittest.main()
