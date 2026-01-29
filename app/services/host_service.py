from app.core.config import STORAGE_PATH, HEARTBEAT_INTERVAL, LOCK_TIMEOUT, SECRET_KEY, ALGORITHM
from datetime import datetime, timezone, timedelta
from app.utils import json_storage
from jose import jwt
import anyio
import asyncio

_session_lock = asyncio.Lock()

def _get_utc_now_iso() -> str:
    """Lấy thời gian UTC hiện tại dạng ISO 8601 string"""
    return datetime.now(timezone.utc).isoformat()

def _calculate_expires_at(start_time: str | datetime) -> str:
    """Tính thời gian hết hạn dựa trên start_time và LOCK_TIMEOUT"""
    if isinstance(start_time, str):
        start_dt = datetime.fromisoformat(start_time)
    else:
        start_dt = start_time
    return (start_dt + timedelta(seconds=LOCK_TIMEOUT)).isoformat()

def _is_session_expired(session: dict) -> bool:
    """Kiểm tra session có bị hết hạn không"""
    if not session.get("is_locked"):
        return False
    
    expires_at_str = session.get("timestamps", {}).get("expires_at")
    if not expires_at_str:
        return True
    
    expires_at = datetime.fromisoformat(expires_at_str)
    return datetime.now(timezone.utc) > expires_at

# --- INTERNAL METHODS (NO LOCK - CALLER MUST LOCK) ---

async def _get_session_internal() -> dict | None:
    """Internal: Read & Check Expiry. Caller must hold lock."""
    storage_path = anyio.Path(STORAGE_PATH)
    if not await storage_path.exists():
        return None
  
    session_path = storage_path / "meta" / "session.json"
    if not await session_path.exists():
        return None
  
    try:
        session = await json_storage.read_json(session_path)
    except:
        return None
  
    if _is_session_expired(session):
        return await _reset_session_internal()
      
    session["heartbeat_interval"] = HEARTBEAT_INTERVAL
    session["lock_timeout"] = LOCK_TIMEOUT
    return session

async def _update_session_internal(data_json: dict) -> dict:
    """Internal: Update session file. Caller must hold lock."""
    if data_json.keys() & {"config"}:
        raise ValueError("Invalid data")
    
    storage_path = anyio.Path(STORAGE_PATH)
    session_path = storage_path / "meta" / "session.json"
    
    if not await session_path.exists():
         raise FileNotFoundError("Session not found")
         
    session_json = await json_storage.read_json(session_path)
    session_json.update(data_json)
    await json_storage.write_json(session_path, session_json)
    return session_json

async def _create_session_internal(host_id: str = None, ip_address: str = None, token: str = None, is_locked: bool = False) -> dict:
    """Internal: Create session file. Caller must hold lock."""
    storage_path = anyio.Path(STORAGE_PATH)
    if not await storage_path.exists():
        raise FileNotFoundError("World storage not found")
    
    session_path = storage_path / "meta" / "session.json"
    # Note: caller should have checked existence if strict, but safe to overwrite or check here
    
    now_iso = _get_utc_now_iso()
    expires_at = _calculate_expires_at(datetime.now(timezone.utc)) if is_locked else None

    session_json = {
        "is_locked": is_locked,
        "host": {"host_id": host_id, "ip_address": ip_address, "token": token},
        "timestamps": {
            "started_at": now_iso if is_locked else None,
            "last_heartbeat": now_iso if is_locked else None,
            "expires_at": expires_at
        }
    }
    await json_storage.write_json(session_path, session_json)
    return session_json

async def _reset_session_internal() -> dict:
    """Internal: Reset session. Caller must hold lock."""
    try:
        return await _update_session_internal({
            "is_locked": False,
            "host": {"host_id": None, "ip_address": None, "token": None},
            "timestamps": {"started_at": None, "last_heartbeat": None, "expires_at": None}
        })
    except FileNotFoundError:
        return {} # Already deleted?

# --- PUBLIC METHODS (WITH LOCK) ---

async def get_session() -> dict | None:
    async with _session_lock:
        return await _get_session_internal()

async def update_session(data_json: dict) -> dict:
    async with _session_lock:
        return await _update_session_internal(data_json)

async def heartbeat_session() -> dict:
    async with _session_lock:
        session = await _get_session_internal()
        if not session:
             raise FileNotFoundError("Session not found")
        
        if not session.get("is_locked"):
             return session

        now_dt = datetime.now(timezone.utc)
        update_data = {
            "timestamps": {
                **session.get("timestamps", {}),
                "last_heartbeat": now_dt.isoformat(),
                "expires_at": _calculate_expires_at(now_dt)
            }
        }
        return await _update_session_internal(update_data)

async def reset_session() -> dict:
    async with _session_lock:
        return await _reset_session_internal()

async def delete_session() -> bool:
     async with _session_lock:
        world_path = anyio.Path(STORAGE_PATH / "world_data")
        session_path = world_path / "meta" / "session.json"
        if await session_path.exists():
            await session_path.unlink()
            return True
        return False

# --- UTILS ---

def generate_token(payload: dict) -> str:
  return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

async def try_claim_session(host_id: str, ip_address: str) -> tuple[bool, str | None, dict | None]:
    """Atomic Claim Session"""
    async with _session_lock:
        session = await _get_session_internal()
        
        # 1. Check if needs creation
        if not session:
            try:
                # Create unlocked first / or locked directly. 
                # Let's create unlocked then lock to match logic flow or create locked.
                token = generate_token({
                    "host_id": host_id, "ip_address": ip_address,
                    "expires_at": _calculate_expires_at(datetime.now(timezone.utc))
                })
                await _create_session_internal(host_id, ip_address, token, is_locked=True)
                return True, None, {"token": token, "heartbeat_interval": HEARTBEAT_INTERVAL, "lock_timeout": LOCK_TIMEOUT}
            except FileNotFoundError:
                return False, "World storage not found", None
        
        # 2. Check lock status
        if session.get("is_locked"):
             return False, "Session is already locked", None
             
        # 3. Lock it
        token = generate_token({
            "host_id": host_id, "ip_address": ip_address,
            "expires_at": _calculate_expires_at(datetime.now(timezone.utc))
        })
        
        now_iso = _get_utc_now_iso()
        await _update_session_internal({
          "is_locked": True,
          "host": {"host_id": host_id, "ip_address": ip_address, "token": token},
          "timestamps": {
              "started_at": now_iso, "last_heartbeat": now_iso,
              "expires_at": _calculate_expires_at(datetime.now(timezone.utc))
          }
        })
        return True, None, {"token": token, "heartbeat_interval": HEARTBEAT_INTERVAL, "lock_timeout": LOCK_TIMEOUT}

async def auth_claim_session(host_id: str, ip_address: str) -> bool:
    async with _session_lock:
        session = await _get_session_internal()
        if not session or not session["is_locked"]:
            return False
            
        current_host = session.get("host", {})
        if current_host.get("host_id") != host_id:
            return False
        if current_host.get("ip_address") != ip_address:
            return False
        return True

async def scan_all_sessions():
    """Background Task"""
    # Just call public get_session which handles locking & expiration
    try:
        await get_session()
    except Exception:
        pass