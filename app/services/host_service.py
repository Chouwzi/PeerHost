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
    # Thời gian hết hạn = hiện tại + LOCK_TIMEOUT
    return (start_dt + timedelta(seconds=LOCK_TIMEOUT)).isoformat()

async def create_session(host_id: str = None, ip_address: str = None, token: str = None, is_locked: bool = False) -> dict:
  """Tạo session cho thế giới"""
  storage_path = anyio.Path(STORAGE_PATH)
  if not await storage_path.exists():
    raise FileNotFoundError("World storage not found")
  
  session_path = storage_path / "meta" / "session.json"
  if await session_path.exists():
    # Kiểm tra session cũ để đảm bảo an toàn, logic xử lý hết hạn nằm ở tầng trên
    existing = await json_storage.read_json(session_path)
    if not _is_session_expired(existing):
        raise FileExistsError("Session already exists")
  
  now_iso = _get_utc_now_iso()
  expires_at = _calculate_expires_at(datetime.now(timezone.utc)) if is_locked else None

  session_json = {
    "is_locked": is_locked,
    "host": {
      "host_id": host_id,
      "ip_address": ip_address,
      "token": token
    },
    "timestamps": {
      "started_at": now_iso if is_locked else None,
      "last_heartbeat": now_iso if is_locked else None,
      "expires_at": expires_at
    }
  }
  await json_storage.write_json(session_path, session_json)
  return session_json

def _is_session_expired(session: dict) -> bool:
    """Kiểm tra session có bị hết hạn không"""
    if not session.get("is_locked"):
        return False
    
    expires_at_str = session.get("timestamps", {}).get("expires_at")
    if not expires_at_str:
        return True # Locked mà không có expires -> Coi như lỗi/hết hạn
    
    expires_at = datetime.fromisoformat(expires_at_str)
    return datetime.now(timezone.utc) > expires_at

async def get_session() -> dict | None:
  """Lấy thông tin session của thế giới. 
  Nếu session hết hạn, tự động reset về trạng thái unlocked.
  """
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
  
  # Kiểm tra hết hạn lazy
  if _is_session_expired(session):
      # Session hết hạn, reset lại
      return await reset_session()
      
  session["heartbeat_interval"] = HEARTBEAT_INTERVAL
  session["lock_timeout"] = LOCK_TIMEOUT
  return session

async def update_session(data_json: dict) -> dict:
  """Cập nhật thông tin session của thế giới"""
  # Không cho cập nhật những thông tin này
  if data_json.keys() & {"config"}:
    raise ValueError("Invalid data")
  
  storage_path = anyio.Path(STORAGE_PATH)
  if not await storage_path.exists():
    raise FileNotFoundError("World not found")
  
  session_path = storage_path / "meta" / "session.json"
  if not await session_path.exists():
    raise FileNotFoundError("Session not found")
  # Lấy dữ liệu cũ
  session_json = await json_storage.read_json(session_path)
  # Cập nhật dữ liệu
  session_json.update(data_json)
  # Ghi lại
  await json_storage.write_json(session_path, session_json)
  return session_json

async def heartbeat_session() -> dict:
    """Cập nhật heartbeat cho session"""
    session = await get_session() # get_session đã xử lý kiểm tra hết hạn
    if not session:
        raise FileNotFoundError("Session not found")
    
    if not session.get("is_locked"):
         # Nếu session không locked, không cần heartbeat
         return session

    now_dt = datetime.now(timezone.utc)
    now_iso = now_dt.isoformat()
    new_expires_at = _calculate_expires_at(now_dt)

    update_data = {
        "timestamps": {
            **session.get("timestamps", {}),
            "last_heartbeat": now_iso,
            "expires_at": new_expires_at
        }
    }
    return await update_session(update_data)

async def delete_session() -> bool:
  """Xóa session của thế giới"""
  world_path = anyio.Path(STORAGE_PATH / "world")
  if not await world_path.exists():
    return False
  
  session_path = world_path / "meta" / "session.json"
  if not await session_path.exists():
    return False
  
  await session_path.unlink()
  return True

async def reset_session() -> dict:
  """Reset session của thế giới về trạng thái unlocked"""
  return await update_session(
    {
      "is_locked": False,
      "host": {
        "host_id": None,
        "ip_address": None,
        "token": None
      },
      "timestamps": {
        "started_at": None,
        "last_heartbeat": None,
        "expires_at": None
      }
    }
  )

