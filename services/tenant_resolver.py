# -*- coding: utf-8 -*-
"""
统一租户上下文解析

历史背景：
- 项目原设计是用 ContextVar (`database/tenant_context.py`) 在请求入口由中间件设置
  TenantContext，让 SQLAlchemy interceptor 自动注入 tenant 过滤。
- 实际上 set_current_tenant 从未在生产路径被调用过（middleware 缺失），9 个路由
  的 `_get_ctx()` 一直拿到 None，登录后报 "未设置租户上下文，请先登录"。
- 尝试过加 async middleware，但触发 interceptor 后某些复杂 SQL 走 with_loader_criteria
  会出 500 错误。
- 最终方案：每个需要 ctx 的路由直接从 `current_user.tenant_id` 查 account_set_id，
  绕开 ContextVar 和 interceptor。

用法：
    from services.tenant_resolver import resolve_tenant_ctx
    tenant_id, account_set_id = resolve_tenant_ctx(db, current_user)
"""
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from models.user_account import UserAccount


def resolve_tenant_ctx(db: Session, user: UserAccount) -> tuple[int, int]:
    """
    从已登录用户解析 (tenant_id, account_set_id)。
    用原生 SQL 查 account_set，避开 ORM 与 DDL 字段不同步的问题。
    """
    row = db.execute(
        text("SELECT account_set_id FROM account_set WHERE tenant_id = :tid LIMIT 1"),
        {"tid": user.tenant_id},
    ).first()
    if not row:
        raise HTTPException(
            status_code=400,
            detail=f"租户 {user.tenant_id} 未找到任何账套，请先建账",
        )
    return user.tenant_id, row[0]
