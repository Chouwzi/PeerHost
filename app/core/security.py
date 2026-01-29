from jose import jwt
from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from app.core.config import SECRET_KEY, ALGORITHM

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

def verify_token(token: str = Depends(oauth2_scheme)) -> dict:
  payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
  return payload
