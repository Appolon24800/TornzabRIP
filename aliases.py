from __future__ import annotations

import json
import logging
import os

from config import ARTIST_ALIASES_FILE

logger = logging.getLogger("torznabrip.aliases")


class Aliases:
    """Bidirectional artist-name aliases loaded from a JSON file.

    Keys are names as Lidarr knows them (e.g. a MusicBrainz kanji name);
    values are the names the streaming catalogs actually index. Loaded at
    startup and reloaded whenever the file's mtime changes, so edits take
    effect without a restart.
    """

    def __init__(self, path: str = ARTIST_ALIASES_FILE) -> None:
        self.path = path
        self._forward: dict[str, str] = {}
        self._reverse: dict[str, str] = {}
        self._mtime: float | None = None
        self.reload()

    def reload(self) -> None:
        try:
            mtime = os.path.getmtime(self.path)
        except OSError:
            self._forward, self._reverse, self._mtime = {}, {}, None
            return
        if mtime == self._mtime:
            return
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            forward = {
                str(k): str(v)
                for k, v in data.items()
                if str(k).strip() and str(v).strip()
            }
        except Exception as exc:
            logger.warning("Could not load artist aliases from %s: %s", self.path, exc)
            return
        reverse: dict[str, str] = {}
        for key, value in forward.items():
            reverse.setdefault(value.strip().lower(), key)
        self._forward, self._reverse, self._mtime = forward, reverse, mtime
        logger.info("Loaded %d artist alias(es) from %s", len(forward), self.path)

    def rewrite(self, text: str) -> str:
        """Replace local names with the catalog names in a search query."""
        self.reload()
        if not text or not self._forward:
            return text
        out = text
        for key in sorted(self._forward, key=len, reverse=True):
            if key in out:
                out = out.replace(key, self._forward[key])
        return " ".join(out.split()) if out != text else out

    def display(self, artist: str) -> str:
        """Map a catalog artist name back to the local (Lidarr) name."""
        self.reload()
        if not artist:
            return artist
        return self._reverse.get(artist.strip().lower(), artist)


aliases = Aliases()
