from fastapi import FastAPI
from sqlmodel import SQLModel
from app.db.database import engine

app = FastAPI(title="PeerHost", version="0.1.0")

app.on_event("startup")
def lifespan():
  # Tạo bảng
  SQLModel.metadata.create_all(engine)