import asyncio
from fastapi import FastAPI
from sqlmodel import SQLModel
from contextlib import asynccontextmanager
from app.core.config import HEARTBEAT_INTERVAL
from app.db.database import engine
from app.routers.hosts import router as host_router
from app.routers.files import router as files_router
from app.routers.manifest import router as manifest_router
from app.routers.distribution import router as distribution_router
from app.routers.launcher import router as launcher_router
from app.services import host_service
from app.services.tunnel_service import tunnel_service

async def monitor_sessions():
    """Tác vụ nền kiểm tra active session"""
    while True:
        try:
           await host_service.scan_all_sessions()
        except Exception as e:
           print(f"Error checking sessions: {e}")
        await asyncio.sleep(HEARTBEAT_INTERVAL)

# --- Lifecycle Management ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Startup Logic
    print("--- Server Startup ---")
    
    # Initialize DB
    SQLModel.metadata.create_all(engine)
    
    # Start Background Tasks
    asyncio.create_task(monitor_sessions())
    
    # Start API Tunnel
    tunnel_service.start()
    
    yield # Server runs here
    
    # 2. Shutdown Logic
    print("--- Server Shutdown ---")
    tunnel_service.stop()

app = FastAPI(title="PeerHost", version="0.1.0", lifespan=lifespan)
  
app.include_router(host_router, prefix="/world", tags=["host"])
app.include_router(files_router, tags=["files"])
app.include_router(manifest_router, tags=["manifest"])
app.include_router(distribution_router)
app.include_router(launcher_router, tags=["launcher"])