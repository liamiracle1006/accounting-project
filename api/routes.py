"""
AgentLedger — RESTful API Routes

Endpoints:
  POST /api/records                — 提交自然语言流水，触发全流程
  GET  /api/records/{id}           — 查询单条流水状态（含凭证ID）
  GET  /api/records                — 分页查询流水列表（含凭证ID）
  GET  /api/vouchers/{id}          — 查询凭证详情（含借贷明细）
  GET  /api/stats/summary          — 仪表盘汇总：收入/支出/利润/凭证数
  GET  /api/reports/income-expense — 按科目收支明细报表
  GET  /api/reports/trial-balance  — 科目余额表（Trial Balance）
"""
import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator
from sqlalchemy import func, case
from sqlalchemy.orm import Session

from database.connection import get_db
from models.operational_record import OperationalRecord, RecordStatus
from models.voucher_header import VoucherHeader
from models.voucher_line import VoucherLine
from models.account_subject import AccountSubject
from services.record_service import RecordService
from ai.llm_client import LLMClientError
from ai.json_parser import JSONParseError
from services.accounting_engine import AccountingError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["accounting"])


# ── Request / Response schemas ────────────────────────────────────────────────

class CreateRecordRequest(BaseModel):
    raw_text: str

    @field_validator("raw_text")
    @classmethod
    def not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("raw_text must not be empty")
        if len(v) > 2000:
            raise ValueError("raw_text must not exceed 2000 characters")
        return v


class RecordResponse(BaseModel):
    record_id:      int
    status:         str
    raw_text:       str
    extracted_json: str | None
    error_message:  str | None
    voucher_id:     int | None = None   # 关联凭证 ID（PROCESSED 时有值）


class VoucherLineResponse(BaseModel):
    line_id:             int
    subject_code:        str
    subject_name:        str | None = None
    direction:           str
    amount:              float
    auxiliary_entity_id: int | None
    memo:                str | None


class VoucherResponse(BaseModel):
    voucher_id:   int
    record_id:    int
    voucher_date: str
    total_amount: float
    memo:         str | None
    lines:        list[VoucherLineResponse]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_record_resp(record: OperationalRecord, voucher_id: int | None) -> dict:
    return {
        "record_id":      record.record_id,
        "status":         record.status,
        "raw_text":       record.raw_text,
        "extracted_json": record.extracted_json,
        "error_message":  record.error_message,
        "voucher_id":     voucher_id,
    }


def _current_ym() -> tuple[int, int]:
    now = datetime.now()
    return now.year, now.month


# ── Records endpoints ─────────────────────────────────────────────────────────

@router.post("/records", response_model=RecordResponse, status_code=201)
def create_record(
    body: CreateRecordRequest,
    db:   Session = Depends(get_db),
) -> Any:
    """接收自然语言业务流水，完整执行 LLM 解析 → 会计映射 → 凭证入库。"""
    service = RecordService(db)
    try:
        record = service.process_raw_text(body.raw_text)
    except (LLMClientError, JSONParseError, AccountingError, ValueError) as exc:
        logger.warning("Processing failed for raw_text='%s...': %s",
                       body.raw_text[:50], exc)
        raise HTTPException(status_code=422, detail=str(exc))

    voucher = (
        db.query(VoucherHeader)
        .filter(VoucherHeader.record_id == record.record_id)
        .first()
    )
    return _make_record_resp(record, voucher.voucher_id if voucher else None)


@router.get("/records", response_model=list[RecordResponse])
def list_records(
    status: str | None = Query(None, description="PENDING/PROCESSED/MANUAL_REVIEW"),
    skip:   int        = Query(0, ge=0),
    limit:  int        = Query(50, ge=1, le=200),
    db:     Session    = Depends(get_db),
) -> Any:
    """分页查询流水列表（含关联凭证 ID）。"""
    q = (
        db.query(OperationalRecord, VoucherHeader.voucher_id)
        .outerjoin(VoucherHeader, VoucherHeader.record_id == OperationalRecord.record_id)
    )
    if status:
        q = q.filter(OperationalRecord.status == status.upper())
    rows = (
        q.order_by(OperationalRecord.record_id.desc())
        .offset(skip).limit(limit).all()
    )
    return [_make_record_resp(r, vid) for r, vid in rows]


