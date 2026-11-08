import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from streamrip_api import StreamRipApi, is_va_artist


def make_api():
    api = StreamRipApi()
    api._ready = True
    api._config = SimpleNamespace(session=SimpleNamespace(
        deezer=SimpleNamespace(quality=2),
        qobuz=SimpleNamespace(quality=3),
    ))
    api._deezer = SimpleNamespace(logged_in=True, search=AsyncMock(return_value=[]))
    return api


class VaMarkerTests(unittest.TestCase):
    def test_markers_recognized(self):
        for name in ("VA", "va", "Va ", "Various Artists", "various artists", "Various"):
            self.assertTrue(is_va_artist(name), name)

    def test_real_artists_not_matched(self):
        for name in ("Vald", "Vaya", "Vitalic", "Daft Punk", "", " ", None):
            self.assertFalse(is_va_artist(name), name)


class VaSearchTests(unittest.TestCase):
    def sent_query(self, **kwargs):
        api = make_api()
        asyncio.run(api.search(**kwargs))
        call = api._deezer.search.call_args
        return call.args[1] if len(call.args) > 1 else ""

    def test_va_artist_dropped_from_combined_query(self):
        self.assertEqual(
            self.sent_query(query="", artist="VA", album="EVANGELION FINALLY"),
            "EVANGELION FINALLY",
        )

    def test_various_artists_also_dropped(self):
        self.assertEqual(
            self.sent_query(query="", artist="Various Artists", album="EVANGELION FINALLY"),
            "EVANGELION FINALLY",
        )

    def test_real_artist_kept(self):
        self.assertEqual(
            self.sent_query(query="", artist="Daft Punk", album="Discovery"),
            "Daft Punk Discovery",
        )


if __name__ == "__main__":
    unittest.main()
