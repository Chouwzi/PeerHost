from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from app.services.distribution_service import DistributionService

router = APIRouter(prefix="/client", tags=["distribution"])
dist_service = DistributionService()

@router.get("/manifest")
async def get_client_manifest():
    """Get the manifest of the latest client code."""
    try:
        return dist_service.get_client_manifest()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/files/{file_path:path}")
async def get_client_file(file_path: str):
    """Download a specific client file."""
    absolute_path = dist_service.get_client_file_path(file_path)
    
    if not absolute_path:
        raise HTTPException(status_code=404, detail="File not found or access denied")
        
    return FileResponse(absolute_path)
