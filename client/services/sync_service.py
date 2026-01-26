import asyncio
import hashlib
import time
import fnmatch
from pathlib import Path
from typing import Set, Tuple, List
import aiohttp
from watchfiles import awatch, Change
from utils.logger import setup_logger

logger = setup_logger("SyncService")

UPLOADER_URL = "/world/files"
MANIFEST_URL = "/world/manifest"
CONFIG_URL = "/world/config"

async def fetch_server_manifest(server_url: str, timeout: int = 30) -> dict | None:
    """Hàm độc lập để lấy manifest từ server."""
    url = f"{server_url}{MANIFEST_URL}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                if resp.status == 200:
                    return await resp.json()
                else:
                    logger.error(f"[Manifest] Lỗi khi lấy manifest: {resp.status}")
                    return None
    except aiohttp.ClientConnectorError:
        # Server is down - silent fail
        logger.debug(f"[Manifest] Server không khả dụng")
        return None
    except Exception as e:
        logger.error(f"[Manifest] Lỗi kết nối lấy manifest: {e}")
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
    
    async def download_file(self, relative_path: str) -> bool:
        """Tải một file từ server về local"""
        url = f"{self.server_url}{UPLOADER_URL}/{relative_path}"
        headers = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                    if resp.status == 200:
                        content = await resp.read()
                        
                        # Tạo đường dẫn đầy đủ
                        target_path = self.watch_dir / relative_path
                        target_path.parent.mkdir(parents=True, exist_ok=True)
                        
                        # Ghi file atomic
                        temp_path = target_path.with_suffix(".tmp")
                        with open(temp_path, "wb") as f:
                            f.write(content)
                        import os
                        os.replace(temp_path, target_path)
                        
                        logger.debug(f"[PreSync] Tải thành công: {relative_path}")
                        return True
                    else:
                        logger.error(f"[PreSync] Lỗi tải file {relative_path}: {resp.status}")
                        return False
        except Exception as e:
            logger.error(f"[PreSync] Exception khi tải {relative_path}: {e}")
            return False
    
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
            logger.error("[PreSync] Không thể lấy danh sách file (Manifest) từ Server")
            return False, 0, 0, None
        
        server_files = manifest.get("files", [])
        logger.debug(f"[PreSync] Server đang có {len(server_files)} file")
        
        # 2. So sánh với local
        files_to_download = []
        
        # Dùng tqdm cho bước so sánh nếu cần, nhưng thường rất nhanh
        for file_info in server_files:
            relative_path = file_info["path"]
            server_hash = file_info["hash"]
            
            local_path = self.watch_dir / relative_path
            
            if not local_path.exists():
                # File không tồn tại ở local
                files_to_download.append(relative_path)
                logger.debug(f"[PreSync] Thiếu file: {relative_path}")
            else:
                # File tồn tại, kiểm tra hash
                local_hash = self._calculate_local_hash(local_path)
                if local_hash != server_hash:
                    files_to_download.append(relative_path)
                    logger.debug(f"[PreSync] Khác nội dung: {relative_path}")
        
        if not files_to_download:
            logger.debug("[PreSync] Dữ liệu đã đồng bộ hoàn toàn.")
            self._is_synced = True
            return True, 0, 0, {f["path"]: f["hash"] for f in server_files}
        
        logger.info(f"[PreSync] Đang đồng bộ {len(files_to_download)} file từ Server...")
        
        # 3. Tải các file thiếu/khác biệt
        downloaded = 0
        
        try:
            from tqdm import tqdm
            with tqdm(total=len(files_to_download), desc="Đang đồng bộ", unit="file", ncols=80) as pbar:
                for relative_path in files_to_download:
                    if await self.download_file(relative_path):
                        downloaded += 1
                        # logger.debug removed to keep tqdm clean
                    else:
                        pbar.write(f"[PreSync] Lỗi khi tải: {relative_path}")
                    pbar.update(1)
        except ImportError:
            for relative_path in files_to_download:
                if await self.download_file(relative_path):
                     downloaded += 1
        
        success = downloaded == len(files_to_download)
        if success:
            self._is_synced = True
            logger.info(f"[PreSync] Hoàn tất! Đã đồng bộ {downloaded}/{len(files_to_download)} tệp tin.")
        else:
            logger.warning(f"[PreSync] Chưa hoàn tất: Chỉ đồng bộ được {downloaded}/{len(files_to_download)} tệp tin.")
        
        return success, downloaded, len(files_to_download), {f["path"]: f["hash"] for f in server_files}

