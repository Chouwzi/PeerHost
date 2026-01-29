import json
import psutil
import logging
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class ProcessTracker:
    """
    Singleton class for tracking and cleaning up subprocesses to prevent zombies.
    Follows SRP: Only handles process state persistence and lifecycle management.
    """
    _instance: Optional['ProcessTracker'] = None
    _cache_file: Path = Path("client/cache/processes.json")
    _processes: Dict[str, Dict[str, Any]] = {}

    def __new__(cls) -> 'ProcessTracker':
        if cls._instance is None:
            cls._instance = super(ProcessTracker, cls).__new__(cls)
            cls._instance._ensure_setup()
        return cls._instance

    def _ensure_setup(self) -> None:
        """Initialize cache directory and load state."""
        try:
            self._cache_file.parent.mkdir(parents=True, exist_ok=True)
            self._load_state()
        except Exception as e:
            logger.error(f"[ProcessTracker] Failed to initialize: {e}")

    def _load_state(self) -> None:
        """Load tracked processes from JSON cache."""
        if not self._cache_file.exists():
            return
        
        try:
            with open(self._cache_file, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    self._processes = json.loads(content)
        except json.JSONDecodeError:
            logger.warning("[ProcessTracker] Cache file corrupted. Resetting.")
            self._processes = {}
        except Exception as e:
            logger.error(f"[ProcessTracker] Load error: {e}")

    def _save_state(self) -> None:
        """Save current state to JSON cache."""
        try:
            with open(self._cache_file, "w", encoding="utf-8") as f:
                json.dump(self._processes, f, indent=2)
        except Exception as e:
            logger.error(f"[ProcessTracker] Save error: {e}")

    def register(self, key: str, pid: int, process_name: str) -> None:
        """
        Registers a process to be tracked.
        
        Args:
            key: Unique identifier (e.g., 'game_server').
            pid: Process ID.
            process_name: Executable name for validation (e.g., 'java.exe').
        """
        if not key or not pid:
            return

        self._processes[key] = {
            "pid": pid,
            "name": process_name,
            "status": "active"
        }
        self._save_state()
        logger.debug(f"[ProcessTracker] Registered '{key}' (PID: {pid}, Name: {process_name})")

    def unregister(self, key: str) -> None:
        """Removes a process from tracking (Graceful shutdown)."""
        if key in self._processes:
            del self._processes[key]
            self._save_state()
            logger.debug(f"[ProcessTracker] Unregistered '{key}'")

    def cleanup_orphans(self) -> None:
        """
        Checks for orphan/zombie processes on startup and kills them.
        Should be called at application startup.
        """
        if not self._processes:
            return

        logger.info("[ProcessTracker] Checking for orphan processes...")
        
        orphans_found = False
        remaining_processes = {}

        for key, info in self._processes.items():
            pid = info.get("pid")
            name = info.get("name")
            
            if self._is_orphan(pid, name):
                logger.warning(f"[ProcessTracker] Found orphan '{key}' (PID: {pid}). Killing...")
                self._kill_process_tree(pid)
                orphans_found = True
            else:
                # If process doesn't exist or isn't our target, just remove it from tracking
                # We don't keep old state on fresh start
                pass

        # Always clear cache on startup after cleanup to start fresh
        self._processes = {}
        self._save_state()
        
        if orphans_found:
            logger.info("[ProcessTracker] Orphan cleanup completed.")

    def _is_orphan(self, pid: int, expected_name: str) -> bool:
        """Verifies if the PID exists and matches the expected process name."""
        try:
            if not psutil.pid_exists(pid):
                return False
            
            proc = psutil.Process(pid)
            # Check if name is similar (e.g., 'java.exe' in 'java.exe')
            # Warning: proc.name() might be different case or full path
            current_name = proc.name().lower()
            return expected_name.lower() in current_name
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            return False

    def _kill_process_tree(self, pid: int) -> None:
        """Terminates a process and all its children."""
        try:
            parent = psutil.Process(pid)
            children = parent.children(recursive=True)
            
            # Kill children first
            for child in children:
                try:
                    child.kill()
                except psutil.NoSuchProcess:
                    pass
            
            # Kill parent
            parent.kill()
            
            # Wait for termination
            psutil.wait_procs(children + [parent], timeout=3)
            
        except psutil.NoSuchProcess:
            pass
        except Exception as e:
            logger.error(f"[ProcessTracker] Failed to kill tree for PID {pid}: {e}")
