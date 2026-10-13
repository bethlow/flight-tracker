import hashlib, hmac, os, time
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from .config import JWT_SECRET, TOKEN_DAYS
from .db import get_conn

def hash_password(password: str) -> str:
    salt = os.urandom(16)
    h = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${h.hex()}"

def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt, h = stored.split("$")
        test = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1, dklen=32)
        return hmac.compare_digest(test.hex(), h)
    except ValueError:
        return False

def make_token(user_id: int) -> str:
    return jwt.encode({"sub": str(user_id), "exp": int(time.time()) + TOKEN_DAYS * 86400}, JWT_SECRET, algorithm="HS256")

_bearer = HTTPBearer(auto_error=False)

def current_user(creds: HTTPAuthorizationCredentials | None = Depends(_bearer), conn=Depends(get_conn)):
    if not creds:
        raise HTTPException(401, "Not signed in")
    try:
        user_id = int(jwt.decode(creds.credentials, JWT_SECRET, algorithms=["HS256"])["sub"])
    except (jwt.PyJWTError, ValueError):
        raise HTTPException(401, "Invalid or expired token")
    user = conn.execute("SELECT id, email, name FROM users WHERE id = %s", (user_id,)).fetchone()
    if not user:
        raise HTTPException(401, "Unknown user")
    return user