# ... (Uploader, DiffManager, FileMonitor classes remain unchanged - skipped for brevity in replacement if not modified)

    
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
    """
    def __init__(self, server_url: str, token: str, processing_context: Set[Path], watch_dir: Path):
        self.base_url = server_url
        self.token = token
        self.chunk_size = 1024 * 1024 # 1MB Chunk
        self.processing_context = processing_context # Shared context to prevent loop
        self.watch_dir = watch_dir

    def _get_relative_path(self, file_path: Path) -> str:
        """Calculate relative path from watch_dir"""
        try:
            return file_path.relative_to(self.watch_dir).as_posix()
        except ValueError:
            return file_path.name

    async def upload_file(self, file_path: Path, known_hash: str = None) -> bool:
        """Upload một file lên server."""
        if not file_path.exists() or not file_path.is_file():
            return False
            
        relative_path = self._get_relative_path(file_path)
        
        url = f"{self.base_url}{UPLOADER_URL}/{relative_path}"
        headers = {"Authorization": f"Bearer {self.token}"}
        
        try:
            file_hash = self._calculate_sha256(file_path)
            
            if known_hash and file_hash == known_hash:
                logger.debug(f"[Upload] Bỏ qua (Đã đồng bộ): {relative_path}")
                return False
                
            headers["X-File-Hash"] = file_hash
            
            async with aiohttp.ClientSession() as session:
                with open(file_path, 'rb') as f:
                    # Pass file object to data triggers chunked upload in aiohttp
                    async with session.post(url, data=f, headers=headers) as resp:
                        if resp.status == 201:
                            logger.debug(f"[Upload] Upload thành công: {relative_path}")
                            return True
                        elif resp.status == 400:
                            logger.error(f"[Upload] Upload thất bại (Lỗi toàn vẹn): {relative_path}")
                            return False
                        elif resp.status == 403:
                            logger.warning(f"[Upload] Bị từ chối (File cấm): {relative_path}")
                            return False
                        else:
                            logger.error(f"[Upload] Lỗi {resp.status}: {relative_path}")
                            return False
                        
        except aiohttp.ClientConnectorError:
            # Server is down - don't spam logs
            logger.debug(f"[Upload] Server không khả dụng: {relative_path}")
            return False
        except Exception as e:
            logger.error(f"[Upload] Lỗi ngoại lệ Upload: {e}")
            return False

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
                        logger.debug(f"[Security] Không thể khôi phục tập tin {relative_path}: {resp.status}")
        except Exception as e:
             logger.debug(f"[Security] Lỗi Khôi phục: {e}")
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

    async def enqueue(self, event_type: Change, file_path: Path):
        """Đẩy event vào hàng đợi xử lý."""
        
        if file_path in self.processing_context:
            logger.debug(f"[Security] Bỏ qua sự kiện đang được xử lý: {file_path.name}")
            return

        if self._is_ignored(file_path.name):
            return

        await self.queue.put((event_type, file_path))

    def _is_ignored(self, filename: str) -> bool:
        """Check xem file có trong danh sách ignore không"""
        for pattern in self.ignored_patterns:
            if fnmatch.fnmatch(filename, pattern):
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
    
    async def wait_for_pending_uploads(self, timeout: float = 5.0):
        """Đợi tất cả upload đang pending hoàn thành."""
        if not self.processing_tasks:
            return 0
        
        pending_count = len(self.processing_tasks)
        logger.debug(f"[Sync] Đang đợi {pending_count} upload hoàn thành...")
        
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
            logger.error(f"[Sync] Lỗi Monitor: {e}")

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
        self.uploader = Uploader(server_url, token, self.processing_context, watch_dir)
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
                        start_cmd = config.get("start_command")
                        
                        self.diff_manager.restricted_patterns = restricted
                        self.diff_manager.ignored_patterns = ignored
                        
                        logger.debug(f"[Config] Restricted: {len(restricted)}, Ignored: {len(ignored)}, CMD: {start_cmd}")
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
                 logger.warning(f"[InitialSync] Không tải được Manifest.")

        logger.debug(f"[InitialSync] Đang quét thư mục: {self.watch_dir}")
        file_count = 0
        
        for file_path in self.watch_dir.rglob("*"):
            if file_path.is_file():
                # Filter Ignore (Client-checked based on server config)
                if self.diff_manager._is_ignored(file_path.name):
                    continue

                if file_path.name in self.diff_manager.restricted_patterns:
                    continue

                try:
                    rel_path = file_path.relative_to(self.watch_dir).as_posix()
                except ValueError:
                    rel_path = file_path.name

                known_hash = known_server_files.get(rel_path) if known_server_files else None
                await self.uploader.upload_file(file_path, known_hash)
                file_count += 1
        
        logger.debug(f"[InitialSync] Hoàn tất. Đã quét {file_count} tệp tin.")
    
    async def initialize(self, known_server_files: dict = None) -> str | None:
        """Chuẩn bị service, lấy config và scan ban đầu. Trả về start_command."""
        start_cmd = await self.fetch_config()
        await self.initial_scan(known_server_files)
        return start_cmd

    async def run_loop(self):
        """Vòng lặp chính của Sync Service (Blocking)"""
        asyncio.create_task(self.diff_manager.start_consumer())
        await self.monitor.start()

    async def start(self, known_server_files: dict = None) -> str | None:
        """Legacy helper (nếu cần), nhưng nên dùng initialize + run_loop riêng"""
        cmd = await self.initialize(known_server_files)
        await self.run_loop()
        return cmd
    
    def stop(self):
        self.monitor.stop()
    
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
                # Skip ignored files
                if self.diff_manager._is_ignored(file_path.name):
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
                except Exception as e:
                    logger.warning(f"[FinalSync] Lỗi upload {file_path.name}: {e}")
        
        logger.info(f"[FinalSync] Hoàn tất! Đã upload {uploaded} file, bỏ qua {skipped} file không thay đổi.")
