from fastapi import APIRouter, HTTPException, status, Depends, Request
from app.schemas.host import SessionCreate, SessionResponse
import app.services.host_service as host_service
from app.dependencies import get_session_token

router = APIRouter()

@router.post("/session", status_code=status.HTTP_201_CREATED)
async def claim_session(payload: SessionCreate, request: Request):
  """Nhận quyền kiểm soát session cho thế giới"""
  # Logic: get_session sẽ tự động clean session đã hết hạn
  client_ip = request.client.host
  session = host_service.get_session()
  
  if not session:
    try:
      # Nếu chưa có session file, tạo mới (logic cũ)
      session = host_service.create_session(payload.host_id, client_ip, is_locked=True)
    except FileNotFoundError:
      raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="World storage not found")
    except FileExistsError:
       # Trường hợp race condition: vừa check xong thì có người tạo
       raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Session already exists")
  elif session.get("is_locked"):
      # Nếu đã locked (và chưa hết hạn - vì get_session đã check), trả về lỗi conflict
      raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Session is already locked")
  else:
      # Session tồn tại nhưng unlocked -> chiếm lấy
      pass

  # Tạo token
  token = host_service.generate_token({
    "host_id": payload.host_id,
    "ip_address": client_ip,
    "expires_at": host_service._calculate_expires_at(host_service.datetime.now(host_service.timezone.utc))
  })
  
  # Cập nhật/Lock session
  host_service.update_session( 
    {
      "is_locked": True,
      "host": {
        "host_id": payload.host_id, 
        "ip_address": client_ip, 
        "token": token
      },
      # Timestamps sẽ được cập nhật ở đây để đảm bảo thống nhất
      "timestamps": {
          "started_at": host_service._get_utc_now_iso(),
          "last_heartbeat": host_service._get_utc_now_iso(),
          "expires_at": host_service._calculate_expires_at(host_service.datetime.now(host_service.timezone.utc))
      }
    }
  )
  return {"token": token,
          "heartbeat_interval": session['heartbeat_interval'],
          "lock_timeout": session['lock_timeout']}

@router.post("/session/heartbeat", status_code=status.HTTP_200_OK)
async def heartbeat(token: dict = Depends(get_session_token)):
    """Gửi heartbeat để duy trì session"""
    # Xác thực quyền sở hữu token
    if not host_service.auth_claim_session(token.get("host_id"), token.get("ip_address")):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized or Session lost")
    
    try:
        host_service.heartbeat_session()
    except FileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    
    return {"status": "ok"}

@router.get("/session", status_code=status.HTTP_200_OK, response_model=SessionResponse)
async def get_session():
  """Lấy thông tin session của thế giới"""
  # get_session có logic tự động reset session hết hạn
  session = host_service.get_session()
  if not session:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
  return SessionResponse(
    is_locked=session["is_locked"],
    host_id=session["host"]["host_id"]
  )

@router.delete("/session", status_code=status.HTTP_204_NO_CONTENT)
async def stop_session(token: dict = Depends(get_session_token)):
  """Ngưng quyền kiểm soát session thế giới"""
  if not host_service.auth_claim_session(token.get("host_id"), token.get("ip_address")):
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
  try:
    host_service.reset_session()
  except FileNotFoundError:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
