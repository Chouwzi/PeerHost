import asyncio
import subprocess
import os
import signal
import shlex
from pathlib import Path
from utils.logger import setup_logger

logger = setup_logger("GameServer")

class GameServerManager:
    """
    Quản lý việc chạy Minecraft Server dưới nền (Background Process).
    Bảo mật: Ẩn window, không cho user tương tác CLI.
    """
    def __init__(self, watch_dir: Path):
        self.watch_dir = watch_dir
        self.process: asyncio.subprocess.Process | None = None
        self._monitor_task: asyncio.Task | None = None
        
        # State Tracking
        self.server_ready = asyncio.Event()
        self.world_saved = asyncio.Event()

    async def start_server(self, start_command: str):
        """Khởi động server với command được cung cấp."""
        if self.process and self.process.returncode is None:
             logger.warning("[GameServer] Server đang chạy, không thể start lại.")
             return

        logger.info(f"[GameServer] Đang khởi động Server")
        
        # Tạo cờ để ẩn cửa sổ console trên Windows
        startupinfo = None
        creationflags = 0
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE # Ẩn cửa sổ
            creationflags = subprocess.CREATE_NO_WINDOW # Không tạo console window mới

        try:
            # Parse command string into args list
            args = shlex.split(start_command)
            program = args[0]
            arguments = args[1:]
            
            # Chạy subprocess trực tiếp (không qua shell)
            self.process = await asyncio.create_subprocess_exec(
                program,
                *arguments,
                cwd=self.watch_dir,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                startupinfo=startupinfo,
                creationflags=creationflags
            )
            
            logger.info(f"[GameServer] Server đã khởi động (PID: {self.process.pid})")
            
            # Start monitoring logs/status in background
            self._monitor_task = asyncio.create_task(self._monitor_output())
            
        except Exception as e:
            logger.error(f"[GameServer] Lỗi khởi động: {e}")

    async def stop_server(self) -> bool:
        """Dừng server nhẹ nhàng (Gửi lệnh stop -> Đợi -> Kill nếu cần)."""
        if not self.process:
            return

        logger.info("[GameServer] Đang dừng Server...")
        
        try:
            # 1. Graceful Shutdown: Gửi lệnh "stop"
            should_wait_save = False
            
            if self.process.stdin:
                if self.server_ready.is_set():
                    try:
                        logger.info("[GameServer] Gửi lệnh 'stop'...")
                        self.process.stdin.write(b"stop\n")
                        await self.process.stdin.drain()
                        should_wait_save = True
                    except Exception as e:
                        logger.warning(f"[GameServer] Không thể gửi lệnh stop: {e}")
                else:
                    logger.warning("[GameServer] Server chưa sẵn sàng (Starting), bỏ qua lệnh 'stop'.")

            # 2. Wait for save completion (Timeout 15s)
            # Chỉ đợi save nếu đã gửi lệnh stop thành công
            if should_wait_save:
                try:
                    await asyncio.wait_for(self.world_saved.wait(), timeout=15.0)
                    logger.info("[GameServer] Dữ liệu thế giới đã được lưu thành công.")
                except asyncio.TimeoutError:
                    logger.warning("[GameServer] Chưa nhận được xác nhận lưu dữ liệu, tiếp tục đợi process...")
            
            # 3. Wait for process to exit
            # Nếu không wait save (không gửi stop), giảm timeout xuống 1s để kill nhanh
            wait_timeout = 5.0 if should_wait_save else 1.0
            
            try:
                await asyncio.wait_for(self.process.wait(), timeout=wait_timeout)
                logger.info("[GameServer] Server đã tắt tự nhiên.")
                
                return True
            except asyncio.TimeoutError:
                logger.warning("[GameServer] Server dừng quá lâu, Force Kill.")
                
                # 3. Force Kill Tree if stuck
                if os.name == 'nt':
                     subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(self.process.pid)], 
                        creationflags=subprocess.CREATE_NO_WINDOW,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False
                     )
                self.process.kill()
                await self.process.wait()
                return True
        except Exception as e:
            logger.error(f"[GameServer] Lỗi khi dừng: {e}")
            return False
        finally:
            self.force_kill_sync()
            
    def force_kill_sync(self):
        """Hàm đồng bộ để Force Kill process (Dùng cho Win32 Handler)"""
        if self.process:
             try:
                 # 1. Kill Tree
                 if os.name == 'nt':
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(self.process.pid)], 
                        creationflags=subprocess.CREATE_NO_WINDOW,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False
                    )
                 # 2. Kill Object
                 self.process.kill()
             except:
                 pass
             
             # 3. Explicitly Close Pipes
             if self.process:
                def close_transport(stream):
                    if stream and stream._transport:
                        try:
                            stream._transport.close()
                        except Exception:
                            pass
                close_transport(self.process.stdin)
                close_transport(self.process.stdout)
                close_transport(self.process.stderr)
             
             self.process = None
             logger.info("[GameServer] Đã Force Kill Server (Sync).")

    async def _monitor_output(self):
        """Đọc log từ server và theo dõi trạng thái."""
        if not self.process:
            return
        
        # Reset states
        self.server_ready.clear()
        self.world_saved.clear()
            
        try:
            while True:
                # Đọc dòng từ stdout (Non-blocking)
                line = await self.process.stdout.readline()
                if not line:
                    break
                
                # Decode và log
                line_str = line.decode('utf-8', errors='replace').strip()
                if line_str:
                     # Log to console
                     if "Done" in line_str or "Stopping" in line_str or "Saving" in line_str:
                         logger.debug(f"[MC-Log] {line_str}")
                     else:
                         logger.debug(f"[MC-Log] {line_str}")
                         
                     # State Detection
                     if "Done" in line_str and "For help, type" in line_str:
                         self.server_ready.set()
                         logger.info("[GameServer] Server đã sẵn sàng kết nối!")
                         
                     if "ThreadedAnvilChunkStorage: All dimensions are saved" in line_str:
                         self.world_saved.set()
                         logger.info("[GameServer] Dữ liệu đã được lưu.")
                          
        except Exception:
            pass
        finally:
            logger.info("[GameServer] Process Monitor kết thúc.")
            
