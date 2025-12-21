from sqlmodel import Session
from app.db.database import engine
from app.core.security import verify_token

def get_session():
  with Session(engine) as session:
    yield session

get_session_token = verify_token