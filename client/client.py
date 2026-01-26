import time
import logging
from pathlib import Path
from utils import json_parse
from utils.logger import setup_logger
from models import Settings
from session_manager import SessionManager

logger = setup_logger("Client")

class Client:
  def __init__(self):
    self._settings_file = Path(__file__).parent / "settings.json"
    if self._settings_file.exists():
      data = json_parse.load_file(self._settings_file)
      self._settings: Settings = Settings(**data)
      
      # Configure Logger Level
      if self._settings.debug:
        logger.setLevel(logging.DEBUG)
      else:
        logger.setLevel(logging.INFO)
    else:
      raise FileNotFoundError("Settings file not found")
        
    self.session_manager = SessionManager(self._settings)
  
  def start(self) -> None:
    while True:
      session = self.session_manager.get_session()
      
      # Wait if connection failed
      if session is None:
        time.sleep(5)
        continue

      # If session is free, claim it
      if session.get("is_locked") == False and session.get("host_id") == None:
        self.session_manager.claim_session()
    
      # If we own the session, heartbeat
      if session.get("host_id") == self._settings.host_id:
        time.sleep(self.session_manager.heartbeat_interval)
        self.session_manager.heartbeat_session()
      else:
        time.sleep(3)
  
if __name__ == "__main__":
  try:
    client = Client()
    client.start()
  except KeyboardInterrupt:
    logger.info("Client stopped by user.")
  except Exception as e:
    logger.critical(f"Client crashed: {e}")