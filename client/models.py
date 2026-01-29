import pydantic

class Settings(pydantic.BaseModel):
  server_url: str
  host_id: str
  watch_dir: str = "." 
  debug: bool = False

class SessionInfo(pydantic.BaseModel):
  token: str
  heartbeat_interval: int
  lock_timeout: int

class TunnelConfig(pydantic.BaseModel):
  """Tunnel configuration fetched from server"""
  tunnel_name: str = "PeerHost"
  game_hostname: str = ""
  game_local_port: int = 2812

