"""
AgentLedger — Financial Report API (Phase 4, Official Format)

端点：
  GET  /api/reports/balance-sheet          — 资产负债表（会企01表）
  GET  /api/reports/income-statement       — 利润表（会企02表）
  GET  /api/reports/periods                — 会计期间列表
  POST /api/reports/periods/{year}/{month}/close — 月末结账
  POST /api/reports/periods/{year}/{month}/open  — 手动开启期间
"""
import logging
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database.connection import get_db
from models.accounting_period import AccountingPeriod
from models.user_account import UserAccount, UserRole
from services.auth_service import get_current_user, require_role
from services.report_service import ReportService
from services.period_closing_service import PeriodClosingService, PeriodClosingError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/reports", tags=["reports"])

FINANCE_ROLES = (UserRole.BOSS, UserRole.ACCOUNTANT)


# ── Balance Sheet (会企01表) ────────────────────────────────────────────────

@router.get("/balance-sheet")
def get_balance_sheet(
    as_of:        str | None = None,
    current_user: UserAccount = Depends(get_current_user),
    db:           Session     = Depends(get_db),
) -> Any:
    """
    返回截至指定日期（默认今天）的官方格式资产负债表（会企01表）。
    包含期末余额和期初（年初）余额两列。
    as_of 格式：YYYY-MM-DD
    """
    try:
        as_of_date = date.fromisoformat(as_of) if as_of else date.today()
    except ValueError:
        raise HTTPException(status_code=422, detail="as_of 格式应为 YYYY-MM-DD")

    svc = ReportService(db)
    bs  = svc.get_balance_sheet(as_of_date)

    def items(lst):
        return [
            {
                "code":     i.code,
                "name":     i.name,
                "end_bal":  float(i.end_bal),
                "beg_bal":  float(i.beg_bal),
                "is_total": i.is_total,
            }
            for i in lst
        ]

    return {
        "as_of_date":  bs.as_of_date,
        "beg_of_year": bs.beg_of_year,
        "assets":      items(bs.assets),
        "liabilities": items(bs.liabilities),
        "equity":      items(bs.equity),
        "balanced":    bs.balanced,
        "diff":        float(bs.diff),
    }


# ── Income Statement (会企02表) ─────────────────────────────────────────────

@router.get("/income-statement")
def get_income_statement(
    date_from:    str | None = None,
    date_to:      str | None = None,
    current_user: UserAccount = Depends(get_current_user),
    db:           Session     = Depends(get_db),
) -> Any:
    """
    返回指定区间的官方格式利润表（会企02表）。
    包含本期金额和上年同期金额两列。
    默认：当月 1 日至今天。
    """
    today = date.today()
    try:
        df = date.fromisoformat(date_from) if date_from else date(today.year, today.month, 1)
        dt = date.fromisoformat(date_to)   if date_to   else today
    except ValueError:
        raise HTTPException(status_code=422, detail="日期格式应为 YYYY-MM-DD")

    svc = ReportService(db)
    is_ = svc.get_income_statement(df, dt)

    return {
        "date_from":  is_.date_from,
        "date_to":    is_.date_to,
        "prev_from":  is_.prev_from,
        "prev_to":    is_.prev_to,
        "items": [
            {
                "code":     i.code,
                "name":     i.name,
                "cur_amt":  float(i.cur_amt),
                "prev_amt": float(i.prev_amt),
                "is_total": i.is_total,
            }
            for i in is_.items
        ],
    }


# ── Accounting Periods ─────────────────────────────────────────────────────

@router.get("/periods")
def list_periods(
    current_user: UserAccount = Depends(get_current_user),
    db:           Session     = Depends(get_db),
) -> Any:
    svc     = PeriodClosingService(db)
    periods = svc.list_periods()
    return [_period_dict(p) for p in periods]


@router.post("/periods/{year}/{month}/close", status_code=201)
def close_period(
    year:         int,
    month:        int,
    current_user: UserAccount = Depends(require_role(*FINANCE_ROLES)),
    db:           Session     = Depends(get_db),
) -> Any:
    """
    执行月末结账：生成损益结转凭证，锁定期间。
    幂等：已结账则报错。
    """
    if not (1 <= month <= 12):
        raise HTTPException(status_code=422, detail="month 必须在 1-12 之间")
    if year < 2020 or year > 2035:
        raise HTTPException(status_code=422, detail="year 超出合理范围")

    svc = PeriodClosingService(db)
    try:
        result = svc.close_period(year, month, current_user.user_id)
    except PeriodClosingError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    return {
        "year":       result.year,
        "month":      result.month,
        "net_profit": float(result.net_profit),
        "voucher_id": result.voucher_id,
        "message":    result.message,
    }


@router.post("/periods/{year}/{month}/open")
def ensure_period_open(
    year:         int,
    month:        int,
    current_user: UserAccount = Depends(get_current_user),
    db:           Session     = Depends(get_db),
) -> Any:
    """手动打开（创建）一个期间，通常由系统自动创建，此接口供补录使用。"""
    svc    = PeriodClosingService(db)
    period = svc.get_or_create_period(year, month)
    return _period_dict(period)


def _period_dict(p: AccountingPeriod) -> dict:
    return {
        "period_id":          p.period_id,
        "year":               p.year,
        "month":              p.month,
        "label":              f"{p.year}-{p.month:02d}",
        "status":             p.status,
        "closed_at":          str(p.closed_at) if p.closed_at else None,
        "closing_voucher_id": p.closing_voucher_id,
    }