@router.get("/records/{record_id}", response_model=RecordResponse)
def get_record(record_id: int, db: Session = Depends(get_db)) -> Any:
    """查询单条业务流水（含关联凭证 ID）。"""
    record = db.get(OperationalRecord, record_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Record {record_id} not found")
    voucher = (
        db.query(VoucherHeader)
        .filter(VoucherHeader.record_id == record_id)
        .first()
    )
    return _make_record_resp(record, voucher.voucher_id if voucher else None)


@router.get("/vouchers/{voucher_id}", response_model=VoucherResponse)
def get_voucher(voucher_id: int, db: Session = Depends(get_db)) -> Any:
    """查询凭证主表 + 借贷明细（支持穿透审计）。"""
    voucher = db.get(VoucherHeader, voucher_id)
    if not voucher:
        raise HTTPException(status_code=404, detail=f"Voucher {voucher_id} not found")

    rows = (
        db.query(VoucherLine, AccountSubject.subject_name)
        .outerjoin(AccountSubject, AccountSubject.subject_code == VoucherLine.subject_code)
        .filter(VoucherLine.voucher_id == voucher_id)
        .all()
    )
    return {
        "voucher_id":   voucher.voucher_id,
        "record_id":    voucher.record_id,
        "voucher_date": str(voucher.voucher_date),
        "total_amount": float(voucher.total_amount),
        "memo":         voucher.memo,
        "lines": [
            {
                "line_id":             l.line_id,
                "subject_code":        l.subject_code,
                "subject_name":        name,
                "direction":           l.direction,
                "amount":              float(l.amount),
                "auxiliary_entity_id": l.auxiliary_entity_id,
                "memo":                l.memo,
            }
            for l, name in rows
        ],
    }


# ── Stats / Dashboard ─────────────────────────────────────────────────────────

@router.get("/stats/summary")
def get_summary(
    year:  int | None = Query(None, description="年份，默认当年"),
    month: int | None = Query(None, description="月份 1-12，默认当月"),
    db: Session = Depends(get_db),
) -> Any:
    """仪表盘汇总：当期收入、支出、净利润、凭证数、待审核数。"""
    cur_year, cur_month = _current_ym()
    year  = year  or cur_year
    month = month or cur_month

    agg = (
        db.query(
            func.sum(case(
                (AccountSubject.subject_type == "收入", VoucherLine.amount),
                else_=0,
            )).label("total_income"),
            func.sum(case(
                (AccountSubject.subject_type == "费用", VoucherLine.amount),
                else_=0,
            )).label("total_expense"),
        )
        .join(VoucherLine, VoucherLine.subject_code == AccountSubject.subject_code)
        .join(VoucherHeader, VoucherHeader.voucher_id == VoucherLine.voucher_id)
        .filter(func.year(VoucherHeader.voucher_date) == year)
        .filter(func.month(VoucherHeader.voucher_date) == month)
        .first()
    )

    total_income  = float(agg.total_income  or 0)
    total_expense = float(agg.total_expense or 0)

    total_vouchers = (
        db.query(func.count(VoucherHeader.voucher_id))
        .filter(func.year(VoucherHeader.voucher_date) == year)
        .filter(func.month(VoucherHeader.voucher_date) == month)
        .scalar() or 0
    )
    pending_review = (
        db.query(func.count(OperationalRecord.record_id))
        .filter(OperationalRecord.status == RecordStatus.MANUAL_REVIEW)
        .scalar() or 0
    )

    return {
        "year":           year,
        "month":          month,
        "total_income":   total_income,
        "total_expense":  total_expense,
        "net_profit":     total_income - total_expense,
        "total_vouchers": total_vouchers,
        "pending_review": pending_review,
    }


# ── Reports ───────────────────────────────────────────────────────────────────

@router.get("/reports/income-expense")
def income_expense_report(
    year:  int | None = Query(None),
    month: int | None = Query(None),
    db: Session = Depends(get_db),
) -> Any:
    """按科目分组的收支明细（仅收入/费用类科目）。"""
    cur_year, cur_month = _current_ym()
    year  = year  or cur_year
    month = month or cur_month

    rows = (
        db.query(
            AccountSubject.subject_code,
            AccountSubject.subject_name,
            AccountSubject.subject_type,
            func.sum(case(
                (VoucherLine.direction == "DEBIT", VoucherLine.amount),
                else_=0,
            )).label("debit_amount"),
            func.sum(case(
                (VoucherLine.direction == "CREDIT", VoucherLine.amount),
                else_=0,
            )).label("credit_amount"),
            func.count(VoucherLine.line_id).label("tx_count"),
        )
        .join(VoucherLine, VoucherLine.subject_code == AccountSubject.subject_code)
        .join(VoucherHeader, VoucherHeader.voucher_id == VoucherLine.voucher_id)
        .filter(AccountSubject.subject_type.in_(["收入", "费用"]))
        .filter(func.year(VoucherHeader.voucher_date) == year)
        .filter(func.month(VoucherHeader.voucher_date) == month)
        .group_by(
            AccountSubject.subject_code,
            AccountSubject.subject_name,
            AccountSubject.subject_type,
        )
        .order_by(AccountSubject.subject_code)
        .all()
    )

    return [
        {
            "subject_code":  r.subject_code,
            "subject_name":  r.subject_name,
            "subject_type":  r.subject_type,
            "debit_amount":  float(r.debit_amount),
            "credit_amount": float(r.credit_amount),
            # 净发生额：收入取贷方，费用取借方
            "net_amount":    float(r.credit_amount) if r.subject_type == "收入"
                             else float(r.debit_amount),
            "tx_count":      r.tx_count,
        }
        for r in rows
    ]


@router.get("/reports/trial-balance")
def trial_balance(
    date_from: str | None = Query(None, description="起始日期 YYYY-MM-DD，默认当年1月1日"),
    date_to:   str | None = Query(None, description="截止日期 YYYY-MM-DD，默认今日"),
    db: Session = Depends(get_db),
) -> Any:
    """
    科目余额表（Trial Balance）。
    列出期间内有发生额的所有科目，含借方合计、贷方合计、净余额。
    """
    now = datetime.now()
    date_from = date_from or f"{now.year}-01-01"
    date_to   = date_to   or now.strftime("%Y-%m-%d")

    rows = (
        db.query(
            AccountSubject.subject_code,
            AccountSubject.subject_name,
            AccountSubject.subject_type,
            AccountSubject.direction.label("normal_direction"),
            func.sum(case(
                (VoucherLine.direction == "DEBIT", VoucherLine.amount),
                else_=0,
            )).label("debit_total"),
            func.sum(case(
                (VoucherLine.direction == "CREDIT", VoucherLine.amount),
                else_=0,
            )).label("credit_total"),
        )
        .join(VoucherLine, VoucherLine.subject_code == AccountSubject.subject_code)
        .join(VoucherHeader, VoucherHeader.voucher_id == VoucherLine.voucher_id)
        .filter(VoucherHeader.voucher_date >= date_from)
        .filter(VoucherHeader.voucher_date <= date_to)
        .group_by(
            AccountSubject.subject_code,
            AccountSubject.subject_name,
            AccountSubject.subject_type,
            AccountSubject.direction,
        )
        .order_by(AccountSubject.subject_code)
        .all()
    )

    result = []
    for r in rows:
        debit  = float(r.debit_total)
        credit = float(r.credit_total)
        balance = (debit - credit) if r.normal_direction == "DEBIT" else (credit - debit)
        result.append({
            "subject_code":      r.subject_code,
            "subject_name":      r.subject_name,
            "subject_type":      r.subject_type,
            "normal_direction":  r.normal_direction,
            "debit_total":       debit,
            "credit_total":      credit,
            "balance":           balance,
        })

    return result
