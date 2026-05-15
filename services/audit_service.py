"""
AgentLedger — AuditService (Phase 5)

提供不可篡改的操作日志记录。

使用方式：
    audit(db, user, "voucher_header", voucher_id, AuditAction.STATUS_CHANGE,
          before={"review_status": "PENDING_REVIEW"},
          after={"review_status": "POSTED"},
          desc="凭证审核通过")
"""
import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from models.audit_log import AuditLog, AuditAction

logger = logging.getLogger(__name__)


def audit(
    db:          Session,
    user:        Any,               # UserAccount 对象，或 None（系统操作）
    table_name:  str,
    record_id:   Any,               # 主键，自动转为字符串
    action:      str,               # AuditAction.*
    before:      dict | None = None,
    after:       dict | None = None,
    desc:        str  | None = None,
    ip:          str  | None = None,
) -> AuditLog:
    """
    写入一条审计日志。调用方负责在外层 commit。
    此函数只做 db.add，不自行 commit，避免干扰调用方的事务边界。
    """
    # AuditLog.tenant_id 是 NOT NULL：从 user 拿，user 没有则降级到默认租户
    tenant_id = getattr(user, "tenant_id", None) or 1
    entry = AuditLog(
        tenant_id    = tenant_id,
        table_name   = table_name,
        record_id    = str(record_id),
        action       = action,
        user_id      = getattr(user, "user_id",  None),
        username     = getattr(user, "username", None),
        before_value = before,
        after_value  = after,
        description  = desc,
        ip_address   = ip,
    )
    db.add(entry)
    logger.debug("audit %s %s.%s by=%s", action, table_name, record_id,
                 getattr(user, "username", "system"))
    return entry


def get_ip(request: Any) -> str | None:
    """从 FastAPI Request 对象提取客户端 IP（兼容反向代理）。"""
    try:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else None
    except Exception:
        return None
