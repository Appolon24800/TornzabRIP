import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, call, patch
from xml.etree.ElementTree import fromstring

from starlette.requests import Request
from streamrip.client import DeezerClient

import torznab
from streamrip_api import StreamRipApi, _deezer_album_fallback_query


ARTIST = "Tame Impala"
ALBUM = "Dracula JENNIE remix Boys Noize Disko version"
QUERY = f"{ARTIST} {ALBUM}"
FALLBACK = "Tame Impala Dracula JENNIE Boys Noize Disko version"
DEEZER_ALBUM = "Dracula (with JENNIE) (Boys Noize Disko Version)"
DEEZER_PAGES = [{
    "data": [{
        "id": 980647761,
        "title": DEEZER_ALBUM,
        "artist": {"name": ARTIST},
        "nb_tracks": 1,
    }],
    "total": 1,
}]


def make_api():
    api = StreamRipApi()
    api._ready = True
    api._config = SimpleNamespace(session=SimpleNamespace(
        deezer=SimpleNamespace(quality=2),
        qobuz=SimpleNamespace(quality=3),
    ))
    api._deezer = SimpleNamespace(logged_in=True, search=AsyncMock())
    return api


class FallbackQueryTests(unittest.TestCase):
    def test_removes_only_standalone_remix_from_album(self):
        cases = [
            (ALBUM, FALLBACK),
            ("Dracula JENNIE REMIX Boys Noize Disko version", FALLBACK),
            ("Dracula (JENNIE remix – Boys Noize Disko version)",
             "Tame Impala Dracula (JENNIE – Boys Noize Disko version)"),
            ("Dracula Remix", "Tame Impala Dracula"),
            ("  Dracula   Remix  ", "Tame Impala Dracula"),
            ("Dracula (Boys Noize Disko Version)", ""),
            ("Remixed", ""),
            ("Remixes", ""),
            ("Remix", ""),
            ("(REMIX)", ""),
            ("", ""),
        ]
        for album, expected in cases:
            with self.subTest(album=album):
                self.assertEqual(_deezer_album_fallback_query(ARTIST, album), expected)

    def test_preserves_artist_named_remix(self):
        self.assertEqual(
            _deezer_album_fallback_query("Remix", "Dracula Remix"),
            "Remix Dracula",
        )


class DeezerSearchTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_structured_search_retries_and_preserves_metadata(self):
        api = make_api()
        api._deezer.search.side_effect = [[], DEEZER_PAGES]
        api._enrich_with_durations = AsyncMock()

        with self.assertLogs("torznabrip.streamrip_api", level="INFO") as logs:
            results = await api.search("", artist=ARTIST, album=ALBUM, limit=7)

        self.assertIn("retrying once", logs.output[0])
        self.assertEqual(api._deezer.search.await_args_list, [
            call("album", QUERY, limit=7),
            call("album", FALLBACK, limit=7),
        ])
        self.assertEqual(len(results), 1)
        result = results[0]
        self.assertEqual(result.release_id, "980647761")
        self.assertEqual(result.artist, ARTIST)
        self.assertEqual(result.album, DEEZER_ALBUM)
        self.assertEqual(result.source, "deezer")
        self.assertEqual(result.media_type, "album")
        self.assertEqual(result.format_label, "FLAC")
        self.assertEqual(result.num_tracks, 1)
        self.assertGreater(result.size_bytes, 0)
        api._enrich_with_durations.assert_awaited_once_with(
            "deezer", api._deezer, results,
        )

    async def test_successful_search_does_not_retry(self):
        api = make_api()
        api._deezer.search.return_value = DEEZER_PAGES
        results = await api.search("", artist=ARTIST, album=ALBUM, enrich=False)
        self.assertEqual(len(results), 1)
        api._deezer.search.assert_awaited_once_with("album", QUERY, limit=50)

    async def test_empty_fallback_stops_after_two_requests(self):
        api = make_api()
        api._deezer.search.return_value = []
        self.assertEqual(await api.search("", artist=ARTIST, album=ALBUM), [])
        self.assertEqual(api._deezer.search.await_count, 2)

    async def test_search_exception_does_not_trigger_fallback(self):
        api = make_api()
        api._deezer.search.side_effect = RuntimeError("rate limited")
        with self.assertLogs("torznabrip.streamrip_api", level="ERROR"):
            self.assertEqual(await api.search("", artist=ARTIST, album=ALBUM), [])
        api._deezer.search.assert_awaited_once_with("album", QUERY, limit=50)

    async def test_fallback_exception_returns_empty_results(self):
        api = make_api()
        api._deezer.search.side_effect = [[], RuntimeError("rate limited")]
        with self.assertLogs("torznabrip.streamrip_api", level="ERROR"):
            self.assertEqual(await api.search("", artist=ARTIST, album=ALBUM), [])
        self.assertEqual(api._deezer.search.await_count, 2)

    async def test_invalid_result_does_not_trigger_fallback(self):
        api = make_api()
        api._deezer.search.return_value = [{"data": [{"title": "missing ID"}]}]
        with self.assertLogs("torznabrip.streamrip_api", level="ERROR"):
            self.assertEqual(await api.search("", artist=ARTIST, album=ALBUM), [])
        self.assertEqual(api._deezer.search.await_count, 1)

    async def test_non_structured_and_non_album_searches_do_not_retry(self):
        cases = [
            {"query": QUERY},
            {"query": QUERY, "artist": ARTIST, "album": ALBUM},
            {"query": "", "artist": "Remix"},
            {"query": "", "album": ALBUM},
            {"query": "", "artist": " ", "album": ALBUM},
            {"query": "", "artist": ARTIST, "album": "Remix"},
            {"query": "", "artist": ARTIST, "album": "Dracula"},
            {"query": "", "artist": ARTIST, "album": ALBUM, "media_type": "track"},
        ]
        for kwargs in cases:
            with self.subTest(kwargs=kwargs):
                api = make_api()
                api._deezer.search.return_value = []
                self.assertEqual(await api.search(**kwargs), [])
                self.assertEqual(api._deezer.search.await_count, 1)

    async def test_qobuz_still_uses_original_query(self):
        api = make_api()
        api._qobuz = SimpleNamespace(logged_in=True, search=AsyncMock(
            return_value=[{"albums": {"items": [{
                "id": "qobuz-album",
                "title": ALBUM,
                "artist": {"name": ARTIST},
            }]}}],
        ))
        api._deezer.search.side_effect = [[], DEEZER_PAGES]
        results = await api.search("", artist=ARTIST, album=ALBUM, enrich=False)
        api._qobuz.search.assert_awaited_once_with("album", QUERY, limit=50)
        self.assertEqual([r.source for r in results], ["qobuz", "deezer"])

    async def test_disabled_deezer_does_not_search(self):
        api = make_api()
        api._deezer.logged_in = False
        self.assertEqual(await api.search("", artist=ARTIST, album=ALBUM), [])
        api._deezer.search.assert_not_awaited()

    async def test_not_ready_does_not_search(self):
        api = make_api()
        api._ready = False
        with self.assertLogs("torznabrip.streamrip_api", level="WARNING"):
            self.assertEqual(await api.search("", artist=ARTIST, album=ALBUM), [])
        api._deezer.search.assert_not_awaited()

    async def test_enrichment_can_be_disabled(self):
        api = make_api()
        api._deezer.search.side_effect = [[], DEEZER_PAGES]
        api._enrich_with_durations = AsyncMock()
        results = await api.search("", artist=ARTIST, album=ALBUM, enrich=False)
        self.assertEqual(len(results), 1)
        api._enrich_with_durations.assert_not_awaited()

    async def test_torznab_response_contains_correct_download_identity(self):
        api = make_api()
        api._deezer.search.side_effect = [[], DEEZER_PAGES]
        api._enrich_with_durations = AsyncMock()
        with patch.object(torznab, "streamrip", api):
            response = await torznab._search(
                make_request(), "music", "", ARTIST, ALBUM,
                "3000,3010,3040,3050", 50, 0,
            )
        assert_deezer_rss(self, response)


def make_request():
    return Request({
        "type": "http",
        "scheme": "http",
        "server": ("localhost", 8686),
        "path": "/api",
        "root_path": "",
        "query_string": b"t=music",
        "headers": [],
    })


def assert_deezer_rss(test, response):
    test.assertEqual(response.status_code, 200)
    root = fromstring(response.body)
    items = root.findall("./channel/item")
    test.assertEqual(len(items), 1)
    item = items[0]
    guid = item.findtext("guid")
    test.assertEqual(torznab.decode_guid(guid), ("deezer", "980647761"))
    test.assertEqual(item.findtext("category"), "3040")
    test.assertEqual(item.findtext("comments"), "https://www.deezer.com/album/980647761")
    test.assertIn(f"download?id={guid}", item.findtext("link"))
    attrs = {attr.get("name"): attr.get("value") for attr in item.findall(
        "{http://torznab.com/schemas/2015/feed}attr",
    )}
    test.assertEqual(attrs["artist"], ARTIST)
    test.assertEqual(attrs["album"], DEEZER_ALBUM)
    test.assertIn(f"dn={guid}", attrs["magneturl"])


@unittest.skipUnless(
    os.environ.get("TORNZABRIP_LIVE_DEEZER_TEST") == "1",
    "Set TORNZABRIP_LIVE_DEEZER_TEST=1 to query Deezer's public API.",
)
class LiveDeezerSearchTests(unittest.IsolatedAsyncioTestCase):
    async def test_dracula_search_reaches_torznab_xml(self):
        api = make_api()
        # Public album search needs no ARL. Do not log in or download anything.
        api._deezer = DeezerClient(api._config)
        api._deezer.logged_in = True
        self.assertEqual(await api._deezer.search("album", QUERY, limit=50), [])
        with patch.object(torznab, "streamrip", api):
            response = await torznab._search(
                make_request(), "music", "", ARTIST, ALBUM,
                "3000,3010,3040,3050", 50, 0,
            )
        assert_deezer_rss(self, response)


if __name__ == "__main__":
    unittest.main()
