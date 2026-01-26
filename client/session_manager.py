import requests as req
from pathlib import Path
from models import Settings, SessionInfo
from config import TOKEN_FILE
from utils.logger import setup_logger

logger = setup_logger("Client")

class SessionManager:
  def __init__(self, settings: Settings):
    self._settings = settings
    self._session_info: SessionInfo | None = None
    
  @property
  def session_info(self) -> SessionInfo | None:
      return self._session_info

  @property
  def heartbeat_interval(self) -> int:
      return self._session_info.heartbeat_interval if self._session_info else 5

  @property
  def lock_timeout(self) -> int:
      return self._session_info.lock_timeout if self._session_info else 15
    
  def load_token(self) -> str | None:
    if not TOKEN_FILE.exists():
      return None
    with open(TOKEN_FILE, "r") as f:
      token = f.read().strip()
      logger.debug(f"[Session] Token loaded: {token}")
      return token
    
  def save_token(self, token: str) -> bool:
    try:
      if not Path(TOKEN_FILE).exists():
        Path(TOKEN_FILE).parent.mkdir(parents=True, exist_ok=True)
      with open(TOKEN_FILE, "w") as f:
        f.write(token)
      logger.debug(f"[Session] Token saved | {token[:20]}...")
      return True
    except Exception as e:
      logger.error(f"[Session] Failed to save token | {e}")
      return False
    
  # Claim Session
  def claim_session(self) -> bool:
    """Nhận Session và lấy quyền Host"""
    data = {"host_id": self._settings.host_id}
    try:
      # Gửi yêu cầu nhận phiên
      headers = {"Content-Type": "application/json"}
      resp = req.post(self._settings.server_url + "/world/session", json=data, headers=headers)
      if resp.status_code == 409:
        logger.error(f"Resp: {resp.json().get('detail')} | Status: {resp.status_code}")
        return False
      self._session_info = SessionInfo(**resp.json())
      self.save_token(self._session_info.token)
      logger.info("[Session] Đăng ký Session thành công")
      return True
    except req.ConnectionError as e:
      logger.error(f"[Session] Lỗi kết nối đến Server")
      return False
    
  # Stop Session
  def stop_session(self) -> bool:
    """Dừng Session"""
    try:
      headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.load_token()}"}
      resp = req.delete(self._settings.server_url + "/world/session", headers=headers)
      if resp.status_code == 204:
        logger.info("[Session] Dừng Session thành công")
        return True
      logger.error(f"[Session] Resp: {resp.json().get('detail')} | Status: {resp.status_code}")
      return False
    except req.ConnectionError as e:
      logger.error(f"[Session] Lỗi kết nối đến Server")
      return False
  
  # Heartbeat
  def heartbeat_session(self) -> dict | None:
    """Gửi yêu cầu duy trì Session"""
    try:
      headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.load_token()}"}
      resp = req.post(
        self._settings.server_url + "/world/session/heartbeat",
        headers=headers
      )
      if resp.status_code == 200:
        logger.debug("[Session] Heartbeat thành công")
        return resp.json()
      logger.error(f"[Session] Lỗi Heartbeat: {resp.json().get('detail')} | Status: {resp.status_code}")
      return None
    except req.ConnectionError as e:
      logger.error(f"[Session] Lỗi kết nối đến Server")
      return None
    except Exception as e:
      logger.error(f"[Session] Lỗi ngoại lệ Heartbeat: {e}")
      return None
    
  # Get Session Infomation
  def get_session(self) -> dict | None:
    """Lấy các thông tin cơ bản của Session"""
    try:
      headers = {"Content-Type": "application/json"}
      resp = req.get(self._settings.server_url + "/world/session", headers=headers)
      if resp.status_code == 200:
        logger.debug("[Session] Lấy thông tin session thành công")
        return resp.json()
      logger.error(f"[Session] Resp: {resp.json().get('detail')} | Status: {resp.status_code}")
      return None
    except req.ConnectionError as e:
      logger.error(f"[Session] Lỗi kết nối đến Server")
      return None
    except Exception as e:
      logger.error(f"[Session] Lỗi lấy thông tin session: {e}")
      return None
