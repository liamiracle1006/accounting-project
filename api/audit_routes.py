"""
AgentLedger — Audit Log API (Phase 5)

端点：
  GET /api/audit-logs            — 查询审计日志（BOSS/ACCOUNTANT）
  GET /api/audit-logs/{table}/{record_id} — 查某条记录的操作历史
"""
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from database.connection import get_db
from models.audit_log import AuditLog
from models.user_account import UserAccount, UserRole
from services.auth_service import require_role

router = APIRouter(prefix="/api/audit-logs", tags=["audit"])

ALLOWED = (UserRole.BOSS, UserRole.ACCOUNTANT)


def _log_dict(l: AuditLog) -> dict:
    return {
        "log_id":       l.log_id,
        "table_name":   l.table_name,
        "record_id":    l.record_id,
        "action":       l.action,
        "user_id":      l.user_id,
        "username":     l.username,
        "before_value": l.before_value,
        "after_value":  l.after_value,
        "description":  l.description,
        "ip_address":   l.ip_address,
        "created_at":   str(l.created_at) if l.created_at else None,
    }


@router.get("")
def list_audit_logs(
    table_name: str | None  = Query(default=None, description="过滤表名"),
    username:   str | None  = Query(default=None, description="过滤操作人"),
    action:     str | None  = Query(default=None, description="过滤操作类型"),
    limit:      int         = Query(default=50, le=200),
    offset:     int         = Query(default=0, ge=0),
    current_user: UserAccount = Depends(require_role(*ALLOWED)),
    db:           Session     = Depends(get_db),
) -> Any:
    q = db.query(AuditLog)
    if table_name:
        q = q.filter(AuditLog.table_name == table_name)
    if username:
        q = q.filter(AuditLog.username.like(f"%{username}%"))
    if action:
        q = q.filter(AuditLog.action == action.upper())
    total = q.count()
    items = q.order_by(AuditLog.log_id.desc()).offset(offset).limit(limit).all()
    return {"total": total, "items": [_log_dict(l) for l in items]}


@router.get("/{table_name}/{record_id}")
def get_record_history(
    table_name:   str,
    record_id:    str,
    current_user: UserAccount = Depends(require_role(*ALLOWED)),
    db:           Session     = Depends(get_db),
) -> Any:
    """查看某条具体记录的完整操作历史。"""
    items = (
        db.query(AuditLog)
        .filter(AuditLog.table_name == table_name, AuditLog.record_id == record_id)
        .order_by(AuditLog.log_id.asc())
        .all()
    )
    return [_log_dict(l) for l in items]
