
import subprocess
import os
from pathlib import Path
import logging

# Setup Server-side logger if not already executing in a context with one, 
# but generally we rely on print or standard logging in services.
logger = logging.getLogger("PeerHost.Tunnel")

class TunnelService:
    """
    Service responsible for managing the lifecycle of the API Cloudflare Tunnel.
    Follows Single Responsibility Principle: Only manages the tunnel process.
    """
    def __init__(self):
        self._process: subprocess.Popen | None = None
        # Definite path to the isolated server tunnel directory
        self._tunnel_dir = Path("app/storage/server_tunnel").resolve()
        self._executable = self._tunnel_dir / "cloudflared.exe"
        self._config = self._tunnel_dir / "api_config.yaml"
        self._tunnel_name = "PeerHost-API"

    def start(self):
        """
        Starts the Cloudflared tunnel in a separate visible window (Windows).
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
            # CREATE_NEW_CONSOLE to open a visible window for the user to monitor status
            creationflags = 0
            if os.name == 'nt':
                creationflags = subprocess.CREATE_NEW_CONSOLE
            
            self._process = subprocess.Popen(
                cmd,
                cwd=str(self._tunnel_dir),
                creationflags=creationflags
                # We do not redirect stdout/stderr so they appear in the new console
            )
            logger.info(f"API Tunnel started with PID: {self._process.pid}")
            
        except Exception as e:
            logger.error(f"Failed to start API Tunnel: {e}")

    def stop(self):
        """
        Stops the tunnel process gracefully.
        """
        if self._process:
            logger.info(f"Stopping API Tunnel (PID: {self._process.pid})...")
            try:
                self._process.terminate()
                # Wait a bit or logic to ensure it closes, but Popen.terminate is usually enough
                # Since it's a separate console, it might close immediately.
                self._process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                 if os.name == 'nt':
                     subprocess.run(["taskkill", "/F", "/T", "/PID", str(self._process.pid)])
            except Exception as e:
                logger.error(f"Error stopping tunnel: {e}")
            finally:
                self._process = None

    def _validate_files(self) -> bool:
        return self._executable.exists() and self._config.exists()

# Singleton instance for simple import
tunnel_service = TunnelService()
