import json
from pathlib import Path

STORAGE_PATH = Path(__file__).parent.parent / "storage"
WORLD_DATA_PATH = STORAGE_PATH / "world_data"

DB_PATH = STORAGE_PATH / "meta" / "file_index.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

DATABASE_URL = f"sqlite:///{DB_PATH}"

# Load all settings from JSON
SETTINGS_PATH = Path("app/settings.json")
_settings = {}
if SETTINGS_PATH.exists():
    with open(SETTINGS_PATH, "r") as f:
        _settings = json.load(f)

HEARTBEAT_INTERVAL = _settings.get("heartbeat_interval", 10)
LOCK_TIMEOUT = _settings.get("lock_timeout", 60)

# Security settings (previously from .env)
SECRET_KEY = _settings.get("secret_key", "")
ALGORITHM = _settings.get("algorithm", "HS256")

# Tunnel settings for client
TUNNEL_NAME = _settings.get("tunnel_name", "PeerHost")
GAME_HOSTNAME = _settings.get("game_hostname", "")
GAME_LOCAL_PORT = _settings.get("game_local_port", 2812)