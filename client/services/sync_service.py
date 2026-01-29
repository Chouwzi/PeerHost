import asyncio
import hashlib
import time
import uuid
import fnmatch
from pathlib import Path
from typing import Set, Tuple, List
import aiohttp
from watchfiles import awatch, Change
from rich.progress import (
    Progress, 
    SpinnerColumn, 
    TextColumn, 
    BarColumn, 
    TaskProgressColumn, 
    TimeRemainingColumn, 
    TransferSpeedColumn, 
    DownloadColumn
)
from common.logger import setup_logger, console

logger = setup_logger("SyncService")

UPLOADER_URL = "/world/files"
MANIFEST_URL = "/world/manifest"
CONFIG_URL = "/world/config"

USER_SAFE_PATTERNS = {
    "options.txt", "optionsof.txt", "servers.dat", "usercache.json", "usernamecache.json",
    "logs/*", "crash-reports/*", "debug/*",
    "screenshots/*", "saves/*", "schematics/*",
    "resourcepacks/*", "shaderpacks/*",
    "TLauncher*", "skin_*", ".auth/*",
    "launcher_profiles.json", "launcher_accounts.json",
    "session.lock",
    "libraries/*", "logs/*", "versions/*"
}

class SessionLostError(Exception):
    """Raised when 401 Unauthorized is received from the server"""
    pass

async def fetch_server_manifest(server_url: str, timeout: int = 30) -> dict | None:
    """Hàm độc lập để lấy manifest từ server (có Retry)."""
    url = f"{server_url}{MANIFEST_URL}"
    retries = 3
    
    for attempt in range(retries):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                    if resp.status == 200:
                        # Verify JSON content type or loose check
                        return await resp.json()
                    elif resp.status in [502, 503, 504]:
                         logger.warning(f"[Manifest] Server error {resp.status}. Retrying {attempt+1}/{retries}...")
                         await asyncio.sleep(2 * (attempt + 1))
                         continue
                    else:
                        logger.error(f"[Manifest] Error fetching manifest: {resp.status}")
                        return None
        except (aiohttp.ClientConnectorError, aiohttp.ClientError) as e:
            logger.debug(f"[Manifest] Connection error: {e}. Retrying {attempt+1}/{retries}...")
            await asyncio.sleep(2 * (attempt + 1))
        except Exception as e:
            logger.error(f"[Manifest] Unexpected error: {e}")
            return None
            
    logger.error("[Manifest] Failed to fetch manifest after retries.")
    return None

async def fetch_server_config(server_url: str, timeout: int = 10) -> dict | None:
    """Hàm độc lập để lấy config từ server (có Retry)."""
    url = f"{server_url}{CONFIG_URL}"
    retries = 3
    
    for attempt in range(retries):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    elif resp.status in [502, 503, 504]:
                         logger.warning(f"[Config] Server error {resp.status}. Retrying {attempt+1}/{retries}...")
                         await asyncio.sleep(2 * (attempt + 1))
                         continue
                    else:
                        return None
        except:
             await asyncio.sleep(2 * (attempt + 1))
             continue
             
    return None

