from enum import Enum, auto
import asyncio
from typing import Optional
from utils.logger import setup_logger

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
                        logger.debug(f"[StateTransition] {self.current_state.name} -> {next_state.name}")
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
        return ClientState.DISCOVERY

    async def _handle_discovery(self) -> ClientState:
        # Kiểm tra trạng thái Session từ Server
        session = await asyncio.to_thread(self.context.session_manager.get_session)
        
        # Lỗi kết nối hoặc chưa có Session
        if session is None:
             logger.debug("[Discovery] Không thể kết nối Server hoặc chưa có Session. Chuyển sang chế độ Đồng bộ.")
             return ClientState.PRE_HOST_SYNC 
             
        current_host_id = session.get("host_id")
        is_locked = session.get("is_locked")
        
        if is_locked and current_host_id != self.context._settings.host_id:
            logger.info(f"[Discovery] Session đang được Host bởi: {current_host_id}. Chuyển sang chế độ Khách (Participant).")
            return ClientState.PARTICIPANT
            
        if is_locked and current_host_id == self.context._settings.host_id:
            logger.info("[Discovery] Phát hiện Session cũ vẫn còn hiệu lực. Đang khôi phục quyền Host...")
            return ClientState.HOSTING
            
        # Session trống -> Có thể Host
        return ClientState.PRE_HOST_SYNC

    async def _handle_participant(self) -> ClientState:
        # Chế độ Khách: Liên tục đồng bộ từ Server (Witness Mode)
        logger.debug("[Participant] Đang kiểm tra cập nhật từ Server...")
        
        # 1. Đồng bộ (Sync Down)
        await self.context.pre_sync_manager.sync_from_server()
        
        # 2. Kiểm tra lại trạng thái Session
        await asyncio.sleep(2) 
        session = await asyncio.to_thread(self.context.session_manager.get_session)
        
        if not session or not session.get("is_locked"):
            logger.info("[Participant] Host đã ngắt kết nối! Đang chuẩn bị ứng cử Host...")
            return ClientState.DISCOVERY
            
        return ClientState.PARTICIPANT

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
             return ClientState.HOSTING
        else:
             return ClientState.DISCOVERY

    async def _handle_hosting(self) -> ClientState:
        # 1. Đảm bảo Sync Service & Game Server đang chạy
        # [Optimization] Pass cached manifest
        await self.context.start_hosting_services(known_server_files=self.cached_manifest)
        # Clear cache to free memory/prevent stale usage if restarted
        if self.cached_manifest:
             self.cached_manifest = None
        
        # 2. Heartbeat
        await asyncio.sleep(self.context.session_manager.heartbeat_interval)
        try:
             updated_session = await asyncio.to_thread(self.context.session_manager.heartbeat_session)
             
             # Kiểm tra tính nhất quán
             current_host_id = updated_session.get("host_id")
             if current_host_id != self.context._settings.host_id:
                  logger.warning("[Hosting] Phát hiện mất quyền Host trong lúc Heartbeat!")
                  await self.context.stop_hosting_services()
                  return ClientState.DISCOVERY
                  
        except Exception as e:
             logger.error(f"[Hosting] Lỗi Heartbeat: {e}")
             # Nếu lỗi Auth (401), coi như mất session
             await self.context.stop_hosting_services()
             return ClientState.DISCOVERY
             
        return ClientState.HOSTING
