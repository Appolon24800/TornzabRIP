import os
import unittest
from unittest.mock import patch
from xml.etree.ElementTree import fromstring

from streamrip.client import DeezerClient

import torznab

from test_deezer_search import make_api, make_request


def norm(text):
    return " ".join((text or "").lower().split())


@unittest.skipUnless(
    os.environ.get("TORNZABRIP_LIVE_DEEZER_TEST") == "1",
    "Set TORNZABRIP_LIVE_DEEZER_TEST=1 to query Deezer's public API.",
)
class LiveReleaseFoundTests(unittest.IsolatedAsyncioTestCase):
    """End-to-end checks that real releases are found through the public,
    unauthenticated Deezer catalog search.

    Only Deezer can be covered here: Qobuz's catalog search rejects
    requests without a user auth token (401 "User authentication is
    required"), and no credential belongs in tests.
    """

    def live_api(self):
        api = make_api()
        # Public album search needs no ARL. Do not log in or download anything.
        api._deezer = DeezerClient(api._config)
        api._deezer.logged_in = True
        return api

    async def search_torznab(self, artist, album):
        api = self.live_api()
        with patch.object(torznab, "streamrip", api):
            return await torznab._search(
                make_request(), "music", "", artist, album,
                "3000,3010,3040,3050", 50, 0,
            )

    async def test_various_artists_album_is_found(self):
        # Lidarr sends artist=VA for Various Artists releases.
        response = await self.search_torznab("VA", "EVANGELION FINALLY")
        self.assertEqual(response.status_code, 200)
        root = fromstring(response.body)
        attrs = [
            {a.get("name"): a.get("value") for a in item.findall(
                "{http://torznab.com/schemas/2015/feed}attr")}
            for item in root.findall("./channel/item")
        ]
        found = [
            a for a in attrs
            if norm(a.get("album", "")) == "evangelion finally"
        ]
        self.assertTrue(found, "expected to find 'Evangelion Finally' via Deezer")
        self.assertEqual(norm(found[0].get("artist", "")), "various artists")

    async def test_va_marker_query_alone_finds_nothing_on_the_catalog(self):
        # Documents why the marker is dropped: the literal "VA <album>"
        # query returns no releases from the public catalog.
        api = self.live_api()
        pages = await api._deezer.search("album", "VA EVANGELION FINALLY", limit=50)
        self.assertEqual(pages, [])


if __name__ == "__main__":
    unittest.main()
