"""
AgentLedger — PeriodClosingService (Phase 4)

月末结账引擎：
  1. 检查期间是否已结账（幂等保护）
  2. 计算本期损益（收入 - 成本 - 费用 = 净利润）
  3. 生成损益结转凭证
     借：6001 主营业务收入 / 6051 其他业务收入（归零）
     贷：6401 主营业务成本 / 660x 费用 / 6801 税费（归零）
     差额转入 4103 本年利润
  4. 将期间标记为 CLOSED，记录凭证 ID
  5. 创建下一个期间（OPEN）
"""
import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from models.accounting_period import AccountingPeriod, PeriodStatus
from models.voucher_header import VoucherHeader, VoucherReviewStatus
from models.voucher_line import VoucherLine
from models.operational_record import OperationalRecord, RecordStatus

logger = logging.getLogger(__name__)

# 损益类科目：结账时要归零的科目 (code_prefix, direction)
INCOME_ACCOUNTS  = [
    ("6001", "CREDIT"),   # 主营业务收入
    ("6051", "CREDIT"),   # 其他业务收入
    ("6101", "CREDIT"),   # 公允价值变动收益
    ("6111", "CREDIT"),   # 投资收益
    ("6117", "CREDIT"),   # 其他收益
    ("6301", "CREDIT"),   # 营业外收入
]
EXPENSE_ACCOUNTS = [
    ("6401", "DEBIT"),    # 主营业务成本
    ("6402", "DEBIT"),    # 其他业务成本
    ("6403", "DEBIT"),    # 税金及附加
    ("6601", "DEBIT"),    # 销售费用
    ("6602", "DEBIT"),    # 管理费用
    ("6603", "DEBIT"),    # 财务费用
    ("6604", "DEBIT"),    # 研发费用
    ("6701", "DEBIT"),    # 资产减值损失
    ("6711", "DEBIT"),    # 营业外支出
    ("6801", "DEBIT"),    # 所得税费用
]
RETAINED_EARNINGS_CODE = "4103"   # 本年利润


@dataclass
class ClosingResult:
    year:       int
    month:      int
    net_profit: Decimal
    voucher_id: int
    message:    str


class PeriodClosingError(Exception):
    pass


