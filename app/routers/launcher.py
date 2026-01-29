from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
import anyio
from pathlib import Path

router = APIRouter()

LAUNCHER_PATH = Path("client_launcher/launcher.py")

@router.get("/launcher/source", response_class=PlainTextResponse)
async def get_launcher_source():
    """
    Returns the source code of the launcher.
    """
    if not LAUNCHER_PATH.exists():
        raise HTTPException(status_code=404, detail="Launcher source not found")
    
    async with await anyio.open_file(LAUNCHER_PATH, "r", encoding="utf-8") as f:
        content = await f.read()
    
    return content
