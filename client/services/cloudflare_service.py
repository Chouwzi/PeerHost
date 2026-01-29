
import asyncio
import subprocess
import os
import signal
from pathlib import Path
from common.logger import setup_logger
from common.process_tracker import ProcessTracker
from models import TunnelConfig

logger = setup_logger("CloudflareSVC")

class CloudflareService:
    """
    Quản lý tiến trình Cloudflared Tunnel.
    Đảm bảo 2 chế độ hoạt động Mutual Exclusion:
    1. Host Mode: Tunneling (Public Game Server)
    2. Participant Mode: Accessing (Connect to Game Server)
    """
    def __init__(self, watch_dir: Path, settings, tunnel_config: TunnelConfig = None):
        self._watch_dir = watch_dir
        self._settings = settings
        self._host_process: asyncio.subprocess.Process | None = None
        self._access_process: asyncio.subprocess.Process | None = None
        
        # Tunnel config from server (or defaults)
        self._tunnel_config = tunnel_config or TunnelConfig()
        
        # Đường dẫn file
        self._cloudflared_path = self._watch_dir / "cloudflared-tunnel" / "cloudflared.exe"
        self._config_path = self._watch_dir / "cloudflared-tunnel" / "config.yaml"
        self._cert_path = self._watch_dir / "cloudflared-tunnel" / "cert.pem"
        self._tunnel_dir = self._cloudflared_path.parent

    def update_tunnel_config(self, tunnel_config: TunnelConfig):
        """Update tunnel config after fetching from server"""
        self._tunnel_config = tunnel_config
        logger.debug(f"[Cloudflare] Updated tunnel config: {tunnel_config.game_hostname}:{tunnel_config.game_local_port}")

    async def start_host_mode(self):
        """Chạy Tunnel để Public Server (Chỉ khi làm Host)"""
        if self._host_process and self._host_process.returncode is None:
            return # Đang chạy rồi

        await self.stop_host() # Đảm bảo dọn dẹp host cũ nếu có
        
        if not await self._validate_files():
            logger.error("[Cloudflare] Thiếu file cấu hình/cert để chạy Host Mode.")
            return

        cmd = [
            str(self._cloudflared_path),
            "tunnel", 
            "--origincert", str(self._cert_path),
            "--config", str(self._config_path),
            "run", self._tunnel_config.tunnel_name
        ]
        
        self._host_process = await self._start_subprocess(cmd, "Host-Mode", registration_key="cloudflared_host")

    async def start_participant_mode(self):
        """Chạy Access để kết nối Game (Chạy mọi lúc)"""
        if self._access_process and self._access_process.returncode is None:
            return # Đang chạy rồi

        await self.stop_access()
        
        # Participant chỉ cần file cloudflared.exe, không cần cert/config của tunnel host
        if not self._cloudflared_path.exists():
             logger.warning("[Cloudflare] Chưa có cloudflared.exe, chờ sync...")
             return # Sẽ thử lại sau khi sync xong
        
        # Use config from server
        access_hostname = self._tunnel_config.game_hostname
        access_local_url = f"127.0.0.1:{self._tunnel_config.game_local_port}"
        
        if not access_hostname:
            logger.warning("[Cloudflare] Chưa có game_hostname từ server, skip Participant mode.")
            return
             
        cmd = [
            str(self._cloudflared_path),
            "access", "tcp",
            "--hostname", access_hostname,
            "--url", access_local_url
        ]
        
        self._access_process = await self._start_subprocess(cmd, "Access-Mode", registration_key="cloudflared_access")

    async def _start_subprocess(self, cmd: list, mode_name: str, registration_key: str = None):
        logger.info(f"[Cloudflare] Đang khởi động {mode_name}...")
        try:
            # Hide Console on Windows
            # Determine visibility based on debug setting
            startupinfo = None
            creationflags = 0
            
            is_debug = self._settings.debug
            
            if os.name == 'nt':
                if is_debug:
                    # Debug Mode: Show Window (New Console)
                    creationflags = subprocess.CREATE_NEW_CONSOLE
                else:
                    # Normal Mode: Hide Window completely
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    startupinfo.wShowWindow = subprocess.SW_HIDE
                    creationflags = subprocess.CREATE_NO_WINDOW
            
            # Always capture stderr for debugging purposes, even if not in debug mode
            stderr_target = asyncio.subprocess.PIPE
            stdout_target = asyncio.subprocess.DEVNULL if not is_debug else None
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=stdout_target, 
                stderr=stderr_target,
                startupinfo=startupinfo,
                creationflags=creationflags,
                cwd=str(self._tunnel_dir) # CRITICAL: Ensure it can find local config/jsons
            )
            
            # Wait a moment to see if it crashes immediately
            await asyncio.sleep(0.5)
            if process.returncode is not None:
                stderr_output = await process.stderr.read()
                err_msg = stderr_output.decode().strip()
                logger.error(f"[Cloudflare] {mode_name} terminated immediately with code {process.returncode}. Error: {err_msg}")
                return None

            logger.info(f"[Cloudflare] {mode_name} Started (PID: {process.pid})")
            
            if registration_key:
                 ProcessTracker().register(registration_key, process.pid, "cloudflared.exe")
            
            return process
        except Exception as e:
            logger.error(f"[Cloudflare] Error starting {mode_name}: {e}")
            return None

    async def stop_host(self):
        """Dừng tiến trình Tunnel Host"""
        if self._host_process:
            logger.warning(f"[Cloudflare] Đang dừng Host-Mode (PID: {self._host_process.pid})...")
            await self._stop_process(self._host_process)
            
            # Unregister
            ProcessTracker().unregister("cloudflared_host")
            
            self._host_process = None

    async def stop_access(self):
        """Dừng tiến trình Access Participant"""
        if self._access_process:
            logger.warning(f"[Cloudflare] Đang dừng Access-Mode (PID: {self._access_process.pid})...")
            await self._stop_process(self._access_process)
            
            # Unregister
            ProcessTracker().unregister("cloudflared_access")
            
            self._access_process = None

    async def stop_any(self):
        """Dừng tất cả các tiến trình Cloudflare"""
        await self.stop_host()
        await self.stop_access()

    def is_host_running(self) -> bool:
        """Kiểm tra Tunnel Host còn sống không"""
        return self._host_process is not None and self._host_process.returncode is None

    def is_access_running(self) -> bool:
        """Kiểm tra Access Participant còn sống không"""
        return self._access_process is not None and self._access_process.returncode is None

    async def _stop_process(self, process: asyncio.subprocess.Process):
        try:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=3.0)
            except asyncio.TimeoutError:
                if os.name == 'nt':
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)], 
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                process.kill()
        except Exception as e:
            logger.error(f"[Cloudflare] Lỗi khi dừng process: {e}")

                
    async def _validate_files(self):
        return (self._cloudflared_path.exists() and 
                self._config_path.exists() and 
                self._cert_path.exists())
