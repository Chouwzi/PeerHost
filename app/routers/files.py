from fastapi import APIRouter, HTTPException, status, Depends, Request, Header
from fastapi.responses import Response
from app.services import file_service, host_service
from app.dependencies import get_session_token

router = APIRouter()

@router.post("/world/files/{relative_path:path}", status_code=status.HTTP_201_CREATED)
async def upload_file(
    relative_path: str,
    request: Request,
    token: dict = Depends(get_session_token),
    x_file_hash: str = Header(None, alias="X-File-Hash")
):
    """
    API Upload file từ Client.
    Cần gửi kèm Header 'X-File-Hash' để đảm bảo tính toàn vẹn dữ liệu.
    """
    # 1. Authorize (Chỉ Host hiện tại mới được upload)
    if not await host_service.auth_claim_session(token.get("host_id"), token.get("ip_address")):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

    if not x_file_hash:
         raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing X-File-Hash header")

    # 2. Call Service with Stream
    # request.stream() trả về AsyncGenerator[bytes]
    try:
        await file_service.save_file(
            host_id=token.get("host_id"),
            relative_path=relative_path,
            content_stream=request.stream(),
            client_hash=x_file_hash
        )
    except PermissionError as e:
        # Client upload file cấm -> Từ chối (Logic 403)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except ValueError as e:
        # Integrity Error hoặc Invalid Path
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
    
    return {"message": "File uploaded successfully"}


@router.get("/world/files/{relative_path:path}")
async def download_file(
    relative_path: str
):
    """
    API Download file (cho Auto-Revert hoặc Sync Guest sau này).
    Auth: Public (để Client sync trước khi claim session).
    """
    # Authorization logic: Hiện tại Public để hỗ trợ Pre-Host Sync.
    # Sau này có thể thêm Guest Token nếu cần bảo mật hơn.
    
    content = await file_service.get_file(relative_path)
    if content is None:
         raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
         
    # Trả về binary content
    return Response(content=content, media_type="application/octet-stream")

@router.get("/world/config")
async def get_sync_configuration():
    """
    API trả về cấu hình Sync cho Client.
    Bao gồm:
    - restricted: Danh sách file cấm (Client cần revert nếu sửa).
    - ignored: Danh sách file rác (Client không nên upload).
    """
    return file_service.get_sync_config()
