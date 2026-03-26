"""
AgentLedger — CashFlowService (Phase 4)

现金流量表（会企03表，间接法）

间接法：从净利润出发，调整非现金项目，得出经营活动现金流量。
投资/筹资活动：直接从相关科目变动推算。

注意：完整的现金流量表需要辅助现金科目标记，此处采用近似估算法，
      通过期末/期初余额变动推算各类现金流量，适用于小微企业报表。
"""
import logging
import calendar
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from models.voucher_line import VoucherLine
from models.voucher_header import VoucherHeader

logger = logging.getLogger(__name__)


@dataclass
class CFLineItem:
    code:     str
    name:     str
    cur_amt:  Decimal
    prev_amt: Decimal
    is_total: bool = False


@dataclass
class CashFlowStatement:
    date_from:    str
    date_to:      str
    prev_from:    str
    prev_to:      str
    items:        list[CFLineItem] = field(default_factory=list)


def _build_balances(db: Session, as_of: date) -> dict[str, Decimal]:
    rows = (
        db.query(
            VoucherLine.subject_code,
            VoucherLine.direction,
            func.sum(VoucherLine.amount).label("total"),
        )
        .join(VoucherHeader, VoucherLine.voucher_id == VoucherHeader.voucher_id)
        .filter(VoucherHeader.voucher_date <= as_of)
        .group_by(VoucherLine.subject_code, VoucherLine.direction)
        .all()
    )
    balances: dict[str, Decimal] = {}
    for code, direction, total in rows:
        val = Decimal(str(total))
        balances[code] = balances.get(code, Decimal("0")) + (
            val if direction == "DEBIT" else -val
        )
    return balances


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
        )
        .scalar()
    )
    return Decimal(str(row or 0))


def _asset_bal(b: dict, *codes: str) -> Decimal:
    return sum((max(b.get(c, Decimal("0")), Decimal("0")) for c in codes), Decimal("0"))


def _liab_bal(b: dict, *codes: str) -> Decimal:
    return sum((max(-b.get(c, Decimal("0")), Decimal("0")) for c in codes), Decimal("0"))


