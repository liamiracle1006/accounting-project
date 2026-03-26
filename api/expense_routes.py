"""
AgentLedger — Expense Request API (Phase 3)

端点：
  POST /api/expenses                     — 提交费用申请（所有角色）
  GET  /api/expenses                     — 列表（老板/财务看全部；员工看自己的）
  GET  /api/expenses/{id}                — 详情
  POST /api/expenses/{id}/approve        — 审批通过（BOSS / DEPT_MANAGER）
  POST /api/expenses/{id}/reject         — 驳回（BOSS / DEPT_MANAGER）
"""
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database.connection import get_db
from models.expense_request import ExpenseRequest, ExpenseStatus
from models.user_account import UserAccount, UserRole
from services.auth_service import get_current_user, require_role

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/expenses", tags=["expenses"])

APPROVER_ROLES = (UserRole.BOSS, UserRole.DEPT_MANAGER)


# ── Schemas ────────────────────────────────────────────────────────────────────

class SubmitExpenseRequest(BaseModel):
    title:        str   = Field(..., min_length=1, max_length=200)
    amount:       float = Field(..., gt=0)
    expense_type: str   = Field(..., min_length=1, max_length=100)
    description:  str | None = None
    dept_id:      int | None = None


class ReviewRequest(BaseModel):
    note: str | None = Field(default=None, max_length=500)


def _req_to_dict(r: ExpenseRequest) -> dict:
    return {
        "request_id":   r.request_id,
        "applicant_id": r.applicant_id,
        "dept_id":      r.dept_id,
        "title":        r.title,
        "amount":       float(r.amount),
        "expense_type": r.expense_type,
        "description":  r.description,
        "status":       r.status,
        "reviewer_id":  r.reviewer_id,
        "review_note":  r.review_note,
        "reviewed_at":  str(r.reviewed_at) if r.reviewed_at else None,
        "record_id":    r.record_id,
        "created_at":   str(r.created_at)  if r.created_at  else None,
    }


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post("", status_code=201)
def submit_expense(
    body:         SubmitExpenseRequest,
    current_user: UserAccount = Depends(get_current_user),
    db:           Session     = Depends(get_db),
) -> Any:
    req = ExpenseRequest(
        applicant_id = current_user.user_id,
        dept_id      = body.dept_id or current_user.department_id,
        title        = body.title,
        amount       = body.amount,
        expense_type = body.expense_type,
        description  = body.description,
        status       = ExpenseStatus.PENDING,
    )
    db.add(req)
    db.commit()
    db.refresh(req)
    logger.info("Expense submitted: id=%s amount=%.2f by=%s",
                req.request_id, req.amount, current_user.username)
    return _req_to_dict(req)


@router.get("")
def list_expenses(
    status:       str | None = None,
    current_user: UserAccount = Depends(get_current_user),
    db:           Session     = Depends(get_db),
) -> Any:
    q = db.query(ExpenseRequest)
    # 普通员工只能看自己的；老板和财务看全部
    if current_user.role not in (UserRole.BOSS, UserRole.ACCOUNTANT):
        q = q.filter(ExpenseRequest.applicant_id == current_user.user_id)
    if status:
        q = q.filter(ExpenseRequest.status == status.upper())
    items = q.order_by(ExpenseRequest.request_id.desc()).limit(200).all()
    return [_req_to_dict(r) for r in items]


@router.get("/{request_id}")
def get_expense(
    request_id:   int,
    current_user: UserAccount = Depends(get_current_user),
    db:           Session     = Depends(get_db),
) -> Any:
    req = db.get(ExpenseRequest, request_id)
    if not req:
        raise HTTPException(status_code=404, detail="费用申请不存在")
    # 普通员工只能查自己的
    if current_user.role not in (UserRole.BOSS, UserRole.ACCOUNTANT) \
            and req.applicant_id != current_user.user_id:
        raise HTTPException(status_code=403, detail="无权查看此申请")
    return _req_to_dict(req)


@router.post("/{request_id}/approve")
def approve_expense(
    request_id:   int,
    body:         ReviewRequest,
    current_user: UserAccount = Depends(require_role(*APPROVER_ROLES)),
    db:           Session     = Depends(get_db),
) -> Any:
    req = db.get(ExpenseRequest, request_id)
    if not req:
        raise HTTPException(status_code=404, detail="费用申请不存在")
    if req.status != ExpenseStatus.PENDING:
        raise HTTPException(status_code=409, detail=f"申请当前状态为 {req.status}，无法审批")

    req.status      = ExpenseStatus.APPROVED
    req.reviewer_id = current_user.user_id
    req.review_note = body.note
    req.reviewed_at = datetime.now(timezone.utc)
    db.commit()
    logger.info("Expense approved: id=%s by=%s", request_id, current_user.username)
    return _req_to_dict(req)


@router.post("/{request_id}/reject")
def reject_expense(
    request_id:   int,
    body:         ReviewRequest,
    current_user: UserAccount = Depends(require_role(*APPROVER_ROLES)),
    db:           Session     = Depends(get_db),
) -> Any:
    req = db.get(ExpenseRequest, request_id)
    if not req:
        raise HTTPException(status_code=404, detail="费用申请不存在")
    if req.status != ExpenseStatus.PENDING:
        raise HTTPException(status_code=409, detail=f"申请当前状态为 {req.status}，无法操作")

    req.status      = ExpenseStatus.REJECTED
    req.reviewer_id = current_user.user_id
    req.review_note = body.note
    req.reviewed_at = datetime.now(timezone.utc)
    db.commit()
    logger.info("Expense rejected: id=%s by=%s note=%s", request_id, current_user.username, body.note)
    return _req_to_dict(req)
