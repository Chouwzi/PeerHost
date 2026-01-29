import sys
import os
import hashlib
import subprocess
import time
import json
import zipfile
import shutil
from pathlib import Path
# Ensure required libraries are installed
required_libs = ["requests"]
import importlib.util

def ensure_libs(libs):
    for lib in libs:
        if importlib.util.find_spec(lib) is None:
            print(f"[Launcher] Đang cài đặt thư viện: {lib} ...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", lib])

ensure_libs(required_libs)
import requests
import re

# Java Runtime Configuration
JAVA_RUNTIME_DIR = Path("runtime") / "java"
JAVA_EXE = JAVA_RUNTIME_DIR / "bin" / "java.exe"
JAVA_VERSION_FILE = JAVA_RUNTIME_DIR / ".version"

# Marker file to indicate we should use system Java
USE_SYSTEM_JAVA_FILE = Path("runtime") / ".use_system_java"

def get_current_java_version() -> str | None:
    """Get currently installed portable Java version from marker file."""
    if JAVA_VERSION_FILE.exists():
        return JAVA_VERSION_FILE.read_text().strip()
    return None

def check_system_java(required_version: str) -> bool:
    """
    Check if system Java matches the required major version.
    Returns True if system Java is available and matches.
    """
    try:
        result = subprocess.run(
            ["java", "-version"],
            capture_output=True,
            text=True,
            timeout=10
        )
        # Java version output goes to stderr
        output = result.stderr
        
        # Parse version from output like: openjdk version "21.0.2" or java version "21"
        match = re.search(r'version "(\d+)', output)
        if match:
            system_major_version = match.group(1)
            if system_major_version == required_version:
                print(f"[Launcher] Phát hiện Java {system_major_version} trên hệ thống. Sử dụng System Java.")
                return True
            else:
                print(f"[Launcher] System Java version {system_major_version} không khớp với yêu cầu ({required_version}).")
    except FileNotFoundError:
        print("[Launcher] Không tìm thấy Java trên hệ thống.")
    except Exception as e:
        print(f"[Launcher] Lỗi kiểm tra System Java: {e}")
    
    return False

