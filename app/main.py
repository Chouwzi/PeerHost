from fastapi import FastAPI
from sqlmodel import SQLModel
from app.db.database import engine
from app.routers.worlds import router as world_router
from app.routers.hosts import router as host_router

app = FastAPI(title="PeerHost", version="0.1.0")

app.on_event("startup")
def lifespan():
  # Tạo bảng
  SQLModel.metadata.create_all(engine)
  
app.include_router(world_router, prefix="/worlds", tags=["worlds"])
app.include_router(host_router, prefix="/worlds/{world_id}", tags=["hosts"])