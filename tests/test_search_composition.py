import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from xml.etree.ElementTree import fromstring

from starlette.requests import Request

import torznab
from lidarr_sync import LidarrSync
from streamrip_api import StreamRipApi

from test_deezer_search import make_api, make_request


class QueryCompositionTests(unittest.TestCase):
    def sent_query(self, api, **kwargs):
        import asyncio
        asyncio.run(api.search(**kwargs))
        call = api._deezer.search.call_args
        if call is None:
            return None
        return call.args[1] if len(call.args) > 1 else None

    def test_q_only(self):
        self.assertEqual(self.sent_query(make_api(), query="Daft Punk"), "Daft Punk")

    def test_artist_only(self):
        self.assertEqual(self.sent_query(make_api(), query="", artist="Daft Punk"), "Daft Punk")

    def test_album_only(self):
        self.assertEqual(self.sent_query(make_api(), query="", album="Discovery"), "Discovery")

    def test_artist_and_album_combined(self):
        self.assertEqual(
            self.sent_query(make_api(), query="", artist="Daft Punk", album="Discovery"),
            "Daft Punk Discovery",
        )

    def test_q_takes_precedence_over_artist_and_album(self):
        self.assertEqual(
            self.sent_query(make_api(), query="RAM", artist="Daft Punk", album="Discovery"),
            "RAM",
        )

    def test_all_empty_searches_nothing(self):
        api = make_api()
        self.assertEqual(self.sent_query(api, query="", artist="", album=""), None)
        api._deezer.search.assert_not_awaited()

    def test_va_marker_variants_all_dropped(self):
        for marker in ("VA", "va", "Va", " VA ", "Various", "various artists", "Various Artists"):
            with self.subTest(marker=marker):
                self.assertEqual(
                    self.sent_query(
                        make_api(), query="", artist=marker, album="EVANGELION FINALLY"
                    ),
                    "EVANGELION FINALLY",
                )

    def test_va_artist_alone_searches_nothing(self):
        # A bare VA marker carries no searchable term.
        api = make_api()
        self.assertEqual(self.sent_query(api, query="", artist="VA", album=""), None)
        api._deezer.search.assert_not_awaited()

    def test_va_marker_in_album_title_is_kept(self):
        # Only the artist parameter is checked; album titles containing
        # "VA" (e.g. "VA Sessions") must survive untouched.
        self.assertEqual(
            self.sent_query(make_api(), query="", artist="Daft Punk", album="VA Sessions"),
            "Daft Punk VA Sessions",
        )

    def test_real_artist_matching_va_prefix_is_kept(self):
        self.assertEqual(
            self.sent_query(make_api(), query="", artist="Vald", album="XEU"),
            "Vald XEU",
        )


class CapsTests(unittest.TestCase):
    def test_caps_lists_audio_categories(self):
        response = torznab._caps(make_request())
        self.assertEqual(response.status_code, 200)
        root = fromstring(response.body)
        cats = {c.get("id") for c in root.findall("./categories/category")}
        self.assertEqual(cats, {"3000", "3010", "3040", "3050"})


class FakeResponse:
    def __init__(self, status, payload):
        self.status = status
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def json(self, content_type=None):
        return self._payload


class MonitoredArtistFilterTests(unittest.TestCase):
    def make_sync(self, payload, status=200):
        sync = LidarrSync(None)
        session = SimpleNamespace(
            get=lambda url, timeout=None: FakeResponse(status, payload)
        )
        sync._session = session
        return sync

    def test_keeps_monitored_drops_unmonitored_and_va(self):
        payload = [
            {"monitored": True, "artistName": "Daft Punk"},
            {"monitored": False, "artistName": "Nirvana"},
            {"monitored": True, "artistName": "Various Artists"},
            {"monitored": True, "artistName": "VA"},
            {"monitored": True, "metadata": {"name": "鷺巣詩郎"}},
            {"monitored": True},
        ]
        import asyncio
        artists = asyncio.run(self.make_sync(payload)._fetch_monitored_artists())
        self.assertEqual(artists, ["Daft Punk", "鷺巣詩郎"])

    def test_http_error_returns_empty(self):
        import asyncio
        self.assertEqual(asyncio.run(self.make_sync([], status=500)._fetch_monitored_artists()), [])


if __name__ == "__main__":
    unittest.main()
