from app.core.config import STORAGE_PATH, HEARTBEAT_INTERVAL, LOCK_TIMEOUT, SECRET_KEY, ALGORITHM
from datetime import datetime, timezone, timedelta
from app.utils import json_storage
from jose import jwt

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

def create_session(host_id: str = None, ip_address: str = None, token: str = None, is_locked: bool = False) -> dict:
  """Tạo session cho thế giới"""
  if not STORAGE_PATH.exists():
    raise FileNotFoundError("World storage not found")
  
  session_path = STORAGE_PATH / "meta" / "session.json"
  if session_path.exists():
    # Kiểm tra session cũ để đảm bảo an toàn, logic xử lý hết hạn nằm ở tầng trên
    existing = json_storage.read_json(session_path)
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
  json_storage.write_json(session_path, session_json)
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

def get_session() -> dict | None:
  """Lấy thông tin session của thế giới. 
  Nếu session hết hạn, tự động reset về trạng thái unlocked.
  """
  if not STORAGE_PATH.exists():
    return None
  
  session_path = STORAGE_PATH / "meta" / "session.json"
  if not session_path.exists():
    return None
  
  session = json_storage.read_json(session_path)
  
  # Kiểm tra hết hạn lazy
  if _is_session_expired(session):
      # Session hết hạn, reset lại
      return reset_session()
      
  session["heartbeat_interval"] = HEARTBEAT_INTERVAL
  session["lock_timeout"] = LOCK_TIMEOUT
  return session

def update_session(data_json: dict) -> dict:
  """Cập nhật thông tin session của thế giới"""
  # Không cho cập nhật những thông tin này
  if data_json.keys() & {"config"}:
    raise ValueError("Invalid data")
  
  if not STORAGE_PATH.exists():
    raise FileNotFoundError("World not found")
  
  session_path = STORAGE_PATH / "meta" / "session.json"
  if not session_path.exists():
    raise FileNotFoundError("Session not found")
  # Lấy dữ liệu cũ
  session_json = json_storage.read_json(session_path)
  # Cập nhật dữ liệu
  session_json.update(data_json)
  # Ghi lại
  json_storage.write_json(session_path, session_json)
  return session_json

def heartbeat_session() -> dict:
    """Cập nhật heartbeat cho session"""
    session = get_session() # get_session đã xử lý kiểm tra hết hạn
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
    return update_session(update_data)

def delete_session() -> bool:
  """Xóa session của thế giới"""
  world_path = STORAGE_PATH / "world"
  if not world_path.exists():
    return False
  
  session_path = world_path / "meta" / "session.json"
  if not session_path.exists():
    return False
  
  session_path.unlink()
  return True

def reset_session() -> dict:
  """Reset session của thế giới về trạng thái unlocked"""
  return update_session(
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


def auth_claim_session(host_id: str, ip_address: str) -> bool:
  """Xác nhận quyền kiểm soát session cho thế giới"""
  session = get_session() # Dùng get_session để trigger kiểm tra hết hạn nếu có
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

def scan_all_sessions():
    """Quét world duy nhất và kiểm tra session hết hạn"""
    if not STORAGE_PATH.exists():
        return
    
    world_path = STORAGE_PATH / "world"
    if not world_path.exists():
        return

    try:
        # get_session tự động kiểm tra và reset nếu hết hạn
        get_session()
    except Exception:
        pass