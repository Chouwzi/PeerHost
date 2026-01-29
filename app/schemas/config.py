from pydantic import BaseModel


class ServerSettings(BaseModel):
    """Server configuration loaded from settings.json"""
    heartbeat_interval: int = 2
    lock_timeout: int = 7
    start_command: str = ""
    mirror_sync: bool = True
    secret_key: str
    algorithm: str = "HS256"
    tunnel_name: str = "PeerHost"
    game_hostname: str = ""
    game_local_port: int = 2812
    java_version: str = "21"


class SyncConfig(BaseModel):
    """Config sent to client via /world/config endpoint"""
    restricted: list[str]
    ignored: list[str]
    readonly: list[str]
    start_command: str | None
    mirror_sync: bool
    tunnel_name: str
    game_hostname: str
    game_local_port: int
    java_version: str = "21"
