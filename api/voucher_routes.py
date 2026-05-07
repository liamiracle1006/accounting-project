"""
AgentLedger V4.0 — 凭证管理 API Routes (Sprint 3.2)

端点一览（/api/vouchers）：

  ── 列表 & 详情 ────────────────────────────────────────────────────────────
  GET    /                        — 凭证列表（多维过滤 + 分页）
  GET    /{voucher_id}            — 凭证详情（含分录行）

  ── 手工 CRUD ──────────────────────────────────────────────────────────────
  POST   /                        — 手工新建凭证
  PUT    /{voucher_id}            — 更新凭证（仅 DRAFT / REJECTED 状态）

  ── 状态机 ────────────────────────────────────────────────────────────────
  POST   /{voucher_id}/review     — 审核（DRAFT/PENDING_REVIEW → POSTED）
  POST   /{voucher_id}/unreview   — 反审核（POSTED → PENDING_REVIEW）

  ── 软删除 & 回收站 ────────────────────────────────────────────────────────
  DELETE /{voucher_id}            — 软删除（移入回收站，仅 DRAFT 状态）
  GET    /trash                   — 回收站列表
  POST   /{voucher_id}/restore    — 还原（从回收站恢复）

  ── 断号整理 ──────────────────────────────────────────────────────────────
  POST   /reorganize              — 对指定期间重新顺序编号

异常映射：
  VoucherNotFoundError → 404
  VoucherLockedError   → 403
  VoucherStateError    → 422
  ValueError           → 422
"""
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database.connection import get_db
from schemas.voucher_schemas import (
    PaginatedVouchers,
    ReorganizeInput,
    ReorganizeResult,
    VoucherCreateInput,
    VoucherOut,
    VoucherQuery,
    VoucherReviewInput,
    VoucherUpdateInput,
)
from services.voucher_service import (
    VoucherLockedError,
    VoucherNotFoundError,
    VoucherService,
    VoucherStateError,
)
from services.auth_service import get_current_user
from models.user_account import UserAccount

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/vouchers", tags=["vouchers"])


# ── Context helpers ───────────────────────────────────────────────────────────

def _get_ctx(
    user: UserAccount = Depends(get_current_user),
    db:   Session     = Depends(get_db),
) -> tuple[int, int]:
    from services.tenant_resolver import resolve_tenant_ctx
    return resolve_tenant_ctx(db, user)


def _svc_error(exc: Exception) -> HTTPException:
    if isinstance(exc, VoucherNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, VoucherLockedError):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, (VoucherStateError, ValueError)):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=403, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


# ══════════════════════════════════════════════════════════════════════════════
# 列表 & 详情
# ══════════════════════════════════════════════════════════════════════════════

@router.get(
    "",
    response_model=PaginatedVouchers,
    summary="凭证列表（多维过滤 + 分页）",
)
def list_vouchers(
    q:   VoucherQuery = Depends(),
    ctx: tuple        = Depends(_get_ctx),
    db:  Session      = Depends(get_db),
) -> Any:
    """
    支持以下过滤维度（均为可选，组合使用）：
      - period_year / period_month — 会计期间（从 voucher_date 推导）
      - voucher_word               — 凭证字精确匹配
      - summary_keyword            — 摘要关键词模糊搜索
      - subject_code               — 科目编码前缀匹配（如 1002 匹配 100201）
      - min_amount / max_amount    — 凭证合计金额区间
      - include_deleted            — 是否包含回收站内凭证（默认 False）

    返回分页结果，列表条目不含分录行明细（用 GET /{id} 获取详情）。
    """
    tenant_id, account_set_id = ctx
    svc = VoucherService(db)
    try:
        return svc.get_voucher_list(tenant_id, account_set_id, q)
    except Exception as exc:
        raise _svc_error(exc)


@router.get(
    "/trash",
    response_model=list,
    summary="回收站列表",
)
def list_trash(
    ctx: tuple   = Depends(_get_ctx),
    db:  Session = Depends(get_db),
) -> Any:
    """返回所有软删除的凭证列表（按日期倒序）。"""
    tenant_id, account_set_id = ctx
    svc = VoucherService(db)
    try:
        items = svc.list_trash(tenant_id, account_set_id)
        return [item.model_dump() for item in items]
    except Exception as exc:
        raise _svc_error(exc)


@router.get(
    "/{voucher_id}",
    response_model=VoucherOut,
    summary="凭证详情（含分录行）",
)
def get_voucher(
    voucher_id: int,
    ctx: tuple   = Depends(_get_ctx),
    db:  Session = Depends(get_db),
) -> Any:
    tenant_id, account_set_id = ctx
    svc = VoucherService(db)
    try:
        return svc.get_voucher(voucher_id, tenant_id, account_set_id)
    except Exception as exc:
        raise _svc_error(exc)


# ══════════════════════════════════════════════════════════════════════════════
# 手工 CRUD
# ══════════════════════════════════════════════════════════════════════════════

@router.post(
    "",
    response_model=VoucherOut,
    status_code=201,
    summary="手工新建凭证",
)
def create_voucher(
    body:         VoucherCreateInput,
    ctx:          tuple        = Depends(_get_ctx),
    db:           Session      = Depends(get_db),
    current_user: UserAccount  = Depends(get_current_user),
) -> Any:
    """
    手工录入凭证。
    前置校验：借贷平衡（Pydantic model_validator 已验证）。
    自动创建关联的 OperationalRecord（满足 record_id FK）。
    初始状态为 DRAFT。
    """
    tenant_id, account_set_id = ctx
    svc = VoucherService(db)
    try:
        vh = svc.create_voucher(tenant_id, account_set_id, body, creator_id=current_user.id)
        db.commit()
        db.refresh(vh)
        return svc.get_voucher(vh.voucher_id, tenant_id, account_set_id)
    except Exception as exc:
        db.rollback()
        raise _svc_error(exc)


