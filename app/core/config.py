from dotenv import load_dotenv
load_dotenv()

import os
from pathlib import Path

import json

STORAGE_PATH = Path(os.getenv("STORAGE_PATH", str(Path(__file__).parent.parent / "storage")))

DB_PATH = STORAGE_PATH / "meta" / "file_index.db"
DATABASE_URL = f"sqlite:///.{str(DB_PATH)}"

# Load non-secret settings from JSON
SETTINGS_PATH = Path("app/settings.json")
_settings = {}
if SETTINGS_PATH.exists():
    with open(SETTINGS_PATH, "r") as f:
        _settings = json.load(f)

HEARTBEAT_INTERVAL = _settings.get("heartbeat_interval", 10)
LOCK_TIMEOUT = _settings.get("lock_timeout", 60)

SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = os.getenv("ALGORITHM")