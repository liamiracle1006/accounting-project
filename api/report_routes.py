"""
AgentLedger — Financial Report API (Phase 4, Official Format)

端点：
  GET  /api/reports/balance-sheet          — 资产负债表（会企01表）
  GET  /api/reports/income-statement       — 利润表（会企02表）
  GET  /api/reports/cash-flow              — 现金流量表（会企03表）
  GET  /api/reports/equity-changes         — 所有者权益变动表（会企04表）
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
from services.cashflow_service import CashFlowService
from services.equity_change_service import EquityChangeService

from services.ledger_service import LedgerService
from services.ledger_detail_service import LedgerDetailService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/reports", tags=["reports"])

FINANCE_ROLES = (UserRole.BOSS, UserRole.ACCOUNTANT)


def _get_ctx() -> tuple[int, int]:
    from database.tenant_context import get_current_tenant
    ctx = get_current_tenant()
    if ctx is None:
        raise HTTPException(status_code=401, detail="未设置租户上下文，请先登录")
    if ctx.account_set_id is None:
        raise HTTPException(status_code=400, detail="请先选择账套")
    return ctx.tenant_id, ctx.account_set_id


# ── Trial Balance (科目余额表 Sprint 4.1) ──────────────────────────────────

@router.get("/trial-balance")
def get_trial_balance(
    date_from:          str | None = None,
    date_to:            str | None = None,
    max_level:          int | None = None,
    hide_zero:          bool       = False,
    start_subject_code: str | None = None,
    end_subject_code:   str | None = None,
    current_user: UserAccount = Depends(get_current_user),
    db:           Session     = Depends(get_db),
) -> Any:
    """
    科目余额表（试算平衡表）。
    返回 [date_from, date_to] 期间所有科目的六列余额。
    试算平衡断言在后端执行，不平时 balanced=false + 警告信息。
    """
    today = date.today()
    try:
        df = date.fromisoformat(date_from) if date_from else date(today.year, today.month, 1)
        dt = date.fromisoformat(date_to)   if date_to   else today
    except ValueError:
        raise HTTPException(status_code=422, detail="日期格式应为 YYYY-MM-DD")

    tenant_id, account_set_id = _get_ctx()
    svc   = LedgerService(db)
    items = svc.calculate_period_balances(
        tenant_id          = tenant_id,
        account_set_id     = account_set_id,
        date_from          = df,
        date_to            = dt,
        max_level          = max_level,
        hide_zero          = hide_zero,
        start_subject_code = start_subject_code,
        end_subject_code   = end_subject_code,
    )

    # 试算平衡断言
    from decimal import Decimal
    total_opening_d = sum(i.opening_debit  for i in items)
    total_opening_c = sum(i.opening_credit for i in items)
    total_current_d = sum(i.current_debit  for i in items)
    total_current_c = sum(i.current_credit for i in items)
    total_closing_d = sum(i.closing_debit  for i in items)
    total_closing_c = sum(i.closing_credit for i in items)

    opening_balanced = abs(total_opening_d - total_opening_c) < Decimal("1.00")
    current_balanced = abs(total_current_d - total_current_c) < Decimal("1.00")
    closing_balanced = abs(total_closing_d - total_closing_c) < Decimal("1.00")
    balanced = opening_balanced and current_balanced and closing_balanced

    if not balanced:
        logger.error(
            "试算不平衡！期初 D=%s C=%s | 本期 D=%s C=%s | 期末 D=%s C=%s",
            total_opening_d, total_opening_c,
            total_current_d, total_current_c,
            total_closing_d, total_closing_c,
        )

    return {
        "date_from":        str(df),
        "date_to":          str(dt),
        "balanced":         balanced,
        "opening_balanced": opening_balanced,
        "current_balanced": current_balanced,
        "closing_balanced": closing_balanced,
        "totals": {
            "opening_debit":  float(total_opening_d),
            "opening_credit": float(total_opening_c),
            "current_debit":  float(total_current_d),
            "current_credit": float(total_current_c),
            "closing_debit":  float(total_closing_d),
            "closing_credit": float(total_closing_c),
        },
        "items": [
            {
                "code":           i.code,
                "name":           i.name,
                "level":          i.level,
                "direction":      i.direction,
                "parent_code":    i.parent_code,
                "opening_debit":  float(i.opening_debit),
                "opening_credit": float(i.opening_credit),
                "current_debit":  float(i.current_debit),
                "current_credit": float(i.current_credit),
                "closing_debit":  float(i.closing_debit),
                "closing_credit": float(i.closing_credit),
            }
            for i in items
        ],
    }


# ── Detailed Ledger (明细账 Sprint 4.2) ───────────────────────────────────

@router.get("/detailed-ledger")
def get_detailed_ledger(
    subject_code: str,
    date_from:    str | None = None,
    date_to:      str | None = None,
    keyword:      str | None = None,
    current_user: UserAccount = Depends(get_current_user),
    db:           Session     = Depends(get_db),
) -> Any:
    """
    单科目明细账（逐笔余额）。
    返回：期初余额行 + 凭证明细行 + 本期合计行 + 本年累计行。
    """
    if not subject_code:
        raise HTTPException(status_code=422, detail="subject_code 不能为空")

    today = date.today()
    try:
        df = date.fromisoformat(date_from) if date_from else date(today.year, today.month, 1)
        dt = date.fromisoformat(date_to)   if date_to   else today
    except ValueError:
        raise HTTPException(status_code=422, detail="日期格式应为 YYYY-MM-DD")

    tenant_id, account_set_id = _get_ctx()
    svc = LedgerDetailService(db)
    try:
        rows = svc.get_detailed_ledger(
            tenant_id      = tenant_id,
            account_set_id = account_set_id,
            subject_code   = subject_code,
            date_from      = df,
            date_to        = dt,
            keyword        = keyword,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    from dataclasses import asdict
    return {
        "subject_code": subject_code,
        "date_from":    str(df),
        "date_to":      str(dt),
        "rows":         [asdict(r) for r in rows],
    }


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


# ── Cash Flow Statement (会企03表) ─────────────────────────────────────────

@router.get("/cash-flow")
def get_cash_flow(
    date_from:    str | None = None,
    date_to:      str | None = None,
    current_user: UserAccount = Depends(get_current_user),
    db:           Session     = Depends(get_db),
) -> Any:
    """
    返回指定区间的现金流量表（会企03表，间接法）。
    默认：当年 1 月 1 日至今天。
    """
    today = date.today()
    try:
        df = date.fromisoformat(date_from) if date_from else date(today.year, 1, 1)
        dt = date.fromisoformat(date_to)   if date_to   else today
    except ValueError:
        raise HTTPException(status_code=422, detail="日期格式应为 YYYY-MM-DD")

    svc = CashFlowService(db)
    cf  = svc.get_cash_flow(df, dt)

    return {
        "date_from": cf.date_from,
        "date_to":   cf.date_to,
        "prev_from": cf.prev_from,
        "prev_to":   cf.prev_to,
        "items": [
            {
                "code":     i.code,
                "name":     i.name,
                "cur_amt":  float(i.cur_amt),
                "prev_amt": float(i.prev_amt),
                "is_total": i.is_total,
            }
            for i in cf.items
        ],
    }


# ── Statement of Changes in Equity (会企04表) ───────────────────────────────

@router.get("/equity-changes")
def get_equity_changes(
    year:         int | None = None,
    current_user: UserAccount = Depends(get_current_user),
    db:           Session     = Depends(get_db),
) -> Any:
    """
    返回指定年度的所有者权益变动表（会企04表）。
    默认：当年。
    """
    y = year or date.today().year
    svc  = EquityChangeService(db)
    stmt = svc.get_equity_changes(y)

    def row_dict(r):
        return {
            "name":            r.name,
            "paid_in":         float(r.paid_in),
            "capital_reserve": float(r.capital_reserve),
            "surplus_reserve": float(r.surplus_reserve),
            "retained":        float(r.retained),
            "total":           float(r.total),
            "is_total":        r.is_total,
        }

    return {
        "year":      stmt.year,
        "cur_rows":  [row_dict(r) for r in stmt.cur_rows],
        "prev_rows": [row_dict(r) for r in stmt.prev_rows],
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
