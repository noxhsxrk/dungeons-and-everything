"""Display companion in a World Kit campaign: Thai character sheets, no DM-prep leaks in the
player codex, no SRD links where the world has no SRD."""
import importlib.util
import json
import os
import pathlib
import shutil
import sys
import tempfile
import unittest
import urllib.parse

from tests._unicode import needs_unicode_fs

ROOT = pathlib.Path(__file__).resolve().parent.parent
DISPLAY = ROOT / "skills" / "dne" / "display"
FIXTURE = ROOT / "tests" / "fixtures" / "worldkit-eden.json"


@needs_unicode_fs
class DisplayWorldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        root = pathlib.Path(cls._tmp.name)
        camp = root / "campaigns" / "eden"
        (camp / "characters").mkdir(parents=True)
        (camp / "state.md").write_text("**Ruleset:** 2014\n## Faction Moves\n- Reapers relocate the core (secret plan)\n"
                                       "## Active Quests\n- Find the oxygen thief\n", encoding="utf-8")
        (camp / "world.md").write_text("## The Mystery — Who cut the air\n- **Answer:** the Chief did it\n", encoding="utf-8")
        shutil.copy(FIXTURE, camp / "worldkit.json")
        (camp / "characters" / "ทองดี.md").write_text("# ทองดี\n", encoding="utf-8")
        (camp / "graph.json").write_text(json.dumps({"nodes": [
            {"id": "place_dock", "type": "location", "name": "Dock 9", "summary": "flooded"},
            {"id": "faction_eden", "type": "faction", "name": "EDEN", "summary": "the AI"},
            {"id": "place_core", "type": "location", "name": "Hidden Core", "tags": ["dm_only"]}], "edges": []}),
            encoding="utf-8")
        rt = root / ".rt"
        rt.mkdir()
        (rt / ".campaign").write_text("eden", encoding="utf-8")
        cls._env = {k: os.environ.get(k) for k in ("DNE_CAMPAIGN_ROOT", "DNE_RUNTIME_DIR")}
        os.environ["DNE_CAMPAIGN_ROOT"] = str(root)
        os.environ["DNE_RUNTIME_DIR"] = str(rt)
        sys.path.insert(0, str(DISPLAY))
        sys.path.insert(0, str(ROOT / "skills" / "dne" / "scripts"))
        spec = importlib.util.spec_from_file_location("dne_display_world", DISPLAY / "dne-display-app.py")
        cls.app = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.app)
        # runtime_paths may already be imported by another display test with a different runtime dir
        cls.app.CAMP_FILE = str(rt / ".campaign")
        cls.client = cls.app.app.test_client()

    @classmethod
    def tearDownClass(cls):
        for k, v in cls._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        cls._tmp.cleanup()

    def test_thai_character_sheet(self):
        r = self.client.get("/character/" + urllib.parse.quote("ทองดี"))
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        self.assertIn("ทองดี", r.get_data(as_text=True))
        self.assertNotEqual(self.client.get("/character/" + urllib.parse.quote("../state")).status_code, 200)

    def test_table_settings_page_covers_every_flag(self):
        r = self.client.get("/setup")
        self.assertEqual(r.status_code, 200)
        page = r.get_data(as_text=True)
        self.assertIn("[DnE table settings]", page)
        import campaign_version
        for flag in campaign_version.FLAGS:
            self.assertIn(f'"{flag}"', page, flag)

    def test_codex_has_no_dm_prep(self):
        body = json.dumps(self.client.get("/codex").get_json(), ensure_ascii=False)
        self.assertNotIn("the Chief did it", body)       # world.md mystery answer
        self.assertNotIn("relocate the core", body)       # Faction Moves
        self.assertNotIn("Hidden Core", body)             # dm_only graph node
        self.assertIn("Dock 9", body)
        self.assertIn("EDEN", body)

    def test_codex_npc_table_skips_header_separator_and_party(self):
        camp = pathlib.Path(os.environ["DNE_CAMPAIGN_ROOT"]) / "campaigns" / "eden"
        (camp / "npcs.md").write_text(
            "| ชื่อ | บทบาท | ท่าที |\n| ------ | --- | ---------- |\n"
            "| **Rina** | Club mate | friendly |\n| Nox | the player | — |\n", encoding="utf-8")
        with self.app._stats_lock:
            saved = self.app._current_stats.get("players")
            self.app._current_stats["players"] = [{"name": "Nox"}]
        try:
            npcs = self.client.get("/codex").get_json()["npcs"]
        finally:
            with self.app._stats_lock:
                self.app._current_stats["players"] = saved or []
            (camp / "npcs.md").unlink()
        self.assertEqual([n["name"] for n in npcs], ["Rina"])
        self.assertEqual(npcs[0]["role"], "Club mate")

    def test_no_srd_reference_link_in_world_campaign(self):
        j = self.client.get("/srd-lookup", query_string={"name": "fireball", "category": "spell"}).get_json()
        self.assertFalse(j.get("found"))
        self.assertFalse(j.get("reference_url"))


if __name__ == "__main__":
    unittest.main()
