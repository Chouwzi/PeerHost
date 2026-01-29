import requests as req
from pathlib import Path
from models import Settings, SessionInfo
from config import TOKEN_FILE
from common.logger import setup_logger

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

  def _get_error_msg(self, resp: req.Response) -> str:
      """Safely extract error message from response (JSON or Text)"""
      try:
          data = resp.json()
          return data.get("detail", str(data))
      except ValueError:
          return resp.text[:100] # Return first 100 chars of text (e.g. HTML title)
    
  # Claim Session
  def claim_session(self) -> bool:
    """Nhận Session và lấy quyền Host"""
    data = {"host_id": self._settings.host_id}
    try:
      # Gửi yêu cầu nhận phiên
      headers = {"Content-Type": "application/json"}
      resp = req.post(self._settings.server_url + "/world/session", json=data, headers=headers)
      if resp.status_code == 409:
          # Conflict: Session already exists. Check if we can resume.
          logger.warning("[Session] Session đã tồn tại. Đang thử khôi phục Session...")
          if self.check_connection():
               # Try to heartbeat using existing token
               _, hb_code = self.heartbeat_session()
               if hb_code == 200:
                   logger.info("[Session] Khôi phục Session thành công!")
                   return True
               else:
                   logger.error(f"[Session] Không thể khôi phục Session (Heartbeat Code: {hb_code}).")
                   return False
          return False

      if resp.status_code == 201 or resp.status_code == 200:
          self._session_info = SessionInfo(**resp.json())
          self.save_token(self._session_info.token)
          logger.info("[bold #00b09b][[/][bold #04b098]S[/][bold #08b195]e[/][bold #0cb292]s[/][bold #11b290]s[/][bold #15b38d]i[/][bold #19b48a]o[/][bold #1eb588]n[/][bold #22b585]][/] [bold #2ab780]Đ[/][bold #2fb77d]ă[/][bold #33b87a]n[/][bold #37b978]g[/] [bold #40ba72]k[/][bold #44bb70]ý[/] [bold #4dbc6a]S[/][bold #51bd67]e[/][bold #55be65]s[/][bold #5abf62]s[/][bold #5ebf5f]i[/][bold #62c05d]o[/][bold #66c15a]n[/] [bold #6fc255]t[/][bold #73c352]h[/][bold #78c44f]à[/][bold #7cc44d]n[/][bold #80c54a]h[/] [bold #89c645]c[/][bold #8dc742]ô[/][bold #91c83f]n[/][bold #96c93d]g[/]")
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
      logger.error(f"[Session] Resp: {self._get_error_msg(resp)} | Status: {resp.status_code}")
      return False
    except req.ConnectionError as e:
      logger.error(f"[Session] Lỗi kết nối đến Server")
      return False
  
  # Heartbeat
  def heartbeat_session(self) -> tuple[dict | None, int]:
    """Gửi yêu cầu duy trì Session. Trả về (data, status_code)"""
    try:
      headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.load_token()}"}
      resp = req.post(
        self._settings.server_url + "/world/session/heartbeat",
        headers=headers,
        timeout=10
      )
      if resp.status_code == 200:
        logger.debug("[Session] Heartbeat thành công")
        return resp.json(), 200
      
      logger.debug(f"[Session] Lỗi Heartbeat: {self._get_error_msg(resp)} | Status: {resp.status_code}")
      return None, resp.status_code
      
    except req.ConnectionError:
      logger.error(f"[Session] Lỗi kết nối đến Server")
      return None, 503 # Service Unavailable (Connection Error)
    except Exception as e:
      logger.error(f"[Session] Lỗi ngoại lệ Heartbeat: {e}")
      return None, 500
    
  # Get Session Infomation
  def get_session(self) -> dict | None:
    """Lấy các thông tin cơ bản của Session"""
    try:
      headers = {"Content-Type": "application/json"}
      resp = req.get(self._settings.server_url + "/world/session", headers=headers)
      if resp.status_code == 200:
        logger.debug("[Session] Lấy thông tin session thành công")
        return resp.json()
      logger.error(f"[Session] Resp: {self._get_error_msg(resp)} | Status: {resp.status_code}")
      return None
    except req.ConnectionError as e:
      logger.error(f"[Session] Lỗi kết nối đến Server")
      return None
    except Exception as e:
      logger.error(f"[Session] Lỗi lấy thông tin session: {e}")
      return None

  # Check Connection (Lightweight)
  def check_connection(self) -> bool:
      """Kiểm tra kết nối tới Server (Pinging)"""
      try:
          headers = {"Content-Type": "application/json"}
          resp = req.get(self._settings.server_url + "/world/session", headers=headers, timeout=5)
          
          if resp.status_code == 200:
               # Verify it's actually JSON (not Cloudflare HTML 200 Page)
               try:
                   resp.json()
                   return True
               except ValueError:
                   return False
          return False
      except Exception:
          return False
