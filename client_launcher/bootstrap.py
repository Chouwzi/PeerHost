import sys
import os
import requests
import zipfile
import subprocess
import io
import shutil
from pathlib import Path
from time import sleep

# Force UTF-8 Encoding for Windows Console
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

# Configuration
SERVER_URL = "https://peerhost.chouwzi.io.vn"
PYTHON_VERSION = "3.11.9"
PYTHON_EMBED_URL = f"https://www.python.org/ftp/python/{PYTHON_VERSION}/python-{PYTHON_VERSION}-embed-amd64.zip"
GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"

RUNTIME_DIR = Path("runtime")
PYTHON_EXE = RUNTIME_DIR / "python.exe"
PIP_EXE = RUNTIME_DIR / "Scripts" / "pip.exe"

def download_file(url, target_path: Path):
    print(f"[Bootstrap] Downloading {url}...")
    try:
        with requests.get(url, stream=True, timeout=30) as r:
            r.raise_for_status()
            with open(target_path, 'wb') as f:
                shutil.copyfileobj(r.raw, f)
        return True
    except Exception as e:
        print(f"[Bootstrap] Failed to download {url}: {e}")
        return False

def setup_runtime():
    """Download and set up Embedded Python Runtime."""
    if PYTHON_EXE.exists():
        return True

    print(f"[Bootstrap] Runtime not found. Setting up Python {PYTHON_VERSION}...")
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    
    # 1. Download Python Embed Zip
    zip_path = RUNTIME_DIR / "python_embed.zip"
    if not download_file(PYTHON_EMBED_URL, zip_path):
        return False

    # 2. Extract
    print("[Bootstrap] Extracting runtime...")
    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(RUNTIME_DIR)
        zip_path.unlink() # Cleanup
    except Exception as e:
        print(f"[Bootstrap] Extraction failed: {e}")
        return False

    # 3. Enable 'import site' for Pip support
    # Find python3xx._pth file
    pth_files = list(RUNTIME_DIR.glob("python*._pth"))
    if pth_files:
        pth_file = pth_files[0]
        try:
            content = pth_file.read_text()
            # Uncomment 'import site'
            new_content = content.replace("#import site", "import site")
            pth_file.write_text(new_content)
            print("[Bootstrap] Configured runtime for Pip support.")
        except Exception as e:
            print(f"[Bootstrap] Failed to modify .pth file: {e}")
            return False
            
    # 4. Install Pip
    print("[Bootstrap] Installing Pip...")
    get_pip_path = RUNTIME_DIR / "get_pip.py"
    if download_file(GET_PIP_URL, get_pip_path):
        try:
            # Run get-pip.py using the new runtime
            # IMPORTANT: Since CWD is set to RUNTIME_DIR, we must use relative path or name for the script
            # get_pip_path is absolute/relative from root. If we are in Runtime dir, just use the name
            subprocess.check_call([str(PYTHON_EXE.resolve()), get_pip_path.name], cwd=str(RUNTIME_DIR))
            get_pip_path.unlink()
        except Exception as e:
            print(f"[Bootstrap] Failed to install Pip: {e}")
            # Continue anyway? No, pip is needed for dependencies
            return False
            
    print("[Bootstrap] Runtime setup complete!")
    return True

def fetch_and_run_launcher():
    try:
        # STEP 1: Ensure Runtime exists
        if not setup_runtime():
            print("[Bootstrap] CRITICAL: Failed to setup runtime.")
            input("Press Enter to exit...")
            return

        # STEP 2: Fetch Launcher Source (Optional check for update)
        # Actually, since we have a full python environment, maybe we just run launcher.py?
        # But we still want to fetch the LATEST launcher code first from server?
        # Yes, existing logic: Fetch -> Save/Exec.
        # But now we cannot easily 'exec' inside bootstrap process properly because bootstrap is frozen.
        # Instead, we should DOWNLOAD launcher.py to disk and run it with runtime python.
        
        launcher_path = Path("client_launcher") / "launcher.py"
        launcher_path.parent.mkdir(exist_ok=True)
        
        try:
            print(f"[Bootstrap] Checking for launcher updates...")
            response = requests.get(f"{SERVER_URL}/launcher/source", timeout=10)
            if response.status_code == 200:
                launcher_path.write_text(response.text, encoding='utf-8')
            else:
                 print(f"[Bootstrap] Warning: Could not download latest launcher (HTTP {response.status_code}). Using local copy.")
        except Exception as e:
             print(f"[Bootstrap] Warning: Could not check for updates: {e}")
             
        if not launcher_path.exists():
            print("[Bootstrap] Error: Launcher script missing and download failed.")
            input("Press Enter to exit...")
            return

        # STEP 3: Run Launcher using Runtime Python
        # This allows launcher.py to use pip install (which runs in the runtime context)
        print("[Bootstrap] Starting Launcher...")
        
        # We need to make sure we run it from CWD so it finds 'client' folder
        cmd = [str(PYTHON_EXE), str(launcher_path)]
        
        # Hide console window? No, users want logs.
        try:
            subprocess.run(cmd)
        except KeyboardInterrupt:
            # User pressed Ctrl+C. The child process (launcher) should handle it.
            # We just exit gracefully.
            print("\n[Bootstrap] Exiting...")
            pass

    except Exception as e:
        print(f"[Bootstrap] System Error: {e}")
        import traceback
        traceback.print_exc()
        input("Press Enter to exit...")

if __name__ == "__main__":
    fetch_and_run_launcher()
