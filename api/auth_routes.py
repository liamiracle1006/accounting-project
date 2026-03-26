"""
AgentLedger — Auth API (Phase 3)

端点：
  POST /api/auth/login          — 用户名+密码登录，返回 JWT token
  GET  /api/auth/me             — 查看当前登录用户信息
  POST /api/auth/users          — 创建用户（仅 BOSS）
  PUT  /api/auth/users/{id}/password — 修改密码（本人或 BOSS）
"""
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database.connection import get_db
from models.user_account import UserAccount, UserRole
from services.auth_service import (
    verify_password,
    hash_password,
    create_access_token,
    get_current_user,
    require_role,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])


# ── Schemas ────────────────────────────────────────────────────────────────────

class CreateUserRequest(BaseModel):
    username:     str = Field(..., min_length=2, max_length=50)
    password:     str = Field(..., min_length=6, max_length=100)
    display_name: str = Field(..., min_length=1, max_length=100)
    role:         str = Field(default=UserRole.ACCOUNTANT)


class ChangePasswordRequest(BaseModel):
    new_password: str = Field(..., min_length=6, max_length=100)


def _user_to_dict(u: UserAccount) -> dict:
    return {
        "user_id":       u.user_id,
        "username":      u.username,
        "display_name":  u.display_name,
        "role":          u.role,
        "department_id": u.department_id,
        "is_active":     bool(u.is_active),
        "last_login_at": str(u.last_login_at) if u.last_login_at else None,
        "created_at":    str(u.created_at)    if u.created_at    else None,
    }


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post("/login")
def login(
    form: OAuth2PasswordRequestForm = Depends(),
    db:   Session                   = Depends(get_db),
) -> Any:
    """
    标准 OAuth2 密码流登录。
    返回 access_token（JWT）和用户基本信息。
    前端存入 localStorage，后续请求带 Authorization: Bearer <token>。
    """
    user = db.query(UserAccount).filter(
        UserAccount.username  == form.username,
        UserAccount.is_active == 1,
    ).first()

    if not user or not verify_password(form.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )

    # 更新最后登录时间
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()

    token = create_access_token(user.user_id, user.username, user.role)
    logger.info("User logged in: username=%s role=%s", user.username, user.role)

    return {
        "access_token": token,
        "token_type":   "bearer",
        "user":         _user_to_dict(user),
    }


@router.get("/me")
def get_me(current_user: UserAccount = Depends(get_current_user)) -> Any:
    """返回当前登录用户信息（token 验证）。"""
    return _user_to_dict(current_user)


@router.post("/users", status_code=201)
def create_user(
    body:         CreateUserRequest,
    current_user: UserAccount = Depends(require_role(UserRole.BOSS)),
    db:           Session     = Depends(get_db),
) -> Any:
    """创建新用户（仅老板可操作）。"""
    if body.role not in UserRole.ALL:
        raise HTTPException(status_code=422, detail=f"role 必须是 {UserRole.ALL}")

    if db.query(UserAccount).filter(UserAccount.username == body.username).first():
        raise HTTPException(status_code=409, detail=f"用户名 '{body.username}' 已存在")

    user = UserAccount(
        username      = body.username,
        password_hash = hash_password(body.password),
        display_name  = body.display_name,
        role          = body.role,
        is_active     = 1,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    logger.info("User created: id=%s username=%s role=%s by boss=%s",
                user.user_id, user.username, user.role, current_user.username)
    return _user_to_dict(user)


@router.get("/users")
def list_users(
    current_user: UserAccount = Depends(require_role(UserRole.BOSS)),
    db:           Session     = Depends(get_db),
) -> Any:
    """列出所有用户（仅老板）。"""
    users = db.query(UserAccount).order_by(UserAccount.user_id).all()
    return [_user_to_dict(u) for u in users]


@router.put("/users/{user_id}/password")
def change_password(
    user_id:      int,
    body:         ChangePasswordRequest,
    current_user: UserAccount = Depends(get_current_user),
    db:           Session     = Depends(get_db),
) -> Any:
    """
    修改密码。
    - 本人可改自己的密码
    - 老板可改任何人的密码
    """
    if current_user.user_id != user_id and current_user.role != UserRole.BOSS:
        raise HTTPException(status_code=403, detail="只能修改自己的密码")

    user = db.get(UserAccount, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    user.password_hash = hash_password(body.new_password)
    db.commit()
    logger.info("Password changed: user_id=%s by=%s", user_id, current_user.username)
    return {"ok": True, "message": "密码已修改"}
