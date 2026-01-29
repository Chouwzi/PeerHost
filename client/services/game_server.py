import asyncio
import subprocess
import os
import signal
import shlex
from pathlib import Path
from common.logger import setup_logger, console
from common.process_tracker import ProcessTracker

logger = setup_logger("GameServer")

# Portable Java paths (relative to CWD where PeerHost.exe runs)
PORTABLE_JAVA_EXE = Path("runtime") / "java" / "bin" / "java.exe"
USE_SYSTEM_JAVA_FILE = Path("runtime") / ".use_system_java"

def verify_java_exists(java_path: str) -> bool:
    """Verify that Java is actually executable at the given path."""
    try:
        result = subprocess.run(
            [java_path, "-version"],
            capture_output=True,
            timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        )
        return result.returncode == 0 or "version" in result.stderr.decode('utf-8', errors='ignore').lower()
    except Exception as e:
        logger.debug(f"[GameServer] Java verification failed for {java_path}: {e}")
        return False

def get_java_executable() -> str:
    """
    Get the Java executable path.
    Priority:
    1. System Java (if .use_system_java marker exists AND java works)
    2. Portable Java (if downloaded AND exists)
    3. Fallback to system Java (hope it works)
    """
    # Check if launcher determined we should use system Java
    if USE_SYSTEM_JAVA_FILE.exists():
        if verify_java_exists("java"):
            logger.info("[GameServer] Sử dụng System Java")
            return "java"
        else:
            logger.warning("[GameServer] System Java marker exists but Java not found in PATH!")
    
    # Check for portable Java
    if PORTABLE_JAVA_EXE.exists():
        portable_path = str(PORTABLE_JAVA_EXE.resolve())
        if verify_java_exists(portable_path):
            logger.info(f"[GameServer] Sử dụng Portable Java: {portable_path}")
            return portable_path
        else:
            logger.warning(f"[GameServer] Portable Java exists but verification failed: {portable_path}")
    
    # Last resort fallback to system Java
    logger.warning("[GameServer] Fallback to system Java (may not work)")
    return "java"

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

    def is_running(self) -> bool:
        """Kiểm tra Minecraft Server còn sống không"""
        return self.process is not None and self.process.returncode is None

    async def start_server(self, start_command: str):
        """Khởi động server với command được cung cấp."""
        if self.is_running():
            logger.warning("[GameServer] Server is already running!")
            return

        # Replace 'java' with portable Java path if available
        java_exe = get_java_executable()
        if start_command.startswith("java "):
            # Replace just the 'java' part, keeping the space
            start_command = '"' + java_exe + '"' + start_command[4:]
        
        # Use posix=False on Windows to properly handle paths with backslashes
        if os.name == 'nt':
            cmd_args = shlex.split(start_command, posix=False)
            # Remove quotes that shlex leaves in on Windows
            cmd_args = [arg.strip('"') for arg in cmd_args]
        else:
            cmd_args = shlex.split(start_command)
        cwd = self.watch_dir
        
        
        try:
             # Create startup info to hide window (Windows only)
             startupinfo = None
             if os.name == 'nt':
                 startupinfo = subprocess.STARTUPINFO()
                 startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                 startupinfo.wShowWindow = subprocess.SW_HIDE

             self.process = await asyncio.create_subprocess_exec(
                *cmd_args,
                cwd=cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                stdin=asyncio.subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0, # Extra safety
                startupinfo=startupinfo
            )
             
             # Register Process for Zombie Cleanup
             ProcessTracker().register("game_server", self.process.pid, "java.exe")
             
             self.server_ready.clear()
             self._monitor_task = asyncio.create_task(self._monitor_output())
             logger.info(f"[GameServer] Server started with PID: {self.process.pid}")
             
        except Exception as e:
            logger.error(f"[GameServer] Failed to start server: {e}")

    async def stop_server(self):
        """Dừng server an toàn (Graceful Shutdown)."""
        if not self.process:
            return

        logger.warning("[GameServer] Đang dừng Server...")
        
        try:
            # 1. Graceful Shutdown: Gửi lệnh "stop"
            if self.process.stdin:
                logger.debug("[GameServer] Sending 'stop' command...")
                self.process.stdin.write(b"stop\n")
                await self.process.stdin.drain()
            
            # 2. Đợi server lưu data và tắt (Timeout 30s)
            try:
                # Wait for World Saved event FIRST (Confirm data flushed)
                # But parallel with waiting for exit?
                # Actually server prints "Saved" then exits.
                
                # Check server ready/save events if needed
                should_wait_save = self.server_ready.is_set() # Only wait if it was fully up
                
                if should_wait_save:
                    try:
                        await asyncio.wait_for(self.world_saved.wait(), timeout=15.0)
                        logger.info("[GameServer] Dữ liệu Minecraft đã được lưu.")
                    except asyncio.TimeoutError:
                        logger.warning("[GameServer] Chưa nhận được xác nhận lưu dữ liệu, tiếp tục đợi process...")
                
                # Wait for process exit
                await asyncio.wait_for(self.process.wait(), timeout=15.0)
                logger.info("[GameServer] Server stopped gracefully.")
                
            except asyncio.TimeoutError:
                logger.warning("[GameServer] Graceful shutdown timeout. Forcing kill...")
                self.force_kill_sync()

        except Exception as e:
            logger.error(f"[GameServer] Shutdown error: {e}")
            self.force_kill_sync()
        finally:
             if self._monitor_task:
                 self._monitor_task.cancel()
             self.process = None

    def force_kill_sync(self):
        """Force kill process synchronously (Last Resort)."""
        if self.process:
             try:
                 # Standard kill
                 self.process.kill()
             except:
                 pass
                 
             # Windows TaskKill to be sure (Tree Kill)
             if os.name == 'nt' and self.process.pid:
                 subprocess.run(f"taskkill /F /PID {self.process.pid} /T", 
                              stdout=subprocess.DEVNULL, 
                              stderr=subprocess.DEVNULL,
                              shell=True)
                              
             # Close pipes to avoid leaks
             def close_transport(transport):
                 try:
                     if transport: transport.close()
                 except: pass

             if self.process.stdin: 
                close_transport(self.process.stdin.get_extra_info('pipe'))
             if self.process.stdout: 
                close_transport(self.process.stdout)
             if self.process.stderr: 
                close_transport(self.process.stderr)

             # Unregister Process
             ProcessTracker().unregister("game_server")
             
             self.process = None
             logger.warning("[GameServer] Đã Force Kill Server (Sync).")

    async def _monitor_output(self):
        """Đọc log từ server và theo dõi trạng thái."""
        self.world_saved.clear()
        
        # Adding Logging Spinner
        # Use a status context to show spinner while starting
        
        try:
            with console.status("[bold #12c2e9]S[/][bold #17bfe9]e[/][bold #1cbde9]r[/][bold #21bae9]v[/][bold #26b8e9]e[/][bold #2cb6e9]r[/] [bold #36b1e9]M[/][bold #3baee9]i[/][bold #41acea]n[/][bold #46aaea]e[/][bold #4ba7ea]c[/][bold #50a5ea]r[/][bold #56a3ea]a[/][bold #5ba0ea]f[/][bold #609eea]t[/] [bold #6b99eb]đ[/][bold #7097eb]a[/][bold #7594eb]n[/][bold #7a92eb]g[/] [bold #858deb]k[/][bold #8a8beb]h[/][bold #8f88eb]ở[/][bold #9486eb]i[/] [bold #9f81ec]đ[/][bold #a47fec]ộ[/][bold #a97cec]n[/][bold #af7aec]g[/][bold #b478ec],[/] [bold #be73ec]q[/][bold #c471ed]u[/][bold #c570e8]á[/] [bold #c86edf]t[/][bold #c96ddb]r[/][bold #cb6cd7]ì[/][bold #cc6bd2]n[/][bold #ce6ace]h[/] [bold #d168c5]n[/][bold #d267c1]à[/][bold #d466bd]y[/] [bold #d764b4]c[/][bold #d863b0]ó[/] [bold #db61a7]t[/][bold #dd60a3]h[/][bold #de5f9e]ể[/] [bold #e15d95]m[/][bold #e25c91]ấ[/][bold #e45b8d]t[/] [bold #e75984]v[/][bold #e85880]à[/][bold #ea577b]i[/] [bold #ed5573]p[/][bold #ee546e]h[/][bold #f0536a]ú[/][bold #f15266]t[/][bold #f35161].[/][bold #f4505d].[/][bold #f64f59].[/]", 
                                spinner="dots") as status:
                while self.is_running():
                    line = await self.process.stdout.readline()
                    if not line:
                        break
                        
                    try:
                        line_str = line.decode('utf-8', errors='replace').strip()
                    except:
                        continue
                        
                    if line_str:
                         # Log to console
                         if "Done" in line_str or "Stopping" in line_str or "Saving" in line_str:
                             logger.debug(f"[Minecraft-Log] {line_str}")
                         else:
                             logger.debug(f"[Minecraft-Log] {line_str}")
                             
                         # State Detection
                         if "Done" in line_str and "For help, type" in line_str:
                             self.server_ready.set()
                             # Stop spinner when ready
                             status.stop() 
                             logger.warning("[bold #ff0000][[/][bold #ff1000]G[/][bold #ff2100]a[/][bold #ff3100]m[/][bold #ff4200]e[/][bold #ff5300]S[/][bold #ff6300]e[/][bold #ff7400]r[/][bold #ff8500]v[/][bold #ff9400]e[/][bold #ffa200]r[/][bold #ffb100]][/] [bold #ffce00]S[/][bold #ffdd00]e[/][bold #ffeb00]r[/][bold #fffa00]v[/][bold #eaff00]e[/][bold #caff00]r[/] [bold #8cff00]M[/][bold #6dff00]i[/][bold #4eff00]n[/][bold #2eff00]e[/][bold #0fff00]c[/][bold #00ff0f]r[/][bold #00ff2e]a[/][bold #00ff4e]f[/][bold #00ff6d]t[/] [bold #00ffab]đ[/][bold #00ffca]ã[/] [bold #00faff]s[/][bold #00ebff]ẵ[/][bold #00dcff]n[/] [bold #00bfff]s[/][bold #00b1ff]à[/][bold #00a2ff]n[/][bold #0094ff]g[/] [bold #2474ff]k[/][bold #4363ff]ế[/][bold #6253ff]t[/] [bold #a131ff]n[/][bold #c021ff]ố[/][bold #df10ff]i[/][bold #ff00ff]![/]")
                             
                         if "ThreadedAnvilChunkStorage: All dimensions are saved" in line_str:
                             self.world_saved.set()
                            #  logger.info("[GameServer] [bold #FF0000]Dữ liệu Minecraft đã được lưu.[/bold #FF0000]")
                              
        except Exception:
            pass
        finally:
            logger.debug("[GameServer] Process monitor finished.")
