from fastapi import APIRouter, HTTPException
from app.schemas.world import WorldResponse, WorldListResponse, WorldCreate
from app.services import world_service
router = APIRouter()

@router.post("", status_code=201)
def create_world(payload: WorldCreate):
  world_id = payload.id
  world = world_service.get_world(world_id)
  if world != None:
    raise HTTPException(status_code=409, detail="World already exists")
  world_path = world_service.create_world(world_id)
  return {"path": world_path}

@router.delete("/{world_id}", status_code=204)
def delete_world(world_id: str):
  # Xóa trên ổ đĩa lưu trữ
  status = world_service.delete_world(world_id)
  if not status:
    raise HTTPException(status_code=404, detail="World not found")
  
@router.get("/{world_id}", response_model=WorldResponse)
def get_world(world_id: str):
  world = world_service.get_world(world_id)
  if not world:
    raise HTTPException(status_code=404, detail="World not found")
  return WorldResponse(**world)

@router.get("", response_model=WorldListResponse)
def list_worlds():
  worlds = world_service.list_worlds()
  return WorldListResponse(
    items=worlds,
    total=len(worlds)
  )