def setup_java(java_version: str = "21"):
    """
    Setup Java runtime. Priority:
    1. Check if system Java matches required version
    2. Check if portable Java already downloaded and matches
    3. Download portable Java from Adoptium
    """
    # 1. Check system Java first
    if check_system_java(java_version):
        # Mark that we should use system Java
        USE_SYSTEM_JAVA_FILE.parent.mkdir(parents=True, exist_ok=True)
        USE_SYSTEM_JAVA_FILE.write_text(java_version)
        return True
    
    # Remove system java marker if exists (we'll use portable)
    if USE_SYSTEM_JAVA_FILE.exists():
        USE_SYSTEM_JAVA_FILE.unlink()
    
    # 2. Check portable Java
    current_version = get_current_java_version()
    
    if JAVA_EXE.exists() and current_version == java_version:
        print(f"[Launcher] Portable Java JDK {java_version} đã có sẵn.")
        return True
    
    if current_version and current_version != java_version:
        print(f"[Launcher] Cần cập nhật Java từ {current_version} lên {java_version}...")
        # Remove old version
        if JAVA_RUNTIME_DIR.exists():
            shutil.rmtree(JAVA_RUNTIME_DIR)
    
    # 3. Download portable Java
    print(f"[Launcher] Đang tải Java JDK {java_version} từ Adoptium...")
    JAVA_RUNTIME_DIR.parent.mkdir(parents=True, exist_ok=True)
    
    # Build Adoptium API URL dynamically
    adoptium_url = f"https://api.adoptium.net/v3/binary/latest/{java_version}/ga/windows/x64/jdk/hotspot/normal/eclipse"
    
    zip_path = JAVA_RUNTIME_DIR.parent / "java_jdk.zip"
    
    try:
        # Download with progress
        with requests.get(adoptium_url, stream=True, timeout=(30, 600)) as r:
            r.raise_for_status()
            total_size = int(r.headers.get('content-length', 0))
            downloaded = 0
            
            with open(zip_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size > 0:
                            percent = (downloaded / total_size) * 100
                            print(f"\r[Launcher] Đang tải Java: {percent:.1f}% ({downloaded // 1024 // 1024}MB / {total_size // 1024 // 1024}MB)", end="", flush=True)
            print()  # New line after progress
        
        print("[Launcher] Đang giải nén Java JDK...")
        
        # Extract to temp dir first, then rename
        temp_extract = JAVA_RUNTIME_DIR.parent / "java_temp"
        if temp_extract.exists():
            shutil.rmtree(temp_extract)
        
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(temp_extract)
        
        # Adoptium extracts to a folder like "jdk-21.0.2+13"
        # Find the extracted folder and rename to our target
        extracted_folders = list(temp_extract.iterdir())
        if extracted_folders:
            extracted_jdk = extracted_folders[0]
            if JAVA_RUNTIME_DIR.exists():
                shutil.rmtree(JAVA_RUNTIME_DIR)
            shutil.move(str(extracted_jdk), str(JAVA_RUNTIME_DIR))
        
        # Cleanup
        if temp_extract.exists():
            shutil.rmtree(temp_extract)
        zip_path.unlink()
        
        # Write version marker file
        JAVA_VERSION_FILE.write_text(java_version)
        
        print(f"[Launcher] Java JDK {java_version} đã được cài đặt thành công!")
        return True
        
    except Exception as e:
        print(f"[Launcher] Lỗi khi tải Java: {e}")
        if zip_path.exists():
            zip_path.unlink()
        return False

# Configuration
SERVER_URL = "https://peerhost.chouwzi.io.vn"

# When running via exec(), __file__ might not be reliable or point to bootstrap.py
# We should prefer using the current working directory or finding the script location carefully.
try:
    # CLIENT_DIR = Path(__file__).parent
    CLIENT_DIR = Path("client")
except NameError:
    # Fallback if __file__ is undefined (though globals() usually passes it)
    CLIENT_DIR = Path(os.getcwd())

# Ensure CLIENT_DIR is absolute for security checks
CLIENT_DIR_ABS = CLIENT_DIR.resolve()

CLIENT_SCRIPT = CLIENT_DIR / "client.py"
REQUIREMENTS_FILE = CLIENT_DIR / "requirements.txt" 

def calculate_file_hash(file_path: Path) -> str:
    """Calculate SHA256 hash of a file."""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(65536), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()

def is_safe_path(base_path: Path, target_path: Path) -> bool:
    """
    Prevent Path Traversal by checking if target_path is within base_path.
    Both should be resolved absolute paths.
    """
    # resolve() handles symlinks and '..'
    try:
        resolved_target = target_path.resolve()
        # On Windows, resolve() might return lowercase drive letters inconsistently? 
        # Usually checking str(resolved).startswith(str(base)) is enough.
        return str(resolved_target).startswith(str(base_path))
    except Exception:
        return False

def check_for_updates(): 
    """Check for updates from the server."""
    print("[Launcher] Đang kiểm tra cập nhật...")
    try:
        # Increase manifest timeout to 30s as per impact analysis
        # Server might be waking up or calculating hashes for the first time
        response = requests.get(f"{SERVER_URL}/client/manifest", timeout=30)
        
        if response.status_code != 200:
            print(f"[Launcher] Lỗi khi tải manifest: {response.status_code}")
            return False

        try:
            server_manifest = response.json()
        except json.JSONDecodeError:
            print("[Launcher] Lỗi cú pháp Manifest từ server (Có thể là phản hồi rác).")
            return False

        files = server_manifest.get("files", [])
        
        updates_needed = []
        
        for file_info in files:
            rel_path = file_info["path"]
            server_hash = file_info["hash"]
            
            # --- SECURITY CHECK: PATH TRAVERSAL ---
            # Construct the absolute target path
            target_path_raw = CLIENT_DIR / rel_path
            
            # Check if this path tries to escape CLIENT_DIR
            # Note: target_path_raw might be non-existent, resolve() might fail or resolve '..'
            # For non-existent files, resolve() works on parent if parent exists, or we check purely lexical?
            # Safer: Use os.path.abspath and check common prefix.
            
            try:
                # We need to ensure we don't write outside CLIENT_DIR_ABS
                # Let's resolve the requested path relative to CWD first? No, relative to CLIENT_DIR.
                abs_target = (CLIENT_DIR / rel_path).resolve()
            except Exception:
                 # If resolving fails (e.g. invalid chars), skip it
                 print(f"[Launcher] Warning: Skipping invalid path {rel_path}")
                 continue

            if not str(abs_target).startswith(str(CLIENT_DIR_ABS)):
                # PATH TRAVERSAL ATTEMPT DETECTED
                print(f"[Launcher] SECURITY ALERT: Bỏ qua file đáng ngờ cố ghi ra ngoài thư mục: {rel_path}")
                continue
            # --------------------------------------

            # Logic continues with safe paths
            local_path = abs_target # Use the safe absolute path
            
            # Special handling for requirements.txt (If it's inside client dir, previous check passes)
            if rel_path == "requirements.txt":
                 local_path = REQUIREMENTS_FILE.resolve()

            if not local_path.exists():
                updates_needed.append(file_info)
            else:
                local_hash = calculate_file_hash(local_path)
                if local_hash != server_hash:
                    updates_needed.append(file_info)

        if not updates_needed:
            print("[Launcher] Client đã được cập nhật.")
            return False

        print(f"[Launcher] Tìm thấy {len(updates_needed)} file cần cập nhật. Đang tải...")
        
        for file_info in updates_needed:
            rel_path = file_info["path"]
            download_url = f"{SERVER_URL}/client/files/{rel_path}"
            
            # Re-resolve for safety block (Double check before write)
            target_path = (CLIENT_DIR / rel_path).resolve()
            
            # Check again JUST IN CASE
            if not str(target_path).startswith(str(CLIENT_DIR_ABS)):
                 print(f"[Launcher] SECURITY ALERT: Skipping unsafe path {rel_path}")
                 continue

            if rel_path == "requirements.txt":
                 target_path = REQUIREMENTS_FILE
            
            # Use a temporary file path for atomic updates
            temp_path = target_path.with_suffix(target_path.suffix + ".tmp")
            
            target_path.parent.mkdir(parents=True, exist_ok=True)
            
            print(f"[Launcher] Đang tải {rel_path}...")
            
            # RETRY MECHANISM
            downloaded = False
            for attempt in range(3):
                try:
                    # STREAMING DOWNLOAD
                    # timeout=(10, 300) -> 10s to connect, 300s to read (5 mins tolerance for stalls)
                    with requests.get(download_url, stream=True, timeout=(10, 300)) as resp:
                        resp.raise_for_status()
                        
                        # Write to temp file first
                        with open(temp_path, "wb") as f:
                            for chunk in resp.iter_content(chunk_size=8192):
                                if chunk: # filter out keep-alive new chunks
                                    f.write(chunk)
                                    
                    # Rename temp file to actual file (Atomic update)
                    if target_path.exists():
                         target_path.unlink()
                    temp_path.rename(target_path)
                    
                    downloaded = True
                    break # Success
                    
                except requests.exceptions.RequestException as e:
                    print(f"[Launcher] Lỗi (Thử lại {attempt+1}/3): {e}")
                    time.sleep(2 * (attempt + 1)) # Exponentialish backoff
                except Exception as e:
                    print(f"[Launcher] Lỗi không mong muốn: {e}")
                    # Clean up temp file
                    if temp_path.exists():
                        temp_path.unlink()
                    break 
            
            if not downloaded:
                print(f"[Launcher] CRITICAL: Không thể tải {rel_path} sau 3 lần thử. Đang dừng cập nhật.")
                # Clean up temp file
                if temp_path.exists():
                    temp_path.unlink()
                return False # Stop immediately to avoid broken state

        print("[Launcher] Đã cập nhật xong!")
        return True

    except Exception as e:
        print(f"[Launcher] Lỗi kết nối: {e}")
        return False

def install_dependencies():
    """Install dependencies if needed."""
    # In frozen mode (PyInstaller), we cannot pip install. Dependencies must be bundled.
    if getattr(sys, 'frozen', False):
        # We assume dependencies are already Kbundled via hidden-imports.
        # We could verify them via importlib, but we can't fix it anyway.
        return

    if REQUIREMENTS_FILE.exists():
        print("[Launcher] Đang kiểm tra dependencies và tải nếu thiếu sót...")
        try:
             subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", str(REQUIREMENTS_FILE)])
             print("[Launcher] Đã cài đặt dependencies.")
        except subprocess.CalledProcessError:
             print("[Launcher] Lỗi: Không thể cài đặt dependencies!")

def main():
    # 0. Fetch server config to get java_version
    java_version = "21"  # Default fallback
    try:
        print("[Launcher] Đang lấy cấu hình từ server...")
        response = requests.get(f"{SERVER_URL}/world/config", timeout=10)
        if response.status_code == 200:
            config = response.json()
            java_version = config.get("java_version", "21")
            print(f"[Launcher] Java version từ server: {java_version}")
    except Exception as e:
        print(f"[Launcher] Warning: Không thể lấy cấu hình từ server: {e}")
    
    # 1. Setup Java Runtime (if not present or version mismatch)
    if not setup_java(java_version):
        print("[Launcher] CRITICAL: Không thể cài đặt Java. Một số tính năng sẽ không hoạt động.")
    
    # 2. Check for client updates
    updates_applied = check_for_updates()
    
    if updates_applied:
        install_dependencies()
        
    # Check if client script exists before launching
    if not CLIENT_SCRIPT.exists():
        print(f"[Launcher] Lỗi: Không tìm thấy {CLIENT_SCRIPT}!")
        print("[Launcher] Cài đặt thất bại. Vui lòng kiểm tra kết nối internet và thử lại.")
        return

    # 3. Launch Client
    print("[Launcher] Đang khởi động Client...")
    try:
        import runpy
        # FIX: Add client directory to sys.path so 'common' and other modules can be imported
        if str(CLIENT_DIR_ABS) not in sys.path:
            sys.path.insert(0, str(CLIENT_DIR_ABS))
            
        # Execute the client script in the current process
        # This avoids spawning a new process which would cause an infinite loop in frozen/bootstrap mode
        runpy.run_path(str(CLIENT_SCRIPT), run_name="__main__")
    except KeyboardInterrupt:
        print("[Launcher] Đang dừng...")
    except Exception as e:
        print(f"[Launcher] Lỗi: {e}")
        import traceback
        traceback.print_exc()
        input("Nhấn Enter để thoát...")

if __name__ == "__main__":
    main()