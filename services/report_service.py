"""
AgentLedger — ReportService (Phase 4)

生成三大财务报表：
  - 资产负债表 (Balance Sheet)
  - 利润表     (Income Statement)

科目映射约定（中国小企业会计准则）：
  资产   = 1xxx 借方余额
  负债   = 2xxx 贷方余额
  权益   = 4xxx 贷方余额（含3xxx 实收资本等）
  收入   = 6001, 6051 贷方
  成本   = 6401 借方
  期间费用 = 6602(管理), 6603(财务), 6711(销售) 借方
  税费   = 6801 借方
"""
import logging
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from models.voucher_line import VoucherLine
from models.voucher_header import VoucherHeader

logger = logging.getLogger(__name__)


@dataclass
class LineItem:
    code:   str
    name:   str
    amount: Decimal


@dataclass
class BalanceSheet:
    as_of_date: str
    # 资产
    current_assets:     list[LineItem] = field(default_factory=list)
    non_current_assets: list[LineItem] = field(default_factory=list)
    total_assets:       Decimal = Decimal("0")
    # 负债
    current_liabilities:     list[LineItem] = field(default_factory=list)
    non_current_liabilities: list[LineItem] = field(default_factory=list)
    total_liabilities:       Decimal = Decimal("0")
    # 权益
    equity_items:  list[LineItem] = field(default_factory=list)
    total_equity:  Decimal = Decimal("0")
    # 平衡校验
    balanced: bool = True
    diff:     Decimal = Decimal("0")


@dataclass
class IncomeStatement:
    date_from: str
    date_to:   str
    revenue:            Decimal = Decimal("0")
    other_revenue:      Decimal = Decimal("0")
    total_revenue:      Decimal = Decimal("0")
    cogs:               Decimal = Decimal("0")
    gross_profit:       Decimal = Decimal("0")
    admin_expense:      Decimal = Decimal("0")
    finance_expense:    Decimal = Decimal("0")
    selling_expense:    Decimal = Decimal("0")
    total_opex:         Decimal = Decimal("0")
    operating_profit:   Decimal = Decimal("0")
    tax_expense:        Decimal = Decimal("0")
    net_profit:         Decimal = Decimal("0")


class ReportService:
    def __init__(self, db: Session) -> None:
        self._db = db

    # ── Balance Sheet ──────────────────────────────────────────────────────────

    def get_balance_sheet(self, as_of: date) -> BalanceSheet:
        """
        生成截至 as_of 日期的资产负债表。
        逻辑：累计所有凭证明细，按科目前缀分组计算净余额。
        """
        bs = BalanceSheet(as_of_date=str(as_of))

        # 所有凭证明细（截至日期）
        rows = (
            self._db.query(
                VoucherLine.subject_code,
                VoucherLine.direction,
                func.sum(VoucherLine.amount).label("total"),
            )
            .join(VoucherHeader, VoucherLine.voucher_id == VoucherHeader.voucher_id)
            .filter(VoucherHeader.voucher_date <= as_of)
            .group_by(VoucherLine.subject_code, VoucherLine.direction)
            .all()
        )

        # 按科目聚合：debit - credit
        balances: dict[str, Decimal] = {}
        for code, direction, total in rows:
            val = Decimal(str(total))
            balances[code] = balances.get(code, Decimal("0")) + (
                val if direction == "DEBIT" else -val
            )

        # 科目名称映射（尽量覆盖常用科目）
        NAMES = {
            "1001": "库存现金",    "1002": "银行存款",    "1012": "其他货币资金",
            "1101": "短期投资",    "1122": "应收账款",    "1123": "预付账款",
            "1131": "应收股利",    "1221": "其他应收款",  "1401": "原材料",
            "1405": "库存商品",    "1601": "固定资产",    "1602": "累计折旧",
            "1604": "在建工程",    "1701": "长期待摊费用",
            "2001": "短期借款",    "2202": "应付账款",    "2211": "应付职工薪酬",
            "2221": "应交税费",    "2231": "其他应付款",  "2501": "长期借款",
            "4001": "实收资本",    "4002": "资本公积",    "4101": "盈余公积",
            "4103": "本年利润",    "4104": "利润分配",
        }

        def name(code: str) -> str:
            return NAMES.get(code, code)

        # 分类
        for code, bal in sorted(balances.items()):
            if abs(bal) < Decimal("0.01"):
                continue
            item = LineItem(code=code, name=name(code), amount=abs(bal))

            if code.startswith("1"):
                # 资产类：借方余额为正
                if code in ("1602",):   # 累计折旧是资产抵减项，贷方余额
                    item.amount = -bal if bal < 0 else bal
                if code[:2] in ("10", "11", "12", "14"):
                    bs.current_assets.append(item)
                else:
                    bs.non_current_assets.append(item)

            elif code.startswith("2"):
                # 负债类：贷方余额为正 → bal 为负
                item.amount = abs(bal)
                bs.current_liabilities.append(item)

            elif code.startswith(("4", "3")):
                # 权益类：贷方余额 → bal 为负
                item.amount = abs(bal)
                bs.equity_items.append(item)

        bs.total_assets     = sum((i.amount for i in bs.current_assets + bs.non_current_assets), Decimal("0"))
        bs.total_liabilities = sum((i.amount for i in bs.current_liabilities + bs.non_current_liabilities), Decimal("0"))
        bs.total_equity      = sum((i.amount for i in bs.equity_items), Decimal("0"))

        bs.diff     = bs.total_assets - (bs.total_liabilities + bs.total_equity)
        bs.balanced = abs(bs.diff) < Decimal("1.00")

        return bs

    # ── Income Statement ───────────────────────────────────────────────────────

    def get_income_statement(self, date_from: date, date_to: date) -> IncomeStatement:
        """
        生成指定区间的利润表。
        """
        is_ = IncomeStatement(date_from=str(date_from), date_to=str(date_to))

        def _sum(code_prefix: str, direction: str) -> Decimal:
            row = (
                self._db.query(func.sum(VoucherLine.amount))
                .join(VoucherHeader, VoucherLine.voucher_id == VoucherHeader.voucher_id)
                .filter(
                    VoucherLine.subject_code.like(f"{code_prefix}%"),
                    VoucherLine.direction == direction,
                    VoucherHeader.voucher_date >= date_from,
                    VoucherHeader.voucher_date <= date_to,
                )
                .scalar()
            )
            return Decimal(str(row or 0))

        is_.revenue         = _sum("6001", "CREDIT")
        is_.other_revenue   = _sum("6051", "CREDIT")
        is_.total_revenue   = is_.revenue + is_.other_revenue

        is_.cogs            = _sum("6401", "DEBIT")
        is_.gross_profit    = is_.total_revenue - is_.cogs

        is_.admin_expense   = _sum("6602", "DEBIT")
        is_.finance_expense = _sum("6603", "DEBIT")
        is_.selling_expense = _sum("6711", "DEBIT")
        is_.total_opex      = is_.admin_expense + is_.finance_expense + is_.selling_expense

        is_.operating_profit = is_.gross_profit - is_.total_opex
        is_.tax_expense      = _sum("6801", "DEBIT")
        is_.net_profit       = is_.operating_profit - is_.tax_expense

        return is_
