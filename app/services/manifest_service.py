"""
Manifest Service - Scan world files and generate manifest
"""

import hashlib
from pathlib import Path
from typing import List, Dict, Tuple
import anyio
from app.core.config import STORAGE_PATH, WORLD_DATA_PATH

# --- STAT CACHE IMPLEMENTATION ---
class StatCache:
    """
    In-memory cache for file hashes based on path, mtime, and size.
    Prevents re-hashing large files if they haven't changed.
    """
    def __init__(self):
        # Key: file_path (str), Value: (mtime, size, hash)
        self._cache: Dict[str, Tuple[float, int, str]] = {}
    
    def get(self, path: str, mtime: float, size: int) -> str | None:
        if path in self._cache:
            cached_mtime, cached_size, cached_hash = self._cache[path]
            if cached_mtime == mtime and cached_size == size:
                return cached_hash
        return None

    def set(self, path: str, mtime: float, size: int, file_hash: str):
        self._cache[path] = (mtime, size, file_hash)

    def clear(self):
        self._cache.clear()

# Global singleton cache instance
# Note: In a multi-worker implementation (e.g. gunicorn w/ multiple workers), 
# this cache would be per-worker. This is acceptable as each worker needs its own cache anyway.
_stat_cache = StatCache()


def _calculate_file_hash_sync(file_path: Path) -> str:
    """
    Synchronous function to calculate SHA256. 
    Intended to be run in a thread to avoid blocking the event loop.
    """
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        # Read in larger chunks (64KB) for efficiency
        for byte_block in iter(lambda: f.read(65536), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


async def calculate_file_hash(file_path: anyio.Path) -> str:
    """
    Calculate SHA256 hash of a file.
    Offloads to a thread for CPU-bound work.
    """
    # Convert anyio.Path to standard pathlib.Path for sync operation
    sync_path = Path(str(file_path))
    
    # Run in thread pool to prevent blocking the async event loop
    return await anyio.to_thread.run_sync(_calculate_file_hash_sync, sync_path)


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
    
    # 1. Glob all files first (IO bound-ish)
    # Using scandir via pathlib is generally fast.
    # We use sync Path.rglob because anyio doesn't fully replace pathlib's globbing convenience yet
    # and globbing is usually fast enough. If blocking is an issue, we can wrap this too.
    sync_root = Path(WORLD_DATA_PATH)
    
    # Performance: Scan logic
    try:
        all_files = [f for f in sync_root.rglob("*") if f.is_file()]
    except Exception:
        return []

    for sync_path in all_files:
        # Skip meta folder (session.json, etc.)
        if "meta" in sync_path.parts:
            continue
            
        # Skip lock files and temp files
        if sync_path.name.endswith((".lock", ".tmp", ".log")):
            continue
        
        try:
            # Get relative path from root folder
            relative_path = sync_path.relative_to(WORLD_DATA_PATH).as_posix()
            
            # Get stat info (Sync stat is fast on SSDs, but strictly should be async if paranoid)
            # We'll stick to os.stat for speed in this loop, or use the path obj.
            stat = sync_path.stat()
            mtime = stat.st_mtime
            size = stat.st_size
            
            # 2. Check Cache
            cached_hash = _stat_cache.get(relative_path, mtime, size)
            
            if cached_hash:
                file_hash = cached_hash
            else:
                # 3. Cache Miss -> Calculate Hash (Offloaded)
                # We use the async wrapper which calls to_thread
                async_path = anyio.Path(sync_path)
                file_hash = await calculate_file_hash(async_path)
                
                # Update Cache
                _stat_cache.set(relative_path, mtime, size, file_hash)
            
            files.append({
                "path": relative_path,
                "hash": file_hash,
                "size": size
            })
        except Exception as e:
            # Skip files that can't be read or race condition deleted
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

def clear_cache():
    """Utility to clear cache (e.g. for testing)"""
    _stat_cache.clear()
