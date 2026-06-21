"""
JWT Authentication and RBAC for the Financial System.
Supports roles: admin, accountant, auditor.
Users are stored in the database.
Token is delivered via httpOnly cookie (primary) with Bearer header fallback.
CSRF protection via double-submit cookie pattern.
"""
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from fastapi import Depends, HTTPException, Security, Request, Cookie, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy.orm import Session

from sqlalchemy.sql import func

from app.database import get_db
from app.models.financial import User as UserModel

_SECRET_KEY_ENV = os.environ.get("JWT_SECRET_KEY")
if not _SECRET_KEY_ENV:
    raise RuntimeError(
        "JWT_SECRET_KEY environment variable is required. "
        "Generate a random 64-character hex string for production. "
        "For dev, set it in .env or docker-compose.yml."
    )
SECRET_KEY = _SECRET_KEY_ENV
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60  # 1 hour for financial system security

security = HTTPBearer(auto_error=False)

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

MIN_PASSWORD_LENGTH = 12
MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_MINUTES = 30


def validate_password_strength(password: str) -> str | None:
    """Return error message if password is too weak, or None if acceptable."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters"
    if not any(c.islower() for c in password):
        return "Password must contain at least one lowercase letter"
    if not any(c.isupper() for c in password):
        return "Password must contain at least one uppercase letter"
    if not any(c.isdigit() for c in password):
        return "Password must contain at least one digit"
    if not any(c in "!@#$%^&*()_+-=[]{}|;:,.<>?/~ \"\'" for c in password):
        return "Password must contain at least one special character"
    return None


def generate_csrf_token() -> str:
    return secrets.token_hex(32)


def verify_csrf(
    request: Request,
    x_csrf_token: Optional[str] = Header(None, alias="X-CSRF-Token"),
):
    if request.method in SAFE_METHODS:
        return
    csrf_cookie = request.cookies.get("csrf_token")
    if not csrf_cookie or not x_csrf_token:
        raise HTTPException(status_code=403, detail="CSRF token missing")
    if not secrets.compare_digest(csrf_cookie, x_csrf_token):
        raise HTTPException(status_code=403, detail="CSRF token mismatch")


class CurrentUser(BaseModel):
    id: int
    username: str
    role: str  # "admin", "accountant", "auditor"


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def get_user(db: Session, username: str) -> Optional[UserModel]:
    return db.query(UserModel).filter(
        UserModel.username == username,
        UserModel.is_active == True,
    ).first()


def authenticate_user(db: Session, username: str, password: str) -> Optional[UserModel]:
    user = get_user(db, username)
    if not user:
        return None

    # Check account lockout
    now_utc = datetime.now(timezone.utc)
    if user.locked_until:
        locked = user.locked_until
        if locked.tzinfo is None:
            locked = locked.replace(tzinfo=timezone.utc)
        if locked > now_utc:
            return None  # Account is locked, don't even verify password

    if not verify_password(password, user.hashed_password):
        # Atomic increment to prevent lost updates under concurrent logins
        db.query(UserModel).filter(UserModel.id == user.id).update(
            {UserModel.failed_login_attempts: UserModel.failed_login_attempts + 1},
            synchronize_session='fetch',
        )
        db.refresh(user)
        if user.failed_login_attempts >= MAX_LOGIN_ATTEMPTS:
            user.locked_until = now_utc + timedelta(minutes=LOCKOUT_MINUTES)
        db.commit()
        return None

    # Successful login — reset lockout counters
    user.failed_login_attempts = 0
    user.locked_until = None
    user.last_login = datetime.now(timezone.utc)
    db.commit()
    return user


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({
        "exp": expire,
        "jti": secrets.token_hex(16),
        "iss": "trad-account-api",
        "aud": "trad-account",
    })
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def revoke_user_tokens(db: Session, user_id: int) -> None:
    """Invalidate all existing tokens for a user by incrementing token_version."""
    db.query(UserModel).filter(UserModel.id == user_id).update(
        {UserModel.token_version: UserModel.token_version + 1}
    )
    db.commit()


def _validate_token(token: str, db: Session) -> CurrentUser:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM], audience="trad-account")
        username: str = payload.get("sub")
        role: str = payload.get("role", "accountant")
        token_version: int = payload.get("token_version", -1)
        if username is None:
            raise HTTPException(status_code=401, detail="Invalid user")

        db_user = db.query(UserModel).filter(
            UserModel.username == username,
            UserModel.is_active == True,
        ).first()
        if not db_user:
            raise HTTPException(status_code=401, detail="User not found or deactivated")
        if token_version != db_user.token_version:
            raise HTTPException(status_code=401, detail="Token has been revoked")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return CurrentUser(id=db_user.id, username=db_user.username, role=db_user.role.value)


def get_current_user(
    request: Request = None,
    access_token: Optional[str] = Cookie(None),
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security),
    db: Session = Depends(get_db),
) -> CurrentUser:
    token = None
    if access_token:
        token = access_token
    elif credentials:
        token = credentials.credentials

    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    return _validate_token(token, db)


def require_role(*roles: str):
    """Dependency factory: only allow specified roles."""
    async def role_checker(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail=f"Role '{user.role}' not allowed. Required: {roles}")
        return user

    return role_checker


# Convenience: admin can do everything, accountant can write, auditor can only read
require_admin = require_role("admin")
require_write = require_role("admin", "accountant")
require_read = require_role("admin", "accountant", "auditor")
