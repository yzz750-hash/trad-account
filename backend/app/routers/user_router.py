"""User management endpoints (admin only)."""
from typing import Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, field_serializer
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth import require_admin, get_current_user, CurrentUser, hash_password, validate_password_strength, revoke_user_tokens
from app.models.financial import User, UserRole

router = APIRouter()


class UserResponse(BaseModel):
    id: int
    username: str
    role: str
    is_active: bool
    last_login: datetime | None = None
    created_at: datetime | None = None
    model_config = ConfigDict(from_attributes=True)

    @field_serializer("last_login", "created_at")
    def serialize_datetime(self, v: datetime | None) -> str | None:
        if v is None:
            return None
        return v.isoformat()


class UserCreate(BaseModel):
    username: str
    password: str
    role: str = "accountant"


class ResetPasswordRequest(BaseModel):
    new_password: str


@router.get("", response_model=list[UserResponse])
def list_users(
    search: Optional[str] = Query(None, description="Search by username"),
    db: Session = Depends(get_db),
    _admin: CurrentUser = Depends(require_admin),
):
    q = db.query(User)
    if search:
        q = q.filter(User.username.contains(search))
    users = q.order_by(User.id).all()
    return [UserResponse.model_validate(u) for u in users]


@router.post("", response_model=UserResponse)
def create_user(
    user_in: UserCreate,
    db: Session = Depends(get_db),
    _admin: CurrentUser = Depends(require_admin),
):
    if user_in.role not in ("admin", "accountant", "auditor"):
        raise HTTPException(status_code=400, detail="Invalid role")
    pw_error = validate_password_strength(user_in.password)
    if pw_error:
        raise HTTPException(status_code=400, detail=pw_error)
    existing = db.query(User).filter(User.username == user_in.username).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username already exists")
    new_user = User(
        username=user_in.username,
        hashed_password=hash_password(user_in.password),
        role=UserRole(user_in.role),
        is_active=True,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return UserResponse.model_validate(new_user)


@router.put("/{user_id}/reset-password")
def reset_password(
    user_id: int,
    req: ResetPasswordRequest,
    db: Session = Depends(get_db),
    _admin: CurrentUser = Depends(require_admin),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    pw_error = validate_password_strength(req.new_password)
    if pw_error:
        raise HTTPException(status_code=400, detail=pw_error)
    user.hashed_password = hash_password(req.new_password)
    revoke_user_tokens(db, user.id)
    db.commit()
    return {"status": "success", "message": f"Password reset for {user.username}"}


@router.put("/{user_id}/deactivate")
def deactivate_user(
    user_id: int,
    db: Session = Depends(get_db),
    _admin: CurrentUser = Depends(require_admin),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.username == "admin":
        raise HTTPException(status_code=400, detail="Cannot deactivate the default admin user")
    # 防止管理员自停用导致系统失去管理权限
    if user.id == _admin.id:
        raise HTTPException(status_code=400, detail="Cannot deactivate your own account")
    user.is_active = False
    db.commit()
    return {"status": "success", "message": f"User {user.username} deactivated"}


@router.put("/{user_id}/activate")
def activate_user(
    user_id: int,
    db: Session = Depends(get_db),
    _admin: CurrentUser = Depends(require_admin),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_active = True
    db.commit()
    return {"status": "success", "message": f"User {user.username} activated"}
