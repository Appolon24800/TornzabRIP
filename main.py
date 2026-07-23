from __future__ import annotations

import hashlib
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import PlainTextResponse

from config import (
    DEFAULT_PORT,
    DOWNLOAD_TARGET_DIR,
    SERVER_TITLE,
)
from job_store import store, DownloadJob, JobState
from streamrip_api import streamrip, SearchResult
from torznab import decode_guid, encode_guid, info_hash, router as torznab_router
from qbittorrent import router as qbit_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("torznabrip")

logging.getLogger("streamrip").setLevel(logging.WARNING)
logging.getLogger("aiohttp").setLevel(logging.WARNING)
logging.getLogger("deezer").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting %s on port %d ...", SERVER_TITLE, DEFAULT_PORT)
    os.makedirs(DOWNLOAD_TARGET_DIR, exist_ok=True)
    store.load()
    await streamrip.startup()
    yield
    await streamrip.shutdown()
    logger.info("%s shut down.", SERVER_TITLE)


app = FastAPI(
    title=SERVER_TITLE,
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(torznab_router)
app.include_router(qbit_router)


def _bencode_str(s: str) -> bytes:
    b = s.encode("utf-8")
    return str(len(b)).encode() + b":" + b


def _bencode_int(i: int) -> bytes:
    return b"i" + str(i).encode() + b"e"


def _bencode_dict(d: dict) -> bytes:
    parts = []
    for k in sorted(d.keys()):
        parts.append(_bencode_str(k))
        v = d[k]
        if isinstance(v, str):
            parts.append(_bencode_str(v))
        elif isinstance(v, int):
            parts.append(_bencode_int(v))
        elif isinstance(v, bytes):
            parts.append(_bencode_str(v.decode()) if v else b"0:")
        else:
            parts.append(_bencode_str(str(v)))
    return b"d" + b"".join(parts) + b"e"


def _generate_torrent(guid: str) -> bytes:
    source, release_id = decode_guid(guid)
    title = f"{source.upper()}: {release_id}"
    comment = f"guid:{guid}"

    result = b"d"
    result += _bencode_str("comment") + _bencode_str(comment)
    result += _bencode_str("created by") + _bencode_str("TorznabRIP")
    result += _bencode_str("creation date") + _bencode_int(1700000000)
    result += _bencode_str("encoding") + _bencode_str("UTF-8")

    result += _bencode_str("info")
    result += b"d"
    result += _bencode_str("length") + _bencode_int(0)
    result += _bencode_str("name") + _bencode_str(title)
    result += _bencode_str("piece length") + _bencode_int(262144)
    result += _bencode_str("pieces") + _bencode_str("")
    result += b"e"

    result += b"e"
    return result


def _generate_magnet(guid: str) -> str:
    source, release_id = decode_guid(guid)
    title = f"{source.upper()}: {release_id}"
    ih = info_hash(guid)
    return f"magnet:?xt=urn:btih:{ih}&dn={title}&tr=http://localhost:8686/announce"


@app.get("/download")
async def download_torrent(
    request: Request,
    id: str = Query(..., description="Encoded guid"),
):
    try:
        source, release_id = decode_guid(id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid guid: {exc}")

    logger.info("/download: source=%s release_id=%s", source, release_id)

    torrent_data = _generate_torrent(id)

    filename = f"{release_id}.torrent"
    return Response(
        content=torrent_data,
        media_type="application/x-bittorrent",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@app.get("/announce/{guid}")
async def announce(guid: str):
    return PlainTextResponse(
        "d8:intervali1800e5:peerslee",
        media_type="text/plain",
    )


@app.get("/")
async def root():
    return {
        "server": SERVER_TITLE,
        "torznab": "/api",
        "qbittorrent_api": "/api/v2",
        "download": "/download?id=<guid>",
    }


if __name__ == "__main__":
    import uvicorn
    import sys

    port = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT

    print(f"""
╔══════════════════════════════════════════════════════════╗
║                    TorznabRIP v1.0.0                      ║
╠══════════════════════════════════════════════════════════╣
║  Lidarr Indexer URL:                                     ║
║    http://localhost:{port}/api                             ║
║                                                          ║
║  Lidarr Download Client:                                 ║
║    http://localhost:{port}                                 ║
║    Type: qBittorrent                                     ║
╠══════════════════════════════════════════════════════════╣
║  Download target:                                        ║
║    {DOWNLOAD_TARGET_DIR}
╠══════════════════════════════════════════════════════════╣
║  Sources: Qobuz + Deezer via StreamRip                   ║
╚══════════════════════════════════════════════════════════╝
    """.strip())

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        log_level="info",
        reload=False,
    )
