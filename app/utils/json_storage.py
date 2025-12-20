from pathlib import Path
import json
import os

def write_json(path: Path, data: dict) -> None:
  path.parent.mkdir(parents=True, exist_ok=True)
  tmp = path.with_suffix(".tmp")

  with tmp.open("w", encoding="utf-8") as f:
      json.dump(data, f, ensure_ascii=False, indent=2)

  os.replace(tmp, path)

def read_json(path: Path) -> dict:
  if not path.exists():
    return {}
  with path.open("r", encoding="utf-8") as f:
    return json.load(f)
