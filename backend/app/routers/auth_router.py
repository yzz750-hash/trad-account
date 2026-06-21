import os
from fastapi import APIRouter, HTTPException, Depends, Response, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth import authenticate_user, create_access_token, get_current_user, CurrentUser, ACCESS_TOKEN_EXPIRE_MINUTES, generate_csrf_token, revoke_user_tokens

COOKIE_SECURE = os.environ.get("ENVIRONMENT", "development") == "production"

router = APIRouter()


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=128)
    password: str = Field(..., min_length=1, max_length=256)


@router.post("/login")
def login(request: LoginRequest, response: Response, db: Session = Depends(get_db)):
    user = authenticate_user(db, request.username, request.password)
    if not user:
        raise HTTPException(status_code=401, detail="Incorrect username or password")

    token = create_access_token(
        data={"sub": user.username, "role": user.role.value, "user_id": user.id, "token_version": user.token_version}
    )
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="lax" if COOKIE_SECURE else "lax",
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path="/",
    )
    csrf_token = generate_csrf_token()
    response.set_cookie(
        key="csrf_token",
        value=csrf_token,
        httponly=False,  # readable by JS so frontend can send it as header
        secure=COOKIE_SECURE,
        samesite="lax" if COOKIE_SECURE else "lax",
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path="/",
    )
    return {
        "access_token": token,  # included for Bearer auth clients and test compatibility
        "user": {"id": user.id, "username": user.username, "role": user.role.value},
    }


@router.post("/logout")
def logout(response: Response, user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    revoke_user_tokens(db, user.id)
    response.delete_cookie(key="access_token", path="/")
    response.delete_cookie(key="csrf_token", path="/")
    return {"status": "ok"}


@router.get("/me")
def get_me(user: CurrentUser = Depends(get_current_user)):
    return user.model_dump()
