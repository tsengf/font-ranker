import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import server


class RankStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "rankings.json"
        self.catalog = {
            "version": "test",
            "fonts": [
                {"id": "Alpha", "name": "Alpha", "downloadUrl": "https://example/Alpha.zip"},
                {"id": "Beta", "name": "Beta", "downloadUrl": "https://example/Beta.zip"},
            ],
        }

    def tearDown(self):
        self.temp.cleanup()

    def test_vote_updates_elo_and_persists_ranked_list(self):
        store = server.RankStore(self.path, self.catalog)
        result = store.vote("Beta", "Alpha")
        self.assertEqual(result["totalVotes"], 1)
        self.assertEqual(result["ranking"][0]["id"], "Beta")
        saved = json.loads(self.path.read_text())
        self.assertEqual(saved["fonts"]["Beta"]["rating"], 1016.0)
        self.assertEqual(saved["ranking"][0]["rank"], 1)

    def test_rejects_invalid_vote(self):
        store = server.RankStore(self.path, self.catalog)
        with self.assertRaises(ValueError):
            store.vote("Alpha", "Alpha")

    def test_undo_restores_ratings_and_original_pair(self):
        store = server.RankStore(self.path, self.catalog)
        store.vote("Beta", "Alpha", ["Alpha", "Beta"])
        state, pair = store.undo()
        self.assertEqual(pair, ["Alpha", "Beta"])
        self.assertEqual(state["totalVotes"], 0)
        self.assertEqual(state["ranking"][0]["rating"], 1000.0)
        self.assertTrue(all(row["comparisons"] == 0 for row in state["ranking"]))
        persisted = json.loads(self.path.read_text())
        self.assertEqual(persisted["history"], [])

    def test_undo_without_history_is_rejected(self):
        store = server.RankStore(self.path, self.catalog)
        with self.assertRaises(ValueError):
            store.undo()

    def test_single_legacy_vote_can_be_undone(self):
        self.path.write_text(json.dumps({
            "schemaVersion": 1,
            "totalVotes": 1,
            "fonts": {
                "Alpha": {"name": "Alpha", "rating": 984.0, "wins": 0, "losses": 1, "comparisons": 1},
                "Beta": {"name": "Beta", "rating": 1016.0, "wins": 1, "losses": 0, "comparisons": 1},
            },
        }))
        store = server.RankStore(self.path, self.catalog)
        state, pair = store.undo()
        self.assertEqual(pair, ["Beta", "Alpha"])
        self.assertEqual(state["totalVotes"], 0)

    def test_priority_pair_connects_an_unseen_font(self):
        catalog = {
            "version": "test",
            "fonts": self.catalog["fonts"] + [
                {"id": "Gamma", "name": "Gamma", "downloadUrl": "https://example/Gamma.zip"},
            ],
        }
        store = server.RankStore(self.path, catalog)
        store.vote("Alpha", "Beta")
        pair = store.priority_pair()
        self.assertIn("Gamma", pair)

    def test_priority_pair_uses_least_compared_adjacent_fonts(self):
        catalog = {
            "version": "test",
            "fonts": self.catalog["fonts"] + [
                {"id": "Gamma", "name": "Gamma", "downloadUrl": "https://example/Gamma.zip"},
            ],
        }
        store = server.RankStore(self.path, catalog)
        store.state["fonts"]["Alpha"].update(rating=1100, comparisons=3)
        store.state["fonts"]["Beta"].update(rating=1000, comparisons=3)
        store.state["fonts"]["Gamma"].update(rating=900, comparisons=1)
        store.state["pairCounts"] = {store.pair_key("Alpha", "Beta"): 2}
        pair = store.priority_pair()
        self.assertEqual(set(pair), {"Beta", "Gamma"})


class FontArchiveTests(unittest.TestCase):
    def test_prefers_regular_mono_font(self):
        with tempfile.NamedTemporaryFile(suffix=".zip") as temp:
            with zipfile.ZipFile(temp.name, "w") as archive:
                archive.writestr("FontNerdFont-Bold.ttf", b"bold")
                archive.writestr("FontNerdFontMono-Regular.ttf", b"regular mono")
                archive.writestr("FontNerdFont-Italic.ttf", b"italic")
            with zipfile.ZipFile(temp.name) as archive:
                self.assertEqual(server.choose_font_member(archive), "FontNerdFontMono-Regular.ttf")


class PreparedFontTests(unittest.TestCase):
    def test_prepares_a_ranked_font_from_the_catalog(self):
        with mock.patch.object(server, "CACHE") as cache:
            cache.fonts = {"Sample": {"id": "Sample", "name": "Sample Mono"}}
            cache.ensure.return_value = (Path("font.ttf"), "truetype")

            self.assertEqual(server.prepare_font("Sample"), {
                "id": "Sample",
                "name": "Sample Mono",
                "fontUrl": "/fonts/Sample/font.ttf",
                "format": "truetype",
            })
            cache.ensure.assert_called_once_with("Sample")

    def test_rejects_an_unknown_ranked_font(self):
        with mock.patch.object(server, "CACHE") as cache:
            cache.fonts = {}

            with self.assertRaisesRegex(ValueError, "Unknown font"):
                server.prepare_font("Missing")
            cache.ensure.assert_not_called()


class FontPreviewEndpointTests(unittest.TestCase):
    def test_returns_the_requested_font(self):
        handler = object.__new__(server.Handler)
        handler.path = "/api/font/Sample"
        handler.json_response = mock.Mock()
        font = {"id": "Sample", "fontUrl": "/fonts/Sample/font.ttf"}

        with mock.patch.object(server, "prepare_font", return_value=font) as prepare:
            handler.do_GET()

        prepare.assert_called_once_with("Sample")
        handler.json_response.assert_called_once_with(font)

    def test_unknown_font_returns_not_found(self):
        handler = object.__new__(server.Handler)
        handler.path = "/api/font/Missing"
        handler.json_response = mock.Mock()

        with mock.patch.object(server, "prepare_font", side_effect=ValueError("Unknown font")):
            handler.do_GET()

        handler.json_response.assert_called_once_with(
            {"error": "Unknown font"}, server.HTTPStatus.NOT_FOUND
        )


if __name__ == "__main__":
    unittest.main()
