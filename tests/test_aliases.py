import json
import os
import tempfile
import time
import unittest
from unittest.mock import patch
from xml.etree.ElementTree import fromstring

from starlette.requests import Request

from aliases import Aliases

ALIASES = {"鷺巣詩郎": "Shiro Sagisu", "高中正義": "Masayoshi Takanaka"}


def make_request() -> Request:
    return Request({
        "type": "http",
        "scheme": "http",
        "server": ("localhost", 8686),
        "path": "/api",
        "root_path": "",
        "query_string": b"t=music",
        "headers": [],
    })


class AliasFileTests(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(ALIASES, f, ensure_ascii=False)

    def tearDown(self):
        os.unlink(self.path)

    def test_missing_file_is_identity(self):
        a = Aliases("/nonexistent/artist_aliases.json")
        self.assertEqual(a.rewrite("鷺巣詩郎 Evangelion"), "鷺巣詩郎 Evangelion")
        self.assertEqual(a.display("Shiro Sagisu"), "Shiro Sagisu")

    def test_rewrites_queries(self):
        a = Aliases(self.path)
        self.assertEqual(
            a.rewrite("鷺巣詩郎 Neon Genesis Evangelion"),
            "Shiro Sagisu Neon Genesis Evangelion",
        )
        self.assertEqual(a.rewrite("高中正義"), "Masayoshi Takanaka")

    def test_collapses_whitespace_left_by_replacement(self):
        a = Aliases(self.path)
        self.assertEqual(a.rewrite("鷺巣詩郎  x"), "Shiro Sagisu x")

    def test_longest_key_applies_first(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"ab": "X", "abc": "Y"}, f)
        os.utime(self.path, (time.time() + 10, time.time() + 10))
        a = Aliases(self.path)
        self.assertEqual(a.rewrite("abc"), "Y")

    def test_display_maps_catalog_name_back(self):
        a = Aliases(self.path)
        self.assertEqual(a.display("Shiro Sagisu"), "鷺巣詩郎")
        self.assertEqual(a.display("shiro SAGISU"), "鷺巣詩郎")
        self.assertEqual(a.display("Daft Punk"), "Daft Punk")
        self.assertEqual(a.display(""), "")

    def test_reloads_when_file_changes(self):
        a = Aliases(self.path)
        self.assertEqual(a.rewrite("鷺巣詩郎"), "Shiro Sagisu")
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"鷺巣詩郎": "Sagisu Shirō"}, f, ensure_ascii=False)
        os.utime(self.path, (time.time() + 10, time.time() + 10))
        self.assertEqual(a.rewrite("鷺巣詩郎"), "Sagisu Shirō")
        self.assertEqual(a.display("sagisu shirō"), "鷺巣詩郎")

    def test_invalid_json_keeps_previous_aliases(self):
        a = Aliases(self.path)
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("{not json")
        os.utime(self.path, (time.time() + 10, time.time() + 10))
        self.assertEqual(a.rewrite("鷺巣詩郎"), "Shiro Sagisu")


class SearchRewriteTests(unittest.TestCase):
    def test_search_translates_artist_before_composing_query(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock

        from streamrip_api import StreamRipApi

        api = StreamRipApi()
        api._ready = True
        api._config = SimpleNamespace(session=SimpleNamespace(
            deezer=SimpleNamespace(quality=2),
            qobuz=SimpleNamespace(quality=3),
        ))
        api._deezer = SimpleNamespace(logged_in=True, search=AsyncMock(return_value=[]))

        with tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            json.dump(ALIASES, f, ensure_ascii=False)
            alias_path = f.name
        try:
            with patch("streamrip_api.aliases", Aliases(alias_path)):
                import asyncio
                asyncio.run(api.search(query="", artist="鷺巣詩郎", album="The End of Evangelion"))
        finally:
            os.unlink(alias_path)

        sent = api._deezer.search.call_args
        query_sent = sent.args[1] if len(sent.args) > 1 else ""
        self.assertIn("Shiro Sagisu", query_sent)


class ItemXmlDisplayTests(unittest.TestCase):
    def test_title_and_attr_use_local_artist_name(self):
        import torznab
        from streamrip_api import SearchResult

        item = SearchResult(
            source="qobuz", release_id="0064932621955", media_type="album",
            title="X", artist="Shiro Sagisu", album="EVANGELION FINALLY",
            num_tracks=15, format_label="FLAC",
        )
        with tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            json.dump(ALIASES, f, ensure_ascii=False)
            alias_path = f.name
        try:
            with patch.object(torznab, "aliases", Aliases(alias_path)):
                el = torznab._item_xml(item, make_request())
        finally:
            os.unlink(alias_path)

        title = el.find("title").text
        self.assertTrue(title.startswith("鷺巣詩郎 - EVANGELION FINALLY"))
        attrs = {
            a.get("name"): a.get("value")
            for a in el.findall("{http://torznab.com/schemas/2015/feed}attr")
        }
        self.assertEqual(attrs.get("artist"), "鷺巣詩郎")


if __name__ == "__main__":
    unittest.main()
