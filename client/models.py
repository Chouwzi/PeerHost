import pydantic

class Settings(pydantic.BaseModel):
  server_url: str
  host_id: str
  debug: bool = False

class SessionInfo(pydantic.BaseModel):
  token: str
  heartbeat_interval: int
  lock_timeout: int
