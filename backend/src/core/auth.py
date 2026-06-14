"""
auth.py — Authentication endpoints for DataGuard.

POST /auth/register  — create a new user (first-run setup, no auth required)
POST /auth/login     — returns a signed JWT access token
GET  /auth/me        — returns current user info (requires Bearer token)
POST /auth/logout    — client-side only; server just returns 200
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
import bcrypt as _bcrypt
from jose import JWTError, jwt
from sqlalchemy.orm import Session

import src.core.config as config
from src.core.database import get_db
from src.domain.entities import User
from src.domain.schemas import Token, UserCreate, UserLogin, UserOut

logger = logging.getLogger("dataguard.auth")
router = APIRouter()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _hash(password: str) -> str:
    # bcrypt truncates at 72 bytes; encode explicitly so the limit is clear
    return _bcrypt.hashpw(password.encode("utf-8")[:72], _bcrypt.gensalt(12)).decode()

def _verify(plain: str, hashed: str) -> bool:
    try:
        return _bcrypt.checkpw(plain.encode("utf-8")[:72], hashed.encode())
    except Exception:
        return False

def _create_token(username: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=config.JWT_EXPIRE_HOURS)
    return jwt.encode(
        {"sub": username, "exp": expire},
        config.JWT_SECRET,
        algorithm=config.JWT_ALGORITHM,
    )


def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Dependency — resolves Bearer token → User row. Raises 401 if invalid."""
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    try:
        payload  = jwt.decode(token, config.JWT_SECRET, algorithms=[config.JWT_ALGORITHM])
        username = payload.get("sub")
        if not username:
            raise ValueError
    except (JWTError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")

    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")
    return user


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/register", response_model=UserOut, status_code=201)
def register(data: UserCreate, db: Session = Depends(get_db)):
    """Create a new user account. Username and email must be unique."""
    if db.query(User).filter(User.username == data.username).first():
        raise HTTPException(400, f"Username '{data.username}' is already taken")
    if data.email and db.query(User).filter(User.email == data.email).first():
        raise HTTPException(400, f"Email '{data.email}' is already registered")

    user = User(
        username=data.username,
        email=data.email,
        full_name=data.full_name,
        password_hash=_hash(data.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    logger.info("New user registered: %s", user.username)
    return user


@router.post("/login", response_model=Token)
def login(data: UserLogin, db: Session = Depends(get_db)):
    """Verify credentials and return a signed JWT token."""
    user = db.query(User).filter(User.username == data.username).first()
    if not user or not _verify(data.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect username or password")

    # Update last_login timestamp
    user.last_login = datetime.now(timezone.utc)
    db.commit()

    token = _create_token(user.username)
    logger.info("User logged in: %s", user.username)
    return Token(
        access_token=token,
        username=user.username,
        full_name=user.full_name,
    )


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    """Return the authenticated user's profile."""
    return current_user


@router.post("/logout")
def logout():
    """Token invalidation is handled client-side (clear from localStorage)."""
    return {"message": "Logged out successfully"}
