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
CATEGORY_AUDIO_FLAC = 3020
CATEGORY_AUDIO_OTHER = 3030
CATEGORY_AUDIO_LOSSLESS = 3040
