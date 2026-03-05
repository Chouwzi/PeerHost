"""
Single-instance enforcement using OS-level file locking.
Cross-platform: msvcrt.locking (Windows) / fcntl.flock (Linux).

Lock file: client/cache/peerhost.lock
The OS kernel guarantees lock release on process death (crash, SIGKILL, etc.).

Includes stale lock detection: if a previous process crashed and left a lock file,
this code detects it and cleans up automatically.
"""
import os
import sys
import atexit
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class InstanceLock:
    _lock_file: Path = Path(__file__).resolve().parent.parent / "cache" / "peerhost.lock"

    def __init__(self):
        self._fd: Optional[object] = None
        self._acquired = False

    def _is_process_alive(self, pid: int) -> bool:
        """Check if a process with given PID is still alive."""
        try:
            import psutil
            return psutil.pid_exists(pid)
        except ImportError:
            # psutil not available, assume process is alive to be safe
            logger.warning("[InstanceLock] psutil not available, cannot check stale locks")
            return True
        except Exception as e:
            logger.warning(f"[InstanceLock] Error checking process: {e}")
            return True

    def _cleanup_stale_lock(self) -> bool:
        """
        Detect and cleanup stale lock file from crashed process.
        Returns True if stale lock was cleaned up, False otherwise.
        """
        if not self._lock_file.exists():
            return False

        try:
            content = self._lock_file.read_text(encoding='utf-8').strip()
            if not content:
                return False

            old_pid = int(content)

            # Check if the process that held the lock is still alive
            if not self._is_process_alive(old_pid):
                logger.info(f"[InstanceLock] Detected stale lock from PID {old_pid} (process no longer exists)")
                try:
                    self._lock_file.unlink()
                    logger.info("[InstanceLock] Cleaned up stale lock file")
                    return True
                except Exception as e:
                    logger.warning(f"[InstanceLock] Failed to cleanup stale lock: {e}")
                    return False
            else:
                # Process is still alive, lock is valid
                logger.debug(f"[InstanceLock] Lock file exists and process {old_pid} is alive")
                return False

        except PermissionError:
            # File is actively locked by another process (cannot even read it)
            # This means the lock is definitely NOT stale
            logger.debug("[InstanceLock] Lock file is actively held (PermissionError on read)")
            return False

        except (ValueError, UnicodeDecodeError) as e:
            # Lock file corrupted, cleanup
            logger.warning(f"[InstanceLock] Lock file corrupted: {e}")
            try:
                self._lock_file.unlink()
                logger.info("[InstanceLock] Removed corrupted lock file")
                return True
            except Exception as cleanup_error:
                logger.error(f"[InstanceLock] Failed to cleanup corrupted lock: {cleanup_error}")
                return False

    def acquire(self) -> bool:
        try:
            self._lock_file.parent.mkdir(parents=True, exist_ok=True)
            self._fd = open(self._lock_file, 'w')

            if sys.platform == 'win32':
                import msvcrt
                msvcrt.locking(self._fd.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

            self._fd.write(str(os.getpid()))
            self._fd.flush()
            self._acquired = True

            atexit.register(self.release)
            logger.debug(f"[InstanceLock] Lock acquired (PID: {os.getpid()})")
            return True

        except (IOError, OSError):
            # Lock is held by another process, check if it's stale
            if self._fd:
                try:
                    self._fd.close()
                except Exception:
                    pass
                self._fd = None

            # Try to cleanup stale lock
            if self._cleanup_stale_lock():
                # Stale lock was cleaned up, try again
                logger.info("[InstanceLock] Retrying lock acquire after stale cleanup...")
                return self.acquire()

            return False

        except Exception as e:
            logger.error(f"[InstanceLock] Unexpected error: {e}")
            if self._fd:
                try:
                    self._fd.close()
                except Exception:
                    pass
                self._fd = None
            return False

    def release(self):
        if not self._acquired or not self._fd:
            return
        try:
            if sys.platform == 'win32':
                import msvcrt
                self._fd.seek(0)
                msvcrt.locking(self._fd.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._fd, fcntl.LOCK_UN)
            self._fd.close()
        except Exception:
            try:
                self._fd.close()
            except Exception:
                pass
        self._fd = None
        self._acquired = False
        logger.debug("[InstanceLock] Lock released")

