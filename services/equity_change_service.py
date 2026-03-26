"""
AgentLedger — EquityChangeService (Phase 4)

所有者权益变动表（会企04表，简化版）

列：实收资本 / 资本公积 / 盈余公积 / 未分配利润 / 合计
行：年初余额 / 本期增减 / 期末余额
"""
import logging
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from models.voucher_line import VoucherLine
from models.voucher_header import VoucherHeader, VoucherReviewStatus

logger = logging.getLogger(__name__)


@dataclass
class EquityRow:
    name:             str
    paid_in:          Decimal   # 实收资本
    capital_reserve:  Decimal   # 资本公积
    surplus_reserve:  Decimal   # 盈余公积
    retained:         Decimal   # 未分配利润
    total:            Decimal
    is_total:         bool = False


@dataclass
class EquityChangeStatement:
    year:      int
    cur_rows:  list[EquityRow] = field(default_factory=list)   # 本年
    prev_rows: list[EquityRow] = field(default_factory=list)   # 上年


def _build_balances(db: Session, as_of: date) -> dict[str, Decimal]:
    rows = (
        db.query(
            VoucherLine.subject_code,
            VoucherLine.direction,
            func.sum(VoucherLine.amount).label("total"),
        )
        .join(VoucherHeader, VoucherLine.voucher_id == VoucherHeader.voucher_id)
        .filter(
            VoucherHeader.voucher_date <= as_of,
            VoucherHeader.review_status == VoucherReviewStatus.POSTED,
        )
        .group_by(VoucherLine.subject_code, VoucherLine.direction)
        .all()
    )
    b: dict[str, Decimal] = {}
    for code, direction, total in rows:
        val = Decimal(str(total))
        b[code] = b.get(code, Decimal("0")) + (val if direction == "DEBIT" else -val)
    return b


def _eq(b: dict, *codes: str) -> Decimal:
    """权益贷方余额（正值）"""
    return sum((max(-b.get(c, Decimal("0")), Decimal("0")) for c in codes), Decimal("0"))


def _make_row(b: dict, name: str, is_total: bool = False) -> EquityRow:
    paid_in  = _eq(b, "4001", "3001")
    cap_res  = _eq(b, "4002")
    sur_res  = _eq(b, "4101")
    retained = _eq(b, "4103", "4104")
    total    = paid_in + cap_res + sur_res + retained
    return EquityRow(
        name=name,
        paid_in=paid_in,
        capital_reserve=cap_res,
        surplus_reserve=sur_res,
        retained=retained,
        total=total,
        is_total=is_total,
    )


class EquityChangeService:
    def __init__(self, db: Session) -> None:
        self._db = db

    def get_equity_changes(self, year: int) -> EquityChangeStatement:
        stmt = EquityChangeStatement(year=year)

        # ── 本年 ────────────────────────────────────────────────────────────
        beg_date  = date(year - 1, 12, 31)    # 上年末 = 本年年初
        end_date  = date(year, 12, 31)

        beg_bal   = _build_balances(self._db, beg_date)
        end_bal   = _build_balances(self._db, end_date)

        beg_row   = _make_row(beg_bal, "年初余额")
        end_row   = _make_row(end_bal, "期末余额", is_total=True)

        # 本期增减 = 期末 - 年初
        chg_row = EquityRow(
            name             = "本期增减",
            paid_in          = end_row.paid_in          - beg_row.paid_in,
            capital_reserve  = end_row.capital_reserve  - beg_row.capital_reserve,
            surplus_reserve  = end_row.surplus_reserve  - beg_row.surplus_reserve,
            retained         = end_row.retained         - beg_row.retained,
            total            = end_row.total            - beg_row.total,
        )

        stmt.cur_rows = [beg_row, chg_row, end_row]

        # ── 上年 ────────────────────────────────────────────────────────────
        pbeg_date = date(year - 2, 12, 31)
        pend_date = date(year - 1, 12, 31)

        pbeg_bal  = _build_balances(self._db, pbeg_date)
        pend_bal  = _build_balances(self._db, pend_date)

        pbeg_row  = _make_row(pbeg_bal, "上年年初余额")
        pend_row  = _make_row(pend_bal, "上年期末余额", is_total=True)

        pchg_row  = EquityRow(
            name             = "上年本期增减",
            paid_in          = pend_row.paid_in          - pbeg_row.paid_in,
            capital_reserve  = pend_row.capital_reserve  - pbeg_row.capital_reserve,
            surplus_reserve  = pend_row.surplus_reserve  - pbeg_row.surplus_reserve,
            retained         = pend_row.retained         - pbeg_row.retained,
            total            = pend_row.total            - pbeg_row.total,
        )

        stmt.prev_rows = [pbeg_row, pchg_row, pend_row]

        return stmt
