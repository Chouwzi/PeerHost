import sys
import os

# Get the absolute path to the project root
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, project_root)

# Ensure the current directory is also in the path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)
sys.path.insert(0, os.path.dirname(current_dir))

from pathlib import Path
from sqlmodel import Session, SQLModel
from app.services.file_index_service import get_file, create_file_record, delete_record, list_file_record
from app.db.database import engine
from random import randint

SQLModel.metadata.create_all(engine)

with Session(engine) as session:
  for i in range(0, 10):
    x_ran, z_ran = randint(-50, 50), randint(-50, 50)
    save_path = Path(f"region/test_r.{x_ran}.{z_ran}.mca")
    file_name = save_path.name
    file_hash = f"thisisfakehash{randint(100000000, 999999999)}"
    size = randint(1, 50) * 1024 * 1024
    host = f"Client-{randint(0, 5)}"
    create_file_record(session, str(save_path), file_name, file_hash, size, host)
    for i, v in enumerate(list_file_record(session)):
      print(i, v.file_name, v.update_by_host)
      
with Session(engine) as session:
  for i, v in enumerate(list_file_record(session)):
    if "test" in v.file_name:
      delete_record(session, v.path)