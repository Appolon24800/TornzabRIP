from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Optional

import aiohttp

from config import LIDARR_API_KEY, LIDARR_URL, RSS_SYNC_INTERVAL, SEEN_RELEASES_FILE

logger = logging.getLogger("torznabrip.lidarr_sync")


def _norm(name: str) -> str:
    return (name or "").strip().lower()


class LidarrSync:
    """Periodically discovers Deezer releases for monitored Lidarr artists and
    surfaces the ones that are new since the last run in the indexer's RSS feed.

    First run only "seeds" the set of already-known releases (so the feed is
    not flooded with an artist's entire back catalogue); every subsequent run
    adds genuinely new releases to the feed.
    """

    def __init__(self, streamrip_api) -> None:
        self._api = streamrip_api
        self._session: Optional[aiohttp.ClientSession] = None
        self._task: Optional[asyncio.Task] = None
        self._seen: set[str] = set()
        self._initialized: bool = False
        self._feed: list = []  # list[SearchResult], newest first
        self._lock = asyncio.Lock()
        self._enabled = bool(LIDARR_URL and LIDARR_API_KEY)

    @property
    def enabled(self) -> bool:
        return self._enabled

    # ----- lifecycle ---------------------------------------------------------

    async def start(self) -> None:
        if not self._enabled:
            logger.info(
                "Lidarr RSS sync disabled (set LIDARR_URL and LIDARR_API_KEY to enable)."
            )
            return
        self._load()
        self._session = aiohttp.ClientSession()
        self._task = asyncio.create_task(self._loop())
        logger.info(
            "Lidarr RSS sync enabled; polling every %ds (seeded=%s, seen=%d).",
            RSS_SYNC_INTERVAL, self._initialized, len(self._seen),
        )

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._session:
            await self._session.close()
            self._session = None

    async def _loop(self) -> None:
        await asyncio.sleep(15)  # let streamrip clients settle after startup
        while True:
            try:
                await self.sync_once()
            except Exception as exc:
                logger.error("Lidarr sync run failed: %s", exc)
            await asyncio.sleep(RSS_SYNC_INTERVAL)

    # ----- persistence -------------------------------------------------------

    def _load(self) -> None:
        if not os.path.exists(SEEN_RELEASES_FILE):
            return
        try:
            with open(SEEN_RELEASES_FILE) as f:
                data = json.load(f)
            self._seen = set(data.get("seen", []))
            self._initialized = bool(data.get("initialized", False))
        except Exception as exc:
            logger.warning("Could not load %s: %s", SEEN_RELEASES_FILE, exc)

    def _save(self) -> None:
        try:
            os.makedirs(os.path.dirname(SEEN_RELEASES_FILE) or ".", exist_ok=True)
            with open(SEEN_RELEASES_FILE, "w") as f:
                json.dump(
                    {"seen": sorted(self._seen), "initialized": self._initialized},
                    f,
                )
        except Exception as exc:
            logger.warning("Could not save %s: %s", SEEN_RELEASES_FILE, exc)

    # ----- Lidarr ------------------------------------------------------------

    async def _fetch_monitored_artists(self) -> list[str]:
        assert self._session is not None
        url = f"{LIDARR_URL}/api/v1/artist?apikey={LIDARR_API_KEY}"
        async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            if resp.status != 200:
                logger.warning("Lidarr artist list returned HTTP %d", resp.status)
                return []
            data = await resp.json(content_type=None)

        artists: list[str] = []
        for entry in data:
            if not entry.get("monitored"):
                continue
            name = (
                entry.get("artistName")
                or (entry.get("metadata") or {}).get("value")
                or (entry.get("metadata") or {}).get("name")
            )
            if name:
                artists.append(name)
        return artists

    # ----- sync --------------------------------------------------------------

    async def sync_once(self) -> None:
        artists = await self._fetch_monitored_artists()
        if not artists:
            logger.info("Lidarr sync: no monitored artists returned.")
            return

        logger.info(
            "Lidarr sync: checking %d monitored artists (seeded=%s)",
            len(artists), self._initialized,
        )

        sem = asyncio.Semaphore(3)
        new_releases: list = []
        feed_keys: set[str] = set()

        async def check_artist(name: str) -> None:
            async with sem:
                try:
                    results = await self._api.search(
                        query=name, media_type="album", limit=50, enrich=False,
                    )
                except Exception as exc:
                    logger.error("Search for %r failed: %s", name, exc)
                    return
            target = _norm(name)
            for r in results:
                if not r or _norm(r.artist) != target:
                    continue
                key = f"{r.source}:{r.release_id}"
                if key in self._seen:
                    continue
                self._seen.add(key)
                if self._initialized and key not in feed_keys:
                    feed_keys.add(key)
                    new_releases.append(r)

        await asyncio.gather(*(check_artist(a) for a in artists))

        # Only the (typically few) new releases need accurate durations/sizes.
        if new_releases:
            await self._api.enrich_results(new_releases)
            async with self._lock:
                # newest first, de-duplicated, capped
                self._feed = (new_releases + self._feed)[:200]

        was_initialized = self._initialized
        self._initialized = True
        self._save()

        if was_initialized:
            logger.info("Lidarr sync: %d new release(s) added to the feed.", len(new_releases))
        else:
            logger.info(
                "Lidarr sync: seeded %d known release(s); feed starts empty until next new release.",
                len(self._seen),
            )

    # ----- feed access -------------------------------------------------------

    async def get_new_releases(self, limit: int = 100) -> list:
        async with self._lock:
            return list(self._feed[:limit])