class PreSyncManager:
    """
    Quản lý việc tải file từ Server về Client TRƯỚC khi làm Host.
    Đảm bảo client có đầy đủ world data trước khi claim session.
    """
    
    def __init__(self, server_url: str, watch_dir: Path, token: str = None):
        self.server_url = server_url
        self.watch_dir = watch_dir
        self.token = token
        self._is_synced = False
        
    def set_token(self, token: str):
        """Set token sau khi client nhận được từ server"""
        self.token = token
        
    def _calculate_local_hash(self, file_path: Path) -> str:
        """Tính SHA256 của file local"""
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256_hash.update(chunk)
        return sha256_hash.hexdigest()
    
    async def get_manifest(self) -> dict | None:
        """Wrapper cho fetch_server_manifest"""
        return await fetch_server_manifest(self.server_url)
    
    async def download_file(self, relative_path: str, progress: Progress = None, task_id: int = None, file_size: int = 0) -> bool:
        """Tải một file từ server về local với Progress Bar (nếu có)"""
        url = f"{self.server_url}{UPLOADER_URL}/{relative_path}"
        headers = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        
        try:
            async with aiohttp.ClientSession() as session:
                # Use longer timeout for large files (sock_read allows long downloads as long as data flows)
                timeout = aiohttp.ClientTimeout(sock_connect=10, sock_read=300) 
                async with session.get(url, headers=headers, timeout=timeout) as resp:
                    if resp.status == 200:
                        # Tạo đường dẫn đầy đủ
                        target_path = self.watch_dir / relative_path
                        target_path.parent.mkdir(parents=True, exist_ok=True)
                        
                        # Ghi file atomic với Chunking (Unique Temp File)
                        temp_path = target_path.parent / f"{target_path.name}.{uuid.uuid4()}.tmp"
                        downloaded_bytes = 0
                        
                        with open(temp_path, "wb") as f:
                            async for chunk in resp.content.iter_chunked(32 * 1024): # 32KB chunks
                                f.write(chunk)
                                downloaded_bytes += len(chunk)
                                if progress and task_id is not None:
                                    progress.advance(task_id, advance=len(chunk))
                                    # Update filename to reflect active download (Fix concurrency display)
                                    progress.update(task_id, filename=relative_path.split("/")[-1])
                                    
                        import os
                        os.replace(temp_path, target_path)
                        
                        logger.debug(f"[PreSync] Tải thành công ({downloaded_bytes/1024:.1f} KB): {relative_path}")
                        return True
                    else:
                        logger.error(f"[PreSync] Download error {relative_path}: {resp.status}")
                        return False
        except Exception as e:
            logger.error(f"[PreSync] Exception during download {relative_path}: {e}")
            return False
            
    async def _prune_extra_files(self, server_files: list):
        """Xóa các file local không có trên server (Trừ USER_SAFE_PATTERNS)"""
        server_paths = {f["path"] for f in server_files}
        removed_count = 0
        
        for file_path in self.watch_dir.rglob("*"):
             if not file_path.is_file():
                 continue
                 
             try:
                 rel_path = file_path.relative_to(self.watch_dir).as_posix()
             except ValueError:
                 continue
                 
             # 1. Skip if exists on server
             if rel_path in server_paths:
                 continue
                 
             # 2. Skip if is SAFE Pattern
             is_safe = False
             for pattern in USER_SAFE_PATTERNS:
                 if fnmatch.fnmatch(rel_path, pattern) or fnmatch.fnmatch(file_path.name, pattern):
                     is_safe = True
                     break
             
             if is_safe:
                 # logger.debug(f"[Prune] Skip Safe File: {rel_path}")
                 continue
                 
             # 3. Delete
             try:
                 file_path.unlink()
                 logger.info(f"[Prune] Đã xóa file thừa: {rel_path}")
                 removed_count += 1
             except Exception as e:
                 logger.warning(f"[Prune] Không thể xóa {rel_path}: {e}")
                 
        if removed_count > 0:
            logger.info(f"[Prune] Đã dọn dẹp {removed_count} file thừa.")
    
    async def sync_from_server(self) -> tuple[bool, int, int, dict | None]:
        """
        So sánh và tải các file thiếu/khác biệt từ server.
        
        Returns:
            (success, downloaded_count, total_different, manifest)
        """
        logger.debug("[PreSync] Bắt đầu kiểm tra và đồng bộ từ Server...")
        
        # 1. Lấy manifest từ server
        manifest = await self.get_manifest()
        if not manifest:
            logger.error("[PreSync] Failed to fetch manifest from server")
            return False, 0, 0, None
        
        server_files = manifest.get("files", [])
        logger.debug(f"[PreSync] Server đang có {len(server_files)} file")
        
        # 2. Lấy config từ server (Check Mirror Mode)
        server_config = await fetch_server_config(self.server_url)
        mirror_sync = server_config.get("mirror_sync", False) if server_config else False
        
        if mirror_sync:
            logger.debug("[PreSync] Mirror Mode đang bật. Đang quét file thừa để xóa...")
            await self._prune_extra_files(server_files)

        # 3. So sánh với local
        files_to_download = []
        
        # Dùng tqdm cho bước so sánh nếu cần, nhưng thường rất nhanh
        for file_info in server_files:
            relative_path = file_info["path"]
            server_hash = file_info["hash"]
            file_size = file_info.get("size", 0)
            
            local_path = self.watch_dir / relative_path
            
            if not local_path.exists():
                # File không tồn tại ở local
                # Note: Append full info dict, not just path
                files_to_download.append(file_info)
                logger.debug(f"[PreSync] Thiếu file: {relative_path} ({file_size} B)")
            else:
                # File tồn tại, kiểm tra hash
                local_hash = self._calculate_local_hash(local_path)
                if local_hash != server_hash:
                    files_to_download.append(file_info)
                    logger.debug(f"[PreSync] Khác nội dung: {relative_path}")
        
        if not files_to_download:
            logger.debug("[PreSync] Tất cả file đã được đồng bộ.")
            # Ensure we return a flat dict for consistency with the download case
            server_files_dict = {f["path"]: f["hash"] for f in manifest.get("files", [])}
            return True, 0, 0, server_files_dict
        
        # 4. Tải file (Concurrent)
        total_bytes = sum(f.get("size", 0) for f in files_to_download)
        total_files = len(files_to_download)
        
        # Format size smart
        if total_bytes < 1024:
            size_str = f"{total_bytes} B"
        elif total_bytes < 1024 * 1024:
            size_str = f"{total_bytes/1024:.2f} KB"
        else:
            size_str = f"{total_bytes/1024/1024:.2f} MB"
            
        # logger.info(f"[italic grey58][PreSync] Đang đồng bộ:[/] [bold grey68]{total_files} file[/] [italic grey58]| Tổng:[/] [bold grey68]{size_str}[/]")
        
        downloaded_count = 0
        sem = asyncio.Semaphore(10) # Max 10 concurrent downloads
        
        async def download_worker(file_info, progress, task_id):
            async with sem:
                 path = file_info["path"]
                 # Update filename field at the end
                 filename = path.split("/")[-1]
                 progress.update(task_id, filename=filename)
                 
                 size = file_info.get("size", 0)
                 res = await self.download_file(path, progress, task_id, size)
                 return res
                 
        # Create rich progress bar with modern columns
        with Progress(
            SpinnerColumn(),
            TextColumn("[bold cyan]{task.description}"), # Fixed Description
            BarColumn(bar_width=40, complete_style="bold #85FF52", finished_style="bold #85FF52"),
            TaskProgressColumn(),
            DownloadColumn(),
            TransferSpeedColumn(),
            TimeRemainingColumn(),
            TextColumn("[bold yellow]{task.fields[filename]}"), # Filename at the end (Yellow)
            console=console,
            transient=True 
        ) as progress:
             task_id = progress.add_task("[bold cyan]Downloading...[/bold cyan]", total=total_bytes, filename="")
             tasks = [download_worker(f, progress, task_id) for f in files_to_download]
             results = await asyncio.gather(*tasks)
             
        downloaded_count = sum(1 for r in results if r)
        
        # Must return dict[path, hash] for cached_manifest usage in initial_scan
        server_files_dict = {f["path"]: f["hash"] for f in manifest.get("files", [])}
        
        # CRITICAL FIX: Only return True if ALL files were successfully downloaded
        is_success = (downloaded_count == len(files_to_download))
        if not is_success:
             logger.error(f"[PreSync] Đồng bộ thất bại: Chỉ tải được {downloaded_count}/{len(files_to_download)} file.")
        else:
             logger.info(f"[italic grey58][PreSync] Đồng bộ thành công:[/] [bold grey68]{downloaded_count} file[/] [italic grey58]| Tổng:[/] [bold grey68]{size_str}[/].")

        return is_success, downloaded_count, len(files_to_download), server_files_dict

    async def sync_priority(self, patterns: list[str]) -> bool:
        """
        Đồng bộ ưu tiên các file khớp pattern (VD: cloudflared-tunnel/*).
        Chặn (Wait) cho đến khi xong.
        """
        logger.info(f"[PreSync] Bắt đầu đồng bộ ưu tiên cho patterns: {patterns}")
        import fnmatch
        
        manifest = await self.get_manifest()
        if not manifest:
             logger.error("[PreSync] Error fetching manifest for priority sync.")
             return False
             
        server_files = manifest.get("files", [])
        priority_files = []
        
        for file_info in server_files:
            path = file_info["path"]
            # Check matching patterns
            is_match = False
            for pat in patterns:
                if fnmatch.fnmatch(path, pat):
                    is_match = True
                    break
            
            if is_match:
                priority_files.append(file_info)
                
        if not priority_files:
            logger.debug("[PreSync] Không tìm thấy file ưu tiên nào cần sync.")
            return True
            
        # Check diff only for these files
        to_download = []
        for file_info in priority_files:
             relative_path = file_info["path"]
             server_hash = file_info["hash"]
             local_path = self.watch_dir / relative_path
             
             if not local_path.exists():
                 to_download.append(file_info)
             else:
                 local_hash = self._calculate_local_hash(local_path)
                 if local_hash != server_hash:
                     to_download.append(file_info)
                     
        if not to_download:
             logger.info("[PreSync] Các file ưu tiên đã khớp (Skip).")
             return True
             
        total_bytes = sum(f.get("size", 0) for f in to_download)
        logger.info(f"[PreSync] Đang tải ưu tiên {len(to_download)} file ({total_bytes/1024/1024:.2f} MB)...")
        
        sem = asyncio.Semaphore(5)
        
        async def download_worker(file_info, progress, task_id):
            async with sem:
                 path = file_info["path"]
                 filename = path.split("/")[-1]
                 progress.update(task_id, filename=filename)

                 size = file_info.get("size", 0)
                 res = await self.download_file(path, progress, task_id, size)
                 progress.advance(task_id, advance=0) # Handled inside download_file
                 return res
                 
        with Progress(
            SpinnerColumn(),
            TextColumn("[bold magenta]{task.description}"),
            BarColumn(bar_width=40, complete_style="bold #85FF52", finished_style="bold #85FF52"),
            TaskProgressColumn(),
            DownloadColumn(),
            TransferSpeedColumn(),
            TimeRemainingColumn(),
            TextColumn("[bold yellow]{task.fields[filename]}"), # Filename at end
            console=console,
            transient=True
        ) as progress:
            task_id = progress.add_task("[bold magenta]Cloudflared...[/bold magenta]", total=total_bytes, filename="")
            tasks = [download_worker(f, progress, task_id) for f in to_download]
            results = await asyncio.gather(*tasks)
            
        success_count = sum(1 for r in results if r)
        
        logger.info(f"[PreSync] Hoàn tất Priority Sync: {success_count}/{len(to_download)} file.")
        return success_count == len(to_download)

    
    async def is_fully_synced(self) -> bool:
        """
        Kiểm tra nhanh xem client đã sync đầy đủ với server chưa.
        """
        if self._is_synced:
            return True
        
        manifest = await self.get_manifest()
        if not manifest:
            return False
        
        server_files = manifest.get("files", [])
        
        for file_info in server_files:
            relative_path = file_info["path"]
            server_hash = file_info["hash"]
            local_path = self.watch_dir / relative_path
            
            if not local_path.exists():
                return False
            
            local_hash = self._calculate_local_hash(local_path)
            if local_hash != server_hash:
                return False
        
        self._is_synced = True
        return True

