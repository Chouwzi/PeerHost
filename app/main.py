from fastapi import FastAPI
from sqlmodel import SQLModel
from app.db.database import engine
from contextlib import contextmanager

@contextmanager
def lifespan(app: FastAPI):
  # Tạo bảng
  SQLModel.metadata.create_all(engine)
  
app = FastAPI(title="PeerHost", version="0.1.0", lifespan=lifespan)
