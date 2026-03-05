import asyncio
import subprocess
import os
import signal
import time
import shlex
import re
from pathlib import Path
from common.logger import setup_logger, console
from common.process_tracker import ProcessTracker

logger = setup_logger("GameServer")

class StartupProgressTracker:
    """Estimates Minecraft startup progress based on log phases."""
    def __init__(self):
        self.current_percent = 0.0
        self.phase = "INIT"
        
        # Phase boundaries: (Start %, Phase Name)
        self.phases = {
            "INIT": (0, "Khởi tạo"),
            "LOADER": (15, "Tải Loader"),
            "MODS": (30, "Tải Mods"),
            "WORLD_INIT": (60, "Chuẩn bị World"),
            "SPAWN": (80, "Tạo Spawn Area"),
            "DONE": (100, "Hoàn tất")
        }

    def update_from_log(self, line: str) -> float:
        # 1. Detection Logic
        if "Starting minecraft server version" in line:
            self._jump_to("INIT")
        elif "[FabricLoader]" in line or "MinecraftForge" in line or "Loading Minecraft" in line:
            self._jump_to("LOADER")
        elif "Loading mod" in line or "Registry Event" in line or "COMMON_SETUP" in line:
            self._jump_to("MODS")
        elif "Preparing level" in line or "Reloading ResourceManager" in line:
            self._jump_to("WORLD_INIT")
        elif "Preparing spawn area" in line:
            self._jump_to("SPAWN")
            # Special case: actual percentage
            match = re.search(r"Preparing spawn area: (\d+)%", line)
            if match:
                actual_val = int(match.group(1))
                # Map 0-100 to 80-99
                self.current_percent = 80 + (actual_val * 0.19)
                return self.current_percent
        elif "Done" in line and ("For help" in line or "!" in line):
            self._jump_to("DONE")
            self.current_percent = 100.0
            return 100.0

        # 2. Micro-increments to keep UI alive (max 0.1% per log line)
        # Cap based on phase boundary
        target_max = self._get_phase_max()
        if self.current_percent < target_max:
            self.current_percent += 0.05 # Increment slightly each log
            
        return self.current_percent

    def _jump_to(self, phase_key: str):
        start_p, _ = self.phases.get(phase_key, (0, ""))
        if start_p > self.current_percent:
            self.current_percent = float(start_p)
            self.phase = phase_key

    def _get_phase_max(self) -> float:
        keys = list(self.phases.keys())
        try:
            current_idx = keys.index(self.phase)
            if current_idx + 1 < len(keys):
                return float(self.phases[keys[current_idx + 1]][0]) - 0.1
        except:
            pass
        return 99.9

    def get_status_text(self) -> str:
        _, name = self.phases.get(self.phase, (0, "Đang xử lý"))
        return f"[bold #ffffff]({self.current_percent:.0f}%) [/][bold #12c2e9]S[/][bold #17bfe9]e[/][bold #1cbde9]r[/][bold #21bae9]v[/][bold #26b8e9]e[/][bold #2cb6e9]r[/] [bold #36b1e9]M[/][bold #3baee9]i[/][bold #41acea]n[/][bold #46aaea]e[/][bold #4ba7ea]c[/][bold #50a5ea]r[/][bold #56a3ea]a[/][bold #5ba0ea]f[/][bold #609eea]t[/] [bold #6b99eb]đ[/][bold #7097eb]a[/][bold #7594eb]n[/][bold #7a92eb]g[/] [bold #858deb]k[/][bold #8a8beb]h[/][bold #8f88eb]ởi[/] [bold #9486eb]đ[/][bold #9f81ec]ộ[/][bold #a47fec]n[/][bold #a97cec]g[/] [grey50][i][{name}][/i][/grey50] "

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
    def __init__(self, watch_dir: Path, session_manager=None):
        self.watch_dir = watch_dir
        self.session_manager = session_manager
        self.process: asyncio.subprocess.Process | None = None
        self._monitor_task: asyncio.Task | None = None
        
        # State Tracking
        self.server_ready = asyncio.Event()
        self.world_saved = asyncio.Event()

    def is_running(self) -> bool:
        """Kiểm tra Minecraft Server còn sống không"""
        return self.process is not None and self.process.returncode is None

    async def start_server(self, start_command: str, port: int = 25565):
        """Khởi động server với command được cung cấp."""
        if self.is_running():
            logger.warning("[GameServer] Server is already running!")
            return
            
        self.port = port # Store port for logging

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
        
        logger.info(f"[GameServer] Command: {cmd_args[0]}")
        logger.debug(f"[GameServer] Full command: {' '.join(cmd_args[:5])}...")
        
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
             
             # Increase buffer limit for long lines (e.g. huge JSON or NBT dumps)
             if self.process.stdout:
                 self.process.stdout._limit = 2**25 # 32MB buffer line limit
             
             # Register Process for Zombie Cleanup
             ProcessTracker().register("game_server", self.process.pid, "java.exe")
             
             self.server_ready.clear()
             self._monitor_task = asyncio.create_task(self._monitor_output())
             logger.info(f"[GameServer] Server started with PID: {self.process.pid}")
             
        except Exception as e:
            logger.error(f"[GameServer] Failed to start server: {e}")
            self.process = None

    async def stop_server(self):
        """Dừng server an toàn (gửi lệnh stop)."""
        if not self.is_running():
             return

        logger.warning("[GameServer] Đang dừng Server...")
        
        # Lưu PID trước khi process bị null (cần cho cleanup child processes)
        saved_pid = self.process.pid if self.process else None
        
        try:
            # 1. Graceful Shutdown: Gửi lệnh "stop"
            if self.process.stdin:
                logger.debug("[GameServer] Sending 'stop' command...")
                self.process.stdin.write(b"stop\n")
                await self.process.stdin.drain()
            
            # 2. Đợi server lưu data và tắt (Timeout 30s)
            try:
                # Wait for World Saved event FIRST (Confirm data flushed)
                should_wait_save = False
                if self.is_running():
                    should_wait_save = True
                    
                if should_wait_save:
                    try:
                        await asyncio.wait_for(self.world_saved.wait(), timeout=30.0)
                        logger.info("[GameServer] Dữ liệu Minecraft đã được lưu, vui lòng đợi upload lên server.")
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
             
             # CRITICAL: Luôn kill toàn bộ process tree (child Java processes)
             # Ngay cả khi graceful stop thành công, Java có thể spawn child processes
             # mà parent exit không tự kill (VD: Forge/Fabric launcher)
             if saved_pid:
                 self._cleanup_child_processes(saved_pid)
             
             # Luôn unregister khỏi ProcessTracker
             ProcessTracker().unregister("game_server")
             self.process = None

    def _cleanup_child_processes(self, pid: int):
        """Kill tất cả child processes còn sót lại của Java (psutil tree kill)."""
        try:
            import psutil
            # Kiểm tra parent process có còn không
            if psutil.pid_exists(pid):
                parent = psutil.Process(pid)
                children = parent.children(recursive=True)
                # Kill children trước
                for child in children:
                    try:
                        logger.debug(f"[GameServer] Killing child process: {child.name()} (PID: {child.pid})")
                        child.kill()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                # Kill parent nếu còn sống
                try:
                    parent.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
                # Đợi tất cả chết hẳn
                psutil.wait_procs(children + [parent], timeout=5)
            else:
                # Parent đã chết nhưng child có thể còn sống (orphaned)
                # Tìm các Java process mà PPID đã chết (orphaned by our process)
                for proc in psutil.process_iter(['pid', 'name', 'ppid']):
                    try:
                        if proc.info['ppid'] == pid and 'java' in proc.info['name'].lower():
                            logger.warning(f"[GameServer] Found orphaned Java child (PID: {proc.pid}). Killing...")
                            proc.kill()
                    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                        pass
        except Exception as e:
            logger.debug(f"[GameServer] Child process cleanup error: {e}")
            # Fallback: Windows taskkill
            if os.name == 'nt':
                subprocess.run(f"taskkill /F /PID {pid} /T",
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, shell=True)

    def force_kill_sync(self):
        """Force kill process synchronously (Last Resort)."""
        if self.process:
             pid = self.process.pid
             
             try:
                 # Standard kill
                 self.process.kill()
             except:
                 pass
                 
             # Kill toàn bộ process tree bằng psutil (chính xác hơn taskkill)
             if pid:
                 self._cleanup_child_processes(pid)
                              
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
        tracker = StartupProgressTracker()
        
        try:
            with console.status(tracker.get_status_text(), spinner="dots") as status:
                async for line in self.process.stdout:
                    try:
                        line_str = line.decode('utf-8', errors='replace').strip()
                    except:
                        continue
                    if not line_str:
                         continue
                        
                    # Log to console
                    logger.debug(f"[Minecraft-Log] {line_str}")
                        
                    # Update Tracker and UI
                    tracker.update_from_log(line_str)
                    status.update(tracker.get_status_text())
                    
                    # Broadcast status to Server for Participants
                    if self.session_manager:
                         now = time.time()
                         if not hasattr(self, '_last_status_sync') or (now - self._last_status_sync > 1.5):
                              self.session_manager.sync_status({
                                   "percent": tracker.current_percent,
                                   "phase": tracker.phase,
                                   "phase_name": tracker.phases.get(tracker.phase, (0, "Loading"))[1]
                              })
                              self._last_status_sync = now

                    # State Detection (Trigger Ready)
                    if "Done" in line_str and ("For help, type" in line_str or "!" in line_str):
                        self.server_ready.set()
                        status.stop() 
                        
                        # Sync "Ready" status one last time
                        if self.session_manager:
                             self.session_manager.sync_status({"percent": 100, "phase": "Ready"})
                             
                        logger.warning(f"[bold #ff0000][[/][bold #ff1000]G[/][bold #ff2100]a[/][bold #ff3100]m[/][bold #ff4200]e[/][bold #ff5300]S[/][bold #ff6300]e[/][bold #ff7400]r[/][bold #ff8500]v[/][bold #ff9400]e[/][bold #ffa200]r[/][bold #ffb100]][/] [bold #ffce00]S[/][bold #ffdd00]e[/][bold #ffeb00]r[/][bold #fffa00]v[/][bold #eaff00]e[/][bold #caff00]r[/] [bold #8cff00]M[/][bold #6dff00]i[/][bold #4eff00]n[/][bold #2eff00]e[/][bold #0fff00]c[/][bold #00ff0f]r[/][bold #00ff2e]a[/][bold #00ff4e]f[/][bold #00ff6d]t[/] [bold #00ffab]đ[/][bold #00ffca]ã[/] [bold #00faff]s[/][bold #00ebff]ẵ[/][bold #00dcff]n[/] [bold #00bfff]s[/][bold #00b1ff]à[/][bold #00a2ff]n[/][bold #0094ff]g[/] [bold #2474ff]k[/][bold #4363ff]ế[/][bold #6253ff]t[/] [bold #a131ff]n[/][bold #c021ff]ố[/][bold #df10ff]i[/][bold #ff00ff]![/]")
                        address = f"127.0.0.1:{getattr(self, 'port', 25565)}"
                        logger.warning(f"[bold #ff0000][[/][bold #ff1000]G[/][bold #ff2100]a[/][bold #ff3100]m[/][bold #ff4200]e[/][bold #ff5300]S[/][bold #ff6300]e[/][bold #ff7400]r[/][bold #ff8500]v[/][bold #ff9400]e[/][bold #ffa200]r[/][bold #ffb100]][/] Server Address: [grey50]{address}[/grey50]")
                        
                    if "ThreadedAnvilChunkStorage: All dimensions are saved" in line_str or "Seems like server is stuck while trying to close" in line_str:
                        self.world_saved.set()
        except Exception:
            pass
        finally:
            if self.process:
                rc = self.process.returncode
                if rc is not None and rc != 0 and rc != 130 and rc != -1: 
                     logger.error(f"[GameServer] Server crashed with exit code: {rc}")
                     logger.warning("[GameServer] Please check the logs above for the reason.")
                elif rc == 0:
                     logger.info("[GameServer] Server stopped successfully (Exit Code 0).")
                else:
                     logger.debug(f"[GameServer] Process monitor finished (RC: {rc}).")
