"""
Manifest Router - API endpoint for world file manifest
"""

from fastapi import APIRouter
from app.services import manifest_service

router = APIRouter()


@router.get("/world/manifest")
async def get_manifest():
    """
    Lấy danh sách tất cả file trong world storage kèm hash.
    
    Client dùng API này để so sánh với local files trước khi claim session.
    
    Returns:
        {
            "files": [{"path": "level.dat", "hash": "abc...", "size": 1234}, ...],
            "total_files": 42,
            "total_size": 1234567
        }
    """
    return await manifest_service.get_manifest()
