from enum import Enum, auto
import asyncio
from typing import Optional
from services.sync_service import fetch_server_config
from models import TunnelConfig
from common.logger import setup_logger, console as global_console

logger = setup_logger("StateMachine")

class ClientState(Enum):
    INIT = auto()
    DISCOVERY = auto() # Check session status
    PARTICIPANT = auto() # Guest / Witness Mode (Syncing)
    PRE_HOST_SYNC = auto() # Final sync before hosting
    CLAIM_HOST = auto() # Try to acquire lock
    HOSTING = auto() # Active Host
    ERROR = auto()

class StateMachine:
    def __init__(self, context):
        self.context = context # Client instance
        self.current_state = ClientState.INIT
        self.cached_manifest = None # Cache manifest for optimization
        self._handlers = {
            ClientState.INIT: self._handle_init,
            ClientState.DISCOVERY: self._handle_discovery,
            ClientState.PARTICIPANT: self._handle_participant,
            ClientState.PRE_HOST_SYNC: self._handle_pre_host_sync,
            ClientState.CLAIM_HOST: self._handle_claim_host,
            ClientState.HOSTING: self._handle_hosting,
        }

    async def run(self):
        """Main Loop of State Machine"""
        logger.info("[StateTransition] Đã khởi động")
        while True:
            handler = self._handlers.get(self.current_state)
            if handler:
                try:
                    # Execute handler and get next state
                    next_state = await handler()
                    if next_state != self.current_state:
                        logger.debug(f"[StateTransition] State change: {self.current_state.name} -> {next_state.name}")
                        self.current_state = next_state
                except Exception as e:
                    logger.error(f"[StateTransition] Error in state {self.current_state.name}: {e}")
                    await asyncio.sleep(5) # Prevent tight loop on crash
            else:
                 logger.critical(f"[StateTransition] No handler for state {self.current_state}")
                 await asyncio.sleep(1)

    # --- HANDLERS ---
    
    async def _handle_init(self) -> ClientState:
        # Khởi tạo, kiểm tra môi trường
        
        # 0. Fetch tunnel config from server (once)
        if self.context._tunnel_config is None:
            logger.info("[Init] Đang lấy cấu hình tunnel từ server...")
            config = await fetch_server_config(self.context._settings.server_url)
            if config:
                self.context._tunnel_config = TunnelConfig(
                    tunnel_name=config.get("tunnel_name", "PeerHost"),
                    game_hostname=config.get("game_hostname", ""),
                    game_local_port=config.get("game_local_port", 2812)
                )
                self.context.cloudflare_service.update_tunnel_config(self.context._tunnel_config)
                logger.info(f"[Init] Tunnel config: {self.context._tunnel_config.game_hostname}:{self.context._tunnel_config.game_local_port}")
            else:
                logger.warning("[Init] Không lấy được config từ server, dùng giá trị mặc định.")
                self.context._tunnel_config = TunnelConfig()
                self.context.cloudflare_service.update_tunnel_config(self.context._tunnel_config)
        
        # 1. Check Cloudflared (Priority Sync)
        # Nếu chưa có file executable, tải ngay thư mục đó để User vào game được sớm nhất
        cloudflared_path = self.context.cloudflare_service._cloudflared_path
        if not cloudflared_path.exists():
            logger.info("[Init] Chưa tìm thấy Cloudflared. Đang tải ưu tiên...")
            # Sync priority folder "cloudflared-tunnel"
            # Note: We need relative path pattern from watch_dir. 
            # cloudflared-tunnel is in watch_dir?
            # Based on cloudflare_service.py: self._cloudflared_path = self._watch_dir / "cloudflared-tunnel" / "cloudflared.exe"
            await self.context.pre_sync_manager.sync_priority(["cloudflared-tunnel/*"])
            
        # 2. Bật mặc định chế độ Participant (Access) để sẵn sàng vào game
        await self.context.cloudflare_service.start_participant_mode()
        return ClientState.DISCOVERY

    async def _handle_discovery(self) -> ClientState:
        # 1. Kiểm tra kết nối mạng (Lightweight Ping)
        is_connected = await asyncio.to_thread(self.context.session_manager.check_connection)
        
        if not is_connected:
            logger.warning("[Discovery] Mất kết nối Server. Đang chờ kết nối lại...")
            while True:
                await asyncio.sleep(2)
                is_connected = await asyncio.to_thread(self.context.session_manager.check_connection)
                if is_connected:
                    break
            return ClientState.DISCOVERY 

        # 2. Kiểm tra trạng thái Session từ Server
        session = await asyncio.to_thread(self.context.session_manager.get_session)
        
        # Nếu đã có mạng (ping OK) mà get_session trả về None -> Server lỗi 500/404 hoặc JSON die.
        # Vẫn thử PreHostSync để xem có cứu vãn được không (nếu lỗi lạ), hoặc loop tiếp.
        # Tuy nhiên, nếu server sống mà trả 200 OK thì session sẽ có data.
        if session is None:
             logger.debug("[Discovery] Server phản hồi nhưng không lấy được Session. Chuyển sang PreSync.")
             return ClientState.PRE_HOST_SYNC 
             
        # Start Participant Tunnel (Access Mode) if locked by someone else
        current_host_id = session.get("host_id")
        is_locked = session.get("is_locked")
        
        if is_locked and current_host_id != self.context._settings.host_id:
            logger.info("[Discovery] Thế giới đã có người Host. Đang kết nối...")
            
            # Save host_id for later display
            self._current_host_id = current_host_id
            await self.context.cloudflare_service.start_participant_mode()
            return ClientState.PARTICIPANT
            
        if is_locked and current_host_id == self.context._settings.host_id:
            logger.info("[Discovery] Phát hiện Session cũ vẫn còn hiệu lực. Đang xác thực lại dữ liệu...")
            # If we are already synced, we can jump forward
            if self.context.pre_sync_manager._is_synced:
                 if not self.cached_manifest:
                      self.cached_manifest = {f["path"]: f["hash"] for f in self.context.pre_sync_manager._last_manifest_data.get("files", [])} if self.context.pre_sync_manager._last_manifest_data else None
                 return ClientState.CLAIM_HOST
            return ClientState.PRE_HOST_SYNC
            
        # Session trống -> Có thể Host
        if self.context.pre_sync_manager._is_synced:
             if not self.cached_manifest:
                  self.cached_manifest = {f["path"]: f["hash"] for f in self.context.pre_sync_manager._last_manifest_data.get("files", [])} if self.context.pre_sync_manager._last_manifest_data else None
             logger.debug("[Discovery] Dữ liệu đã đồng bộ. Chuyển sang Claim Host.")
             return ClientState.CLAIM_HOST
             
        return ClientState.PRE_HOST_SYNC

    async def _handle_participant(self) -> ClientState:
        # Chế độ Khách: Liên tục đồng bộ từ Server (Witness Mode)
        # Ensure Access Client is running
        
        logger.debug("[Participant] Đang kiểm tra cập nhật từ Server...")
        
        # 1. Đồng bộ (Sync Down)
        is_synced, _, _, manifest = await self.context.pre_sync_manager.sync_from_server()
        if is_synced:
             self.cached_manifest = manifest
        
        # 2. Kiểm tra lại trạng thái Session và Hiển thị Progress (nếu có)
        session = await asyncio.to_thread(self.context.session_manager.get_session)
        
        if not session or not session.get("is_locked"):
            logger.info("[Participant] Host đã ngắt kết nối! Đang chuẩn bị ứng cử Host...")
            self._cleanup_participant_ui()
            return ClientState.DISCOVERY
            
        status_data = session.get("status")
        if status_data:
             percent = status_data.get("percent", 0)
             phase_name = status_data.get("phase_name", "Đang khởi động")
             phase_key = status_data.get("phase")
             
             if percent < 100 and phase_key != "Ready":
                  msg = f"[bold #ffffff]({percent:.0f}%) [/][bold #12c2e9]Đ[/][bold #17bfe9]a[/][bold #1cbde9]n[/][bold #21bae9]g[/] [bold #26b8e9]đ[/][bold #2cb6e9]ợ[/][bold #31b3e9]i[/] [bold #36b1e9]H[/][bold #3baee9]o[/][bold #41acea]s[/][bold #46aaea]t[/] [bold #4ba7ea]m[/][bold #50a5ea]ở[/] [bold #56a3ea]S[/][bold #5ba0ea]e[/][bold #609eea]r[/][bold #6b99eb]v[/][bold #7097eb]e[/][bold #7594eb]r[/] [grey50][i][{phase_name}][/i][/grey50]"
                  if not hasattr(self, '_participant_status'):
                       self._participant_status = global_console.status(msg)
                       self._participant_status.start()
                  else:
                       self._participant_status.update(msg)
             else:
                  # Server is ready
                  if hasattr(self, '_participant_status'):
                       self._participant_status.stop()
                       del self._participant_status
                  
                  if not hasattr(self, '_showed_ready_msg'):
                       host_id = getattr(self, '_current_host_id', 'Unknown')
                       logger.info(f"[Participant] [bold #00ff00]S[/][bold #05ff00]e[/][bold #0aff00]r[/][bold #0fff00]v[/][bold #14ff00]e[/][bold #19ff00]r[/] [bold #23ff00]đ[/][bold #28ff00]ã[/] [bold #32ff00]s[/][bold #37ff00]ẵ[/][bold #3cff00]n[/] [bold #46ff00]s[/][bold #4bff00]à[/][bold #50ff00]n[/][bold #55ff00]g[/] [bold #5fff00]![/]")
                       logger.info(f"[Participant] Host hiện tại: [bold yellow]{host_id}[/bold yellow]")
                       port = self.context._tunnel_config.game_local_port if self.context._tunnel_config else 25565
                       address = f"127.0.0.1:{port}"
                       logger.warning(f"[bold #ff0000][[/][bold #ff1000]G[/][bold #ff2100]a[/][bold #ff3100]m[/][bold #ff4200]e[/][bold #ff5300]S[/][bold #ff6300]e[/][bold #ff7400]r[/][bold #ff8500]v[/][bold #ff9400]e[/][bold #ffa200]r[/][bold #ffb100]][/] Server Address: [bold #00ff00]{address}[/bold #00ff00]")
                       self._showed_ready_msg = True
        else:
             # No status data yet - starting
             if not hasattr(self, '_participant_status'):
                  self._participant_status = global_console.status("[bold #12c2e9]Đang đợi dữ liệu từ Host...[/]")
                  self._participant_status.start()

        await asyncio.sleep(2) 
        return ClientState.PARTICIPANT

    def _cleanup_participant_ui(self):
        """Dọn dẹp các thanh trạng thái của chế độ khách"""
        if hasattr(self, '_participant_status'):
             try:
                 self._participant_status.stop()
             except:
                 pass
             del self._participant_status
        if hasattr(self, '_showed_ready_msg'):
             del self._showed_ready_msg

    async def _handle_pre_host_sync(self) -> ClientState:
        # Đảm bảo dữ liệu Local khớp hoàn toàn với Server trước khi Host
        logger.debug("[PreHostSync] Đang xác thực dữ liệu toàn vẹn với Server...")
        is_synced, _, _, manifest = await self.context.pre_sync_manager.sync_from_server()
        
        if is_synced:
            self.cached_manifest = manifest
            logger.info("[PreHostSync] Đã đồng bộ dữ liệu hoàn toàn với Server.")
            return ClientState.CLAIM_HOST
        else:
            logger.warning("[PreHostSync] Đồng bộ chưa hoàn tất. Đang thử lại...")
            await asyncio.sleep(2)
            return ClientState.PRE_HOST_SYNC

    async def _handle_claim_host(self) -> ClientState:
        success = await asyncio.to_thread(self.context.session_manager.claim_session)
        
        if success:
             self.context.start_heartbeat_monitor()
             return ClientState.HOSTING
        else:
             return ClientState.DISCOVERY

    async def _handle_hosting(self) -> ClientState:
        # 0. Recovery Guard: Nếu heartbeat recovery đang xử lý (stop CF, game, upload...),
        # KHÔNG can thiệp. Đợi recovery hoàn tất rồi mới kiểm tra lại.
        if self.context._recovery_in_progress:
            logger.debug("[Hosting] Recovery đang xử lý, chờ hoàn tất...")
            await asyncio.sleep(2)
            return ClientState.HOSTING

        # 1. Kiểm tra Heartbeat TRƯỚC khi khởi động lại services
        # Nếu heartbeat đã dừng (do recovery vừa xong hoặc bị hủy), chuyển DISCOVERY ngay
        # để tránh khởi động lại services một cách lãng phí.
        if not self.context._heartbeat_task or self.context._heartbeat_task.done():
             logger.warning("[Hosting] Heartbeat task đã dừng. Quay lại discovery để re-sync.")
             return ClientState.DISCOVERY

        # 2. Đảm bảo Sync Service & Game Server đang chạy
        # [Optimization] Pass cached manifest
        await self.context.start_hosting_services(known_server_files=self.cached_manifest)
        # Clear cache to free memory/prevent stale usage if restarted
        if self.cached_manifest:
             self.cached_manifest = None

        # 3. Monitor Services Health
        await asyncio.sleep(2)

        # Re-check recovery flag sau khi sleep (recovery có thể bắt đầu trong lúc sleep)
        if self.context._recovery_in_progress:
            logger.debug("[Hosting] Recovery bắt đầu trong lúc monitor, chờ hoàn tất...")
            return ClientState.HOSTING

        # Re-check Heartbeat (có thể dừng trong lúc sleep)
        if not self.context._heartbeat_task or self.context._heartbeat_task.done():
             logger.warning("[Hosting] Heartbeat task dừng giữa lúc monitoring")
             return ClientState.DISCOVERY

        # Check Cloudflare Tunnel (Host Mode)
        if not self.context.cloudflare_service.is_host_running():
             logger.error("[Hosting] Cloudflare tunnel (host) đã bị tắt bất thường")
             return ClientState.DISCOVERY

        # Check Game Server
        if self.context.game_server and not self.context.game_server.is_running():
             logger.error("[Hosting] Game server đã bị tắt bất thường")

             # Auto-Restart Logic
             if self.context._last_start_command:
                 logger.info("[Hosting] Đang thử khôi động lại game server...")
                 try:
                     port = self.context._tunnel_config.game_local_port if self.context._tunnel_config else 25565
                     await self.context.game_server.start_server(self.context._last_start_command, port=port)
                     # Wait a bit to prevent rapid loop if it crashes immediately
                     await asyncio.sleep(5)
                     logger.info("[Hosting] Game server khôi động lại thành công")
                     return ClientState.HOSTING
                 except Exception as e:
                     logger.error(f"[Hosting] Lỗi khi khôi động lại: {e}")

             return ClientState.DISCOVERY

        logger.debug("[Hosting] Tất cả services đang hoạt động bình thường")
        return ClientState.HOSTING
