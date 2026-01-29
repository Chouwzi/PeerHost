import asyncio
import logging
from pathlib import Path
from common import json_parse
from rich.panel import Panel
from rich.align import Align
from common.logger import setup_logger, set_debug_mode, console
from models import Settings, TunnelConfig
from session_manager import SessionManager
from services.sync_service import SyncService, PreSyncManager, fetch_server_config
from services.game_server import GameServerManager
from services.cloudflare_service import CloudflareService
from state_machine import StateMachine
from common.process_tracker import ProcessTracker
import os
os.system("cls")

logger = setup_logger("Client")

class Client:
  def __init__(self):
    # 1. Cleanup Orphan Processes (Zombie Prevention)
    ProcessTracker().cleanup_orphans()

    self._settings_file = Path(__file__).parent / "settings.json"
    if self._settings_file.exists():
      data = json_parse.load_file(self._settings_file)
      self._settings: Settings = Settings(**data)
      
      # Configure Logger Level
      set_debug_mode(self._settings.debug)
    else:
        # Create default settings if missing
        self._settings = Settings(
                server_url="https://peerhost.chouwzi.io.vn",
                host_id="", # Will trigger prompt
                watch_dir="./world",
                debug=False
        )
      
        try:
                # Try to save immediately
                save_data = self._settings.model_dump()
        except AttributeError:
                save_data = self._settings.dict()
            
        json_parse.write_file(self._settings_file, save_data)
        logger.info(f"[Setup] Created default settings file at {self._settings_file}")
        
    self.session_manager = SessionManager(self._settings)
    self.sync_service: SyncService | None = None
    self._sync_task: asyncio.Task | None = None
    self._last_start_command: list[str] | None = None
    
    # Pre-Sync Manager
    watch_dir = (Path(__file__).parent / self._settings.watch_dir).resolve()
    if not watch_dir.exists():
        watch_dir.mkdir(parents=True, exist_ok=True)
         
    self.pre_sync_manager = PreSyncManager(
        server_url=self._settings.server_url,
        watch_dir=watch_dir
    )
    
    self.game_server = GameServerManager(watch_dir)
    
    # Tunnel config (will be fetched from server on startup)
    self._tunnel_config: TunnelConfig | None = None
    self.cloudflare_service = CloudflareService(watch_dir, self._settings)
  
    self._heartbeat_task: asyncio.Task | None = None
    self.state_machine = StateMachine(self)
  
  async def start(self) -> None:
    self.loop = asyncio.get_running_loop()
    
    # Print Beautiful Banner
    import pyfiglet
    from rich.panel import Panel
    from rich.align import Align
    
    ascii_art = pyfiglet.figlet_format("PeerHost", font="slant")
    host_id = self._settings.host_id if hasattr(self._settings, 'host_id') and self._settings.host_id else "Unknown"
    from rich.console import Console
    from rich.prompt import Prompt
    console = Console()

    if not hasattr(self._settings, 'host_id') or not self._settings.host_id or self._settings.host_id == "Unknown":
        console.print(Panel("[bold yellow]Thiết lập lần đầu[/bold yellow]\nVui lòng nhập tên người dùng.", border_style="yellow"))
        
        import re
        while True:
            new_host_id = Prompt.ask("[bold cyan]Nhập tên người dùng[/bold cyan]")
            
            if len(new_host_id) <= 5:
                console.print("[bold red]Lỗi:[/bold red] Tên người dùng phải dài hơn 5 ký tự.")
                continue
                
            if not re.match(r'^[a-zA-Z0-9_-]+$', new_host_id):
                console.print("[bold red]Lỗi:[/bold red] Tên người dùng không được chứa ký tự đặc biệt (chỉ chấp nhận a-z, 0-9, -, _).")
                continue
                
            # Valid
            self._settings.host_id = new_host_id
            # Save to settings.json
            try:
                save_data = self._settings.model_dump() # Pydantic v2 (Preferred)
            except AttributeError:
                save_data = self._settings.dict() # Pydantic v1 (Fallback)
                
            json_parse.write_file(self._settings_file, save_data)
            logger.info(f"[Setup] Đã lưu Host ID: {new_host_id}")
            os.system("cls")
            break
        
    host_id = self._settings.host_id
    banner_text = (
        f"[bold cyan]{ascii_art}[/bold cyan]\n"
        f"[bold green]Hybrid P2P • Distributed Cloud Infrastructure[/bold green]\n"
        f"[italic white]Empowering the future of decentralized gaming connectivity[/italic white]\n\n"
        f"[bold yellow]Host Identity:[/bold yellow] [bold white]{host_id}[/bold white]"
    )
    
    console.print(Panel(Align.center(banner_text), border_style="bright_cyan", subtitle="[bold white]Made by Chouwzi with 💖[/bold white]", padding=(1, 2)))
    
    logger.info(f"[Client] Đã khởi động")
    await self.state_machine.run()
    
  def start_heartbeat_monitor(self):
        """Bắt đầu gửi Heartbeat ngầm"""
        if self._heartbeat_task and not self._heartbeat_task.done():
            return

        self._heartbeat_task = asyncio.create_task(self._run_heartbeat_loop())
        logger.debug("[Client] Đã bắt đầu Heartbeat Monitor (Background)")

  def stop_heartbeat_monitor(self):
        """Dừng gửi Heartbeat"""
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            self._heartbeat_task = None
            logger.debug("[Client] Đã dừng Heartbeat Monitor")

  async def _run_heartbeat_loop(self):
        """Vòng lặp gửi heartbeat định kỳ với cơ chế Smart Retry"""
        fail_count = 0
        MAX_RETRIES = 3
        
        try:
            while True:
                interval = self.session_manager.heartbeat_interval
                await asyncio.sleep(interval)
                
                # Gửi heartbeat
                updated, status_code = await asyncio.to_thread(self.session_manager.heartbeat_session)
                
                if status_code == 200:
                    fail_count = 0 # Reset counter on success
                    
                    # Check consistency logic
                    current_host_id = updated.get("host_id")
                    if current_host_id != self._settings.host_id:
                        logger.error("[Heartbeat] Mất quyền Host ID khác! Dừng khẩn cấp.")
                        await self.stop_hosting_services(shutdown_cf_access=False)
                        break
                    continue

                # Handle Errors
                if status_code == 401:
                    logger.error("[Heartbeat] Phiên làm việc đã bị hủy hoặc hết hạn (401). Đang dừng dịch vụ...")
                    await self.stop_hosting_services(shutdown_cf_access=False, skip_session_stop=True, offline_mode=True)
                    break
                
                # Other Errors (502, 500, Timeout)
                fail_count += 1
                logger.warning(f"[Heartbeat] Không thể duy trì phiên (Status: {status_code}). Lần {fail_count}/{MAX_RETRIES}")
                
                if fail_count >= MAX_RETRIES:
                    # 1. Stop heavy services
                    await self.stop_hosting_services(shutdown_cf_access=False, shutdown_cf_host=True, offline_mode=True)
                    
                    # 2. Enter Waiting Loop
                    logger.warning("[Connection] Đang đợi kết nối từ Server...")
                    while True:
                            await asyncio.sleep(2) # Check every 2s
                            try:
                                status = await asyncio.to_thread(self.session_manager.check_connection)
                                if status: break
                            except Exception as e:
                                logger.debug(f"[Connection] Check error: {e}")
        except Exception as e:
            logger.error(f"[Heartbeat] Lỗi ngoại lệ Heartbeat: {e}")
        

  async def start_hosting_services(self, known_server_files: dict = None):
      """Khởi động các dịch vụ Host: Sync -> Game -> Tunnel"""
      if self.sync_service:
          return 

      logger.debug("[Client] Đang khởi động Hosting Services...")
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
      self._last_start_command = start_command # Save for Auto-Restart logic
      
      # 2. Start Sync Loop in Background
      self._sync_task = asyncio.create_task(self.sync_service.run_loop())
      logger.info(f"[Sync] Đã khởi động | Watch Dir: {watch_dir}")
      
      # 3. Start Game Server
      if self.game_server:
          if start_command:
              logger.debug(f"[Client] Starting Game Server with command: {start_command}")
              port = self._tunnel_config.game_local_port if self._tunnel_config else 25565
              await self.game_server.start_server(start_command, port=port)
          else:
              logger.warning("[Client] Không có lệnh khởi động Game Server từ Sync config.")
      
      # 4. Start Cloudflare Tunnel (Host Mode)
      if self.cloudflare_service:
          await self.cloudflare_service.start_host_mode()

  async def stop_hosting_services(self, shutdown_cf_access: bool=True, shutdown_cf_host: bool=True, offline_mode: bool=False, skip_session_stop: bool=False):
      """Dừng các dịch vụ Host theo trình tự chuẩn"""
      logger.warning("[Client] Đang dừng Hosting Services...")

      # 0. Nếu Offline Mode (Mất mạng), chặn ngay Sync để tránh Upload Spam khi tắt Server
      if offline_mode and self.sync_service:
           logger.info("[Client] Offline Mode: Hủy toàn bộ tác vụ Upload đang chờ.")
           self.sync_service.monitor.stop() # Stop watching changes
           self.sync_service.diff_manager.cancel_all() # Cancel pending uploads

      # 1. Dừng Tunnel trước để ngắt các kết nối mới đang vào
      if self.cloudflare_service:
          if shutdown_cf_host:
              await self.cloudflare_service.stop_host()
          if shutdown_cf_access:
              await self.cloudflare_service.stop_access()
          
      # 2. Dừng Game Server (Đợi lưu world xong)
      if self.game_server:
          await self.game_server.stop_server()
      
      # 3. Đợi các file đang upload dở hỏa tất
      if self.sync_service and not offline_mode:
          await self.sync_service.wait_for_pending_uploads(timeout=30.0)
      
      # 4. Đồng bộ cuối cùng (Final Sync) - Lúc này Heartbeat vẫn đang chạy nên Token còn sống
      if self.sync_service and not offline_mode:
          await self.sync_service.final_sync()
            
      # 5. Dừng Heartbeat Monitor TRƯỚC khi đóng Session để tránh gửi request 401
      self.stop_heartbeat_monitor()

      # 6. Thông báo cho Server đóng Session (Giải phóng Lock ngay lập tức)
      if not offline_mode and not skip_session_stop:
        await asyncio.to_thread(self.session_manager.stop_session)
        logger.info("[Session] Đã gửi thông báo đóng Session cho Server.")
      
      # 7. Cuối cùng mới dọn dẹp Sync Service Task
      if self.sync_service:
          logger.debug("[Sync] Cleaning up Sync Service...")
          await self.sync_service.stop()
          if self._sync_task:
              self._sync_task.cancel()
              try:
                  await self._sync_task
              except asyncio.CancelledError: # cancel
                  pass
              except Exception:
                  pass
          self.sync_service = None
          self._sync_task = None
          
  async def stop(self):
    """Dừng toàn bộ Client và Cleanup"""
    await self.stop_hosting_services()
    
    # Cancel all remaining tasks if any
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    for task in tasks:
        task.cancel() 
    await asyncio.gather(*tasks, return_exceptions=True)
  
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