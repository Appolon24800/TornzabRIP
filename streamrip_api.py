from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
from typing import Optional

from streamrip.client import QobuzClient, DeezerClient
from streamrip.config import Config
from streamrip.db import Database, Downloads, Failed, Dummy
from streamrip.media import PendingAlbum
from streamrip.media.track import PendingSingle
from streamrip.metadata import SearchResults

from config import STREAMRIP_CONFIG_PATH, DOWNLOAD_TARGET_DIR

logger = logging.getLogger("torznabrip.streamrip_api")


def _make_dummy_db() -> Database:
    return Database(Dummy(), Dummy())


# Average bitrate per format, in bytes/second. Used to estimate release size
# from the total play length.
_AVG_BYTES_PER_SEC = {
    "flac": 102_400,    # ~800 kbps (CD-quality FLAC)
    "hires": 230_400,   # ~1800 kbps (hi-res FLAC)
    "mp3-320": 40_000,  # 320 kbps
    "mp3-128": 16_000,  # 128 kbps
}

# Average track length used to estimate total play time when the real duration
# is not available.
_AVG_TRACK_SECONDS = 210  # ~3.5 minutes


def _format_key(format_label: str) -> str:
    fl = (format_label or "").upper()
    if fl.startswith("FLAC"):
        return "flac"
    if "HIRES" in fl:
        return "hires"
    if "128" in fl:
        return "mp3-128"
    if "320" in fl:
        return "mp3-320"
    if fl.startswith("MP3"):
        return "mp3-320"
    return "flac"


def _estimate_size(
    format_label: str, num_tracks: int, duration_seconds: int | None = None
) -> int:
    if not duration_seconds or duration_seconds <= 0:
        duration_seconds = max(num_tracks, 1) * _AVG_TRACK_SECONDS
    bps = _AVG_BYTES_PER_SEC.get(_format_key(format_label), 102_400)
    return int(duration_seconds * bps)


def _extract_album_meta(pages: list[dict]) -> dict[str, dict]:
    """Build {release_id: {"tracks": int, "duration": int|None}} from raw
    search/featured responses.

    Covers both Deezer (entries under ``data`` with ``nb_tracks``) and Qobuz
    (entries under a nested ``items`` list with ``tracks_count``).
    """
    meta: dict[str, dict] = {}

    def _scan_entries(entries):
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            eid = entry.get("id")
            if eid is None:
                continue
            tracks = (
                entry.get("nb_tracks")
                or entry.get("tracks_count")
                or entry.get("numberOfTracks")
            )
            duration = entry.get("duration")
            if not tracks and not duration:
                continue
            try:
                meta[str(eid)] = {
                    "tracks": int(tracks) if tracks else 0,
                    "duration": int(duration) if duration else None,
                }
            except (TypeError, ValueError):
                pass

    for page in pages:
        if not isinstance(page, dict):
            continue
        _scan_entries(page.get("data") or [])
        for value in page.values():
            if isinstance(value, dict):
                _scan_entries(value.get("items") or [])

    return meta


class SearchResult:
    __slots__ = (
        "source", "release_id", "media_type", "title", "artist",
        "album", "num_tracks", "format_label", "size_bytes",
        "quality", "year",
    )

    def __init__(
        self,
        source: str,
        release_id: str,
        media_type: str,
        title: str,
        artist: str,
        album: str = "",
        num_tracks: int = 1,
        format_label: str = "FLAC",
        size_bytes: int = 0,
        quality: int = 2,
        year: str = "",
    ) -> None:
        self.source = source
        self.release_id = release_id
        self.media_type = media_type
        self.title = title
        self.artist = artist
        self.album = album or title
        self.num_tracks = num_tracks
        self.format_label = format_label
        self.size_bytes = size_bytes
        self.quality = quality
        self.year = year

    def __repr__(self) -> str:
        return f"SearchResult({self.source}:{self.release_id} '{self.title}')"


