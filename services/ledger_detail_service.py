"""
AgentLedger — LedgerDetailService (Sprint 4.2)

明细账（分类账）引擎：单科目逐笔余额推算。

数据来源（与 LedgerService 完全一致，严禁双重聚合）：
  - 科目信息    : TenantSubject  (balance_direction, subject_name)
  - 年初余额底数 : InitialBalance (year_start_balance — 防篡改)
  - 凭证流水    : VoucherLine JOIN VoucherHeader (POSTED, not deleted)

Running Balance 公式（有符号中间值，正=借，负=贷）：
  opening_signed = year_start_signed
                   + Σ DEBIT(year_start → date_from-1)
                   - Σ CREDIT(year_start → date_from-1)

  对每笔凭证行：
    running += debit - credit   （DEBIT 恒 +，CREDIT 恒 −）

  显示方向：running > 0 → "借"；< 0 → "贷"；== 0 → "平"

输出行序：
  [0]     期初余额行   (row_type="opening")
  [1..n]  凭证明细行   (row_type="transaction")
  [n+1]   本期合计行   (row_type="period_total")
  [n+2]   本年累计行   (row_type="ytd_total")
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from models.accounting import InitialBalance, TenantSubject
from models.voucher_header import VoucherHeader, VoucherReviewStatus
from models.voucher_line import VoucherLine

logger = logging.getLogger(__name__)


# ── 输出数据结构 ───────────────────────────────────────────────────────────────

@dataclass
class LedgerDetailRow:
    row_type:       str          # "opening" | "transaction" | "period_total" | "ytd_total"
    date:           Optional[str]    # "YYYY-MM-DD"；特殊行为 None
    voucher_id:     Optional[int]
    voucher_word:   Optional[str]
    voucher_number: Optional[int]
    subject_code:   str
    subject_name:   str
    memo:           Optional[str]
    debit:          float
    credit:         float
    direction:      Optional[str]    # "借"|"贷"|"平"；period_total/ytd_total 为 None
    balance:        Optional[float]  # period_total/ytd_total 为 None


# ── 工具 ──────────────────────────────────────────────────────────────────────

def _d(v) -> Decimal:
    return Decimal(str(v or 0))


def _signed_to_display(signed: Decimal) -> tuple[str, float]:
    """有符号余额 → (方向文字, 绝对值)"""
    if signed > Decimal("0"):
        return "借", float(signed)
    elif signed < Decimal("0"):
        return "贷", float(-signed)
    return "平", 0.0


# ══════════════════════════════════════════════════════════════════════════════
# LedgerDetailService
# ══════════════════════════════════════════════════════════════════════════════

class LedgerDetailService:

    def __init__(self, db: Session) -> None:
        self._db = db

    # ── Public API ────────────────────────────────────────────────────────────

    def get_detailed_ledger(
        self,
        tenant_id:      int,
        account_set_id: int,
        subject_code:   str,
        date_from:      date,
        date_to:        date,
        keyword:        Optional[str] = None,
    ) -> list[LedgerDetailRow]:
        """
        返回单科目明细账行列表（期初余额 + 凭证明细 + 本期合计 + 本年累计）。

        Raises:
            ValueError: 科目在当前账套中不存在或已禁用/删除。
        """
        # ── Step 1: 查询科目基础信息 ──────────────────────────────────────
        subj = (
            self._db.query(TenantSubject)
            .filter(
                TenantSubject.tenant_id      == tenant_id,
                TenantSubject.account_set_id == account_set_id,
                TenantSubject.subject_code   == subject_code,
                TenantSubject.is_deleted     == False,
            )
            .first()
        )
        if subj is None:
            raise ValueError(f"科目不存在：{subject_code}")

        subject_name      = subj.subject_name
        balance_direction = subj.balance_direction  # "借" or "贷"

        # ── Step 2: 年初余额（防篡改 year_start_balance） ─────────────────
        year_start = date(date_from.year, 1, 1)
        ib = (
            self._db.query(InitialBalance)
            .filter(
                InitialBalance.tenant_id      == tenant_id,
                InitialBalance.account_set_id == account_set_id,
                InitialBalance.subject_code   == subject_code,
                InitialBalance.auxiliary_hash == "",
            )
            .first()
        )
        yr_bal    = _d(ib.year_start_balance) if ib else Decimal("0")
        yr_signed = yr_bal if balance_direction == "借" else -yr_bal

        # ── Step 3: 期前发生额（年初 → date_from-1）→ 期初有符号余额 ─────
        pre_end    = date_from - timedelta(days=1)
        pre        = self._aggregate_single(tenant_id, account_set_id, year_start, pre_end, subject_code)
        opening_sig = yr_signed + pre["DEBIT"] - pre["CREDIT"]

        # ── Step 4: 期内凭证明细行（date_from → date_to，按日期/字号升序）
        q = (
            self._db.query(VoucherLine, VoucherHeader)
            .join(VoucherHeader, VoucherLine.voucher_id == VoucherHeader.voucher_id)
            .filter(
                VoucherHeader.tenant_id      == tenant_id,
                VoucherHeader.account_set_id == account_set_id,
                VoucherLine.subject_code     == subject_code,
                VoucherHeader.voucher_date   >= date_from,
                VoucherHeader.voucher_date   <= date_to,
                VoucherHeader.review_status  == VoucherReviewStatus.POSTED,
                VoucherHeader.is_deleted     == False,
            )
            .order_by(
                VoucherHeader.voucher_date,
                VoucherHeader.voucher_number,
                VoucherLine.line_id,
            )
        )
        if keyword:
            q = q.filter(VoucherLine.memo.ilike(f"%{keyword}%"))

        current_pairs = q.all()

        # ── Step 5: 逐笔推算 Running Balance ─────────────────────────────
        cur_debit_total  = Decimal("0")
        cur_credit_total = Decimal("0")
        running          = opening_sig
        transaction_rows: list[LedgerDetailRow] = []

        for line, header in current_pairs:
            debit  = _d(line.amount) if line.direction == "DEBIT"  else Decimal("0")
            credit = _d(line.amount) if line.direction == "CREDIT" else Decimal("0")
            running          += debit - credit   # DEBIT 恒+，CREDIT 恒−
            cur_debit_total  += debit
            cur_credit_total += credit

            row_dir, row_bal = _signed_to_display(running)
            memo = line.memo or header.memo or ""

            transaction_rows.append(LedgerDetailRow(
                row_type       = "transaction",
                date           = str(header.voucher_date),
                voucher_id     = header.voucher_id,
                voucher_word   = header.voucher_word or "记",
                voucher_number = header.voucher_number,
                subject_code   = subject_code,
                subject_name   = subject_name,
                memo           = memo,
                debit          = float(debit),
                credit         = float(credit),
                direction      = row_dir,
                balance        = row_bal,
            ))

        # ── Step 6: 本年累计（年初 → date_to，单次聚合） ─────────────────
        ytd = self._aggregate_single(tenant_id, account_set_id, year_start, date_to, subject_code)

        # ── Step 7: 组装三个特殊行 ────────────────────────────────────────

        # 期初余额行
        op_dir, op_bal = _signed_to_display(opening_sig)
        opening_row = LedgerDetailRow(
            row_type       = "opening",
            date           = None,
            voucher_id     = None,
            voucher_word   = None,
            voucher_number = None,
            subject_code   = subject_code,
            subject_name   = subject_name,
            memo           = "期初余额",
            debit          = 0.0,
            credit         = 0.0,
            direction      = op_dir,
            balance        = op_bal,
        )

        # 本期合计行
        period_total_row = LedgerDetailRow(
            row_type       = "period_total",
            date           = None,
            voucher_id     = None,
            voucher_word   = None,
            voucher_number = None,
            subject_code   = subject_code,
            subject_name   = subject_name,
            memo           = "本期合计",
            debit          = float(cur_debit_total),
            credit         = float(cur_credit_total),
            direction      = None,
            balance        = None,
        )

        # 本年累计行
        ytd_total_row = LedgerDetailRow(
            row_type       = "ytd_total",
            date           = None,
            voucher_id     = None,
            voucher_word   = None,
            voucher_number = None,
            subject_code   = subject_code,
            subject_name   = subject_name,
            memo           = "本年累计",
            debit          = float(ytd["DEBIT"]),
            credit         = float(ytd["CREDIT"]),
            direction      = None,
            balance        = None,
        )

        return [opening_row] + transaction_rows + [period_total_row, ytd_total_row]

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _aggregate_single(
        self,
        tenant_id:      int,
        account_set_id: int,
        date_from:      date,
        date_to:        date,
        subject_code:   str,
    ) -> dict[str, Decimal]:
        """
        聚合指定科目在指定期间的借/贷发生额（POSTED 凭证，未删除）。
        返回 {"DEBIT": Decimal, "CREDIT": Decimal}。
        日期范围无效（date_from > date_to）时返回零值字典。
        """
        if date_from > date_to:
            return {"DEBIT": Decimal("0"), "CREDIT": Decimal("0")}

        rows = (
            self._db.query(
                VoucherLine.direction,
                func.sum(VoucherLine.amount).label("total"),
            )
            .join(VoucherHeader, VoucherLine.voucher_id == VoucherHeader.voucher_id)
            .filter(
                VoucherHeader.tenant_id      == tenant_id,
                VoucherHeader.account_set_id == account_set_id,
                VoucherLine.subject_code     == subject_code,
                VoucherHeader.voucher_date   >= date_from,
                VoucherHeader.voucher_date   <= date_to,
                VoucherHeader.review_status  == VoucherReviewStatus.POSTED,
                VoucherHeader.is_deleted     == False,
            )
            .group_by(VoucherLine.direction)
            .all()
        )

        result: dict[str, Decimal] = {"DEBIT": Decimal("0"), "CREDIT": Decimal("0")}
        for direction, total in rows:
            result[direction] = Decimal(str(total))
        return result
