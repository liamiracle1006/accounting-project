"""
AgentLedger — EquityChangeService (会企04表，官方格式)

列（11列）：
  实收资本 | 其他权益工具 | 资本公积 | 减：库存股 |
  其他综合收益 | 专项储备 | 盈余公积 | 一般风险准备 |
  未分配利润 | 归属于母公司所有者权益合计 | 少数股东权益

行（本年/上年各~16行）：
  一、年初余额
  二、本年变动金额：
    (一) 综合收益总额
      1. 净利润
      2. 其他综合收益
    (二) 所有者投入和减少资本
      1. 所有者投入资本
      2. 股权激励
      3. 回购注销库存股
    (三) 利润分配
      1. 提取盈余公积
      2. 向所有者分配
    (四) 所有者权益内部结转
      1. 盈余公积弥补亏损
      2. 实收资本转增
  三、期末余额
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
    """官方格式：11列所有者权益变动行"""
    name:             str
    paid_in:          Decimal   # 实收资本
    other_equity:     Decimal   # 其他权益工具
    capital_reserve:  Decimal   # 资本公积
    treasury_stock:   Decimal   # 减：库存股（负值表示减少净资产）
    oci:              Decimal   # 其他综合收益
    special_reserve:  Decimal   # 专项储备
    surplus_reserve:  Decimal   # 盈余公积
    risk_reserve:     Decimal   # 一般风险准备
    retained:         Decimal   # 未分配利润
    total:            Decimal   # 合计
    minority:         Decimal   # 少数股东权益（合并报表用，独立报表为0）
    is_total:         bool = False


@dataclass
class EquityChangeStatement:
    year:      int
    cur_rows:  list[EquityRow] = field(default_factory=list)
    prev_rows: list[EquityRow] = field(default_factory=list)


# ── 余额辅助 ─────────────────────────────────────────────────────────────────

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


def _sum_period(db: Session, code_prefix: str, direction: str,
                date_from: date, date_to: date) -> Decimal:
    row = (
        db.query(func.sum(VoucherLine.amount))
        .join(VoucherHeader, VoucherLine.voucher_id == VoucherHeader.voucher_id)
        .filter(
            VoucherLine.subject_code.like(f"{code_prefix}%"),
            VoucherLine.direction == direction,
            VoucherHeader.voucher_date >= date_from,
            VoucherHeader.voucher_date <= date_to,
            VoucherHeader.review_status == VoucherReviewStatus.POSTED,
        )
        .scalar()
    )
    return Decimal(str(row or 0))


def _eq(b: dict, *codes: str) -> Decimal:
    """权益贷方余额（正值代表净资产增加）"""
    return sum((max(-b.get(c, Decimal("0")), Decimal("0")) for c in codes), Decimal("0"))


def _make_balance_row(b: dict, name: str, is_total: bool = False) -> EquityRow:
    """从余额字典构建一行（期初/期末余额行）"""
    paid_in         = _eq(b, "4001", "3001")
    other_eq        = Decimal("0")                       # 其他权益工具（优先股等，简化为0）
    cap_res         = _eq(b, "4002")
    treasury        = Decimal("0")                       # 库存股（简化为0）
    oci             = _eq(b, "4005")
    spec_res        = Decimal("0")                       # 专项储备（简化为0）
    sur_res         = _eq(b, "4101")
    risk_res        = _eq(b, "4102")
    retained        = _eq(b, "4103", "4104")
    total = paid_in + other_eq + cap_res - treasury + oci + spec_res + sur_res + risk_res + retained
    return EquityRow(
        name=name,
        paid_in=paid_in, other_equity=other_eq, capital_reserve=cap_res,
        treasury_stock=treasury, oci=oci, special_reserve=spec_res,
        surplus_reserve=sur_res, risk_reserve=risk_res, retained=retained,
        total=total, minority=Decimal("0"),
        is_total=is_total,
    )


def _zero_row(name: str, is_total: bool = False) -> EquityRow:
    z = Decimal("0")
    return EquityRow(
        name=name, paid_in=z, other_equity=z, capital_reserve=z,
        treasury_stock=z, oci=z, special_reserve=z, surplus_reserve=z,
        risk_reserve=z, retained=z, total=z, minority=z, is_total=is_total,
    )


def _change_row(end: EquityRow, beg: EquityRow, name: str) -> EquityRow:
    """期末 - 期初 = 本期变动"""
    return EquityRow(
        name=name,
        paid_in         = end.paid_in         - beg.paid_in,
        other_equity    = end.other_equity    - beg.other_equity,
        capital_reserve = end.capital_reserve - beg.capital_reserve,
        treasury_stock  = end.treasury_stock  - beg.treasury_stock,
        oci             = end.oci             - beg.oci,
        special_reserve = end.special_reserve - beg.special_reserve,
        surplus_reserve = end.surplus_reserve - beg.surplus_reserve,
        risk_reserve    = end.risk_reserve    - beg.risk_reserve,
        retained        = end.retained        - beg.retained,
        total           = end.total           - beg.total,
        minority        = end.minority        - beg.minority,
    )


# ── EquityChangeService ──────────────────────────────────────────────────────

class EquityChangeService:
    def __init__(self, db: Session) -> None:
        self._db = db

    def get_equity_changes(self, year: int) -> EquityChangeStatement:
        stmt = EquityChangeStatement(year=year)
        stmt.cur_rows  = self._build_section(year)
        stmt.prev_rows = self._build_section(year - 1)
        return stmt

    def _build_section(self, year: int) -> list[EquityRow]:
        beg_date = date(year - 1, 12, 31)
        end_date = date(year, 12, 31)
        df       = date(year, 1, 1)

        beg_bal  = _build_balances(self._db, beg_date)
        end_bal  = _build_balances(self._db, end_date)

        beg_row  = _make_balance_row(beg_bal, "一、年初余额", is_total=True)

        # ── 本年净利润（损益结转前 6xxx 净额） ──
        net_profit = self._calc_net_profit(df, end_date)

        # ── 其他综合收益变动 ──
        oci_end  = _eq(end_bal, "4005")
        oci_beg  = _eq(beg_bal, "4005")
        oci_chg  = oci_end - oci_beg

        # ── 综合收益总额行 ──
        comp_inc = _zero_row("(一) 综合收益总额")
        comp_inc.retained = net_profit
        comp_inc.oci      = oci_chg
        comp_inc.total    = net_profit + oci_chg

        # 净利润明细行
        np_row = _zero_row("  1. 净利润")
        np_row.retained = net_profit
        np_row.total    = net_profit

        # 其他综合收益明细行
        oci_row = _zero_row("  2. 其他综合收益")
        oci_row.oci   = oci_chg
        oci_row.total = oci_chg

        # ── 所有者投入和减少资本 ──
        cap_in_c = _sum_period(self._db, "4001","CREDIT", df, end_date) + _sum_period(self._db, "3001","CREDIT", df, end_date)
        cap_res_in_c = _sum_period(self._db, "4002","CREDIT", df, end_date)

        owner_invest = _zero_row("(二) 所有者投入和减少资本")
        owner_invest.paid_in         = cap_in_c
        owner_invest.capital_reserve = cap_res_in_c
        owner_invest.total           = cap_in_c + cap_res_in_c

        inv_row = _zero_row("  1. 所有者投入资本")
        inv_row.paid_in         = cap_in_c
        inv_row.capital_reserve = cap_res_in_c
        inv_row.total           = cap_in_c + cap_res_in_c

        # ── 利润分配 ──
        sur_extract = _sum_period(self._db, "4101","CREDIT", df, end_date)  # 提取盈余公积（贷）
        div_paid    = _sum_period(self._db, "4104","DEBIT",  df, end_date)  # 向股东分配（借）

        profit_dist = _zero_row("(三) 利润分配")
        profit_dist.surplus_reserve = sur_extract
        profit_dist.retained        = -(sur_extract + div_paid)
        profit_dist.total           = -(div_paid)

        sur_row = _zero_row("  1. 提取盈余公积")
        sur_row.surplus_reserve = sur_extract
        sur_row.retained        = -sur_extract
        sur_row.total           = Decimal("0")

        div_row = _zero_row("  2. 向所有者（股东）分配")
        div_row.retained = -div_paid
        div_row.total    = -div_paid

        # ── 所有者权益内部结转 ──
        transfer = _zero_row("(四) 所有者权益内部结转")

        # ── 本年变动合计 ──
        total_chg = _change_row(
            _make_balance_row(end_bal, ""),
            _make_balance_row(beg_bal, ""),
            "二、本年变动金额合计",
        )
        total_chg.is_total = True

        end_row = _make_balance_row(end_bal, "三、期末余额", is_total=True)

        return [
            beg_row,
            total_chg,
            comp_inc, np_row, oci_row,
            owner_invest, inv_row,
            profit_dist, sur_row, div_row,
            transfer,
            end_row,
        ]

    def _calc_net_profit(self, date_from: date, date_to: date) -> Decimal:
        """计算区间净利润（不依赖结转，直接汇总损益科目发生额）"""
        INCOME_PREFIXES  = {"6001","6051","6101","6111","6117","6301"}
        rows = (
            self._db.query(
                VoucherLine.subject_code,
                VoucherLine.direction,
                func.sum(VoucherLine.amount).label("total"),
            )
            .join(VoucherHeader, VoucherLine.voucher_id == VoucherHeader.voucher_id)
            .filter(
                VoucherLine.subject_code >= "6001",
                VoucherLine.subject_code <= "6899",
                VoucherHeader.voucher_date >= date_from,
                VoucherHeader.voucher_date <= date_to,
                VoucherHeader.review_status == VoucherReviewStatus.POSTED,
            )
            .group_by(VoucherLine.subject_code, VoucherLine.direction)
            .all()
        )
        income = Decimal("0")
        expense = Decimal("0")
        for code, direction, total in rows:
            val = Decimal(str(total))
            if code[:4] in INCOME_PREFIXES:
                income  += val if direction == "CREDIT" else -val
            else:
                expense += val if direction == "DEBIT"  else -val
        return income - expense
