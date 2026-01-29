import json
from pathlib import Path

def load_file(path: str) -> dict | None:
  data = None
  if Path.exists(path):
    with open(path, 'r') as f:
      data = json.load(f)
  return data

def write_file(path: str, data: dict, overwrite: bool = True) -> bool:
  try:
    if not overwrite and not Path.exists(path):
      return False
    
    with open(path, 'w') as f:
      json.dump(data, f, indent=2)
    return True
    
  except:
    return False
  