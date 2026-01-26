from fastapi import APIRouter, HTTPException, status, Depends, Request
from app.schemas.host import SessionCreate, SessionResponse
import app.services.host_service as host_service
from app.dependencies import get_session_token

router = APIRouter()

@router.post("/session", status_code=status.HTTP_201_CREATED)
async def claim_session(payload: SessionCreate, request: Request):
  """Nhận quyền kiểm soát session cho thế giới"""
  client_ip = request.client.host
  
  # Atomic Claim
  success, error, data = await host_service.try_claim_session(payload.host_id, client_ip)
  
  if not success:
      if error == "World storage not found":
          raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=error)
      elif error in ["Session already exists", "Session is already locked"]:
          raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=error)
      else:
          raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=error)

  return data

@router.post("/session/heartbeat", status_code=status.HTTP_200_OK)
async def heartbeat(token: dict = Depends(get_session_token)):
    """Gửi heartbeat để duy trì session"""
    # Xác thực quyền sở hữu token
    if not await host_service.auth_claim_session(token.get("host_id"), token.get("ip_address")):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized or Session lost")
    
    try:
        await host_service.heartbeat_session()
    except FileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    
    return {"status": "ok"}

@router.get("/session", status_code=status.HTTP_200_OK, response_model=SessionResponse)
async def get_session():
  """Lấy thông tin session của thế giới"""
  # get_session có logic tự động reset session hết hạn
  session = await host_service.get_session()
  if not session:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
  return SessionResponse(
    is_locked=session["is_locked"],
    host_id=session["host"]["host_id"]
  )

@router.delete("/session", status_code=status.HTTP_204_NO_CONTENT)
async def stop_session(token: dict = Depends(get_session_token)):
  """Ngưng quyền kiểm soát session thế giới"""
  if not await host_service.auth_claim_session(token.get("host_id"), token.get("ip_address")):
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
  try:
    await host_service.reset_session()
  except FileNotFoundError:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