@router.put(
    "/{voucher_id}",
    response_model=VoucherOut,
    summary="更新凭证（仅草稿/驳回状态）",
)
def update_voucher(
    voucher_id: int,
    body: VoucherUpdateInput,
    ctx:  tuple   = Depends(_get_ctx),
    db:   Session = Depends(get_db),
) -> Any:
    """
    更新凭证头信息或分录行（若传入 lines 则完整替换）。
    POSTED 状态凭证返回 403。PENDING_REVIEW 状态凭证也返回 403（需先反审核）。
    """
    tenant_id, account_set_id = ctx
    svc = VoucherService(db)
    try:
        svc.update_voucher(voucher_id, tenant_id, account_set_id, body)
        db.commit()
        return svc.get_voucher(voucher_id, tenant_id, account_set_id)
    except Exception as exc:
        db.rollback()
        raise _svc_error(exc)


# ══════════════════════════════════════════════════════════════════════════════
# 状态机
# ══════════════════════════════════════════════════════════════════════════════

@router.post(
    "/{voucher_id}/review",
    response_model=VoucherOut,
    summary="审核凭证（→ POSTED）",
)
def review_voucher(
    voucher_id:   int,
    body:         VoucherReviewInput,
    ctx:          tuple       = Depends(_get_ctx),
    db:           Session     = Depends(get_db),
    current_user: UserAccount = Depends(get_current_user),
) -> Any:
    """
    审核凭证：DRAFT 或 PENDING_REVIEW → POSTED。
    写入 reviewer_id（当前用户）、review_note、reviewed_at。
    AuditGuard 将从此刻起保护凭证不被意外修改。
    """
    tenant_id, account_set_id = ctx
    svc = VoucherService(db)
    try:
        svc.review(
            voucher_id, tenant_id, account_set_id,
            reviewer_id = current_user.id,
            review_note = body.review_note,
        )
        db.commit()
        return svc.get_voucher(voucher_id, tenant_id, account_set_id)
    except Exception as exc:
        db.rollback()
        raise _svc_error(exc)


@router.post(
    "/{voucher_id}/unreview",
    response_model=VoucherOut,
    summary="反审核（POSTED → PENDING_REVIEW）",
)
def unreview_voucher(
    voucher_id: int,
    ctx: tuple   = Depends(_get_ctx),
    db:  Session = Depends(get_db),
) -> Any:
    """
    反审核：仅 POSTED 状态允许操作，回退至 PENDING_REVIEW。
    清空 reviewer_id / review_note / reviewed_at。
    """
    tenant_id, account_set_id = ctx
    svc = VoucherService(db)
    try:
        svc.unreview(voucher_id, tenant_id, account_set_id)
        db.commit()
        return svc.get_voucher(voucher_id, tenant_id, account_set_id)
    except Exception as exc:
        db.rollback()
        raise _svc_error(exc)


# ══════════════════════════════════════════════════════════════════════════════
# 软删除 & 回收站
# ══════════════════════════════════════════════════════════════════════════════

@router.delete(
    "/{voucher_id}",
    status_code=204,
    summary="软删除凭证（移入回收站）",
)
def soft_delete_voucher(
    voucher_id: int,
    ctx: tuple   = Depends(_get_ctx),
    db:  Session = Depends(get_db),
) -> None:
    """
    软删除凭证（is_deleted=True），不物理删除。
    前置条件：状态必须为 DRAFT（POSTED/PENDING_REVIEW 不允许删除）。
    """
    tenant_id, account_set_id = ctx
    svc = VoucherService(db)
    try:
        svc.soft_delete(voucher_id, tenant_id, account_set_id)
        db.commit()
    except Exception as exc:
        db.rollback()
        raise _svc_error(exc)


@router.post(
    "/{voucher_id}/restore",
    response_model=VoucherOut,
    summary="还原凭证（从回收站恢复）",
)
def restore_voucher(
    voucher_id: int,
    ctx: tuple   = Depends(_get_ctx),
    db:  Session = Depends(get_db),
) -> Any:
    """将回收站中的凭证恢复为正常状态（is_deleted=False）。"""
    tenant_id, account_set_id = ctx
    svc = VoucherService(db)
    try:
        svc.restore(voucher_id, tenant_id, account_set_id)
        db.commit()
        return svc.get_voucher(voucher_id, tenant_id, account_set_id)
    except Exception as exc:
        db.rollback()
        raise _svc_error(exc)


# ══════════════════════════════════════════════════════════════════════════════
# 断号整理
# ══════════════════════════════════════════════════════════════════════════════

@router.post(
    "/reorganize",
    response_model=ReorganizeResult,
    summary="断号整理（对指定期间重新顺序编号）",
)
def reorganize_vouchers(
    body: ReorganizeInput,
    ctx:  tuple   = Depends(_get_ctx),
    db:   Session = Depends(get_db),
) -> Any:
    """
    按 voucher_date 升序对指定会计期间内所有未删除凭证重新赋值 voucher_number（1, 2, 3…）。
    财务审计要求期间内凭证号连续，删除中间凭证后需执行此操作。

    ⚠️ 事务保证：若中途发生错误，数据库自动回滚，凭证号不乱。
    """
    tenant_id, account_set_id = ctx
    svc = VoucherService(db)
    try:
        result = svc.reorganize(tenant_id, account_set_id, body)
        db.commit()
        return result
    except Exception as exc:
        db.rollback()
        raise _svc_error(exc)
