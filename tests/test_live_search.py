import json
import os
import tempfile
import unittest
from unittest.mock import patch
from xml.etree.ElementTree import fromstring

from streamrip.client import DeezerClient

import torznab

from aliases import Aliases
from test_deezer_search import make_api, make_request


def norm(text):
    return " ".join((text or "").lower().split())


def items_attrs(response):
    root = fromstring(response.body)
    return [
        {a.get("name"): a.get("value") for a in item.findall(
            "{http://torznab.com/schemas/2015/feed}attr")}
        for item in root.findall("./channel/item")
    ]


@unittest.skipUnless(
    os.environ.get("TORNZABRIP_LIVE_DEEZER_TEST") == "1",
    "Set TORNZABRIP_LIVE_DEEZER_TEST=1 to query Deezer's public API.",
)
class LiveReleaseFoundTests(unittest.IsolatedAsyncioTestCase):
    """End-to-end checks that real releases are found through the public,
    unauthenticated Deezer catalog search, one per query shape Lidarr sends.

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

    async def search_torznab(self, artist="", album="", q=""):
        api = self.live_api()
        with patch.object(torznab, "streamrip", api):
            return await torznab._search(
                make_request(), "music", q, artist, album,
                "3000,3010,3040,3050", 50, 0,
            )

    def assert_found(self, response, **expected):
        """At least one item whose attrs match all normalized expectations."""
        self.assertEqual(response.status_code, 200)
        found = [
            attrs for attrs in items_attrs(response)
            if all(norm(attrs.get(key, "")) == norm(value) for key, value in expected.items())
        ]
        self.assertTrue(
            found,
            f"no release with {expected}; got "
            f"{[a.get('artist') for a in items_attrs(response)][:5]}",
        )
        return found[0]

    async def test_q_only_finds_releases(self):
        response = await self.search_torznab(q="Shiro Sagisu")
        self.assert_found(response, artist="Shiro Sagisu")

    async def test_artist_only_finds_releases(self):
        response = await self.search_torznab(artist="Daft Punk")
        self.assert_found(response, artist="Daft Punk")

    async def test_album_only_finds_release(self):
        response = await self.search_torznab(album="Discovery")
        self.assert_found(response, artist="Daft Punk", album="Discovery")

    async def test_artist_and_album_combined_finds_release(self):
        response = await self.search_torznab(artist="Daft Punk", album="Discovery")
        self.assert_found(response, artist="Daft Punk", album="Discovery")

    async def test_various_artists_album_is_found(self):
        # Lidarr sends artist=VA for Various Artists releases.
        response = await self.search_torznab(artist="VA", album="EVANGELION FINALLY")
        self.assert_found(response, artist="Various Artists", album="Evangelion Finally")

    async def test_various_artists_spelled_out_also_finds(self):
        response = await self.search_torznab(artist="Various Artists", album="EVANGELION FINALLY")
        self.assert_found(response, artist="Various Artists", album="Evangelion Finally")

    async def test_kanji_artist_alias_finds_releases(self):
        # Lidarr stores the MusicBrainz kanji name; the alias file maps it
        # to the name Deezer indexes.
        with tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            json.dump({"鷺巣詩郎": "Shiro Sagisu"}, f, ensure_ascii=False)
            alias_path = f.name
        try:
            import streamrip_api
            with patch.object(streamrip_api, "aliases", Aliases(alias_path)):
                response = await self.search_torznab(artist="鷺巣詩郎")
        finally:
            os.unlink(alias_path)
        self.assert_found(response, artist="Shiro Sagisu")

    async def test_va_marker_query_alone_finds_nothing_on_the_catalog(self):
        # Documents why the marker is dropped: the literal "VA <album>"
        # query returns no releases from the public catalog.
        api = self.live_api()
        pages = await api._deezer.search("album", "VA EVANGELION FINALLY", limit=50)
        self.assertEqual(pages, [])


if __name__ == "__main__":
    unittest.main()
