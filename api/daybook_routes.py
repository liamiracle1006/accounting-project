# -*- coding: utf-8 -*-
"""
序时账导入 API（Phase A）

POST /api/daybook/import — 上传序时账 Excel，按凭证号分组生成 DRAFT 凭证
                          返回创建数量 + 失败明细
"""
import logging
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import text
from sqlalchemy.orm import Session

from database.connection import get_db
from models.user_account import UserAccount, UserRole
from services.auth_service import require_role
from services.daybook_import_service import import_daybook

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/daybook", tags=["daybook"])

FINANCE_ROLES = (UserRole.BOSS, UserRole.ACCOUNTANT)
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB


def _resolve_tenant_ctx(db: Session, user: UserAccount) -> tuple[int, int]:
    """直接从 user.tenant_id 查 account_set_id，绕开 ContextVar。"""
    row = db.execute(
        text("SELECT account_set_id FROM account_set WHERE tenant_id = :tid LIMIT 1"),
        {"tid": user.tenant_id},
    ).first()
    if not row:
        raise HTTPException(status_code=400, detail=f"租户 {user.tenant_id} 未找到任何账套")
    return user.tenant_id, row[0]


@router.post("/import")
async def import_daybook_excel(
    file:         UploadFile = File(...),
    standard:     str        = Form("xiye"),
    current_user: UserAccount = Depends(require_role(*FINANCE_ROLES)),
    db:           Session     = Depends(get_db),
) -> Any:
    """
    上传序时账 Excel，按凭证号分组生成 DRAFT 凭证。

    Excel 结构要求：
    - 列：日期 | 凭证号 | 摘要 | 科目编码 | 科目名称 | 借方金额 | 贷方金额 | ...
    - 同凭证号多行（合并单元格自动 ffill）
    - 凭证号格式 "记-N"
    - 科目码可达 10 位（子科目），自动归一到 4 位母科目

    所有创建的凭证为 DRAFT 状态，需进入凭证管理页面手工审核过账。
    """
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="请上传 .xlsx 或 .xls 文件")

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"文件过大（{len(content) / 1024 / 1024:.1f}MB），上限 50MB",
        )

    tenant_id, account_set_id = _resolve_tenant_ctx(db, current_user)

    try:
        result = import_daybook(
            db, content,
            tenant_id      = tenant_id,
            account_set_id = account_set_id,
            standard       = standard,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.exception("序时账导入失败")
        raise HTTPException(status_code=500, detail=f"导入失败：{exc}")

    logger.info(
        "Daybook imported by user=%s: rows=%d parsed=%d created=%d errors=%d",
        current_user.username,
        result.total_rows, result.parsed_vouchers,
        result.created_vouchers, len(result.errors),
    )

    return {
        "total_rows":       result.total_rows,
        "parsed_vouchers":  result.parsed_vouchers,
        "created_vouchers": result.created_vouchers,
        "error_count":      len(result.errors),
        "column_mapping":   result.column_mapping,
        "errors": [
            {"voucher_no": e.voucher_no, "reason": e.reason, "rows": e.rows}
            for e in result.errors
        ],
    }
