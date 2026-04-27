"""
AgentLedger — AuthService (Phase 3)

职责：
  - 密码 bcrypt 验证
  - JWT 签发与解析
  - 当前用户依赖注入（FastAPI Depends）
"""
import logging
from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from config.settings import JWT_SECRET_KEY, JWT_ALGORITHM, JWT_EXPIRE_HOURS
from database.connection import get_db
from models.user_account import UserAccount

logger = logging.getLogger(__name__)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


# ── Password helpers ───────────────────────────────────────────────────────────

def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt(12)).decode()


# ── JWT helpers ────────────────────────────────────────────────────────────────

def create_access_token(user_id: int, username: str, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRE_HOURS)
    payload = {
        "sub":      str(user_id),
        "username": username,
        "role":     role,
        "exp":      expire,
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    """Decode JWT; raises HTTPException 401 on any failure."""
    try:
        return jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token 无效或已过期，请重新登录",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


# ── FastAPI dependency ─────────────────────────────────────────────────────────

def get_current_user(
    token: str     = Depends(oauth2_scheme),
    db:   Session  = Depends(get_db),
) -> UserAccount:
    """
    FastAPI dependency: 解析 Bearer token，返回当前登录用户。
    用法：current_user: UserAccount = Depends(get_current_user)
    """
    payload = decode_token(token)
    user_id = int(payload.get("sub", 0))
    user    = db.get(UserAccount, user_id)
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在或已禁用",
        )

    # 自动设置租户上下文（从 account_set 表取该租户的默认账套 ID）
    from sqlalchemy import text
    from database.tenant_context import set_current_tenant, TenantContext
    row = db.execute(
        text("SELECT account_set_id FROM account_set WHERE tenant_id = :tid LIMIT 1"),
        {"tid": user.tenant_id},
    ).first()
    set_current_tenant(TenantContext(
        tenant_id      = user.tenant_id,
        account_set_id = row[0] if row else None,
    ))

    return user


def require_role(*roles: str):
    """
    角色鉴权工厂函数。
    用法：Depends(require_role("BOSS", "ACCOUNTANT"))
    """
    def _check(current_user: UserAccount = Depends(get_current_user)) -> UserAccount:
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"权限不足，此操作需要角色：{' 或 '.join(roles)}",
            )
        return current_user
    return _check
