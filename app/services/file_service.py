import hashlib
from pathlib import Path
import anyio
from app.core.config import STORAGE_PATH
from app.services import host_service

# Danh sách file bị cấm ghi từ Client (Server-side Enforcement)
RESTRICTED_PATTERNS = {
    "server.properties",
    "permissions.json",
    "ops.json",
    "whitelist.json",
    "banned-players.json",
    "banned-ips.json",
    "eula.txt",
    "server.jar",
}

# Danh sách file nên bị bỏ qua (Garbage/Temp files/Executables)
IGNORED_PATTERNS = {
    "*.tmp",
    "*.log",
    "*.lock",
    "desktop.ini",
    ".DS_Store",
    "__pycache__/*",
    "*.bak",
    "*~",
}

from app.core.config import SETTINGS_PATH
import json

def get_sync_config() -> dict:
    """Trả về cấu hình Sync cho Client."""
    start_command = None
    if SETTINGS_PATH.exists():
        try:
            with open(SETTINGS_PATH, "r") as f:
                settings = json.load(f)
                start_command = settings.get("start_command")
        except:
            pass

    return {
        "restricted": list(RESTRICTED_PATTERNS),
        "ignored": list(IGNORED_PATTERNS),
        "start_command": start_command
    }

from typing import AsyncGenerator

async def save_file(host_id: str, relative_path: str, content_stream: AsyncGenerator[bytes, None], client_hash: str) -> None:
    """
    Lưu file từ Client gửi lên theo cơ chế Streaming.
    
    Args:
        host_id: ID của Host đang gửi.
        relative_path: Đường dẫn tương đối của file.
        content_stream: Stream nội dung file (AsyncGenerator).
        client_hash: Checksum SHA256 do Client tính.
        
    Raises:
        ValueError: Nếu hash sai hoặc path không hợp lệ.
        PermissionError: Nếu file nằm trong blacklist.
    """
    # 1. Security Check (Path Validation)
    if relative_path in RESTRICTED_PATTERNS:
        raise PermissionError(f"File '{relative_path}' is restricted and cannot be modified by client.")
    
    # Check ignored patterns
    import fnmatch
    for pattern in IGNORED_PATTERNS:
        if fnmatch.fnmatch(relative_path, pattern):
             raise PermissionError(f"File '{relative_path}' is ignored by server policy.")

    # Preventing directory traversal attacks (e.g., ../../etc/passwd)
    if ".." in relative_path or relative_path.startswith("/"):
         raise ValueError("Invalid file path.")

    # 3. Storage Path Resolution (Chuẩn bị đường dẫn)
    root_path = anyio.Path(STORAGE_PATH)
    if not await root_path.exists():
        await root_path.mkdir(parents=True, exist_ok=True)
        
    target_path = root_path / relative_path
    
    # SECURITY: Prevent access to meta folder
    if "meta" in Path(relative_path).parts:
         raise PermissionError("Access to meta folder is restricted.")

    # 4. Async Write & Hashing Streaming
    # Ensure parent dir exists
    await target_path.parent.mkdir(parents=True, exist_ok=True)
    
    hasher = hashlib.sha256()
    
    # Ghi vào file tạm trước để tránh corrupt file thật nếu upload lỗi
    # Note: Use string concat to APPEND .upload_tmp (with_suffix replaces entire suffix)
    temp_path = anyio.Path(str(target_path) + ".upload_tmp")
    
    try:
        async with await anyio.open_file(temp_path, "wb") as f:
            async for chunk in content_stream:
                hasher.update(chunk)
                await f.write(chunk)
                
        # 5. Integrity Check
        server_hash = hasher.hexdigest()
        if server_hash != client_hash:
            # Xóa file tạm nếu sai hash
            await temp_path.unlink(missing_ok=True)
            raise ValueError(f"Integrity Mismatch! Client: {client_hash}, Server: {server_hash}")
            
        # 6. Commit (Move temp to real)
        # On Windows, rename fails if target exists - delete first
        import os
        if os.name == 'nt' and await target_path.exists():
            try:
                await target_path.unlink()
            except PermissionError:
                # File might be locked, try to wait and retry
                import time
                time.sleep(0.1)
                await target_path.unlink()
        
        await temp_path.rename(target_path)
            
    except Exception as e:
        # Clean up temp file on error
        import traceback
        print(f"[FILE_SERVICE ERROR] save_file failed for '{relative_path}':")
        print(f"  Exception: {type(e).__name__}: {e}")
        print(f"  Traceback: {traceback.format_exc()}")
        await temp_path.unlink(missing_ok=True)
        raise e

async def get_file(relative_path: str) -> bytes | None:
    """Đọc file để phục vụ Auto-Revert hoặc Download."""
    # SECURITY: Prevent access to meta folder
    if "meta" in Path(relative_path).parts:
         return None
         
    root_path = anyio.Path(STORAGE_PATH)
    target_path = root_path / relative_path
    
    if not await target_path.exists():
        return None
        
    async with await anyio.open_file(target_path, "rb") as f:
        return await f.read()
