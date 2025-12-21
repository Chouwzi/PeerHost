from pydantic import BaseModel

class SessionCreate(BaseModel):
  host_id: str
  ip_address: str

class SessionResponse(BaseModel):
  is_locked: bool
  host_id: str | None