class Uploader:
    """
    Class chịu trách nhiệm tải file lên Server với cơ chế Chunking và Integrity Check.
    Có tích hợp Concurrency Limiting (Semaphore) và Retry.
    """
    def __init__(self, server_url: str, token: str, processing_context: Set[Path], watch_dir: Path, session: aiohttp.ClientSession = None, max_concurrency: int = 7):
        self.base_url = server_url
        self.token = token
        self.chunk_size = 1024 * 1024 # 1MB Chunk
        self.processing_context = processing_context # Shared context to prevent loop
        self.watch_dir = watch_dir
        self.session = session
        self.semaphore = asyncio.Semaphore(max_concurrency) # Limit concurrent uploads

    def _get_relative_path(self, file_path: Path) -> str:
        """Calculate relative path from watch_dir"""
        try:
            return file_path.relative_to(self.watch_dir).as_posix()
        except ValueError:
            return file_path.name

    async def upload_file(self, file_path: Path, known_hash: str = None) -> bool:
        """Upload một file lên server với Retry và Concurrency Limit."""
        if not file_path.exists() or not file_path.is_file():
            return False
            
        relative_path = self._get_relative_path(file_path)
        
        # Prevent concurrent uploads of the SAME file (e.g. DiffManager vs FinalSync)
        if file_path in self.processing_context:
            logger.debug(f"[Upload] File đang được xử lý bởi task khác: {relative_path}")
            return False

        self.processing_context.add(file_path)
        
        try:
            # 1. Acquire Semaphore (Limit Concurrency)
            async with self.semaphore:
                url = f"{self.base_url}{UPLOADER_URL}/{relative_path}"
                headers = {"Authorization": f"Bearer {self.token}"}
                
                # Pre-calculate Hash (Expensive CPU, do it before network but inside semaphore? No, outside better? NO, has to be careful. Let's do it inside ensure integrity.)
                # Actually calculating hash is heavy. If we do it inside semaphore, we block other uploads. If outside, we spam CPU.
                # Let's keep it here.
                
                try:
                    file_hash = await asyncio.to_thread(self._calculate_sha256, file_path) # Offload CPU
                    
                    if known_hash:
                        if file_hash == known_hash:
                            logger.debug(f"[Upload] Bỏ qua (Matched): {relative_path}")
                            return False
                        else:
                            logger.debug(f"[Upload] Mismatch {relative_path}: Local({file_hash[:8]}) != Server({known_hash[:8]})")
                    else:
                         logger.debug(f"[Upload] New File: {relative_path}")
                    
                    headers["X-File-Hash"] = file_hash
                    
                    # 2. Retry Loop
                    MAX_RETRIES = 3
                    for attempt in range(MAX_RETRIES):
                        try:
                            # Re-open file for each attempt
                            with open(file_path, 'rb') as f:
                                # Uploads can take long, disable total timeout, rely on socket read/write
                                upload_timeout = aiohttp.ClientTimeout(sock_connect=10, sock_read=60) # Reduced check timeout
                                
                                async with self.session.post(url, data=f, headers=headers, timeout=upload_timeout) as resp:
                                    if resp.status == 210 or resp.status == 201: # Success
                                        logger.debug(f"[Upload] Upload thành công: {relative_path}")
                                        return True
                                    elif resp.status == 401:
                                        logger.error(f"[Upload] Lỗi 401: Unauthorized - Huỷ bỏ sync.")
                                        raise SessionLostError("Session expired or unauthorized")
                                    elif resp.status == 400:
                                        logger.warning(f"[Upload] Integrity Mismatch (File thay đổi trong quá trình upload): {relative_path}. Đang thử lại {attempt+1}/{MAX_RETRIES}")
                                        await asyncio.sleep(1)
                                        continue # Retry: recalculate hash and upload again
                                    elif resp.status == 403:
                                        logger.warning(f"[Upload] Bị từ chối (File cấm): {relative_path}")
                                        return False
                                    elif resp.status in [500, 502, 503, 504]:
                                         logger.warning(f"[Upload] Lỗi Server {resp.status} - {relative_path}. Đang thử lại {attempt+1}/{MAX_RETRIES}")
                                         await asyncio.sleep(2 * (attempt + 1))
                                         continue
                                    else:
                                        logger.error(f"[Upload] Lỗi {resp.status}: {relative_path}")
                                        return False
                                        
                        except (aiohttp.ClientConnectorError, aiohttp.ServerDisconnectedError, asyncio.TimeoutError) as e:
                             logger.warning(f"[Upload] Lỗi mạng ({type(e).__name__}) - {relative_path}. Đang thử lại {attempt+1}/{MAX_RETRIES}")
                             await asyncio.sleep(2 * (attempt + 1))
                             continue
                        except SessionLostError:
                            raise # Re-raise 401
                        except Exception as e:
                            logger.error(f"[Upload] Lỗi không mong đợi - {relative_path}. Đang thử lại {attempt+1}/{MAX_RETRIES}")
                            await asyncio.sleep(1)
                            continue

                    logger.error(f"[Upload] Không thể upload {relative_path} sau {MAX_RETRIES} lần thử.")
                    return False
                    
                except SessionLostError:
                    raise
                except PermissionError:
                    logger.debug(f"[Upload] File bị khóa bởi Game (Locked): {relative_path}. Sẽ thử lại sau hoặc đợi tắt Server.")
                    return False
                except Exception as e:
                     logger.error(f"[Upload] Lỗi không mong đợi trong logic upload: {e}")
                     return False
                     
        finally:
            if file_path in self.processing_context:
                self.processing_context.remove(file_path)

    def _calculate_sha256(self, file_path: Path) -> str:
        """Tính SHA256 của file."""
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    async def revert_file(self, file_path: Path):
        """
        Tải file chuẩn từ Server về để ghi đè (Auto-Revert).
        Dùng processing_context để tránh Revert Loop.
        """
        relative_path = self._get_relative_path(file_path)
        url = f"{self.base_url}{UPLOADER_URL}/{relative_path}"

        logger.debug(f"[Security] Đang khôi phục tập tin gốc: {relative_path}...")
        
        self.processing_context.add(file_path)
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        content = await resp.read()
                        
                        # Ghi đè file Atomic
                        temp_path = file_path.with_suffix(".tmp")
                        with open(temp_path, "wb") as f:
                            f.write(content)
                        import os
                        os.replace(temp_path, file_path)
                        logger.debug(f"[Security] Đã khôi phục tập tin: {relative_path}")
                    else:
                        logger.debug(f"[Security] Failed to revert file {relative_path}: {resp.status}")
        except Exception as e:
             logger.debug(f"[Security] Revert Error: {e}")
        finally:
            # 2. Remove from processing context (sau 1-2s để trôi hết events pending)
            await asyncio.sleep(2.0)
            if file_path in self.processing_context:
                self.processing_context.remove(file_path)


