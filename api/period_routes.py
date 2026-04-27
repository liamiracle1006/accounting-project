"""
AgentLedger V4.0 — 会计期间 API Routes (Sprint 3.3)

端点一览（/api/period）：

  GET    /                            — 列出所有期间（按年月倒序，最多24条）
  POST   /{year}/{month}/transfer-pnl — 结转本期损益（幂等，可重复调用）
  POST   /{year}/{month}/close        — 结账（守门员三道防线）
  POST   /{year}/{month}/unclose      — 反结账（仅允许最后一个已结账期间）

异常映射：
  PeriodNotFoundError    → 404
  PeriodAlreadyClosedError / PeriodNotClosedError → 409
  PeriodClosingError     → 400
  RuntimeError（试算不平）→ 500
"""
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database.connection import get_db
from schemas.period_schemas import (
    CloseResult,
    PeriodOut,
    TransferPnLResult,
    UncloseResult,
)
from services.period_closing_service import (
    PeriodAlreadyClosedError,
    PeriodClosingError,
    PeriodClosingService,
    PeriodNotClosedError,
    PeriodNotFoundError,
)
from services.auth_service import get_current_user
from models.user_account import UserAccount

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/period", tags=["period"])


# ── Context helper ────────────────────────────────────────────────────────────

def _get_ctx(db: Session = Depends(get_db)) -> tuple[int, int]:
    from database.tenant_context import get_current_tenant
    ctx = get_current_tenant()
    if ctx is None:
        raise HTTPException(status_code=400, detail="未设置租户上下文，请先登录")
    if ctx.account_set_id is None:
        raise HTTPException(status_code=400, detail="请先选择账套（account_set_id 未设置）")
    return ctx.tenant_id, ctx.account_set_id


def _svc_error(exc: Exception) -> HTTPException:
    if isinstance(exc, PeriodNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, (PeriodAlreadyClosedError, PeriodNotClosedError)):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, PeriodClosingError):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, RuntimeError):
        return HTTPException(status_code=500, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


# ══════════════════════════════════════════════════════════════════════════════
# 列表
# ══════════════════════════════════════════════════════════════════════════════

@router.get(
    "",
    response_model=list[PeriodOut],
    summary="列出所有会计期间",
)
def list_periods(
    ctx: tuple   = Depends(_get_ctx),
    db:  Session = Depends(get_db),
) -> Any:
    """返回当前账套所有期间记录，按年月倒序排列，最多 24 条。"""
    tenant_id, account_set_id = ctx
    svc = PeriodClosingService(db)
    return svc.list_periods(tenant_id, account_set_id)


# ══════════════════════════════════════════════════════════════════════════════
# 结转本期损益
# ══════════════════════════════════════════════════════════════════════════════

@router.post(
    "/{year}/{month}/transfer-pnl",
    response_model=TransferPnLResult,
    status_code=200,
    summary="结转本期损益（幂等）",
)
def transfer_pnl(
    year:         int,
    month:        int,
    ctx:          tuple       = Depends(_get_ctx),
    db:           Session     = Depends(get_db),
    current_user: UserAccount = Depends(get_current_user),
) -> Any:
    """
    结转当期所有损益类科目（6xxx）至 4103 本年利润。
    12月额外将全年 4103 余额结转至 4104 利润分配-未分配利润（年结闭环）。

    接口为幂等设计：重复调用会先软删除旧结转凭证再重新生成。
    此操作不关闭期间（status 仍为 OPEN），需另行调用 close 接口完成结账。
    """
    if not (1 <= month <= 12):
        raise HTTPException(status_code=422, detail="month 必须在 1-12 之间")
    tenant_id, account_set_id = ctx
    svc = PeriodClosingService(db)
    try:
        result = svc.transfer_pnl(
            tenant_id, account_set_id, year, month,
            creator_id=current_user.id,
        )
        db.commit()
        return TransferPnLResult(
            year       = result.year,
            month      = result.month,
            net_profit = float(result.net_profit),
            voucher_id = result.voucher_id,
            message    = result.message,
        )
    except Exception as exc:
        db.rollback()
        raise _svc_error(exc)


# ══════════════════════════════════════════════════════════════════════════════
# 结账
# ══════════════════════════════════════════════════════════════════════════════

@router.post(
    "/{year}/{month}/close",
    response_model=CloseResult,
    status_code=200,
    summary="结账（守门员三道防线）",
)
def close_period(
    year:         int,
    month:        int,
    ctx:          tuple       = Depends(_get_ctx),
    db:           Session     = Depends(get_db),
    current_user: UserAccount = Depends(get_current_user),
) -> Any:
    """
    执行月末结账，内置三道防线：

    1. **断号自动修复**：静默调用 reorganize，确保凭证号连续
    2. **未审核拦截**：存在 DRAFT/PENDING_REVIEW 凭证时返回 400
    3. **损益未结平拦截**：6xxx 期末余额不为零时返回 400（需先执行 transfer-pnl）
    4. **试算平衡兜底**：借贷不平时返回 500（数据异常告警）

    成功后：期间 status 变为 CLOSED，并自动创建下期 OPEN。
    """
    if not (1 <= month <= 12):
        raise HTTPException(status_code=422, detail="month 必须在 1-12 之间")
    tenant_id, account_set_id = ctx
    svc = PeriodClosingService(db)
    try:
        result = svc.close_period(
            tenant_id, account_set_id, year, month,
            user_id=current_user.id,
        )
        db.commit()
        return CloseResult(
            year              = result.year,
            month             = result.month,
            reorganized_count = result.reorganized_count,
            next_period_year  = result.next_period_year,
            next_period_month = result.next_period_month,
            message           = result.message,
        )
    except Exception as exc:
        db.rollback()
        raise _svc_error(exc)


# ══════════════════════════════════════════════════════════════════════════════
# 反结账
# ══════════════════════════════════════════════════════════════════════════════

@router.post(
    "/{year}/{month}/unclose",
    response_model=UncloseResult,
    status_code=200,
    summary="反结账（仅允许最后一个已结账期间）",
)
def unclose_period(
    year:  int,
    month: int,
    ctx:   tuple   = Depends(_get_ctx),
    db:    Session = Depends(get_db),
) -> Any:
    """
    将最后一个 CLOSED 期间回退为 OPEN。

    操作内容：
    - 软删除该期间的结转凭证（closing_voucher_id）
    - 清空 closed_at / closed_by / closing_voucher_id
    - 若下期 period 存在且无凭证，则删除该空白 period 记录

    注意：只允许对最近一个已结账期间操作，中间期间不允许单独反结账。
    """
    if not (1 <= month <= 12):
        raise HTTPException(status_code=422, detail="month 必须在 1-12 之间")
    tenant_id, account_set_id = ctx
    svc = PeriodClosingService(db)
    try:
        result = svc.unclose_period(tenant_id, account_set_id, year, month)
        db.commit()
        return UncloseResult(
            year    = result.year,
            month   = result.month,
            message = result.message,
        )
    except Exception as exc:
        db.rollback()
        raise _svc_error(exc)
