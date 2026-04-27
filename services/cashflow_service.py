"""
AgentLedger — CashFlowService (会企03表，直接法)

直接法：经营活动的现金流量按收/支现金项目逐项列示。
投资/筹资活动：从相关科目发生额推算。

实现策略（近似法）：
  - 销售收到的现金 ≈ 主营/其他业务收入 + 预收款项变动 - 应收账款变动
  - 购买商品付的现金 ≈ 主营成本 + 存货增加 + 应付账款减少
  - 支付员工的现金 ≈ 管理/销售费用中的薪酬部分（应付职工薪酬变动修正）
  - 支付税款 ≈ 所得税费用 + 应交税费减少
  适用于小微企业，实务中可按现金收付标注细化。
"""
import logging
import calendar
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from models.voucher_line import VoucherLine
from models.voucher_header import VoucherHeader, VoucherReviewStatus
from models.asset_register import AssetRegister, AssetStatus

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


# ── 通用查询辅助 ─────────────────────────────────────────────────────────────

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
            VoucherHeader.review_status == VoucherReviewStatus.POSTED,
        )
        .scalar()
    )
    return Decimal(str(row or 0))


def _asset_bal(b: dict, *codes: str) -> Decimal:
    return sum((max(b.get(c, Decimal("0")), Decimal("0")) for c in codes), Decimal("0"))


def _liab_bal(b: dict, *codes: str) -> Decimal:
    return sum((max(-b.get(c, Decimal("0")), Decimal("0")) for c in codes), Decimal("0"))


# ── CashFlowService ──────────────────────────────────────────────────────────

