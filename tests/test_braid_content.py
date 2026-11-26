"""The genre-tagged content library (data/content.json, content.py): every genre has enough to start a World Kit,
a mix draws from the union of its tags with the main genre first, era bans hold, and the output is a valid kit."""
from __future__ import annotations

import contextlib
import io
import json
import pathlib
import re
import sys
import unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "skills" / "dne" / "scripts"))
sys.path.insert(0, str(HERE))
import content  # noqa: E402
import story_gen  # noqa: E402
import worldkit  # noqa: E402
from test_braid_drama_modules import TRADE as TRADE_5  # noqa: E402
from test_braid_modules import TRADE as TRADE_4  # noqa: E402


class Library(unittest.TestCase):
    def test_every_genre_can_start_a_kit(self):
        for g in story_gen.genre_ids():
            parts = content.for_mix([g])
            with self.subTest(g):
                self.assertGreaterEqual(len(parts["labels"]), 2)
                self.assertGreaterEqual(len(parts["equipment"]), 1)
                self.assertGreaterEqual(len(parts["threats"]), 2)
                self.assertEqual(worldkit.validate_braid({"_meta": {"name": g}, **parts}), [])

    def test_tags_are_genres_and_names_are_unique(self):
        known, lib = set(story_gen.genre_ids()), content.library()
        for kind in content.KINDS:
            names = [e["name"] for e in lib[kind]]
            self.assertEqual(len(names), len(set(names)), kind)
            for e in lib[kind]:
                self.assertTrue(e["tags"] and set(e["tags"]) <= known, (kind, e["name"], e["tags"]))

    def test_a_mix_is_the_union_with_the_main_genre_first(self):
        parts = content.for_mix(["western", "horror"])
        tags = {e["name"]: e["tags"] for e in content.library()["labels"]}
        firsts = [("western" in tags[e["name"]]) for e in parts["labels"]]
        self.assertEqual(firsts, sorted(firsts, reverse=True))             # every western label before the horror ones
        self.assertIn("Sceptic", [e["name"] for e in parts["labels"]])
        self.assertNotIn("tags", parts["labels"][0])                       # kit-shaped

    def test_era_bans_hold_unless_eras_are_mixed(self):
        names = lambda parts: [e["name"] for e in parts["labels"]]   # noqa: E731
        self.assertNotIn("Radio operator", names(content.for_mix(["western", "war"])))
        self.assertIn("Radio operator", names(content.for_mix(["western", "war"], mix_eras=True)))
        self.assertNotIn("Car keys that might work", [e["name"] for e in content.for_mix(["fantasy", "slasher"])["equipment"]])

    def test_no_trade_names(self):
        text = (content.paths.data_dir() / "content.json").read_text(encoding="utf-8")
        self.assertEqual([t for t in TRADE_4 + TRADE_5 + [r"(?i)kids on bikes", r"(?i)groundhog"] if re.search(t, text)], [])

    def test_cli(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(content.main(["pirates,cozy", "--kind", "threats"]), 0)
        self.assertEqual(json.loads(out.getvalue())[0]["name"], "Navy frigate")
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(content.main(["nope"]), 2)


if __name__ == "__main__":
    unittest.main()
