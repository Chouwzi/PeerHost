
import os
import hashlib
from typing import List, Dict
from pathlib import Path
from fastapi import UploadFile

# We assume there is a "source_client" folder that contains the latest client code.
# In a real deployment, this might be a separate repo or a specific build artifact.
# For this dev setup, we will serve the current 'client' folder itself or a copy.
# Ideally, we should have a `release/client` folder.
# For simplicity, we will serve `client/` but EXCLUDE `client/world` and `client/settings.json`.

PROJECT_ROOT = Path(".").absolute()
SOURCE_CLIENT_DIR = PROJECT_ROOT / "client" 
REQUIREMENTS_FILE = SOURCE_CLIENT_DIR / "requirements.txt"

def calculate_file_hash(file_path: Path) -> str:
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()

class DistributionService:
    def get_client_manifest(self) -> Dict:
        """
        Scan source_client directory and return list of files and hashes.
        Excludes user-specific data (world, settings.json, logs, temp).
        """
        files = []
        
        # 1. Scan client/ directory
        if SOURCE_CLIENT_DIR.exists():
            for sync_path in SOURCE_CLIENT_DIR.rglob("*"):
                if sync_path.is_file():
                    # Check exclusions
                    rel_path = sync_path.relative_to(SOURCE_CLIENT_DIR).as_posix()
                    
                    if any(x in rel_path for x in ["__pycache__", ".git", ".venv", "world", "logs", ".pytest_cache"]):
                        continue
                    
                    if sync_path.name in ["settings.json", "launcher.py"]: 
                        # launcher.py usually shouldn't update itself easily while running, 
                        # but we can include it if we have a strategy. Exclude for safety now.
                        # settings.json must NOT be overwritten.
                        continue
                        
                    if sync_path.suffix in [".tmp", ".log"]:
                        continue
                        
                    files.append({
                        "path": rel_path,
                        "hash": calculate_file_hash(sync_path)
                    })
        
        # 2. Include requirements.txt from root
        if REQUIREMENTS_FILE.exists():
             files.append({
                 "path": "requirements.txt",
                 "hash": calculate_file_hash(REQUIREMENTS_FILE)
             })
             
        return {
            "version": "1.0.0", # TODO: Dynamic versioning
            "files": files
        }

    def get_client_file_path(self, relative_path: str) -> Path | None:
        """Return the absolute path to a requested client file."""
        if relative_path == "requirements.txt":
            return REQUIREMENTS_FILE if REQUIREMENTS_FILE.exists() else None
            
        target_path = SOURCE_CLIENT_DIR / relative_path
        
        # Security check to prevent path traversal
        try:
             target_path.resolve().relative_to(SOURCE_CLIENT_DIR.resolve())
        except ValueError:
             return None
             
        if target_path.exists() and target_path.is_file():
            return target_path
            
        return None
