import sys
import os
import shutil

# Get the absolute path to the project root
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, project_root)

# Ensure the current directory is also in the path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)
sys.path.insert(0, os.path.dirname(current_dir))

from app.core.config import STORAGE_PATH
from pathlib import Path
import python_nbt.nbt as nbt

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
  """Tạo cấu trúc thư mục của thế giới

  Args:
      world_id (str): ID thế giới

  Returns:
      Path: Đường dẫn thư mục
  """
  worlds_path = STORAGE_PATH / "worlds"
  worlds_path.mkdir(parents=True, exist_ok=True)

  world_root_path = worlds_path / world_id
  world_root_path.mkdir(exist_ok=True)

  world_path = world_root_path / "world"
  meta_path = world_root_path / "meta"
  snapshots_path = world_root_path / "snapshots"

  world_path.mkdir(exist_ok=True)
  meta_path.mkdir(exist_ok=True)
  snapshots_path.mkdir(exist_ok=True)

  return worlds_path