class CashFlowService:
    def __init__(self, db: Session) -> None:
        self._db = db

    def get_cash_flow(self, date_from: date, date_to: date) -> CashFlowStatement:
        """
        间接法现金流量表（会企03表）。
        上期 = 上年同期。
        """
        prev_from = date(date_from.year - 1, date_from.month, date_from.day)
        last_day  = calendar.monthrange(date_to.year - 1, date_to.month)[1]
        prev_to   = date(date_to.year - 1, date_to.month, min(date_to.day, last_day))

        cf = CashFlowStatement(
            date_from = str(date_from),
            date_to   = str(date_to),
            prev_from = str(prev_from),
            prev_to   = str(prev_to),
        )

        def S(prefix, direction, df, dt):
            return _sum_period(self._db, prefix, direction, df, dt)

        def row(code, name, cur, prev, is_total=False):
            cf.items.append(CFLineItem(
                code=code, name=name,
                cur_amt=cur, prev_amt=prev,
                is_total=is_total,
            ))

        # ── 一、经营活动产生的现金流量（间接法） ─────────────────────────

        # 净利润（本期）
        rev_c  = S("6001","CREDIT", date_from, date_to) + S("6051","CREDIT", date_from, date_to)
        exp_c  = (S("6401","DEBIT", date_from, date_to)
                  + S("6403","DEBIT", date_from, date_to)
                  + S("6601","DEBIT", date_from, date_to)
                  + S("6602","DEBIT", date_from, date_to)
                  + S("6603","DEBIT", date_from, date_to)
                  + S("6604","DEBIT", date_from, date_to)
                  + S("6711","DEBIT", date_from, date_to)
                  + S("6801","DEBIT", date_from, date_to))
        ebt_c  = rev_c - exp_c + S("6301","CREDIT", date_from, date_to)
        np_c   = ebt_c - S("6801","DEBIT", date_from, date_to)

        rev_p  = S("6001","CREDIT", prev_from, prev_to) + S("6051","CREDIT", prev_from, prev_to)
        exp_p  = (S("6401","DEBIT", prev_from, prev_to)
                  + S("6403","DEBIT", prev_from, prev_to)
                  + S("6601","DEBIT", prev_from, prev_to)
                  + S("6602","DEBIT", prev_from, prev_to)
                  + S("6603","DEBIT", prev_from, prev_to)
                  + S("6604","DEBIT", prev_from, prev_to)
                  + S("6711","DEBIT", prev_from, prev_to)
                  + S("6801","DEBIT", prev_from, prev_to))
        ebt_p  = rev_p - exp_p + S("6301","CREDIT", prev_from, prev_to)
        np_p   = ebt_p - S("6801","DEBIT", prev_from, prev_to)

        row("NP", "净利润", np_c, np_p)

        # 调整项：计算期末/期初余额变动
        end_bal  = _build_balances(self._db, date_to)
        beg_bal  = _build_balances(self._db, date(date_from.year, date_from.month, date_from.day)
                                   if date_from.month > 1
                                   else date(date_from.year - 1, 12, 31))
        pend_bal = _build_balances(self._db, prev_to)
        pbeg_bal = _build_balances(self._db, date(prev_from.year, prev_from.month, prev_from.day)
                                   if prev_from.month > 1
                                   else date(prev_from.year - 1, 12, 31))

        def asset_chg(b_end, b_beg, *codes):
            """资产增加为现金流出（负），减少为流入（正）"""
            return (_asset_bal(b_beg, *codes) - _asset_bal(b_end, *codes))

        def liab_chg(b_end, b_beg, *codes):
            """负债增加为现金流入（正），减少为流出（负）"""
            return (_liab_bal(b_end, *codes) - _liab_bal(b_beg, *codes))

        # 固定资产折旧、无形资产摊销（费用科目中的非现金部分简化为管理费用20%估算）
        # 实际应从资产折旧模块取数；此处用折旧凭证行直接取
        depr_c = S("6602","DEBIT", date_from, date_to) * Decimal("0.3")  # 粗估折旧占管理费用30%
        depr_p = S("6602","DEBIT", prev_from, prev_to) * Decimal("0.3")
        row("DEPR", "加：资产折旧及摊销", depr_c, depr_p)

        # 应收账款减少（增加）
        ar_chg_c = asset_chg(end_bal, beg_bal, "1122", "1111")
        ar_chg_p = asset_chg(pend_bal, pbeg_bal, "1122", "1111")
        row("AR", "应收账款（增加）/减少", ar_chg_c, ar_chg_p)

        # 存货减少（增加）
        inv_chg_c = asset_chg(end_bal, beg_bal, "1401","1402","1403","1405")
        inv_chg_p = asset_chg(pend_bal, pbeg_bal, "1401","1402","1403","1405")
        row("INV", "存货（增加）/减少", inv_chg_c, inv_chg_p)

        # 应付账款增加（减少）
        ap_chg_c = liab_chg(end_bal, beg_bal, "2202", "2201")
        ap_chg_p = liab_chg(pend_bal, pbeg_bal, "2202", "2201")
        row("AP", "应付账款增加/（减少）", ap_chg_c, ap_chg_p)

        # 应付职工薪酬增加（减少）
        sal_chg_c = liab_chg(end_bal, beg_bal, "2211")
        sal_chg_p = liab_chg(pend_bal, pbeg_bal, "2211")
        row("SAL", "应付职工薪酬增加/（减少）", sal_chg_c, sal_chg_p)

        # 应交税费增加（减少）
        tax_chg_c = liab_chg(end_bal, beg_bal, "2221")
        tax_chg_p = liab_chg(pend_bal, pbeg_bal, "2221")
        row("TAX", "应交税费增加/（减少）", tax_chg_c, tax_chg_p)

        op_cf_c = np_c + depr_c + ar_chg_c + inv_chg_c + ap_chg_c + sal_chg_c + tax_chg_c
        op_cf_p = np_p + depr_p + ar_chg_p + inv_chg_p + ap_chg_p + sal_chg_p + tax_chg_p
        row("", "一、经营活动产生的现金流量净额", op_cf_c, op_cf_p, True)

        # ── 二、投资活动 ────────────────────────────────────────────────────

        # 购建固定资产（1601借方发生额）
        fa_buy_c = S("1601","DEBIT", date_from, date_to)
        fa_buy_p = S("1601","DEBIT", prev_from, prev_to)
        row("FA_BUY", "减：购建固定资产、无形资产", -fa_buy_c, -fa_buy_p)

        # 处置固定资产（1601贷方发生额 → 收入）
        fa_sell_c = S("1601","CREDIT", date_from, date_to)
        fa_sell_p = S("1601","CREDIT", prev_from, prev_to)
        row("FA_SELL", "收回处置固定资产净额", fa_sell_c, fa_sell_p)

        inv_cf_c = -fa_buy_c + fa_sell_c
        inv_cf_p = -fa_buy_p + fa_sell_p
        row("", "二、投资活动产生的现金流量净额", inv_cf_c, inv_cf_p, True)

        # ── 三、筹资活动 ────────────────────────────────────────────────────

        # 借款收到
        borrow_c = S("2001","CREDIT", date_from, date_to) + S("2501","CREDIT", date_from, date_to)
        borrow_p = S("2001","CREDIT", prev_from, prev_to) + S("2501","CREDIT", prev_from, prev_to)
        row("BORROW", "借款收到的现金", borrow_c, borrow_p)

        # 偿还借款
        repay_c = S("2001","DEBIT",  date_from, date_to) + S("2501","DEBIT",  date_from, date_to)
        repay_p = S("2001","DEBIT",  prev_from, prev_to) + S("2501","DEBIT",  prev_from, prev_to)
        row("REPAY", "偿还债务支付的现金", -repay_c, -repay_p)

        fin_cf_c = borrow_c - repay_c
        fin_cf_p = borrow_p - repay_p
        row("", "三、筹资活动产生的现金流量净额", fin_cf_c, fin_cf_p, True)

        # ── 四、现金及现金等价物净增加 ──────────────────────────────────────

        net_c = op_cf_c + inv_cf_c + fin_cf_c
        net_p = op_cf_p + inv_cf_p + fin_cf_p
        row("", "四、现金及现金等价物净增加额", net_c, net_p, True)

        # 期初现金余额
        cash_beg_c = _asset_bal(beg_bal, "1001","1002","1012")
        cash_beg_p = _asset_bal(pbeg_bal, "1001","1002","1012")
        row("CASH_BEG", "加：期初现金及现金等价物余额", cash_beg_c, cash_beg_p)

        # 期末现金余额
        cash_end_c = _asset_bal(end_bal, "1001","1002","1012")
        cash_end_p = _asset_bal(pend_bal, "1001","1002","1012")
        row("CASH_END", "五、期末现金及现金等价物余额", cash_end_c, cash_end_p, True)

        return cf
