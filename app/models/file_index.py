from sqlmodel import SQLModel, Field
from datetime import datetime, timezone

class FileIndex(SQLModel, table=True):
  path: str = Field(primary_key=True, index=True)
  file_name: str
  hash: str
  size: int
  update_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
  by_client: str