class StreamRipApi:
    def __init__(self) -> None:
        self._config: Optional[Config] = None
        self._qobuz: Optional[QobuzClient] = None
        self._deezer: Optional[DeezerClient] = None
        self._db = _make_dummy_db()
        self._ready = False
        self._duration_cache: dict[str, int] = {}
        self._lidarr_sync = None

    async def startup(self) -> None:
        if not os.path.exists(STREAMRIP_CONFIG_PATH):
            logger.warning(
                "StreamRip config not found at %s — searches will fail.",
                STREAMRIP_CONFIG_PATH,
            )
            return

        tmp_path = tempfile.mktemp(suffix=".toml", prefix="streamrip_")
        shutil.copy2(STREAMRIP_CONFIG_PATH, tmp_path)

        try:
            try:
                self._config = Config(tmp_path)
            except Exception:
                logger.info("Config format outdated; migrating temp copy.")
                Config.update_file(tmp_path)
                self._config = Config(tmp_path)
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

        self._config.session.downloads.folder = DOWNLOAD_TARGET_DIR
        self._config.session.downloads.source_subdirectories = False
        self._config.session.cli.progress_bars = False
        self._config.session.cli.text_output = False

        self._qobuz = QobuzClient(self._config)
        self._deezer = DeezerClient(self._config)

        results = await asyncio.gather(
            self._login_safe("qobuz", self._qobuz),
            self._login_safe("deezer", self._deezer),
        )

        if results[0] or results[1]:
            self._ready = True
            logger.info("StreamRip API ready (qobuz=%s, deezer=%s)", results[0], results[1])
        else:
            logger.error("Neither Qobuz nor Deezer could log in.")

    async def shutdown(self) -> None:
        for client in (self._qobuz, self._deezer):
            if client is not None and hasattr(client, "session") and client.session:
                try:
                    await client.session.close()
                except Exception:
                    pass

    @staticmethod
    async def _login_safe(source: str, client) -> bool:
        try:
            await client.login()
            logger.info("Logged into %s successfully.", source)
            return True
        except Exception as exc:
            logger.warning("Could not log into %s: %s", source, exc)
            return False

    async def search(
        self,
        query: str,
        artist: str = "",
        album: str = "",
        media_type: str = "album",
        limit: int = 50,
        enrich: bool = True,
    ) -> list[SearchResult]:
        if not self._ready:
            logger.warning("StreamRipApi not ready; returning empty results.")
            return []

        search_query = query.strip()
        if not search_query and artist and album:
            search_query = f"{artist} {album}"
        elif not search_query and artist:
            search_query = artist
        elif not search_query and album:
            search_query = album
        if not search_query:
            return []

        tasks = []
        if self._qobuz and self._qobuz.logged_in:
            tasks.append(self._search_safe("qobuz", self._qobuz, media_type, search_query, limit, enrich))
        if self._deezer and self._deezer.logged_in:
            tasks.append(self._search_safe("deezer", self._deezer, media_type, search_query, limit, enrich))

        if not tasks:
            return []

        results_lists = await asyncio.gather(*tasks, return_exceptions=True)

        merged: list[SearchResult] = []
        for result in results_lists:
            if isinstance(result, Exception):
                logger.error("Search error: %s", result)
                continue
            if isinstance(result, list):
                merged.extend(result)

        return merged

    async def enrich_results(self, results: list[SearchResult]) -> None:
        """Fill in real durations/sizes for a mixed-source list of results."""
        if not results:
            return
        by_source: dict[str, list[SearchResult]] = {}
        for r in results:
            by_source.setdefault(r.source, []).append(r)
        for source, group in by_source.items():
            client = self._qobuz if source == "qobuz" else self._deezer
            if client and getattr(client, "logged_in", False):
                await self._enrich_with_durations(source, client, group)

    async def _search_safe(
        self,
        source: str,
        client,
        media_type: str,
        query: str,
        limit: int,
        enrich: bool = True,
    ) -> list[SearchResult]:
        try:
            pages = await client.search(media_type, query, limit=limit)
        except Exception as exc:
            logger.error("Search on %s failed: %s", source, exc)
            return []

        if not pages:
            return []

        results = self._build_results(source, pages, media_type)
        if enrich:
            await self._enrich_with_durations(source, client, results)
        return results

    async def _enrich_with_durations(
        self, source: str, client, results: list[SearchResult]
    ) -> None:
        """Replace estimated sizes with ones based on the real album duration.

        Durations are fetched per-release via the source client (concurrently)
        and cached for the process lifetime. Anything that can't be fetched
        keeps its track-count-based estimate.
        """
        if not results:
            return

        sem = asyncio.Semaphore(8)

        async def _fetch(release_id: str) -> Optional[int]:
            async with sem:
                try:
                    if source == "qobuz":
                        meta = await asyncio.wait_for(
                            client.get_metadata(release_id, "album"), timeout=5
                        )
                    else:
                        meta = await asyncio.wait_for(
                            client.get_album(release_id), timeout=5
                        )
                    d = meta.get("duration") if isinstance(meta, dict) else None
                    return int(d) if d else None
                except Exception as exc:
                    logger.debug(
                        "duration fetch failed %s:%s: %s", source, release_id, exc
                    )
                    return None

        pending: list[tuple[SearchResult, str]] = []
        for r in results:
            key = f"{source}:{r.release_id}"
            cached = self._duration_cache.get(key)
            if cached:
                r.size_bytes = _estimate_size(r.format_label, r.num_tracks or 1, cached)
            else:
                pending.append((r, key))

        async def _task(r: SearchResult, key: str) -> None:
            d = await _fetch(r.release_id)
            if d:
                self._duration_cache[key] = d
                r.size_bytes = _estimate_size(r.format_label, r.num_tracks or 1, d)

        await asyncio.gather(*(_task(r, k) for r, k in pending), return_exceptions=True)

    def _build_results(
        self, source: str, pages: list[dict], media_type: str
    ) -> list[SearchResult]:
        try:
            search_results = SearchResults.from_pages(source, media_type, pages)
        except Exception as exc:
            logger.error("Error parsing %s results: %s", source, exc)
            return []

        # streamrip's AlbumSummary doesn't read Deezer's `nb_tracks`, so pull
        # the real track counts (and duration, when available) straight from
        # the raw response entries.
        album_meta = _extract_album_meta(pages)

        quality = self._get_quality(source)
        format_label = self._format_label(source, quality)

        normalised: list[SearchResult] = []
        for item in search_results.results:
            try:
                sr = self._normalise_summary(item, source, format_label, quality)
                if not sr:
                    continue
                info = album_meta.get(str(sr.release_id))
                if info:
                    if info.get("tracks"):
                        sr.num_tracks = info["tracks"]
                    sr.size_bytes = _estimate_size(
                        format_label, sr.num_tracks, info.get("duration")
                    )
                normalised.append(sr)
            except Exception as exc:
                logger.error("Error normalising %s result: %s", source, exc)
                continue

        return normalised

    def _get_quality(self, source: str) -> int:
        if source == "qobuz":
            return self._config.session.qobuz.quality
        elif source == "deezer":
            return self._config.session.deezer.quality
        return 2

    def _format_label(self, source: str, quality: int) -> str:
        if source == "qobuz":
            return "MP3" if quality <= 1 else "FLAC"
        elif source == "deezer":
            if quality == 0:
                return "MP3-128"
            elif quality == 1:
                return "MP3-320"
            else:
                return "FLAC"
        return "FLAC"

    def _normalise_summary(
        self, item, source: str, format_label: str, quality: int
    ) -> Optional[SearchResult]:
        artist = getattr(item, "artist", "") or ""
        name = getattr(item, "name", "") or ""
        title = name
        album = name
        num_tracks = int(getattr(item, "num_tracks", "1") or "1")

        size_bytes = _estimate_size(format_label, num_tracks)
        year = getattr(item, "date_released", "") or ""

        return SearchResult(
            source=source,
            release_id=item.id,
            media_type=item.media_type(),
            title=title,
            artist=artist,
            album=album,
            num_tracks=num_tracks,
            format_label=format_label,
            size_bytes=size_bytes,
            quality=quality,
            year=year,
        )

    async def featured(self, limit: int = 50) -> list[SearchResult]:
        if not self._ready:
            return []

        # When Lidarr RSS sync is configured, the empty-query feed reflects new
        # releases by the user's monitored artists rather than generic charts.
        if self._lidarr_sync and self._lidarr_sync.enabled:
            curated = await self._lidarr_sync.get_new_releases(limit)
            if curated:
                return curated
            logger.info("Lidarr feed empty; falling back to featured releases.")

        tasks = []
        if self._qobuz and self._qobuz.logged_in:
            tasks.append(self._featured_safe("qobuz", self._qobuz, limit))
        if self._deezer and self._deezer.logged_in:
            tasks.append(self._featured_safe("deezer", self._deezer, limit))

        if not tasks:
            return []

        results_lists = await asyncio.gather(*tasks, return_exceptions=True)
        merged: list[SearchResult] = []
        for result in results_lists:
            if isinstance(result, Exception):
                logger.error("Featured fetch error: %s", result)
                continue
            if isinstance(result, list):
                merged.extend(result)
        return merged

    async def _featured_safe(
        self, source: str, client, limit: int
    ) -> list[SearchResult]:
        try:
            if source == "qobuz":
                pages = await client.get_featured("new-releases", limit=limit)
                media_type = "album"
            else:
                # Deezer has no working "featured" endpoint in this streamrip
                # build (the editorial API omits the `total` key the parser
                # expects), so fall back to a real search. Empty queries come
                # from Lidarr's indexer test / RSS sync, which just need to see
                # some valid releases.
                from datetime import datetime
                fallback_query = str(datetime.now().year)
                pages = await client.search("album", fallback_query, limit=limit)
                media_type = "album"

            if not pages:
                return []

            results = self._build_results(source, pages, media_type)
        except Exception as exc:
            logger.error("Featured error on %s: %s", source, exc)
            return []

        await self._enrich_with_durations(source, client, results)
        logger.info("Featured: got %d results from %s", len(results), source)
        return results

    async def download(
        self,
        source: str,
        release_id: str,
        media_type: str = "album",
        progress_callback=None,
    ) -> str:
        client = self._qobuz if source == "qobuz" else self._deezer
        if client is None:
            raise RuntimeError(f"No client for source {source}")
        if not client.logged_in:
            raise RuntimeError(f"Client {source} is not logged in")

        logger.info("Starting download: source=%s id=%s type=%s", source, release_id, media_type)

        if media_type in ("album", "track"):
            pending = PendingAlbum(release_id, client, self._config, self._db) \
                if media_type == "album" else \
                PendingSingle(release_id, client, self._config, self._db)
        else:
            pending = PendingAlbum(release_id, client, self._config, self._db)

        logger.debug("Resolving %s:%s ...", source, release_id)
        try:
            media = await pending.resolve()
        except Exception as exc:
            raise RuntimeError(f"Resolve failed for {source}:{release_id}: {exc}") from exc

        if media is None:
            raise RuntimeError(f"Resolve returned None for {source}:{release_id}")

        logger.debug("Ripping %s:%s ...", source, release_id)
        if progress_callback:
            progress_callback(0.3)

        try:
            await media.rip()
        except Exception as exc:
            raise RuntimeError(f"Download failed for {source}:{release_id}: {exc}") from exc

        if progress_callback:
            progress_callback(1.0)

        actual_folder = getattr(media, "folder", self._config.session.downloads.folder)
        logger.info("Download completed: %s -> %s", release_id, actual_folder)
        return actual_folder


streamrip = StreamRipApi()