class CashFlowService:
    def __init__(self, db: Session) -> None:
        self._db = db

    def get_cash_flow(self, date_from: date, date_to: date) -> CashFlowStatement:
        """
        直接法现金流量表（会企03表）。
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

        # 期末/期初余额（用于运营资本变动修正）
        end_bal  = _build_balances(self._db, date_to)
        beg_bal  = _build_balances(
            self._db,
            date(date_from.year - 1, 12, 31) if date_from.month == 1
            else date(date_from.year, date_from.month, 1),
        )
        pend_bal = _build_balances(self._db, prev_to)
        pbeg_bal = _build_balances(
            self._db,
            date(prev_from.year - 1, 12, 31) if prev_from.month == 1
            else date(prev_from.year, prev_from.month, 1),
        )

        def asset_dec(b_end, b_beg, *codes):
            """资产余额减少 = 现金流入（正）"""
            return _asset_bal(b_beg, *codes) - _asset_bal(b_end, *codes)

        def liab_inc(b_end, b_beg, *codes):
            """负债余额增加 = 现金流入（正）"""
            return _liab_bal(b_end, *codes) - _liab_bal(b_beg, *codes)

        # ── 一、经营活动产生的现金流量（直接法） ─────────────────────────────

        row("", "一、经营活动产生的现金流量：", Decimal("0"), Decimal("0"))

        # 1. 销售商品、提供劳务收到的现金
        #    ≈ 营业收入 + 应收账款减少 + 预收款/合同负债增加
        rev_c  = S("6001","CREDIT", date_from, date_to) + S("6051","CREDIT", date_from, date_to)
        rev_p  = S("6001","CREDIT", prev_from, prev_to) + S("6051","CREDIT", prev_from, prev_to)
        ar_dec_c = asset_dec(end_bal, beg_bal, "1122","1111")
        ar_dec_p = asset_dec(pend_bal, pbeg_bal, "1122","1111")
        adv_inc_c = liab_inc(end_bal, beg_bal, "2203","2205")
        adv_inc_p = liab_inc(pend_bal, pbeg_bal, "2203","2205")
        cash_recv_c = rev_c + ar_dec_c + adv_inc_c
        cash_recv_p = rev_p + ar_dec_p + adv_inc_p
        row("6001", "销售商品、提供劳务收到的现金",    cash_recv_c, cash_recv_p)

        # 2. 收到的税费返还（应交税费贷方发生额中VAT退税近似）
        tax_ref_c = S("2221","DEBIT", date_from, date_to)
        tax_ref_p = S("2221","DEBIT", prev_from, prev_to)
        row("2221", "收到的税费返还",                  Decimal("0"), Decimal("0"))

        # 3. 收到其他与经营活动有关的现金（营业外收入+其他收益）
        other_in_c = S("6301","CREDIT", date_from, date_to) + S("6117","CREDIT", date_from, date_to)
        other_in_p = S("6301","CREDIT", prev_from, prev_to) + S("6117","CREDIT", prev_from, prev_to)
        row("6301", "收到其他与经营活动有关的现金",    other_in_c, other_in_p)

        op_in_c = cash_recv_c + other_in_c
        op_in_p = cash_recv_p + other_in_p
        row("", "经营活动现金流入小计",                op_in_c, op_in_p, True)

        # 4. 购买商品、接受劳务支付的现金
        #    ≈ 主营业务成本 + 存货增加 - 应付账款增加
        cogs_c   = S("6401","DEBIT", date_from, date_to) + S("6402","DEBIT", date_from, date_to)
        cogs_p   = S("6401","DEBIT", prev_from, prev_to) + S("6402","DEBIT", prev_from, prev_to)
        inv_inc_c  = _asset_bal(end_bal,"1401","1402","1403","1405") - _asset_bal(beg_bal,"1401","1402","1403","1405")
        inv_inc_p  = _asset_bal(pend_bal,"1401","1402","1403","1405") - _asset_bal(pbeg_bal,"1401","1402","1403","1405")
        ap_inc_c   = liab_inc(end_bal, beg_bal, "2202","2201")
        ap_inc_p   = liab_inc(pend_bal, pbeg_bal, "2202","2201")
        cash_goods_c = max(cogs_c + inv_inc_c - ap_inc_c, Decimal("0"))
        cash_goods_p = max(cogs_p + inv_inc_p - ap_inc_p, Decimal("0"))
        row("6401", "购买商品、接受劳务支付的现金",    -cash_goods_c, -cash_goods_p)

        # 5. 支付给职工以及为职工支付的现金
        #    ≈ 6602管理费用中的薪酬部分，用应付职工薪酬变动修正
        #    简化：6602借方 + 6601借方中的销售薪酬，减应付职工薪酬增加
        sal_exp_c = S("6602","DEBIT", date_from, date_to) * Decimal("0.4")  # 估算40%为薪酬
        sal_exp_p = S("6602","DEBIT", prev_from, prev_to) * Decimal("0.4")
        sal_liab_inc_c = liab_inc(end_bal, beg_bal, "2211")
        sal_liab_inc_p = liab_inc(pend_bal, pbeg_bal, "2211")
        cash_sal_c = max(sal_exp_c - sal_liab_inc_c, Decimal("0"))
        cash_sal_p = max(sal_exp_p - sal_liab_inc_p, Decimal("0"))
        row("2211", "支付给职工以及为职工支付的现金",  -cash_sal_c, -cash_sal_p)

        # 6. 支付的各项税费
        #    ≈ 所得税费用 + 税金及附加 + 应交税费减少
        tax_exp_c  = S("6801","DEBIT", date_from, date_to) + S("6403","DEBIT", date_from, date_to)
        tax_exp_p  = S("6801","DEBIT", prev_from, prev_to) + S("6403","DEBIT", prev_from, prev_to)
        tax_liab_dec_c = -liab_inc(end_bal, beg_bal, "2221")   # 负值表示减少（现金流出）
        tax_liab_dec_p = -liab_inc(pend_bal, pbeg_bal, "2221")
        cash_tax_c = max(tax_exp_c + tax_liab_dec_c, Decimal("0"))
        cash_tax_p = max(tax_exp_p + tax_liab_dec_p, Decimal("0"))
        row("6801", "支付的各项税费",                  -cash_tax_c, -cash_tax_p)

        # 7. 支付其他与经营活动有关的现金（销售+财务+其余管理费用）
        other_op_c = (S("6601","DEBIT", date_from, date_to)
                      + S("6603","DEBIT", date_from, date_to)
                      + S("6604","DEBIT", date_from, date_to)
                      + S("6711","DEBIT", date_from, date_to)
                      + S("6602","DEBIT", date_from, date_to) * Decimal("0.6"))
        other_op_p = (S("6601","DEBIT", prev_from, prev_to)
                      + S("6603","DEBIT", prev_from, prev_to)
                      + S("6604","DEBIT", prev_from, prev_to)
                      + S("6711","DEBIT", prev_from, prev_to)
                      + S("6602","DEBIT", prev_from, prev_to) * Decimal("0.6"))
        row("6601", "支付其他与经营活动有关的现金",    -other_op_c, -other_op_p)

        op_out_c = cash_goods_c + cash_sal_c + cash_tax_c + other_op_c
        op_out_p = cash_goods_p + cash_sal_p + cash_tax_p + other_op_p
        row("", "经营活动现金流出小计",                -op_out_c, -op_out_p, True)

        op_cf_c = op_in_c - op_out_c
        op_cf_p = op_in_p - op_out_p
        row("", "一、经营活动产生的现金流量净额",      op_cf_c, op_cf_p, True)

        # ── 二、投资活动产生的现金流量 ────────────────────────────────────────

        row("", "二、投资活动产生的现金流量：", Decimal("0"), Decimal("0"))

        # 处置固定资产收到的现金（1601贷方 + 1603借方发生额）
        fa_disp_c = S("1603","DEBIT", date_from, date_to)
        fa_disp_p = S("1603","DEBIT", prev_from, prev_to)
        row("1603", "处置固定资产、无形资产收到的现金净额", fa_disp_c, fa_disp_p)

        # 收到投资收益
        inv_income_c = S("6111","CREDIT", date_from, date_to)
        inv_income_p = S("6111","CREDIT", prev_from, prev_to)
        row("6111", "收到的投资收益",                  inv_income_c, inv_income_p)

        inv_in_c = fa_disp_c + inv_income_c
        inv_in_p = fa_disp_p + inv_income_p
        row("", "投资活动现金流入小计",                inv_in_c, inv_in_p, True)

        # 购建固定资产、无形资产支付的现金
        fa_buy_c = S("1601","DEBIT", date_from, date_to) + S("1701","DEBIT", date_from, date_to)
        fa_buy_p = S("1601","DEBIT", prev_from, prev_to) + S("1701","DEBIT", prev_from, prev_to)
        row("1601", "购建固定资产、无形资产支付的现金", -fa_buy_c, -fa_buy_p)

        # 对外投资支付的现金
        equity_inv_c = S("1501","DEBIT", date_from, date_to)
        equity_inv_p = S("1501","DEBIT", prev_from, prev_to)
        row("1501", "对外投资支付的现金",               -equity_inv_c, -equity_inv_p)

        inv_out_c = fa_buy_c + equity_inv_c
        inv_out_p = fa_buy_p + equity_inv_p
        row("", "投资活动现金流出小计",                -inv_out_c, -inv_out_p, True)

        inv_cf_c = inv_in_c - inv_out_c
        inv_cf_p = inv_in_p - inv_out_p
        row("", "二、投资活动产生的现金流量净额",      inv_cf_c, inv_cf_p, True)

        # ── 三、筹资活动产生的现金流量 ────────────────────────────────────────

        row("", "三、筹资活动产生的现金流量：", Decimal("0"), Decimal("0"))

        # 吸收投资收到的现金（实收资本增加）
        equity_in_c = S("4001","CREDIT", date_from, date_to) + S("3001","CREDIT", date_from, date_to)
        equity_in_p = S("4001","CREDIT", prev_from, prev_to) + S("3001","CREDIT", prev_from, prev_to)
        row("4001", "吸收投资收到的现金",               equity_in_c, equity_in_p)

        # 借款收到的现金
        borrow_c = S("2001","CREDIT", date_from, date_to) + S("2501","CREDIT", date_from, date_to)
        borrow_p = S("2001","CREDIT", prev_from, prev_to) + S("2501","CREDIT", prev_from, prev_to)
        row("2001", "借款收到的现金",                   borrow_c, borrow_p)

        fin_in_c = equity_in_c + borrow_c
        fin_in_p = equity_in_p + borrow_p
        row("", "筹资活动现金流入小计",                fin_in_c, fin_in_p, True)

        # 偿还债务支付的现金
        repay_c = S("2001","DEBIT", date_from, date_to) + S("2501","DEBIT", date_from, date_to)
        repay_p = S("2001","DEBIT", prev_from, prev_to) + S("2501","DEBIT", prev_from, prev_to)
        row("", "偿还债务支付的现金",                   -repay_c, -repay_p)

        # 分配股利、利润或偿付利息支付的现金
        div_c = S("4104","DEBIT", date_from, date_to) + S("2232","DEBIT", date_from, date_to)
        div_p = S("4104","DEBIT", prev_from, prev_to) + S("2232","DEBIT", prev_from, prev_to)
        row("4104", "分配股利、利润或偿付利息支付的现金", -div_c, -div_p)

        fin_out_c = repay_c + div_c
        fin_out_p = repay_p + div_p
        row("", "筹资活动现金流出小计",                -fin_out_c, -fin_out_p, True)

        fin_cf_c = fin_in_c - fin_out_c
        fin_cf_p = fin_in_p - fin_out_p
        row("", "三、筹资活动产生的现金流量净额",      fin_cf_c, fin_cf_p, True)

        # ── 四、现金及现金等价物净增加额 ─────────────────────────────────────

        net_c = op_cf_c + inv_cf_c + fin_cf_c
        net_p = op_cf_p + inv_cf_p + fin_cf_p
        row("", "四、现金及现金等价物净增加额",         net_c, net_p, True)

        cash_beg_c = _asset_bal(beg_bal, "1001","1002","1012")
        cash_beg_p = _asset_bal(pbeg_bal, "1001","1002","1012")
        row("", "加：期初现金及现金等价物余额",         cash_beg_c, cash_beg_p)

        cash_end_c = _asset_bal(end_bal, "1001","1002","1012")
        cash_end_p = _asset_bal(pend_bal, "1001","1002","1012")
        row("", "五、期末现金及现金等价物余额",         cash_end_c, cash_end_p, True)

        return cf
