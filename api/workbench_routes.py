"""
AgentLedger — Accountant Workbench API (Phase 3)

财务工作台：凭证审核专用端点。

端点：
  GET  /api/workbench/vouchers           — 列出待审核/全部凭证（财务/老板）
  GET  /api/workbench/vouchers/{id}      — 凭证详情（含明细行）
  POST /api/workbench/vouchers/{id}/post   — 审核通过 → POSTED
  POST /api/workbench/vouchers/{id}/reject — 驳回 → REJECTED
  POST /api/workbench/vouchers/{id}/submit — 将 DRAFT 提交审核 → PENDING_REVIEW
"""
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database.connection import get_db
from models.voucher_header import VoucherHeader, VoucherReviewStatus
from models.voucher_line import VoucherLine
from models.user_account import UserAccount, UserRole
from services.auth_service import get_current_user, require_role

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/workbench", tags=["workbench"])

FINANCE_ROLES = (UserRole.BOSS, UserRole.ACCOUNTANT)


# ── Schemas ────────────────────────────────────────────────────────────────────

class ReviewNote(BaseModel):
    note: str | None = Field(default=None, max_length=500)


def _line_to_dict(l: VoucherLine) -> dict:
    return {
        "line_id":      l.line_id,
        "subject_code": l.subject_code,
        "direction":    l.direction,
        "amount":       float(l.amount),
        "memo":         l.memo,
    }


def _voucher_to_dict(v: VoucherHeader, include_lines: bool = False) -> dict:
    d = {
        "voucher_id":    v.voucher_id,
        "record_id":     v.record_id,
        "voucher_date":  str(v.voucher_date),
        "total_amount":  float(v.total_amount),
        "memo":          v.memo,
        "review_status": v.review_status,
        "reviewer_id":   v.reviewer_id,
        "review_note":   v.review_note,
        "reviewed_at":   str(v.reviewed_at) if v.reviewed_at else None,
        "created_at":    str(v.created_at)  if v.created_at  else None,
    }
    if include_lines:
        d["lines"] = [_line_to_dict(l) for l in v.lines]
    return d


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/vouchers")
def list_vouchers(
    review_status: str | None = None,
    current_user:  UserAccount = Depends(require_role(*FINANCE_ROLES)),
    db:            Session     = Depends(get_db),
) -> Any:
    """列出凭证（财务/老板）。默认返回 PENDING_REVIEW 状态。"""
    status_filter = review_status or VoucherReviewStatus.PENDING_REVIEW
    q = db.query(VoucherHeader)
    if status_filter != "ALL":
        q = q.filter(VoucherHeader.review_status == status_filter.upper())
    items = q.order_by(VoucherHeader.voucher_id.desc()).limit(200).all()
    return [_voucher_to_dict(v) for v in items]


@router.get("/vouchers/{voucher_id}")
def get_voucher_detail(
    voucher_id:   int,
    current_user: UserAccount = Depends(require_role(*FINANCE_ROLES)),
    db:           Session     = Depends(get_db),
) -> Any:
    v = db.get(VoucherHeader, voucher_id)
    if not v:
        raise HTTPException(status_code=404, detail="凭证不存在")
    return _voucher_to_dict(v, include_lines=True)


@router.post("/vouchers/{voucher_id}/submit")
def submit_for_review(
    voucher_id:   int,
    current_user: UserAccount = Depends(get_current_user),
    db:           Session     = Depends(get_db),
) -> Any:
    """将 DRAFT 凭证提交财务审核。"""
    v = db.get(VoucherHeader, voucher_id)
    if not v:
        raise HTTPException(status_code=404, detail="凭证不存在")
    if v.review_status != VoucherReviewStatus.DRAFT:
        raise HTTPException(status_code=409, detail=f"凭证状态为 {v.review_status}，不可再次提交")

    v.review_status = VoucherReviewStatus.PENDING_REVIEW
    db.commit()
    logger.info("Voucher submitted for review: id=%s by=%s", voucher_id, current_user.username)
    return _voucher_to_dict(v)


@router.post("/vouchers/{voucher_id}/post")
def post_voucher(
    voucher_id:   int,
    body:         ReviewNote,
    current_user: UserAccount = Depends(require_role(*FINANCE_ROLES)),
    db:           Session     = Depends(get_db),
) -> Any:
    """审核通过，凭证正式入账（POSTED）。"""
    v = db.get(VoucherHeader, voucher_id)
    if not v:
        raise HTTPException(status_code=404, detail="凭证不存在")
    if v.review_status not in (VoucherReviewStatus.PENDING_REVIEW, VoucherReviewStatus.DRAFT):
        raise HTTPException(status_code=409, detail=f"凭证状态为 {v.review_status}，无法审核")

    v.review_status = VoucherReviewStatus.POSTED
    v.reviewer_id   = current_user.user_id
    v.review_note   = body.note
    v.reviewed_at   = datetime.now(timezone.utc)
    db.commit()
    logger.info("Voucher posted: id=%s by=%s", voucher_id, current_user.username)
    return _voucher_to_dict(v)


@router.post("/vouchers/{voucher_id}/reject")
def reject_voucher(
    voucher_id:   int,
    body:         ReviewNote,
    current_user: UserAccount = Depends(require_role(*FINANCE_ROLES)),
    db:           Session     = Depends(get_db),
) -> Any:
    """驳回凭证，退回修改。"""
    v = db.get(VoucherHeader, voucher_id)
    if not v:
        raise HTTPException(status_code=404, detail="凭证不存在")
    if v.review_status != VoucherReviewStatus.PENDING_REVIEW:
        raise HTTPException(status_code=409, detail=f"凭证状态为 {v.review_status}，无法驳回")

    v.review_status = VoucherReviewStatus.REJECTED
    v.reviewer_id   = current_user.user_id
    v.review_note   = body.note
    v.reviewed_at   = datetime.now(timezone.utc)
    db.commit()
    logger.info("Voucher rejected: id=%s by=%s note=%s", voucher_id, current_user.username, body.note)
    return _voucher_to_dict(v)