class PeriodClosingService:
    def __init__(self, db: Session) -> None:
        self._db = db

    # ── Public ─────────────────────────────────────────────────────────────────

    def get_or_create_period(self, year: int, month: int) -> AccountingPeriod:
        p = self._db.query(AccountingPeriod).filter_by(year=year, month=month).first()
        if not p:
            p = AccountingPeriod(year=year, month=month, status=PeriodStatus.OPEN)
            self._db.add(p)
            self._db.commit()
            self._db.refresh(p)
        return p

    def list_periods(self, limit: int = 24) -> list[AccountingPeriod]:
        return (
            self._db.query(AccountingPeriod)
            .order_by(AccountingPeriod.year.desc(), AccountingPeriod.month.desc())
            .limit(limit)
            .all()
        )

    def close_period(self, year: int, month: int, user_id: int) -> ClosingResult:
        """
        执行月末结账。
        幂等：若已 CLOSED 则直接返回已有结果。
        """
        period = self.get_or_create_period(year, month)

        if period.status == PeriodStatus.CLOSED:
            raise PeriodClosingError(f"{year}-{month:02d} 期间已结账，无法重复操作")

        # 期间日期范围
        date_from = date(year, month, 1)
        last_day  = self._last_day(year, month)

        # 计算各损益科目本期发生额
        income_total = sum(
            self._sum_period(prefix, direction, date_from, last_day)
            for prefix, direction in INCOME_ACCOUNTS
        )
        expense_total = sum(
            self._sum_period(prefix, direction, date_from, last_day)
            for prefix, direction in EXPENSE_ACCOUNTS
        )
        net_profit = income_total - expense_total

        if income_total == 0 and expense_total == 0:
            raise PeriodClosingError(f"{year}-{month:02d} 期间无损益数据，无需结账")

        # 生成一条"期末结账"流水记录
        closing_record = OperationalRecord(
            raw_text = f"[系统] {year}-{month:02d} 期末损益结转",
            status   = RecordStatus.PROCESSED,
        )
        self._db.add(closing_record)
        self._db.flush()

        # 生成损益结转凭证
        voucher = VoucherHeader(
            record_id     = closing_record.record_id,
            voucher_date  = last_day,
            total_amount  = income_total,
            memo          = f"{year}-{month:02d} 期末损益结转",
            review_status = VoucherReviewStatus.POSTED,  # 结账凭证直接入账
            reviewer_id   = user_id,
            reviewed_at   = datetime.now(timezone.utc),
        )
        self._db.add(voucher)
        self._db.flush()

        lines: list[VoucherLine] = []

        # 借：收入科目归零（反向冲销贷方余额）
        for prefix, _ in INCOME_ACCOUNTS:
            amt = self._sum_period(prefix, "CREDIT", date_from, last_day)
            if amt > 0:
                lines.append(VoucherLine(
                    voucher_id   = voucher.voucher_id,
                    subject_code = prefix,
                    direction    = "DEBIT",
                    amount       = amt,
                    memo         = "损益结转",
                ))

        # 贷：费用/成本科目归零（反向冲销借方余额）
        for prefix, _ in EXPENSE_ACCOUNTS:
            amt = self._sum_period(prefix, "DEBIT", date_from, last_day)
            if amt > 0:
                lines.append(VoucherLine(
                    voucher_id   = voucher.voucher_id,
                    subject_code = prefix,
                    direction    = "CREDIT",
                    amount       = amt,
                    memo         = "损益结转",
                ))

        # 净利润转入 4103 本年利润
        if net_profit > 0:
            lines.append(VoucherLine(
                voucher_id   = voucher.voucher_id,
                subject_code = RETAINED_EARNINGS_CODE,
                direction    = "CREDIT",
                amount       = net_profit,
                memo         = f"{year}-{month:02d} 净利润",
            ))
        elif net_profit < 0:
            lines.append(VoucherLine(
                voucher_id   = voucher.voucher_id,
                subject_code = RETAINED_EARNINGS_CODE,
                direction    = "DEBIT",
                amount       = abs(net_profit),
                memo         = f"{year}-{month:02d} 净亏损",
            ))

        for line in lines:
            self._db.add(line)

        # 标记期间为 CLOSED
        period.status            = PeriodStatus.CLOSED
        period.closed_at         = datetime.now(timezone.utc)
        period.closed_by         = user_id
        period.closing_voucher_id = voucher.voucher_id

        # 审计日志：期末结账
        from services.audit_guard import audit_period_closed
        period_str = f"{year}-{month:02d}"
        audit_period_closed(self._db, period_str)

        self._db.commit()

        # 自动创建下一个期间
        ny, nm = (year, month + 1) if month < 12 else (year + 1, 1)
        self.get_or_create_period(ny, nm)

        logger.info("Period closed: %d-%02d net_profit=%.2f voucher=%d",
                    year, month, net_profit, voucher.voucher_id)

        return ClosingResult(
            year       = year,
            month      = month,
            net_profit = net_profit,
            voucher_id = voucher.voucher_id,
            message    = f"{year}-{month:02d} 结账完成，净利润 ¥{net_profit:,.2f}",
        )

    # ── Internal ───────────────────────────────────────────────────────────────

    def _sum_period(self, code_prefix: str, direction: str,
                    date_from: date, date_to: date) -> Decimal:
        row = (
            self._db.query(func.sum(VoucherLine.amount))
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

    @staticmethod
    def _last_day(year: int, month: int) -> date:
        import calendar
        return date(year, month, calendar.monthrange(year, month)[1])
