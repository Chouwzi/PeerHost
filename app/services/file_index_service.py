from sqlmodel import Session, select
from datetime import datetime, timezone
from app.models.file_index import FileIndex

def create_file_record(
  session: Session, 
  path: str, 
  file_name: str, 
  hash: str, 
  size: int, 
  update_by_host: str,
  host_ip: str = None,
) -> FileIndex:
  """Tạo bản ghi thông tin file mới

  Args:
      session (Session): Phiên làm việc với db
      path (str): Đường dẫn file
      filename (str): Tên file
      hash (str): Mã hash
      size (int): Kích thước file
      update_by_host (str): Tên host upload
      host_ip (str, Optional): IP của host upload

  Returns:
      FileIndex: Bản ghi của file
  """
  db_file = get_file(session, path)
  if db_file: return db_file
  
  db_file = FileIndex(
    path=path,
    file_name=file_name,
    hash=hash,
    size=size,
    update_at=datetime.now(timezone.utc),
    update_by_host=update_by_host,
    host_ip=host_ip,
  )
  
  session.add(db_file)
  session.commit()
  session.refresh(db_file)
  
  return db_file

def get_file(
  session: Session,
  file_path: str,
)-> FileIndex | None:
  """Lấy bản ghi của file

  Args:
      session (Session): Phiên làm việc với db
      file_path (str): Đường dẫn file

  Returns:
      FileIndex | None: Bản ghi của file
  """
  return session.get(FileIndex, file_path)

def delete_record(
  session: Session,
  file_path: str,
) -> bool:
  """Xóa bản ghi

  Args:
      session (Session): Phiên làm việc với db
      file_path (str): Đường dẫn file cần xóa

  Returns:
      bool: Trạng thái xóa
  """
  db_file = session.get(FileIndex, file_path)
  session.delete(db_file)
  session.commit()
  if not db_file:
    return False
  return True

def list_file_record(session: Session):
  """Liệt kê tất cả các bản ghi file có trong db

  Args:
      session (Session): Phiên làm việc với db

  Returns:
      _type_: Các bản ghi file
  """
  return session.exec(select(FileIndex)).all()