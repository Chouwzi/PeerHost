from sqlmodel import SQLModel, create_engine
from app.core.config import DATABASE_URL

engine = create_engine(
  url=DATABASE_URL,
  echo=False,
)