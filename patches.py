"""Runtime patches over the pinned streamrip build, kept in one place.

Two things live here:

1. ``DeezerDownloadable._download`` is replaced with a streaming version.
   Upstream buffers the *entire* encrypted track in a ``bytearray`` before
   decrypting and writing it, so every concurrent track holds its full file
   size in RAM (a FLAC album rip with 6 concurrent tracks can transiently
   occupy several hundred MB, and the freed heap is not returned to the OS,
   so RSS ratchets up and stays there). Deezer's frame encryption decrypts
   each 2048-byte block independently (fixed IV, new cipher per block), so
   the stream can be decrypted and written frame-by-frame with a bounded
   buffer and byte-identical output.

2. ``trim_memory()`` calls ``malloc_trim(0)`` so the glibc heap (which held
   those large transients) is handed back to the kernel after each job.
"""

from __future__ import annotations

import ctypes
import json
import logging
from typing import Callable

import aiofiles

from streamrip.client.downloadable import (
    DeezerDownloadable,
    fast_async_download,
)
from streamrip.exceptions import NonStreamableError

logger = logging.getLogger("torznabrip.patches")

_ENC_CHUNK = 2048
_FRAME_SIZE = 3 * _ENC_CHUNK  # Deezer frame: 2048 encrypted bytes + 4096 plain


def trim_memory() -> None:
    """Return free heap pages to the OS. No-op where libc is unavailable."""
    try:
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except Exception:
        pass


def _decrypt_frames(data: bytes | bytearray, key: bytes) -> bytearray:
    """Decrypt complete Deezer frames exactly like upstream's buffered loop.

    Every 6144-byte frame starts with one 2048-byte Blowfish-CBC block;
    a trailing partial frame decrypts its first 2048 bytes only when at
    least that many bytes remain.
    """
    out = bytearray()
    decrypt = DeezerDownloadable._decrypt_chunk
    for i in range(0, len(data), _FRAME_SIZE):
        frame = data[i : i + _FRAME_SIZE]
        if len(frame) >= _ENC_CHUNK:
            out += decrypt(key, frame[:_ENC_CHUNK])
            out += frame[_ENC_CHUNK:]
        else:
            out += frame
    return out


async def _streaming_download(self, path: str, callback: Callable[[int], None]):
    """Drop-in replacement for DeezerDownloadable._download with O(64KB) RAM."""
    async with self.session.get(self.url, allow_redirects=True) as resp:
        resp.raise_for_status()
        self._size = int(resp.headers.get("Content-Length", 0))
        if self._size < 20000 and not self.url.endswith(".jpg"):
            try:
                info = await resp.json()
                try:
                    # Usually happens with deezloader downloads
                    raise NonStreamableError(f"{info['error']} - {info['message']}")
                except KeyError:
                    raise NonStreamableError(info)
            except json.JSONDecodeError:
                raise NonStreamableError("File not found.")

        if self.is_encrypted.search(self.url) is None:
            await fast_async_download(
                path, self.url, self.session.headers, callback
            )
            return

        key = self._generate_blowfish_key(self.id)
        tail = bytearray()
        async with aiofiles.open(path, "wb") as audio:
            async for data, _ in resp.content.iter_chunks():
                callback(len(data))
                tail += data
                end = len(tail) // _FRAME_SIZE * _FRAME_SIZE
                if not end:
                    continue
                await audio.write(_decrypt_frames(tail[:end], key))
                del tail[:end]
            if tail:
                await audio.write(_decrypt_frames(tail, key))


_applied = False


def apply_patches() -> None:
    """Install the patches once, before any download can start."""
    global _applied
    if _applied:
        return
    DeezerDownloadable._download = _streaming_download
    _applied = True
    logger.info("Applied streamrip patches: streaming Deezer downloads.")
