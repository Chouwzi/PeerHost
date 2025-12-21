from fastapi import APIRouter, HTTPException, status, Depends
from app.schemas.host import SessionCreate, SessionResponse
import app.services.host_service as host_service
from app.dependencies import get_session_token

router = APIRouter()

@router.post("/session", status_code=status.HTTP_201_CREATED)
async def claim_session(world_id: str, payload: SessionCreate):
  """Nhận quyền kiểm soát session cho thế giới"""
  session = host_service.get_session(world_id)
  if not session:
    try:
      host_service.create_session(world_id, payload.host_id, payload.ip_address)
    except FileNotFoundError:
      raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="World not found")
  elif session.get("is_locked"):
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Session is already locked")
  token = host_service.generate_token({
    "host_id": payload.host_id,
    "ip_address": payload.ip_address,
    "world_id": world_id
  })
  host_service.update_session(
    world_id, 
    {
      "is_locked": True,
      "host": {
        "host_id": payload.host_id, 
        "ip_address": payload.ip_address, 
        "token": token
      }
    }
  )
  return {"token": token}

@router.get("/session", status_code=status.HTTP_200_OK, response_model=SessionResponse)
async def get_session(world_id: str):
  """Lấy thông tin session của thế giới"""
  session = host_service.get_session(world_id)
  if not session:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
  return SessionResponse(
    is_locked=session["is_locked"],
    host_id=session["host"]["host_id"]
  )

@router.delete("/session", status_code=status.HTTP_204_NO_CONTENT)
async def stop_session(world_id: str, token: dict = Depends(get_session_token)):
  """Ngưng quyền kiểm soát session thế giới"""
  if not host_service.auth_claim_session(world_id, token.get("host_id"), token.get("ip_address")):
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
  try:
    host_service.reset_session(world_id)
  except FileNotFoundError:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
