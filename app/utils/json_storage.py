from pathlib import Path
import json
import anyio
import os

async def write_json(path: Path, data: dict) -> None:
  path_obj = anyio.Path(path)
  await path_obj.parent.mkdir(parents=True, exist_ok=True)
  tmp = path_obj.with_suffix(".tmp")
  
  async with await anyio.open_file(tmp, "w", encoding="utf-8") as f:
      await f.write(json.dumps(data, indent=2, ensure_ascii=False))
      
  # Fix for Windows: os.replace is atomic and allows overwrite
  await anyio.to_thread.run_sync(os.replace, str(tmp), str(path_obj))

async def read_json(path: Path) -> dict:
  path = anyio.Path(path)
  if not await path.exists():
    return {}
  async with await anyio.open_file(path, "r", encoding="utf-8") as f:
    content = await f.read()
    return json.loads(content)
