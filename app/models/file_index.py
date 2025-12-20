from sqlmodel import SQLModel, Field
from datetime import datetime, timezone
from typing import Optional

class FileIndex(SQLModel, table=True):
  path: str = Field(primary_key=True, index=True)
  file_name: str
  hash: str
  size: int
  update_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
  update_by_host: str
  host_ip: Optional[str] = None