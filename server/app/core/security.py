from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db import get_db
from app.models import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

ROLE_VIEWER, ROLE_ANALYST, ROLE_APPROVER, ROLE_ADMIN = "viewer", "analyst", "approver", "admin"
ALL_ROLES = [ROLE_VIEWER, ROLE_ANALYST, ROLE_APPROVER, ROLE_ADMIN]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode()[:72], bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode()[:72], hashed.encode())
    except ValueError:
        return False


def create_access_token(user: User) -> str:
    s = get_settings()
    exp = datetime.now(timezone.utc) + timedelta(minutes=s.access_token_minutes)
    payload = {"sub": str(user.id), "email": user.email, "role": user.role.name, "exp": exp}
    return jwt.encode(payload, s.secret_key, algorithm=s.jwt_algorithm)


def decode_token(token: str) -> dict:
    s = get_settings()
    return jwt.decode(token, s.secret_key, algorithms=[s.jwt_algorithm])


def user_from_token(token: str, db: Session) -> User:
    try:
        data = decode_token(token)
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token", {"WWW-Authenticate": "Bearer"})
    user = db.get(User, int(data["sub"]))
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found or disabled")
    return user


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    return user_from_token(token, db)


def require_roles(*roles: str):
    """Least-privilege dependency: admin always passes, otherwise the role must be listed."""
    allowed = set(roles) | {ROLE_ADMIN}

    def dep(user: User = Depends(get_current_user)) -> User:
        if user.role.name not in allowed:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Role '{user.role.name}' is not permitted for this action")
        return user

    return dep
