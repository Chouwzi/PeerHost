from dotenv import load_dotenv
load_dotenv()

import os
from pathlib import Path

WORLD_ID = os.getenv("WORLD_ID")
STORAGE_PATH = Path(os.getenv("STORAGE_PATH"))

DB_PATH = STORAGE_PATH / "worlds" / WORLD_ID / "meta" / "file_index.db"
DATABASE_URL = f"sqlite:///.{str(DB_PATH)}"