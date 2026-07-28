from __future__ import annotations

import base64
import hashlib
import logging
from typing import Optional
from xml.etree.ElementTree import Element, SubElement, tostring

from fastapi import APIRouter, Query, Request, Response

from streamrip_api import streamrip, SearchResult
from config import (
    SERVER_TITLE,
    CATEGORY_AUDIO,
    CATEGORY_AUDIO_MP3,
    CATEGORY_AUDIO_OTHER,
    CATEGORY_AUDIO_LOSSLESS,
    API_KEY,
)

logger = logging.getLogger("torznabrip.torznab")

router = APIRouter(tags=["torznab"])


def encode_guid(source: str, release_id: str) -> str:
    raw = f"{source}:{release_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_guid(guid: str) -> tuple[str, str]:
    padding = 4 - len(guid) % 4
    if padding != 4:
        guid += "=" * padding
    raw = base64.urlsafe_b64decode(guid.encode()).decode()
    source, _, release_id = raw.partition(":")
    return source, release_id


def info_hash(guid: str) -> str:
    return hashlib.sha1(guid.encode()).hexdigest()


def _check_apikey(apikey: Optional[str]) -> bool:
    if not API_KEY:
        return True
    return apikey == API_KEY


CATEGORY_MAP = {
    "MP3": CATEGORY_AUDIO_MP3,
    "MP3-128": CATEGORY_AUDIO_MP3,
    "MP3-320": CATEGORY_AUDIO_MP3,
    "FLAC": CATEGORY_AUDIO_LOSSLESS,
}


def _category(format_label: str) -> int:
    return CATEGORY_MAP.get(format_label.upper(), CATEGORY_AUDIO)


def _generate_magnet(guid: str) -> str:
    ih = info_hash(guid)
    return f"magnet:?xt=urn:btih:{ih}&dn={guid}&tr=http://localhost:8686/announce"


def _make_rss_channel(request: Request) -> Element:
    rss = Element("rss", version="2.0", attrib={
        "xmlns:atom": "http://www.w3.org/2005/Atom",
        "xmlns:torznab": "http://torznab.com/schemas/2015/feed",
    })
    channel = SubElement(rss, "channel")
    SubElement(channel, "title").text = SERVER_TITLE
    SubElement(channel, "description").text = f"{SERVER_TITLE} — Torznab Indexer"
    SubElement(channel, "link").text = str(request.base_url).rstrip("/")
    atom_link = SubElement(channel, "{http://www.w3.org/2005/Atom}link")
    atom_link.set("href", str(request.url))
    atom_link.set("rel", "self")
    atom_link.set("type", "application/rss+xml")
    return rss


def _source_url(source: str, release_id: str) -> str:
    if source == "qobuz":
        return f"https://open.qobuz.com/album/{release_id}"
    elif source == "deezer":
        return f"https://www.deezer.com/album/{release_id}"
    return ""


def _item_xml(item: SearchResult, request: Request) -> Element:
    guid = encode_guid(item.source, item.release_id)
    hash_val = info_hash(guid)
    tracks = item.num_tracks or 0
    track_tag = f" [{tracks} track{'s' if tracks != 1 else ''}]" if tracks > 0 else ""
    title = f"{item.artist} - {item.album} [{item.format_label}] [{item.source.capitalize()}]{track_tag}"
    download_url = f"{request.base_url}download?id={guid}"
    external_url = _source_url(item.source, item.release_id)

    el = Element("item")
    SubElement(el, "title").text = title
    SubElement(el, "guid", isPermaLink="true").text = guid
    SubElement(el, "link").text = download_url
    SubElement(el, "comments").text = external_url or download_url
    SubElement(el, "pubDate").text = "Wed, 01 Jan 2025 00:00:00 +0000"
    SubElement(el, "category").text = str(_category(item.format_label))

    SubElement(el, "size").text = str(item.size_bytes)

    enc = SubElement(el, "enclosure")
    enc.set("url", download_url)
    enc.set("length", str(item.size_bytes))
    enc.set("type", "application/x-bittorrent")

    attrs = [
        ("seeders", "67"),
        ("leechers", "69"),
        ("downloadvolumefactor", "0"),
        ("uploadvolumefactor", "1"),
        ("minimumratio", "1"),
        ("minimumseedtime", "0"),
    ]
    for name, value in attrs:
        a = SubElement(el, "{http://torznab.com/schemas/2015/feed}attr")
        a.set("name", name)
        a.set("value", value)

    if item.artist:
        a = SubElement(el, "{http://torznab.com/schemas/2015/feed}attr")
        a.set("name", "artist")
        a.set("value", item.artist)
    if item.album:
        a = SubElement(el, "{http://torznab.com/schemas/2015/feed}attr")
        a.set("name", "album")
        a.set("value", item.album)

    magnet = _generate_magnet(guid)
    a = SubElement(el, "{http://torznab.com/schemas/2015/feed}attr")
    a.set("name", "magneturl")
    a.set("value", magnet)

    return el


