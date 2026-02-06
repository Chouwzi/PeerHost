
import subprocess
import os
import signal
from pathlib import Path
import logging

# Setup Server-side logger if not already executing in a context with one, 
# but generally we rely on print or standard logging in services.
logger = logging.getLogger("PeerHost.Tunnel")

class TunnelService:
    """
    Service responsible for managing the lifecycle of the API Cloudflare Tunnel.
    Follows Single Responsibility Principle: Only manages the tunnel process.
    Supports both Windows and Linux platforms.
    """
    def __init__(self):
        self._process: subprocess.Popen | None = None
        # Definite path to the isolated server tunnel directory
        self._tunnel_dir = Path("app/storage/server_tunnel").resolve()
        
        # Cross-platform: Choose correct binary based on OS
        if os.name == 'nt':
            self._executable = self._tunnel_dir / "cloudflared.exe"
        else:
            self._executable = self._tunnel_dir / "cloudflared-linux-amd64"
            
        self._config = self._tunnel_dir / "api_config.yaml"
        self._tunnel_name = "PeerHost-API"

    def start(self):
        """
        Starts the Cloudflared tunnel.
        On Windows: Opens in a separate visible console window.
        On Linux: Runs in background (logs go to stdout/stderr of parent).
        """
        if self._process:
            logger.warning("Tunnel is already running.")
            return

        if not self._validate_files():
            logger.error("Missing cloudflared files in app/storage/server_tunnel. Tunnel will not start.")
            return

        cmd = [
            str(self._executable),
            "tunnel",
            "--config", str(self._config),
            "run", self._tunnel_name
        ]

        logger.info(f"Starting API Tunnel: {' '.join(cmd)}")

        try:
            popen_kwargs = {
                "cwd": str(self._tunnel_dir),
            }
            
            if os.name == 'nt':
                # Windows: Open in a separate visible console window
                popen_kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE
            else:
                # Linux: Start new process group for clean termination
                popen_kwargs["start_new_session"] = True
            
            self._process = subprocess.Popen(cmd, **popen_kwargs)
            logger.info(f"API Tunnel started with PID: {self._process.pid}")
            
        except Exception as e:
            logger.error(f"Failed to start API Tunnel: {e}")

    def stop(self):
        """
        Stops the tunnel process gracefully.
        Uses platform-appropriate termination methods.
        """
        if self._process:
            logger.info(f"Stopping API Tunnel (PID: {self._process.pid})...")
            try:
                self._process.terminate()
                self._process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                # Force kill if graceful termination times out
                if os.name == 'nt':
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(self._process.pid)])
                else:
                    # Linux: Kill the entire process group
                    try:
                        os.killpg(os.getpgid(self._process.pid), signal.SIGKILL)
                    except ProcessLookupError:
                        pass  # Already dead
            except Exception as e:
                logger.error(f"Error stopping tunnel: {e}")
            finally:
                self._process = None

    def _validate_files(self) -> bool:
        return self._executable.exists() and self._config.exists()

# Singleton instance for simple import
tunnel_service = TunnelService()
