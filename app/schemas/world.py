from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime
from enum import IntEnum

class Difficulty(IntEnum):
  peaceful = 0
  easy = 1
  normal = 2
  hard = 3

class Spawn(BaseModel):
  pos: List[float] = Field(..., min_length=3, max_length=3)
  dimension: str

class WorldResponse(BaseModel):
  id: str
  level_name: str
  seed: int
  version: str
  difficulty: Difficulty
  spawn: Spawn
  day_time: int
  game_time: int
  created_at: Optional[datetime] = None

class WorldListResponse(BaseModel):
  items: List[WorldResponse]
  total: int
  
class WorldCreate(BaseModel):
  id: str = Field(..., min_length=1)
  level_name: Optional[str] = None
  seed: Optional[int] = None
  version: Optional[str] = None
  difficulty: Optional[Difficulty] = None
  spawn: Optional[Spawn] = None