from app.core.config import STORAGE_PATH
from app.utils import json_storage
from pathlib import Path
import python_nbt.nbt as nbt
from datetime import datetime, timezone
import shutil

def get_world(world_id: str) -> dict | None:
  """Lấy thông tin cơ bản của thế giới

  Args:
      world_id (str): id thế giới

  Returns:
      dict | None: Thông tin thế giới
  """
  STORAGE_PATH.mkdir(parents=True, exist_ok=True)
  world_path = STORAGE_PATH / "worlds" / world_id
  if not world_path.exists():
    return None
  
  level_file = world_path / "world/level.dat"
  if not level_file.exists():
    return None
  
  root_tag = nbt.read_from_nbt_file(str(level_file))

  data_json = root_tag.json_obj(full_json=False)
  data: dict = data_json.get("Data")
  if not data:
    return None

  # print("\nData keys:", list(data.keys()))
  
  return {
    "id": world_id,
    "level_name": data.get("LevelName"),
    "seed": data.get("WorldGenSettings", {}).get("seed"),
    "version": data.get("Version", {}).get("Name"),
    "spawn": {
      "pos": data.get("spawn", {}).get("pos"),
      "dimension": data.get("spawn", "").get("dimension")
    },
    "game_time": data.get("Time"),
    "day_time": data.get("DayTime"),
    "difficulty": data.get("Difficulty")
  }

def list_worlds() -> list[dict]:
  """Danh sách thông tin các thế giới đang lưu trữ

  Returns:
      list[dict]: Danh sách thông tin các thế giới
  """
  worlds_path = STORAGE_PATH / "worlds"
  worlds = []
  for p in worlds_path.iterdir():
    world = get_world(world_id=p.name)
    if world: 
      worlds.append(world)
  return worlds

def delete_world(world_id: str) -> bool:
  """Xóa thế giới trên ổ đĩa

  Args:
      world_id (str): ID thế giới

  Returns:
      bool: Trạng thái xóa
  """
  world_path = STORAGE_PATH / "worlds" / world_id
  if not world_path.exists():
    return False
  
  shutil.rmtree(str(world_path))
  return True

def create_world(world_id: str) -> Path:
  worlds_path = STORAGE_PATH / "worlds"
  world_root_path = worlds_path / world_id

  # (1) Không cho tạo trùng
  if world_root_path.exists():
      raise FileExistsError(f"World '{world_id}' already exists")

  # (2) Tạo thư mục
  (world_root_path / "world").mkdir(parents=True)
  (world_root_path / "meta").mkdir()
  (world_root_path / "snapshots").mkdir()

  # (3) Metadata world
  world_json = {
      "id": world_id,
      "created_at": datetime.now(timezone.utc).isoformat(),
      "status": "inactive"
  }

  # (4) Metadata host
  host_json = {
    "host_id": None,
    "token": None,
    "expires_at": None,
    "last_heartbeat": None
  }

  json_storage.write_json(
      world_root_path / "meta" / "world.json",
      world_json
  )

  json_storage.write_json(
      world_root_path / "meta" / "host.json",
      host_json
  )

  return world_root_path