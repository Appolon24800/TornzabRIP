import os

STREAMRIP_CONFIG_PATH = os.environ.get(
    "STREAMRIP_CONFIG_PATH",
    os.path.expanduser("~/.config/streamrip/config.toml"),
)
DOWNLOAD_TARGET_DIR = os.environ.get("DOWNLOAD_TARGET_DIR", "/data/downloads")
DEFAULT_PORT = int(os.environ.get("PORT", "8686"))

API_KEY = os.environ.get("TORZNABRIP_API_KEY", "")

SERVER_TITLE = "TorznabRIP"
SERVER_VERSION = "5.0.0"
WEB_API_VERSION = "2.9.0"

CATEGORY_AUDIO = 3000
CATEGORY_AUDIO_MP3 = 3010
CATEGORY_AUDIO_LOSSLESS = 3040
CATEGORY_AUDIO_OTHER = 3050

# --- Lidarr RSS sync (optional) -----------------------------------------------
# When both are set, the server periodically polls Lidarr for monitored artists,
# checks Deezer for releases that are new since the last run, and surfaces them
# in the indexer's RSS feed (empty-query / Lidarr RSS sync).
LIDARR_URL = os.environ.get("LIDARR_URL", "").rstrip("/")
LIDARR_API_KEY = os.environ.get("LIDARR_API_KEY", "")
RSS_SYNC_INTERVAL = int(os.environ.get("RSS_SYNC_INTERVAL", "3600"))
SEEN_RELEASES_FILE = os.environ.get(
    "SEEN_RELEASES_FILE",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "seen_releases.json"),
)
