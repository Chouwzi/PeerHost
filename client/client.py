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
    
    self.game_server = GameServerManager(watch_dir, self.session_manager)
    
    # Tunnel config (will be fetched from server on startup)
    self._tunnel_config: TunnelConfig | None = None
    self.cloudflare_service = CloudflareService(watch_dir, self._settings)
  
    self._heartbeat_task: asyncio.Task | None = None
    self._shutdown_lock = asyncio.Lock()  # BUG #6 FIX: Ngăn concurrent shutdown
    self._is_shutting_down = False
    self._recovery_in_progress = False  # Flag: heartbeat recovery đang xử lý
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
        """Vòng lặp gửi heartbeat định kỳ với cơ chế Smart Retry.
        BUG #2 FIX: Phân biệt 401 vs network failure, đảm bảo upload data trước khi tắt.
        BUG #4 FIX: Sau reconnect, re-claim session và upload data.
        """
        fail_count = 0
        MAX_RETRIES = 3
        MAX_RECONNECT_WAIT = 300  # BUG #10 FIX: 5 phút tối đa

        try:
            while True:
                interval = self.session_manager.heartbeat_interval
                await asyncio.sleep(interval)

                # Gửi heartbeat
                updated, status_code = await asyncio.to_thread(self.session_manager.heartbeat_session)

                if status_code == 200:
                    fail_count = 0  # Reset counter on success

                    # Check consistency logic
                    current_host_id = updated.get("host_id")
                    if current_host_id != self._settings.host_id:
                        logger.error("[Heartbeat] Mất quyền Host ID khác! Dừng khẩn cấp.")
                        await self.stop_hosting_services(shutdown_cf_access=False)
                        break
                    continue

                # ── Handle 401 (Session lost/expired) ──
                if status_code == 401:
                    logger.error("[Heartbeat] Phiên làm việc đã bị hủy hoặc hết hạn (401). Khởi động khôi phục khẩn cấp.")
                    # BUG #2 FIX: Dừng game server + upload data TRƯỚC khi tắt hẳn
                    await self._emergency_save_and_shutdown()
                    break

                # ── Handle network/server errors (502, 500, Timeout) ──
                fail_count += 1
                logger.warning(f"[Heartbeat] Lỗi heartbeat (HTTP {status_code}). Lần {fail_count}/{MAX_RETRIES}")

                if fail_count >= MAX_RETRIES:
                    # BUG #4 FIX: Dừng game server (save world), chờ reconnect, rồi upload
                    logger.warning(f"[Heartbeat] Không thể duy trì kết nối sau {MAX_RETRIES} lần thử. Khởi động khôi phục mạng.")
                    await self._network_failure_recovery(MAX_RECONNECT_WAIT)
                    break

        except asyncio.CancelledError:
            pass  # Normal cancellation from stop_heartbeat_monitor
        except Exception as e:
            logger.error(f"[Heartbeat] Lỗi ngoại lệ Heartbeat: {e}")

  async def _emergency_save_and_shutdown(self):
        """BUG #2 FIX: Khi nhận 401, dừng game server -> thử re-claim -> upload -> cleanup.
        Đảm bảo data không bị mất dù session bị hủy bên server."""
        self._recovery_in_progress = True  # Báo state machine không can thiệp
        try:
            logger.warning("[Recovery] Bắt đầu khôi phục khẩn cấp (401: Phiên hết hạn)")

            # 1. Dừng tunnel + monitor ngay để ngăn traffic mới
            if self.cloudflare_service:
                logger.debug("[Recovery] Dừng Cloudflare Tunnel...")
                await self.cloudflare_service.stop_host()
            if self.sync_service:
                logger.debug("[Recovery] Dừng file monitoring...")
                self.sync_service.monitor.stop()
                self.sync_service.diff_manager.cancel_all()

            # 2. Dừng game server (Minecraft save world xuống disk)
            if self.game_server:
                logger.debug("[Recovery] Dừng Game Server...")
                await self.game_server.stop_server()

            # 3. Thử claim lại session để có token hợp lệ cho upload
            logger.info("[Recovery] Đăng ký lại session para có token mới...")
            reclaimed = await asyncio.to_thread(self.session_manager.claim_session)

            if reclaimed and self.sync_service:
                logger.info("[Recovery] Đã đăng ký lại session thành công. Bắt đầu upload dữ liệu...")
                # Cập nhật token mới cho uploader
                new_token = self.session_manager.load_token()
                if new_token:
                    self.sync_service.uploader.token = new_token
                    self.sync_service.ensure_session_alive()  # BUG #7 FIX
                try:
                    await self.sync_service.final_sync()
                    logger.info("[Recovery] Đã upload dữ liệu thành công sau khôi phục session.")
                except Exception as e:
                    logger.error(f"[Recovery] Lỗi khi upload dữ liệu: {e}")
                # Giải phóng session sau khi upload xong
                await asyncio.to_thread(self.session_manager.stop_session)
            else:
                logger.warning("[Recovery] Không thể đăng ký lại session. Dữ liệu giữ lại ở local.")

            # 4. Cleanup
            logger.debug("[Recovery] Dọn dẹp resources...")
            self.stop_heartbeat_monitor()
            if self.sync_service:
                await self.sync_service.stop()
                if self._sync_task:
                    self._sync_task.cancel()
                    try:
                        await self._sync_task
                    except (asyncio.CancelledError, Exception):
                        pass
                self.sync_service = None
                self._sync_task = None
            logger.warning("[Recovery] Kết thúc khôi phục khẩn cấp")
        finally:
            self._recovery_in_progress = False

  async def _network_failure_recovery(self, max_wait: int):
        """BUG #4 FIX: Khi mất mạng (3 heartbeat fails), dừng game server,
        chờ reconnect, rồi re-claim và upload data."""
        self._recovery_in_progress = True  # Báo state machine không can thiệp
        try:
            logger.warning("[Recovery] Bắt đầu khôi phục mạng (Mất kết nối)")

            # 1. Dừng tunnel
            if self.cloudflare_service:
                logger.debug("[Recovery] Dừng Cloudflare Tunnel...")
                await self.cloudflare_service.stop_host()

            # 2. Dừng file monitoring (ngăn upload spam khi mất mạng)
            if self.sync_service:
                logger.debug("[Recovery] Dừng file monitoring...")
                self.sync_service.monitor.stop()
                self.sync_service.diff_manager.cancel_all()

            # 3. Dừng game server (save world xuống disk)
            if self.game_server:
                logger.debug("[Recovery] Dừng Game Server...")
                await self.game_server.stop_server()

            # 4. Chờ kết nối lại (có timeout)
            logger.warning(f"[Connection] Chờ kết nối lại từ Server (tối đa {max_wait}s)...")
            waited = 0
            reconnected = False
            reconnect_progress = 0
            while waited < max_wait:
                await asyncio.sleep(2)
                waited += 2
                reconnect_progress = int((waited / max_wait) * 100)
                try:
                    status = await asyncio.to_thread(self.session_manager.check_connection)
                    if status:
                        reconnected = True
                        logger.info(f"[Connection] Kết nối lại thành công sau {waited}s!")
                        break
                except Exception as e:
                    logger.debug(f"[Connection] Đang kiểm tra... ({waited}s/{max_wait}s)")

            if not reconnected:
                logger.error(f"[Connection] Timeout sau {max_wait}s. Dữ liệu giữ lại ở local.")
            else:
                # 5. Reconnected! Thử claim lại session và upload
                logger.info("[Recovery] Đăng ký lại session sau reconnect...")
                reclaimed = await asyncio.to_thread(self.session_manager.claim_session)

                if reclaimed and self.sync_service:
                    logger.info("[Recovery] Đã đăng ký lại session. Bắt đầu upload dữ liệu...")
                    new_token = self.session_manager.load_token()
                    if new_token:
                        self.sync_service.uploader.token = new_token
                        self.sync_service.ensure_session_alive()  # BUG #7 FIX
                    try:
                        await self.sync_service.final_sync()
                        logger.info("[Recovery] Đã upload dữ liệu thành công sau reconnect.")
                    except Exception as e:
                        logger.error(f"[Recovery] Lỗi khi upload dữ liệu: {e}")
                    # Giải phóng session
                    await asyncio.to_thread(self.session_manager.stop_session)
                else:
                    logger.warning("[Recovery] Không thể đăng ký lại session. Dữ liệu giữ lại ở local.")

            # 6. Cleanup
            logger.debug("[Recovery] Dọn dẹp resources...")
            self.stop_heartbeat_monitor()
            if self.sync_service:
                await self.sync_service.stop()
                if self._sync_task:
                    self._sync_task.cancel()
                    try:
                        await self._sync_task
                    except (asyncio.CancelledError, Exception):
                        pass
                self.sync_service = None
                self._sync_task = None
            logger.warning("[Recovery] Kết thúc khôi phục mạng")
        finally:
            self._recovery_in_progress = False
        

  async def start_hosting_services(self, known_server_files: dict = None):
      """Khởi động các dịch vụ Host: Sync -> Game -> Tunnel"""
      if self.sync_service:
          logger.debug("[Hosting] Hosting services đã active, bỏ qua khởi động lại.")
          return

      logger.info("[Hosting] Bắt đầu khởi động hosting services")
      token = self.session_manager.load_token()
      if not token:
          logger.error("[Hosting] Không thể khởi động services: Thiếu token hợp lệ")
          return

      watch_dir = self.pre_sync_manager.watch_dir
      self.sync_service = SyncService(
          watch_dir=watch_dir,
          server_url=self._settings.server_url,
          token=token
      )

      # 1. Initialize Sync (Fetch Config & Scan)
      logger.debug("[Hosting] Khởi tạo Sync Service (Fetch config & Scan)...")
      start_command = await self.sync_service.initialize(known_server_files)
      self._last_start_command = start_command # Save for Auto-Restart logic

      # 2. Start Sync Loop in Background
      self._sync_task = asyncio.create_task(self.sync_service.run_loop())
      logger.info(f"[Sync] Đã khởi động | Watch Dir: {watch_dir}")

      # 3. Start Game Server
      if self.game_server:
          if start_command:
              logger.debug(f"[GameServer] Khởi động Server: {start_command}")

              port = self._tunnel_config.game_local_port if self._tunnel_config else 25565
              await self.game_server.start_server(start_command, port=port)
          else:
              logger.warning("[Hosting] Không có lệnh khởi động Game Server từ Sync config.")

      # 4. Start Cloudflare Tunnel (Host Mode)
      if self.cloudflare_service:
          logger.info("[Cloudflare] Khởi động Cloudflare Tunnel (Host Mode)...")
          await self.cloudflare_service.start_host_mode()
          logger.info("[Hosting] Tất cả hosting services đã khởi động thành công")

  async def stop_hosting_services(self, shutdown_cf_access: bool=True, shutdown_cf_host: bool=True, offline_mode: bool=False, skip_session_stop: bool=False):
      """Dừng các dịch vụ Host theo trình tự chuẩn.
      BUG #6 FIX: Guard against concurrent calls."""
      async with self._shutdown_lock:
          if self._is_shutting_down:
              logger.debug("[Client] stop_hosting_services already in progress, skipping.")
              return
          self._is_shutting_down = True

      try:
          logger.warning("[Client] Đang dừng Hosting Services...")

          # 0. Nếu Offline Mode (Mất mạng), chặn ngay Sync để tránh Upload Spam khi tắt Server
          if offline_mode and self.sync_service:
               logger.info("[Client] Offline Mode: Hủy toàn bộ tác vụ Upload đang chờ.")
               self.sync_service.monitor.stop()
               self.sync_service.diff_manager.cancel_all()

          # 1. Dừng Tunnel trước để ngắt các kết nối mới đang vào
          if self.cloudflare_service:
              if shutdown_cf_host:
                  await self.cloudflare_service.stop_host()
              if shutdown_cf_access:
                  await self.cloudflare_service.stop_access()

          # 2. Dừng Game Server (Đợi lưu world xong)
          if self.game_server:
              await self.game_server.stop_server()

          # 3. Đợi các file đang upload dở hoàn tất
          if self.sync_service and not offline_mode:
              await self.sync_service.wait_for_pending_uploads(timeout=30.0)

          # 4. Đồng bộ cuối cùng (Final Sync) - Lúc này Heartbeat vẫn đang chạy nên Token còn sống
          if self.sync_service and not offline_mode:
              self.sync_service.ensure_session_alive()  # BUG #7 FIX
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
                  except asyncio.CancelledError:
                      pass
                  except Exception:
                      pass
              self.sync_service = None
              self._sync_task = None
      finally:
          self._is_shutting_down = False
          
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
  import sys
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

  # --- Single Instance Enforcement ---
  _instance_lock = None
  if not os.environ.get("PEERHOST_INSTANCE_LOCKED"):
      from common.instance_lock import InstanceLock
      _instance_lock = InstanceLock()
      if not _instance_lock.acquire():
          from rich.console import Console
          from rich.panel import Panel
          _c = Console()
          _c.print(Panel(
              "[bold red]Phát hiện một phiên PeerHost khác đang chạy![/bold red]\n"
              "[white]Vui lòng đóng phiên cũ trước khi mở phiên mới.[/white]",
              title="[bold yellow]Cảnh báo[/bold yellow]",
              border_style="red"
          ))
          input("Nhấn Enter để thoát...")
          sys.exit(1)

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