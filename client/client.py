import asyncio
import logging
from pathlib import Path
from utils import json_parse
from utils.logger import setup_logger, set_debug_mode
from models import Settings
from session_manager import SessionManager
from services.sync_service import SyncService, PreSyncManager
from services.game_server import GameServerManager

logger = setup_logger("Client")

class Client:
  def __init__(self):
    self._settings_file = Path(__file__).parent / "settings.json"
    if self._settings_file.exists():
      data = json_parse.load_file(self._settings_file)
      self._settings: Settings = Settings(**data)
      
      # Configure Logger Level
      set_debug_mode(self._settings.debug)
    else:
      raise FileNotFoundError("Settings file not found")
        
    self.session_manager = SessionManager(self._settings)
    self.sync_service: SyncService | None = None
    self._sync_task: asyncio.Task | None = None
    
    # Pre-Sync Manager
    watch_dir = (Path(__file__).parent / self._settings.watch_dir).resolve()
    if not watch_dir.exists():
         watch_dir.mkdir(parents=True, exist_ok=True)
         
    self.pre_sync_manager = PreSyncManager(
        server_url=self._settings.server_url,
        watch_dir=watch_dir
    )
    
    self.game_server = GameServerManager(watch_dir)
  
    self.state_machine = StateMachine(self)
  
  async def start(self) -> None:
    self.loop = asyncio.get_running_loop()
    logger.info(f"[Client] Đã khởi động")
    await self.state_machine.run()

  async def start_hosting_services(self, known_server_files: dict = None):
      """Start SyncService and GameServer"""
      if self.sync_service:
          return 

      logger.debug("[Client] Đang khởi động Services...")
      token = self.session_manager.load_token()
      if not token:
          logger.error("[Client] Không thể khởi động Services: Thiếu Token")
          return

      watch_dir = self.pre_sync_manager.watch_dir
      self.sync_service = SyncService(
          watch_dir=watch_dir,
          server_url=self._settings.server_url,
          token=token
      )
      
      # 1. Initialize Sync (Fetch Config & Scan)
      start_command = await self.sync_service.initialize(known_server_files)
      
      # 2. Start Sync Loop in Background
      self._sync_task = asyncio.create_task(self.sync_service.run_loop())
      logger.info(f"[Sync] Đã khởi động | Watch Dir: {watch_dir}")
      
      # 3. Start Game Server (if command exists)
      if start_command:
           logger.debug(f"[Client] Nhận lệnh khởi động Server: {start_command}")
           await self.game_server.start_server(start_command)
      else:
           logger.warning("[Client] Không nhận được lệnh khởi động Server từ Config.")

  async def stop_hosting_services(self):
      # 1. Stop Game Server First (wait for save)
      if self.game_server:
          await self.game_server.stop_server()
      
      # 2. Stop Monitor to prevent new events being queued
      if self.sync_service:
          self.sync_service.stop()
          
      # 3. Wait for pending uploads from DiffManager to complete
      if self.sync_service:
          await self.sync_service.wait_for_pending_uploads(timeout=3.0)
      
      # 4. Final Sync - Upload any remaining saved files
      if self.sync_service:
          await self.sync_service.final_sync()
           
      # 5. Cleanup Sync Service
      if self.sync_service:
          logger.info("[Sync] Đang dừng Sync Service...")
          if self._sync_task:
              self._sync_task.cancel()
              try:
                  await self._sync_task
              except asyncio.CancelledError:
                  pass
          self.sync_service = None
          self._sync_task = None
          
  async def stop(self):
    """Dừng toàn bộ Client và Cleanup"""
    logger.info("[Client] Đang dừng...")
    await self.stop_hosting_services()
    
    # Cancel all remaining tasks if any
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    for task in tasks:
        task.cancel() 
    await asyncio.gather(*tasks, return_exceptions=True)

from state_machine import StateMachine
  
if __name__ == "__main__":
  # Fix for Windows Asyncio Subprocess & Console Close Handler
  import os
  import ctypes
  
  if os.name == 'nt':
       asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
       
       # Setup Console Handler for "X" button
       kernel32 = ctypes.windll.kernel32
       
       # BOOL WINAPI HandlerRoutine(DWORD dwCtrlType);
       HandlerRoutine = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_uint)
       
       def win32_ctrl_handler(dwCtrlType):
           # CTRL_CLOSE_EVENT = 2
           if dwCtrlType == 2: 
               print("[Win32] Window Close Detected. Attempting graceful shutdown...")
               # Force kill server immediately on Close Event
               # We cannot rely on Asyncio loop here because it might be terminating
               if 'client' in locals() or 'client' in globals():
                   c = locals().get('client') or globals().get('client')
                   if c and hasattr(c, 'loop') and c.loop.is_running():
                       try:
                           future = asyncio.run_coroutine_threadsafe(c.stop(), c.loop)
                           # Wait for a few seconds to let it save
                           future.result(timeout=6) 
                       except Exception as e:
                           print(f"[Win32] Graceful shutdown failed: {e}")
                           if c.game_server:
                                c.game_server.force_kill_sync()
                   elif c and c.game_server:
                       # Fallback if loop is closed
                       c.game_server.force_kill_sync()
               return True # Try to ignore closing? No, systems closes anyway.
           return False

       # Create and register handler
       ctrl_handler = HandlerRoutine(win32_ctrl_handler)
       kernel32.SetConsoleCtrlHandler(ctrl_handler, True)

  client = Client()
  
  try:
    # Wrap in a main async function to handle cleanup gracefully
    async def main():
        try:
            await client.start()
        except asyncio.CancelledError:
            pass
        finally:
            await client.stop()

    asyncio.run(main())
    
  except KeyboardInterrupt:
    pass
  except Exception as e:
    logger.critical(f"[Client] Lỗi Critical: {e}")