class DiffManager:
    """
    Quản lý sự thay đổi file, bao gồm Debounce và Filter.
    """
    def __init__(self, uploader: Uploader, watch_dir: Path, 
                 processing_context: Set[Path], 
                 ignored_patterns: List[str] = None):
        self.uploader = uploader
        self.watch_dir = watch_dir
        self.queue = asyncio.Queue()
        self.processing_tasks = {} # Map path -> Timer task
        self.processing_context = processing_context
        self.ignored_patterns = ignored_patterns or []
        self.restricted_patterns = [] # Sẽ được update từ Config
        self.readonly_patterns = [] # Infrastructure files (Download only)

    async def enqueue(self, event_type: Change, file_path: Path):
        """Đẩy event vào hàng đợi xử lý."""
        
        if file_path in self.processing_context:
            logger.debug(f"[Security] Bỏ qua sự kiện đang được xử lý: {file_path.name}")
            return

        try:
            rel_path = file_path.relative_to(self.watch_dir).as_posix()
        except ValueError:
            rel_path = file_path.name

        if self._is_ignored(rel_path):
            return

        # Check Read-Only Policy (Infrastructure Isolation)
        if self._is_readonly(rel_path):
             logger.debug(f"[SyncPolicy] Bỏ qua Upload (Read-Only Infrastructure): {rel_path}")
             return

        await self.queue.put((event_type, file_path))

    def _is_readonly(self, rel_path: str) -> bool:
        """Check xem file có phải infrastructure (Read-Only) không"""
        filename = rel_path.split("/")[-1]
        for pattern in self.readonly_patterns:
            if fnmatch.fnmatch(rel_path, pattern) or fnmatch.fnmatch(filename, pattern):
                return True
        return False

    def _is_ignored(self, rel_path: str) -> bool:
        """Check xem file có trong danh sách ignore không (Dùng relative path)"""
        filename = rel_path.split("/")[-1]
        for pattern in self.ignored_patterns:
            # Check cả full path và chỉ filename (hỗ trợ legacy patterns như *.tmp)
            if fnmatch.fnmatch(rel_path, pattern) or fnmatch.fnmatch(filename, pattern):
                return True
        return False

    async def start_consumer(self):
        """Vòng lặp xử lý event."""
        while True:
            event_type, file_path = await self.queue.get()
            
            if file_path.name in self.restricted_patterns:
                logger.debug(f"[Security] Phát hiện tập tin bị cấm chỉnh sửa: {file_path.name}")
                asyncio.create_task(self.uploader.revert_file(file_path))
                self.queue.task_done()
                continue
            
            if file_path in self.processing_tasks:
                self.processing_tasks[file_path].cancel()
            
            task = asyncio.create_task(self._process_upload_delayed(file_path))
            self.processing_tasks[file_path] = task
            
            self.queue.task_done()

    async def _process_upload_delayed(self, file_path: Path):
        """Đợi 500ms rồi thực hiện upload (Debounce)."""
        try:
            await asyncio.sleep(0.5) 
            await self.uploader.upload_file(file_path)
        except asyncio.CancelledError:
            pass
        finally:
            if file_path in self.processing_tasks:
                del self.processing_tasks[file_path]
    
    async def wait_for_pending_uploads(self, timeout: float = 30.0):
        """Đợi tất cả upload đang pending hoàn thành."""
        if not self.processing_tasks:
            return 0
        
        pending_count = len(self.processing_tasks)
        logger.info(f"[Sync] Đang đợi {pending_count} upload hoàn thành (Timeout {timeout}s)...")
        
        tasks = list(self.processing_tasks.values())
        try:
            await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            logger.warning(f"[Sync] Timeout đợi pending uploads")
        
        logger.info(f"[Sync] Hoàn thành đồng bộ {pending_count} file.")
        return pending_count
    
    def cancel_all(self):
        """Hủy tất cả các task upload đang chờ hoặc đang chạy."""
        count = len(self.processing_tasks)
        if count == 0:
            return
            
        logger.info(f"[Sync] Đang hủy {count} tác vụ upload...")
        for task in self.processing_tasks.values():
            task.cancel()
        self.processing_tasks.clear()