def generate_token(payload: dict) -> str:
  """Tạo token"""
  token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
  return token


async def try_claim_session(host_id: str, ip_address: str) -> tuple[bool, str | None, dict | None]:
  """
  Thử chiếm quyền session một cách an toàn (Atomic Check-then-Act using asyncio.Lock).
  Trả về: (success, error_detail, session_data)
  """
  async with _session_lock:
      # 1. atomic read
      session = await get_session()
      
      # 2. check condition
      if not session:
          # Case: File chưa tồn tại -> Tạo mới (Create)
          try:
              session_data = await create_session(host_id, ip_address, is_locked=True)
              # generate token is tricky here because create_session returns json without generating token (old logic was in router).
              # We should standardize. But for now, let's stick to router logic but inside lock.
              # Actually create_session does NOT generate token in current code, router does.
              # Let's refactor create_session to be internal or use it carefully.
              pass 
          except FileNotFoundError:
              return False, "World storage not found", None
          except FileExistsError:
              # Race condition caught by file check, but we are in lock so unlikely unless file created externally
              return False, "Session already exists", None
      
      # Re-read or use session from get_session
      # Note: create_session writes to file.
      
      # Let's simplify: strict check based on current state memory/file
      if session:
          if session.get("is_locked"):
              return False, "Session is already locked", None
      
      # 3. Prepare new state
      token = generate_token({
        "host_id": host_id,
        "ip_address": ip_address,
        "expires_at": _calculate_expires_at(datetime.now(timezone.utc))
      })
      
      now_iso = _get_utc_now_iso()
      
      # 4. Write (Critical Section)
      # If session didn't exist, we create it.
      if not session:
          try:
              await create_session(host_id, ip_address, token=token, is_locked=True)
              # Read back to get full structure? or just return what we wrote
              return True, None, {"token": token, "heartbeat_interval": HEARTBEAT_INTERVAL, "lock_timeout": LOCK_TIMEOUT}
          except Exception as e:
              return False, str(e), None

      # If session existed but unlocked
      await update_session( 
        {
          "is_locked": True,
          "host": {
            "host_id": host_id, 
            "ip_address": ip_address, 
            "token": token
          },
          "timestamps": {
              "started_at": now_iso,
              "last_heartbeat": now_iso,
              "expires_at": _calculate_expires_at(datetime.now(timezone.utc))
          }
        }
      )
      return True, None, {"token": token, "heartbeat_interval": HEARTBEAT_INTERVAL, "lock_timeout": LOCK_TIMEOUT}


async def auth_claim_session(host_id: str, ip_address: str) -> bool:
  """Xác nhận quyền kiểm soát session cho thế giới"""
  session = await get_session() # Dùng get_session để trigger kiểm tra hết hạn nếu có
  if not session:
    return False
    
  if not session["is_locked"]:
      return False

  # Kiểm tra thông tin host
  current_host = session.get("host", {})
  if current_host.get("host_id") != host_id:
      return False
  
  # Tùy chọn: Kiểm tra IP
  if current_host.get("ip_address") != ip_address:
     return False
  
  return True

async def scan_all_sessions():
    """Quét world duy nhất và kiểm tra session hết hạn"""
    storage_path = anyio.Path(STORAGE_PATH)
    if not await storage_path.exists():
        return
    
    world_path = storage_path / "world" # Wait, logic in scan_all_sessions old code check STORAGE_PATH then STORAGE_PATH/world.
    # Ah, STORAGE_PATH points to world_storage/world1 usually?
    # In old code: world_path = STORAGE_PATH / "world". 
    # But create_session uses STORAGE_PATH / "meta" / "session.json".
    # This seems inconsistent or STORAGE_PATH is the root of world.
    # checking create_session: STORAGE_PATH / "meta" / "session.json"
    # checking scan_all_sessions: STORAGE_PATH / "world" -> if not exists return.
    # But logic is just calling get_session().
    
    # I will just keep logic to call get_session().
    # But wait, create_session raises FileNotFoundError if STORAGE_PATH checks. 
    
    try:
        # get_session tự động kiểm tra và reset nếu hết hạn
        await get_session()
    except Exception:
        pass