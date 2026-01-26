from fastapi import FastAPI
from sqlmodel import SQLModel
from app.db.database import engine
from app.routers.worlds import router as world_router
from app.routers.hosts import router as host_router
from app.routers.files import router as files_router
from app.routers.manifest import router as manifest_router

import asyncio
from app.core.config import HEARTBEAT_INTERVAL
from app.services import host_service


async def monitor_sessions():
    """Tác vụ nền kiểm tra active session"""
    while True:
        try:
           await host_service.scan_all_sessions()
        except Exception as e:
           print(f"Error checking sessions: {e}")
        await asyncio.sleep(HEARTBEAT_INTERVAL)

app = FastAPI(title="PeerHost", version="0.1.0")

@app.on_event("startup")
async def startup_event():
    # Khởi chạy background task
    asyncio.create_task(monitor_sessions())

app.on_event("startup")
def lifespan():
  # Tạo bảng
  SQLModel.metadata.create_all(engine)
  
app.include_router(host_router, prefix="/world", tags=["host"])
app.include_router(files_router, tags=["files"])
app.include_router(manifest_router, tags=["manifest"])