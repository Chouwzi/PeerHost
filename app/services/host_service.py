from app.core.config import STORAGE_PATH, HEARTBEAT_INTERVAL, LOCK_TIMEOUT, SECRET_KEY, ALGORITHM
from datetime import datetime, timezone
from app.utils import json_storage
from jose import jwt

def create_session(world_id: str, host_id: str = None, ip_address: str = None, token: str = None, is_locked: bool = False) -> dict:
  """Tạo session cho thế giới

  Args:
      world_id (str): ID thế giới
      host_id (str): ID host
      ip_address (str): Địa chỉ IP

  Returns:
      dict: Thông tin session
  """
  world_path = STORAGE_PATH / "worlds" / world_id
  if not world_path.exists():
    raise FileNotFoundError(f"World '{world_id}' not found")
  
  session_path = world_path / "meta" / "session.json"
  if session_path.exists():
    raise FileExistsError(f"Session for world '{world_id}' already exists")
  
  session_json = {
    "world_id": world_id,
    "is_locked": is_locked,
    "host": {
      "host_id": host_id,
      "ip_address": ip_address,
      "token": token
    },
    "timestamps": {
      "started_at": None,
      "last_heartbeat": None,
      "expires_at": None
    },
    "config": {
      "heartbeat_interval": HEARTBEAT_INTERVAL,
      "lock_timeout": LOCK_TIMEOUT
    }
  }
  json_storage.write_json(session_path, session_json)
  return session_json

def get_session(world_id: str) -> dict | None:
  """Lấy thông tin session của thế giới

  Args:
      world_id (str): ID thế giới

  Returns:
      dict | None: Thông tin session
  """
  world_path = STORAGE_PATH / "worlds" / world_id
  if not world_path.exists():
    return None
  
  session_path = world_path / "meta" / "session.json"
  if not session_path.exists():
    return None
  
  return json_storage.read_json(session_path)

def update_session(world_id: str, data_json: dict) -> dict:
  """Cập nhật thông tin session của thế giới

  Args:
      world_id (str): ID thế giới
      data_json (dict): Những thông tin cần cập nhật

  Returns:
      dict: Thông tin session
  """
  # Không cho cập nhật những thông tin này
  if data_json.keys() & {"config", "world_id"}:
    raise ValueError("Invalid data")
  
  world_path = STORAGE_PATH / "worlds" / world_id
  if not world_path.exists():
    raise FileNotFoundError(f"World '{world_id}' not found")
  
  session_path = world_path / "meta" / "session.json"
  if not session_path.exists():
    raise FileNotFoundError(f"Session for world '{world_id}' not found")
  # Lấy dữ liệu cũ
  session_json = json_storage.read_json(session_path)
  # Cập nhật dữ liệu
  session_json.update(data_json)
  # Ghi lại
  json_storage.write_json(session_path, session_json)
  return session_json

def delete_session(world_id: str) -> bool:
  """Xóa session của thế giới

  Args:
      world_id (str): ID thế giới

  Returns:
      bool: Trạng thái xóa
  """
  world_path = STORAGE_PATH / "worlds" / world_id
  if not world_path.exists():
    return False
  
  session_path = world_path / "meta" / "session.json"
  if not session_path.exists():
    return False
  
  session_path.unlink()
  return True

def reset_session(world_id: str) -> bool:
  """Reset session của thế giới

  Args:
      world_id (str): ID thế giới

  Returns:
      bool: Trạng thái reset
  """
  return update_session(
    world_id,
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
  """Tạo token

  Args:
      payload (dict): Payload

  Returns:
      str: Token
  """
  token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
  return token


def auth_claim_session(world_id: str, host_id: str, ip_address: str) -> bool:
  """Xác nhận quyền kiểm soát session cho thế giới

  Args:
      world_id (str): ID thế giới
      host_id (str): ID host
      ip_address (str): Địa chỉ IP

  Returns:
      bool: Trạng thái xác nhận
  """
  session = get_session(world_id)
  if not session:
    return False
  return session["host"]["host_id"] == host_id and session["host"]["ip_address"] == ip_address