import time
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import admin
from app.core.security import create_access_token, get_current_user, hash_password, verify_password
from app.db import get_db, utcnow
from app.models import Role, User
from app.schemas import TokenOut, UserCreate, UserOut
from app.services.system import audit

router = APIRouter(prefix="/auth", tags=["Authentication"])
_FAILS: dict[str, list[float]] = defaultdict(list)
MAX_FAILS, WINDOW = 5, 300


def _user_out(u: User) -> UserOut:
    return UserOut(id=u.id, email=u.email, full_name=u.full_name, role=u.role.name)


@router.post("/login", response_model=TokenOut, summary="Obtain a JWT access token")
def login(request: Request, form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    email = form.username.strip().lower()
    now = time.time()
    _FAILS[email] = [t for t in _FAILS[email] if now - t < WINDOW]
    if len(_FAILS[email]) >= MAX_FAILS:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many failed attempts. Try again in a few minutes.")
    user = db.scalar(select(User).where(User.email == email))
    if user is None or not user.is_active or not verify_password(form.password, user.hashed_password):
        _FAILS[email].append(now)
        audit(db, user.id if user else None, "auth.login_failed", "user", email, ip=request.client.host if request.client else None)
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password", {"WWW-Authenticate": "Bearer"})
    _FAILS.pop(email, None)
    user.last_login_at = utcnow()
    audit(db, user.id, "auth.login", "user", user.id, ip=request.client.host if request.client else None)
    db.commit()
    return TokenOut(access_token=create_access_token(user), user=_user_out(user))


@router.get("/me", response_model=UserOut, summary="Current user")
def me(user: User = Depends(get_current_user)):
    return _user_out(user)


@router.get("/users", response_model=list[UserOut], summary="List users (admin)")
def list_users(db: Session = Depends(get_db), _: User = Depends(admin)):
    return [_user_out(u) for u in db.scalars(select(User).order_by(User.id))]


@router.post("/users", response_model=UserOut, status_code=201, summary="Create a user (admin)")
def create_user(body: UserCreate, db: Session = Depends(get_db), actor: User = Depends(admin)):
    if db.scalar(select(User).where(User.email == body.email.lower())):
        raise HTTPException(409, "A user with this email already exists")
    role = db.scalar(select(Role).where(Role.name == body.role))
    u = User(email=body.email.lower(), full_name=body.full_name, hashed_password=hash_password(body.password), role_id=role.id)
    db.add(u)
    audit(db, actor.id, "user.create", "user", body.email, {"role": body.role})
    db.commit()
    db.refresh(u)
    return _user_out(u)
