"""
AgentLedger — LedgerService (Sprint 4.1)

万能算盘：计算任意期间、任意科目范围的六列余额表。

六列定义：
  期初借方 / 期初贷方 / 本期借方 / 本期贷方 / 期末借方 / 期末贷方

数据来源：
  - 科目树      : TenantSubject  (level, parent_code, balance_direction)
  - 期初余额底数 : InitialBalance (year_start_balance — 防篡改年初数)
  - 期间发生额   : VoucherLine JOIN VoucherHeader (POSTED, not deleted)

计算公式（有符号中间值，正=借方余额，负=贷方余额）：
  opening_signed  = year_start_signed
                    + Σ DEBIT(year_start→date_from-1)
                    - Σ CREDIT(year_start→date_from-1)
  closing_signed  = opening_signed + current_debit - current_credit

Roll-up 策略：
  - 本期借方/贷方：粗计（各层级独立累加）
  - 期初/期末余额：有符号净值向父级累加，展示时再拆分借/贷列

DRY 承诺：
  Sprint 4.2 的 Running Balance 和 Sprint 4.3 的公式引擎
  将直接调用 calculate_period_balances，不重新聚合 SQL。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from models.accounting import InitialBalance, TenantSubject
from models.voucher_header import VoucherHeader, VoucherReviewStatus
from models.voucher_line import VoucherLine

logger = logging.getLogger(__name__)


# ── 输出数据结构 ──────────────────────────────────────────────────────────────

@dataclass
class TrialBalanceItem:
    code:            str
    name:            str
    level:           int
    direction:       str        # "借" / "贷"（科目固有方向）
    parent_code:     str | None
    opening_debit:   Decimal = field(default_factory=lambda: Decimal("0"))
    opening_credit:  Decimal = field(default_factory=lambda: Decimal("0"))
    current_debit:   Decimal = field(default_factory=lambda: Decimal("0"))
    current_credit:  Decimal = field(default_factory=lambda: Decimal("0"))
    closing_debit:   Decimal = field(default_factory=lambda: Decimal("0"))
    closing_credit:  Decimal = field(default_factory=lambda: Decimal("0"))
    # 内部有符号中间值（仅用于 roll-up，最终不输出）
    _opening_signed: Decimal = field(default_factory=lambda: Decimal("0"), repr=False)
    _closing_signed: Decimal = field(default_factory=lambda: Decimal("0"), repr=False)


# ── 工具函数 ──────────────────────────────────────────────────────────────────

def _split(signed: Decimal) -> tuple[Decimal, Decimal]:
    """有符号净值 → (借方金额, 贷方金额)"""
    if signed > Decimal("0"):
        return signed, Decimal("0")
    elif signed < Decimal("0"):
        return Decimal("0"), -signed
    return Decimal("0"), Decimal("0")


def _d(value) -> Decimal:
    return Decimal(str(value or 0))


# ══════════════════════════════════════════════════════════════════════════════
# LedgerService
# ══════════════════════════════════════════════════════════════════════════════

class LedgerService:

    def __init__(self, db: Session) -> None:
        self._db = db

    # ── Public API ────────────────────────────────────────────────────────────

    def calculate_period_balances(
        self,
        tenant_id:          int,
        account_set_id:     int,
        date_from:          date,
        date_to:            date,
        max_level:          Optional[int]  = None,
        hide_zero:          bool           = False,
        start_subject_code: Optional[str]  = None,
        end_subject_code:   Optional[str]  = None,
    ) -> list[TrialBalanceItem]:
        """
        计算 [date_from, date_to] 期间所有科目的六列余额。
        返回按 subject_code 排序的扁平列表（包含各层级，供前端自行渲染树状缩进）。
        """
        # ── Step 1: 科目树 ─────────────────────────────────────────────────
        subjects = (
            self._db.query(TenantSubject)
            .filter(
                TenantSubject.tenant_id    == tenant_id,
                TenantSubject.account_set_id == account_set_id,
                TenantSubject.is_deleted   == False,
                TenantSubject.is_enabled   == True,
            )
            .order_by(TenantSubject.subject_code)
            .all()
        )
        if not subjects:
            return []

        # ── Step 2: 期初余额底数（年初余额，auxiliary_hash="" 汇总记录）──────
        ib_rows = (
            self._db.query(InitialBalance)
            .filter(
                InitialBalance.tenant_id     == tenant_id,
                InitialBalance.account_set_id == account_set_id,
                InitialBalance.auxiliary_hash == "",
            )
            .all()
        )
        ib_map: dict[str, InitialBalance] = {r.subject_code: r for r in ib_rows}

        # ── Step 3: 凭证发生额聚合 ─────────────────────────────────────────
        year_start = date(date_from.year, 1, 1)
        pre_end    = date_from - timedelta(days=1)  # 期初前最后一天

        # 年初 → 期初前（用于计算期初余额的当年已发生部分）
        pre_map  = self._aggregate_lines(tenant_id, account_set_id, year_start, pre_end)

        # 本期发生额
        cur_map  = self._aggregate_lines(tenant_id, account_set_id, date_from, date_to)

        # ── Step 4: 逐科目初始化（叶级数据） ──────────────────────────────
        items: dict[str, TrialBalanceItem] = {}
        for subj in subjects:
            ib = ib_map.get(subj.subject_code)
            yr_bal = _d(ib.year_start_balance) if ib else Decimal("0")

            # 年初有符号余额（借方科目正值，贷方科目负值）
            yr_signed = yr_bal if subj.balance_direction == "借" else -yr_bal

            # 年初→期初前发生额
            pre  = pre_map.get(subj.subject_code, {})
            pre_d = _d(pre.get("DEBIT",  0))
            pre_c = _d(pre.get("CREDIT", 0))

            opening_signed = yr_signed + pre_d - pre_c

            # 本期发生额（粗计，借贷分列）
            cur  = cur_map.get(subj.subject_code, {})
            cur_d = _d(cur.get("DEBIT",  0))
            cur_c = _d(cur.get("CREDIT", 0))

            closing_signed = opening_signed + cur_d - cur_c

            item = TrialBalanceItem(
                code        = subj.subject_code,
                name        = subj.subject_name,
                level       = subj.level,
                direction   = subj.balance_direction,
                parent_code = subj.parent_code,
                current_debit  = cur_d,
                current_credit = cur_c,
                _opening_signed = opening_signed,
                _closing_signed = closing_signed,
            )
            # 拆分期初/期末有符号值为借/贷列
            item.opening_debit,  item.opening_credit  = _split(opening_signed)
            item.closing_debit,  item.closing_credit  = _split(closing_signed)
            items[subj.subject_code] = item

        # ── Step 5: Roll-up（从最深层级向上汇总） ─────────────────────────
        max_depth = max((s.level for s in subjects), default=1)
        for lvl in range(max_depth, 0, -1):
            for code, item in items.items():
                if item.level == lvl and item.parent_code:
                    parent = items.get(item.parent_code)
                    if parent is None:
                        continue
                    # 本期发生额：粗计累加
                    parent.current_debit  += item.current_debit
                    parent.current_credit += item.current_credit
                    # 期初/期末：有符号净值累加，事后拆分
                    parent._opening_signed += item._opening_signed
                    parent._closing_signed += item._closing_signed

        # 重新拆分父级期初/期末（roll-up 后）
        for item in items.values():
            if item.level < max_depth:   # 父级节点
                item.opening_debit,  item.opening_credit  = _split(item._opening_signed)
                item.closing_debit,  item.closing_credit  = _split(item._closing_signed)

        # ── Step 6: 过滤 & 排序 ───────────────────────────────────────────
        result = sorted(items.values(), key=lambda x: x.code)

        if max_level is not None:
            result = [r for r in result if r.level <= max_level]

        if start_subject_code:
            result = [r for r in result if r.code >= start_subject_code]

        if end_subject_code:
            result = [r for r in result if r.code <= end_subject_code]

        if hide_zero:
            result = [
                r for r in result
                if not (
                    r.current_debit  == Decimal("0")
                    and r.current_credit == Decimal("0")
                    and r.closing_debit  == Decimal("0")
                    and r.closing_credit == Decimal("0")
                )
            ]

        return result

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _aggregate_lines(
        self,
        tenant_id:     int,
        account_set_id: int,
        date_from:     date,
        date_to:       date,
    ) -> dict[str, dict[str, Decimal]]:
        """
        聚合指定期间所有 POSTED 凭证的借/贷发生额。
        返回 { subject_code: {"DEBIT": Decimal, "CREDIT": Decimal} }
        日期范围为空（date_from > date_to）时直接返回 {}。
        """
        if date_from > date_to:
            return {}

        rows = (
            self._db.query(
                VoucherLine.subject_code,
                VoucherLine.direction,
                func.sum(VoucherLine.amount).label("total"),
            )
            .join(VoucherHeader, VoucherLine.voucher_id == VoucherHeader.voucher_id)
            .filter(
                VoucherHeader.tenant_id      == tenant_id,
                VoucherHeader.account_set_id == account_set_id,
                VoucherHeader.voucher_date   >= date_from,
                VoucherHeader.voucher_date   <= date_to,
                VoucherHeader.review_status  == VoucherReviewStatus.POSTED,
                VoucherHeader.is_deleted     == False,
            )
            .group_by(VoucherLine.subject_code, VoucherLine.direction)
            .all()
        )

        result: dict[str, dict[str, Decimal]] = {}
        for code, direction, total in rows:
            if code not in result:
                result[code] = {"DEBIT": Decimal("0"), "CREDIT": Decimal("0")}
            result[code][direction] = Decimal(str(total))
        return result