@router.get("/api")
async def torznab(
    request: Request,
    t: str = Query("caps", description="Torznab function: caps, music, search"),
    q: str = Query("", description="Free-text search query"),
    artist: str = Query("", description="Artist name"),
    album: str = Query("", description="Album name"),
    track: str = Query("", description="Track title (unused, kept for compatibility)"),
    apikey: str = Query("", description="API key"),
    cat: str = Query("", description="Comma-separated category IDs to filter by"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    logger.info("Torznab request: %s?%s", request.url.path, request.url.query)

    if not _check_apikey(apikey):
        logger.warning("Torznab: invalid apikey=%s", apikey)
        return Response(content="Invalid API key", status_code=403)

    if t == "caps":
        return _caps(request)
    elif t in ("music", "search"):
        return await _search(request, t, q, artist, album, cat, limit, offset)

    logger.info("Torznab: unknown function t=%s", t)
    return Response(content="<error>Unknown function</error>", media_type="application/xml", status_code=400)


def _caps(request: Request):
    caps = Element("caps")
    server = SubElement(caps, "server")
    SubElement(server, "title").text = SERVER_TITLE
    SubElement(server, "strapline").text = "Bridging Lidarr with Qobuz & Deezer via StreamRip"

    searching = SubElement(caps, "searching")
    audio_search = SubElement(searching, "audio-search")
    audio_search.set("available", "yes")
    audio_search.set("supportedParams", "q,artist,album,track")

    music_search = SubElement(searching, "music-search")
    music_search.set("available", "yes")
    music_search.set("supportedParams", "q,artist,album,track")

    cats = SubElement(caps, "categories")
    for cat_id, cat_name in [
        (str(CATEGORY_AUDIO), "Audio"),
        (str(CATEGORY_AUDIO_MP3), "Audio/MP3"),
        (str(CATEGORY_AUDIO_LOSSLESS), "Audio/Lossless"),
        (str(CATEGORY_AUDIO_OTHER), "Audio/Other"),
    ]:
        cat = SubElement(cats, "category")
        cat.set("id", cat_id)
        cat.set("name", cat_name)

    xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n' + tostring(caps, encoding="unicode")
    return Response(content=xml_str, media_type="application/xml")


_ALL_AUDIO_SUBCATS = {3010, 3020, 3030, 3040, 3050, 3060}


def _category_passes(item_category: int, wanted_cats: set[int]) -> bool:
    if not wanted_cats:
        return True
    if item_category in wanted_cats:
        return True
    if 3000 in wanted_cats and item_category in _ALL_AUDIO_SUBCATS:
        return True
    return False


async def _search(
    request: Request,
    t: str,
    q: str,
    artist: str,
    album: str,
    cat: str,
    limit: int,
    offset: int,
):
    query = q.strip()
    artist = artist.strip()
    album = album.strip()

    wanted_cats: set[int] = set()
    if cat:
        for c in cat.split(","):
            try:
                wanted_cats.add(int(c.strip()))
            except ValueError:
                pass

    logger.info(
        "Torznab search: t=%s q=%r artist=%r album=%r cat=%r -> wanted_cats=%s limit=%d offset=%d",
        t, query, artist, album, cat, sorted(wanted_cats) if wanted_cats else "(none)", limit, offset,
    )

    results: list = []

    if query or artist or album:
        try:
            results = await streamrip.search(
                query=query, artist=artist, album=album,
                media_type="album", limit=limit,
            )
        except Exception as exc:
            logger.error("Search error: %s", exc)
    else:
        logger.info("Empty query, fetching featured releases instead.")
        try:
            results = await streamrip.featured(limit=limit)
        except Exception as exc:
            logger.error("Featured fetch error: %s", exc)

    logger.info("Streamrip returned %d raw results (before category filter):", len(results))
    for r in results:
        logger.info("  raw: source=%s release=%s format=%r -> cat=%d  (%s - %s)",
                    r.source, r.release_id, r.format_label, _category(r.format_label),
                    r.artist, r.album)

    pre_filter_count = len(results)
    if wanted_cats:
        kept = []
        for r in results:
            c = _category(r.format_label)
            passed = _category_passes(c, wanted_cats)
            logger.info("  filter: cat=%d wanted=%s -> %s  (%s - %s [%s])",
                        c, sorted(wanted_cats), "KEEP" if passed else "DROP",
                        r.artist, r.album, r.format_label)
            if passed:
                kept.append(r)
        results = kept
    logger.info("Category filter: %d -> %d results (wanted_cats=%s)",
                pre_filter_count, len(results),
                sorted(wanted_cats) if wanted_cats else "(none)")

    rss = _make_rss_channel(request)
    channel = rss.find("channel")
    if channel is None:
        channel = rss

    paginated = results[offset:offset + limit] if offset else results[:limit]

    for item in paginated:
        try:
            channel.append(_item_xml(item, request))
        except Exception as exc:
            logger.error("Error building item XML for %s: %s", item.release_id, exc)

    logger.info("Torznab search: returning %d items in XML (pre-filter=%d, post-filter=%d)",
                len(paginated), pre_filter_count, len(results))

    xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n' + tostring(rss, encoding="unicode")
    return Response(content=xml_str, media_type="application/xml")