class FileMonitor:
    """
    Theo dõi thư mục và phát hiện thay đổi file.
    """
    def __init__(self, path: Path, diff_manager: DiffManager):
        self.path = path
        self.diff_manager = diff_manager
        self._stop_event = asyncio.Event()

    async def start(self):
        """Bắt đầu theo dõi."""
        logger.debug(f"[Sync] Bắt đầu theo dõi thư mục: {self.path}")
        try:
            async for changes in awatch(self.path, stop_event=self._stop_event):
                for change, file_path_str in changes:
                    file_path = Path(file_path_str)
                    
                    if change == Change.modified or change == Change.added:
                        await self.diff_manager.enqueue(change, file_path)
                        
        except Exception as e:
            logger.error(f"[Sync] Monitor error: {e}")

    def stop(self):
        self._stop_event.set()

class SyncService:
    """
    Orchestrator chỉnh tính năng Sync.
    """
    def __init__(self, watch_dir: Path, server_url: str, token: str):
        self.watch_dir = watch_dir
        self.server_url = server_url
        self.processing_context: Set[Path] = set() # Shared state
        self._session: aiohttp.ClientSession | None = None
        self.uploader = Uploader(server_url, token, self.processing_context, watch_dir, None, max_concurrency=5)
        self.diff_manager = DiffManager(self.uploader, watch_dir, self.processing_context)
        self.monitor = FileMonitor(watch_dir, self.diff_manager)
    
    async def fetch_config(self) -> str | None:
        """Lấy cấu hình Sync từ Server. Trả về start_command nếu có."""
        url = f"{self.server_url}{CONFIG_URL}"
        try:
             async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=5) as resp:
                    if resp.status == 200:
                        config = await resp.json()
                        restricted = config.get("restricted", [])
                        ignored = config.get("ignored", [])
                        readonly = config.get("readonly", [])
                        start_cmd = config.get("start_command")
                        
                        self.diff_manager.restricted_patterns = restricted
                        self.diff_manager.ignored_patterns = ignored
                        self.diff_manager.readonly_patterns = readonly # Infrastructure Isolation
                        
                        logger.debug(f"[Config] Restricted: {len(restricted)}, Ignored: {len(ignored)}, ReadOnly: {len(readonly)}, CMD: {start_cmd}")
                        return start_cmd
                    else:
                        logger.warning(f"[Config] Không lấy được config: {resp.status}")
                        return None
        except Exception as e:
            logger.error(f"[Config] Lỗi khi lấy config: {e}")
            return None

    async def initial_scan(self, known_server_files: dict = None):
        """Scan all existing files in watch_dir and upload them."""
        if known_server_files is None:
             logger.debug("[InitialSync] Đang tải Manifest mới nhất từ server...")
             manifest = await fetch_server_manifest(self.server_url)
             if manifest:
                 data = manifest
                 known_server_files = {f["path"]: f["hash"] for f in data.get("files", [])}
                 logger.debug(f"[InitialSync] Đã tải Manifest: Server có tổng {len(known_server_files)} file.")
             else:
                 logger.error(f"[InitialSync] KHÔNG THỂ tải Manifest. Huỷ bỏ Initial Scan để tránh upload thừa.")
                 return # Abort! Safety First.

        logger.debug(f"[InitialSync] Đang quét thư mục: {self.watch_dir}")
        file_count = 0
        
        for file_path in self.watch_dir.rglob("*"):
            if file_path.is_file():
                try:
                    rel_path = file_path.relative_to(self.watch_dir).as_posix()
                except ValueError:
                    rel_path = file_path.name

                # Filter Ignore (Client-checked based on server config)
                if self.diff_manager._is_ignored(rel_path):
                    continue

                # Filter ReadOnly (Infrastructure Isolation)
                if self.diff_manager._is_readonly(rel_path):
                    continue

                if file_path.name in self.diff_manager.restricted_patterns:
                    continue

                try:
                    rel_path = file_path.relative_to(self.watch_dir).as_posix()
                except ValueError:
                    rel_path = file_path.name

                known_hash = known_server_files.get(rel_path) if known_server_files else None
                
                # [DEBUG] Trace Hash Matching
                # logger.debug(f"[Trace] File: {rel_path} | Known Hash (Prefix): {known_hash[:8] if known_hash else 'None'}")
                
                await self.uploader.upload_file(file_path, known_hash)
                file_count += 1
        
        logger.debug(f"[InitialSync] Hoàn tất. Đã quét {file_count} tệp tin.")
    
    async def initialize(self, known_server_files: dict = None) -> str | None:
        """Chuẩn bị service, lấy config và scan ban đầu. Trả về start_command."""
        if not self._session or self._session.closed:
             self._session = aiohttp.ClientSession()
             self.uploader.session = self._session

        start_cmd = await self.fetch_config()
        await self.initial_scan(known_server_files)
        return start_cmd

    async def run_loop(self):
        """Vòng lặp chính của Sync Service (Blocking)"""
        # Store task reference to cancel it gracefully later
        self._consumer_task = asyncio.create_task(self.diff_manager.start_consumer())
        await self.monitor.start()

    async def start(self, known_server_files: dict = None) -> str | None:
        """Legacy helper (nếu cần), nhưng nên dùng initialize + run_loop riêng"""
        cmd = await self.initialize(known_server_files)
        await self.run_loop()
        return cmd
    
    async def stop(self):
        """Dừng dịch vụ Sync và Cleanup Resource."""
        self.monitor.stop()
        self.diff_manager.cancel_all()
        
        # Stop consumer task gracefully
        if hasattr(self, '_consumer_task') and self._consumer_task:
            self._consumer_task.cancel()
            try:
                await self._consumer_task
            except asyncio.CancelledError:
                pass
            self._consumer_task = None
            
        if self._session and not self._session.closed:
             await self._session.close()
    
    async def wait_for_pending_uploads(self, timeout: float = 5.0) -> int:
        """Đợi tất cả upload đang pending từ DiffManager hoàn thành."""
        return await self.diff_manager.wait_for_pending_uploads(timeout)
    
    async def final_sync(self):
        """
        Đồng bộ cuối cùng sau khi Minecraft Server đã save world.
        Chỉ upload những file có hash khác với server.
        """
        logger.info("[FinalSync] Đang đồng bộ dữ liệu cuối cùng trước khi tắt...")
        
        # 1. Fetch current server manifest for hash comparison
        manifest = await fetch_server_manifest(self.server_url)
        known_hashes = {}
        if manifest:
            known_hashes = {f["path"]: f["hash"] for f in manifest.get("files", [])}
        
        uploaded = 0
        skipped = 0
        
        for file_path in self.watch_dir.rglob("*"):
            if file_path.is_file():
                try:
                    rel_path = file_path.relative_to(self.watch_dir).as_posix()
                except ValueError:
                    rel_path = file_path.name

                # Skip ignored files
                if self.diff_manager._is_ignored(rel_path):
                    continue
                
                # Skip ReadOnly (Infrastructure Isolation - Never upload back)
                if self.diff_manager._is_readonly(rel_path):
                    continue

                if file_path.name in self.diff_manager.restricted_patterns:
                    continue
                
                try:
                    rel_path = file_path.relative_to(self.watch_dir).as_posix()
                except ValueError:
                    rel_path = file_path.name
                
                # Get known hash from server
                known_hash = known_hashes.get(rel_path)
                
                try:
                    # upload_file will skip if hash matches
                    if await self.uploader.upload_file(file_path, known_hash):
                        uploaded += 1
                    else:
                        skipped += 1
                except SessionLostError:
                    logger.error("[FinalSync] Stopping final sync due to invalid session (401).")
                    break
                except Exception as e:
                    logger.warning(f"[FinalSync] Error uploading {file_path.name}: {e}")
        
        logger.info(f"[FinalSync] Hoàn tất! Đã upload {uploaded} file, bỏ qua {skipped} file không thay đổi.")
