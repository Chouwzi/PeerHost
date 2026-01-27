"""
Manifest Service - Scan world files and generate manifest
"""

import hashlib
from pathlib import Path
from typing import List, Dict
import anyio
from app.core.config import STORAGE_PATH, WORLD_DATA_PATH


async def calculate_file_hash(file_path: anyio.Path) -> str:
    """Calculate SHA256 hash of a file asynchronously"""
    sha256_hash = hashlib.sha256()
    
    async with await anyio.open_file(file_path, "rb") as f:
        while True:
            chunk = await f.read(8192)
            if not chunk:
                break
            sha256_hash.update(chunk)
    
    return sha256_hash.hexdigest()


async def scan_world_files() -> List[Dict]:
    """
    Scan all files in world storage and return manifest.
    
    Returns:
        List of file info dicts: [{path, hash, size}, ...]
    """
    root_path = anyio.Path(WORLD_DATA_PATH)
    
    if not await root_path.exists():
        return []
    
    files = []
    
    # Scan recursively for all files
    for sync_path in Path(root_path).rglob("*"):
        if sync_path.is_file():
            # Skip meta folder (session.json, etc.)
            if "meta" in sync_path.parts:
                continue
                
            # Skip lock files and temp files
            if sync_path.name.endswith((".lock", ".tmp", ".log")):
                continue
            
            async_path = anyio.Path(sync_path)
            
            try:
                # Get relative path from root folder
                relative_path = sync_path.relative_to(root_path).as_posix()
                
                # Calculate hash
                file_hash = await calculate_file_hash(async_path)
                
                # Get size
                stat = await async_path.stat()
                
                files.append({
                    "path": relative_path,
                    "hash": file_hash,
                    "size": stat.st_size
                })
            except Exception as e:
                # Skip files that can't be read
                continue
    
    return files


async def get_manifest() -> Dict:
    """
    Get full world manifest with file list and totals.
    
    Returns:
        {files: [...], total_files: int, total_size: int}
    """
    files = await scan_world_files()
    
    total_size = sum(f["size"] for f in files)
    
    return {
        "files": files,
        "total_files": len(files),
        "total_size": total_size
    }
