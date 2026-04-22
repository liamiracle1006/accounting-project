"""
AgentLedger — ReportService (Phase 4, Official Format)

生成官方格式财务报表：
  - 资产负债表 (会企01表): 期末余额 + 期初余额
  - 利润表     (会企02表): 本期金额 + 上期金额

科目余额计算规则（中国企业会计准则）：
  借方科目余额 = Σ DEBIT - Σ CREDIT
  贷方科目余额 = Σ CREDIT - Σ DEBIT
"""
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from models.voucher_line import VoucherLine
from models.voucher_header import VoucherHeader, VoucherReviewStatus

logger = logging.getLogger(__name__)


@dataclass
class BSLineItem:
    """资产负债表行项目"""
    code:      str            # 科目代码（空字符串 = 合计行）
    name:      str            # 行项目名称
    end_bal:   Decimal        # 期末余额
    beg_bal:   Decimal        # 期初余额
    is_total:  bool = False   # 是否为合计行


@dataclass
class ISLineItem:
    """利润表行项目"""
    code:      str
    name:      str
    cur_amt:   Decimal        # 本期金额
    prev_amt:  Decimal        # 上期金额
    is_total:  bool = False


@dataclass
class BalanceSheet:
    as_of_date:    str
    beg_of_year:   str        # 期初日期（年初）
    assets:        list[BSLineItem] = field(default_factory=list)
    liabilities:   list[BSLineItem] = field(default_factory=list)
    equity:        list[BSLineItem] = field(default_factory=list)
    balanced:      bool = True
    diff:          Decimal = Decimal("0")


@dataclass
class IncomeStatement:
    date_from:  str
    date_to:    str
    prev_from:  str
    prev_to:    str
    items:      list[ISLineItem] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 科目余额计算辅助
# ---------------------------------------------------------------------------

def _build_balances(db: Session, as_of: date) -> dict[str, Decimal]:
    """
    计算截至 as_of 日期各科目累计余额。
    余额 = Σ DEBIT - Σ CREDIT （正=借方余额，负=贷方余额）
    """
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


def _asset_bal(balances: dict, *codes: str) -> Decimal:
    """资产借方余额合计（正值）"""
    return sum((max(balances.get(c, Decimal("0")), Decimal("0")) for c in codes), Decimal("0"))


def _liab_bal(balances: dict, *codes: str) -> Decimal:
    """负债/权益贷方余额合计（取绝对值，贷方余额为负）"""
    return sum((max(-balances.get(c, Decimal("0")), Decimal("0")) for c in codes), Decimal("0"))


def _net_asset(balances: dict, debit_code: str, credit_code: str) -> Decimal:
    """净值 = 原值(借方) - 累计抵减(贷方余额取正)"""
    gross = max(balances.get(debit_code, Decimal("0")), Decimal("0"))
    contra = max(-balances.get(credit_code, Decimal("0")), Decimal("0"))
    return gross - contra


# ---------------------------------------------------------------------------
# 纯映射函数（不依赖 DB，可复用于外部数据源如 Excel 导入验证）
# ---------------------------------------------------------------------------

def _map_balance_sheet(
    end_bal: dict[str, Decimal],
    beg_bal: dict[str, Decimal],
    as_of_str: str,
    beg_of_year_str: str,
) -> BalanceSheet:
    """
    将预算好的余额字典映射为官方格式资产负债表。
    端口说明：end_bal/beg_bal 格式 = {科目代码: Decimal}
              正值 = 借方余额，负值 = 贷方余额（与 _build_balances 输出相同）
    """
    def E(*codes): return _asset_bal(end_bal, *codes)
    def B(*codes): return _asset_bal(beg_bal, *codes)
    def EL(*codes): return _liab_bal(end_bal, *codes)
    def BL(*codes): return _liab_bal(beg_bal, *codes)

    bs = BalanceSheet(as_of_date=as_of_str, beg_of_year=beg_of_year_str)

    # ── 资产方 ──────────────────────────────────────────────────────────
    def a(code, name, e, b):
        bs.assets.append(BSLineItem(code=code, name=name, end_bal=e, beg_bal=b))

    def atotal(name, e, b):
        bs.assets.append(BSLineItem(code="", name=name, end_bal=e, beg_bal=b, is_total=True))

    # 流动资产
    a("1001+1002+1012", "货币资金",
      E("1001","1002","1012"), B("1001","1002","1012"))
    a("1101", "交易性金融资产",          E("1101"),  B("1101"))
    a("1111", "应收票据",                E("1111"),  B("1111"))
    a("1122", "应收账款",                E("1122"),  B("1122"))
    a("1123", "预付款项",                E("1123"),  B("1123"))
    a("1221", "其他应收款",
      E("1121","1221"), B("1121","1221"))
    a("1401+", "存货",
      E("1401","1402","1403","1405","1406","1408"),
      B("1401","1402","1403","1405","1406","1408"))

    ca_end = sum(i.end_bal for i in bs.assets)
    ca_beg = sum(i.beg_bal for i in bs.assets)
    atotal("流动资产合计", ca_end, ca_beg)

    # 非流动资产
    a("1501", "长期股权投资",            E("1501"),  B("1501"))
    a("1502", "投资性房地产",            E("1502"),  B("1502"))

    fa_end = _net_asset(end_bal, "1601", "1602")
    fa_beg = _net_asset(beg_bal, "1601", "1602")
    a("1601", "固定资产",                fa_end, fa_beg)
    a("1604", "在建工程",                E("1604"), B("1604"))

    ia_end = E("1701") - EL("1703") - EL("1704")
    ia_beg = B("1701") - BL("1703") - BL("1704")
    a("1701", "无形资产",                ia_end,  ia_beg)
    a("1702", "开发支出",                E("1702"),  B("1702"))
    a("1801", "长期待摊费用",            E("1801"),  B("1801"))
    a("1811", "递延所得税资产",          E("1811"),  B("1811"))

    nca_end = (E("1501") + E("1502") + fa_end + E("1604")
               + ia_end + E("1702") + E("1801") + E("1811"))
    nca_beg = (B("1501") + B("1502") + fa_beg + B("1604")
               + ia_beg + B("1702") + B("1801") + B("1811"))
    atotal("非流动资产合计", nca_end, nca_beg)

    ta_end = ca_end + nca_end
    ta_beg = ca_beg + nca_beg
    atotal("资产总计", ta_end, ta_beg)

    # ── 负债和所有者权益方 ──────────────────────────────────────────────
    def l(code, name, e, b):
        bs.liabilities.append(BSLineItem(code=code, name=name, end_bal=e, beg_bal=b))

    def ltotal(name, e, b):
        bs.liabilities.append(BSLineItem(code="", name=name, end_bal=e, beg_bal=b, is_total=True))

    # 流动负债
    l("2001", "短期借款",               EL("2001"), BL("2001"))
    l("2201", "应付票据",               EL("2201"), BL("2201"))
    l("2202", "应付账款",               EL("2202"), BL("2202"))
    l("2203", "预收款项",               EL("2203"), BL("2203"))
    l("2205", "合同负债",               EL("2205"), BL("2205"))
    l("2211", "应付职工薪酬",           EL("2211"), BL("2211"))
    l("2221", "应交税费",               EL("2221"), BL("2221"))
    l("2231", "应付利息",               EL("2231"), BL("2231"))
    l("2232", "应付股利",               EL("2232"), BL("2232"))
    l("2241", "其他应付款",             EL("2241"), BL("2241"))

    cl_end = sum(i.end_bal for i in bs.liabilities)
    cl_beg = sum(i.beg_bal for i in bs.liabilities)
    ltotal("流动负债合计", cl_end, cl_beg)

    # 非流动负债
    l("2501", "长期借款",               EL("2501"), BL("2501"))
    l("2502", "应付债券",               EL("2502"), BL("2502"))
    l("2511", "长期应付款",             EL("2511"), BL("2511"))
    l("2601", "预计负债",               EL("2601"), BL("2601"))
    l("2401", "递延收益",               EL("2401"), BL("2401"))
    l("2441", "递延所得税负债",         EL("2441"), BL("2441"))

    ncl_end = (EL("2501") + EL("2502") + EL("2511")
               + EL("2601") + EL("2401") + EL("2441"))
    ncl_beg = (BL("2501") + BL("2502") + BL("2511")
               + BL("2601") + BL("2401") + BL("2441"))
    ltotal("非流动负债合计", ncl_end, ncl_beg)

    tl_end = cl_end + ncl_end
    tl_beg = cl_beg + ncl_beg
    ltotal("负债合计", tl_end, tl_beg)

    # 所有者权益
    def e(code, name, end, beg):
        bs.equity.append(BSLineItem(code=code, name=name, end_bal=end, beg_bal=beg))

    def etotal(name, end, beg):
        bs.equity.append(BSLineItem(code="", name=name, end_bal=end, beg_bal=beg, is_total=True))

    e("4001", "实收资本（股本）",       EL("4001","3001"), BL("4001","3001"))
    e("4002", "资本公积",               EL("4002"), BL("4002"))
    e("4005", "其他综合收益",           EL("4005"), BL("4005"))
    e("4101", "盈余公积",               EL("4101"), BL("4101"))

    unclosed_pl_end = -sum(
        v for k, v in end_bal.items() if "6001" <= k <= "6899"
    )
    unclosed_pl_beg = -sum(
        v for k, v in beg_bal.items() if "6001" <= k <= "6899"
    )
    e("4103", "未分配利润",
      EL("4103","4104") + unclosed_pl_end,
      BL("4103","4104") + unclosed_pl_beg)

    te_end = sum(i.end_bal for i in bs.equity)
    te_beg = sum(i.beg_bal for i in bs.equity)
    etotal("所有者权益合计", te_end, te_beg)

    tl_e_end = tl_end + te_end
    tl_e_beg = tl_beg + te_beg
    etotal("负债和所有者权益总计", tl_e_end, tl_e_beg)

    bs.diff     = ta_end - tl_e_end
    bs.balanced = abs(bs.diff) < Decimal("1.00")

    return bs


def _map_income_statement(
    cur_fn: Callable[[str, str], Decimal],
    prev_fn: Callable[[str, str], Decimal],
    date_from_str: str,
    date_to_str: str,
    prev_from_str: str,
    prev_to_str: str,
) -> IncomeStatement:
    """
    将两个取数函数映射为官方格式利润表。
    cur_fn(code_prefix, direction) -> Decimal  本期发生额
    prev_fn(code_prefix, direction) -> Decimal 上期发生额
    """
    is_ = IncomeStatement(
        date_from=date_from_str,
        date_to=date_to_str,
        prev_from=prev_from_str,
        prev_to=prev_to_str,
    )

    def row(code, name, cur, prev, is_total=False):
        is_.items.append(ISLineItem(
            code=code, name=name,
            cur_amt=cur, prev_amt=prev,
            is_total=is_total,
        ))

    # 一、营业收入
    rev_c     = cur_fn("6001", "CREDIT")
    rev_p     = prev_fn("6001", "CREDIT")
    orev_c    = cur_fn("6051", "CREDIT")
    orev_p    = prev_fn("6051", "CREDIT")
    trev_c    = rev_c + orev_c
    trev_p    = rev_p + orev_p
    row("6001", "一、营业收入",                    trev_c, trev_p, True)

    # 减：营业成本
    cogs_c    = cur_fn("6401", "DEBIT")
    cogs_p    = prev_fn("6401", "DEBIT")
    row("6401", "减：营业成本",                    cogs_c, cogs_p)

    # 减：税金及附加
    tax_sur_c = cur_fn("6403", "DEBIT")
    tax_sur_p = prev_fn("6403", "DEBIT")
    row("6403", "减：税金及附加",                  tax_sur_c, tax_sur_p)

    # 减：销售费用
    sell_c    = cur_fn("6601", "DEBIT")
    sell_p    = prev_fn("6601", "DEBIT")
    row("6601", "减：销售费用",                    sell_c, sell_p)

    # 减：管理费用
    admin_c   = cur_fn("6602", "DEBIT")
    admin_p   = prev_fn("6602", "DEBIT")
    row("6602", "减：管理费用",                    admin_c, admin_p)

    # 减：财务费用
    fin_c     = cur_fn("6603", "DEBIT")
    fin_p     = prev_fn("6603", "DEBIT")
    row("6603", "减：财务费用",                    fin_c, fin_p)

    # 减：研发费用
    rd_c      = cur_fn("6604", "DEBIT")
    rd_p      = prev_fn("6604", "DEBIT")
    row("6604", "减：研发费用",                    rd_c, rd_p)

    # 加：公允价值变动收益
    fv_c      = cur_fn("6101", "CREDIT")
    fv_p      = prev_fn("6101", "CREDIT")
    row("6101", "加：公允价值变动收益",            fv_c, fv_p)

    # 加：投资收益
    inv_c     = cur_fn("6111", "CREDIT")
    inv_p     = prev_fn("6111", "CREDIT")
    row("6111", "加：投资收益",                    inv_c, inv_p)

    # 加：其他收益
    oth_c     = cur_fn("6117", "CREDIT")
    oth_p     = prev_fn("6117", "CREDIT")
    row("6117", "加：其他收益",                    oth_c, oth_p)

    # 加：资产减值损失（转回为正，损失为负）
    imp_c     = cur_fn("6701", "CREDIT") - cur_fn("6701", "DEBIT")
    imp_p     = prev_fn("6701", "CREDIT") - prev_fn("6701", "DEBIT")
    row("6701", "加：资产减值转回（减：损失）",    imp_c, imp_p)

    # 加：信用减值损失（转回为正，损失为负）
    cred_imp_c = cur_fn("6120", "CREDIT") - cur_fn("6120", "DEBIT")
    cred_imp_p = prev_fn("6120", "CREDIT") - prev_fn("6120", "DEBIT")
    row("6120", "加：信用减值转回（减：损失）",    cred_imp_c, cred_imp_p)

    # 加：资产处置收益
    disp_c    = cur_fn("6115", "CREDIT") - cur_fn("6115", "DEBIT")
    disp_p    = prev_fn("6115", "CREDIT") - prev_fn("6115", "DEBIT")
    row("6115", "加：资产处置收益",                disp_c, disp_p)

    # 二、营业利润
    op_c = (trev_c - cogs_c - tax_sur_c - sell_c - admin_c - fin_c - rd_c
            + fv_c + inv_c + oth_c + imp_c + cred_imp_c + disp_c)
    op_p = (trev_p - cogs_p - tax_sur_p - sell_p - admin_p - fin_p - rd_p
            + fv_p + inv_p + oth_p + imp_p + cred_imp_p + disp_p)
    row("", "二、营业利润",                        op_c, op_p, True)

    # 加：营业外收入
    nonop_in_c = cur_fn("6301", "CREDIT")
    nonop_in_p = prev_fn("6301", "CREDIT")
    row("6301", "加：营业外收入",                  nonop_in_c, nonop_in_p)

    # 减：营业外支出
    nonop_ex_c = cur_fn("6711", "DEBIT")
    nonop_ex_p = prev_fn("6711", "DEBIT")
    row("6711", "减：营业外支出",                  nonop_ex_c, nonop_ex_p)

    # 三、利润总额
    ebt_c = op_c + nonop_in_c - nonop_ex_c
    ebt_p = op_p + nonop_in_p - nonop_ex_p
    row("", "三、利润总额",                        ebt_c, ebt_p, True)

    # 减：所得税费用
    inc_tax_c = cur_fn("6801", "DEBIT")
    inc_tax_p = prev_fn("6801", "DEBIT")
    row("6801", "减：所得税费用",                  inc_tax_c, inc_tax_p)

    # 四、净利润
    np_c = ebt_c - inc_tax_c
    np_p = ebt_p - inc_tax_p
    row("", "四、净利润",                          np_c, np_p, True)

    row("", "  归属于母公司所有者的净利润",        np_c, np_p)
    row("", "五、其他综合收益",                    Decimal("0"), Decimal("0"), True)
    row("", "六、综合收益总额",                    np_c, np_p, True)

    return is_


# ---------------------------------------------------------------------------
# ReportService
# ---------------------------------------------------------------------------

class ReportService:
    def __init__(self, db: Session) -> None:
        self._db = db

    # ── Balance Sheet (会企01表) ────────────────────────────────────────────

    def get_balance_sheet(self, as_of: date) -> BalanceSheet:
        """官方格式资产负债表（会企01表）。"""
        beg_date = date(as_of.year - 1, 12, 31)
        end_bal  = _build_balances(self._db, as_of)
        beg_bal  = _build_balances(self._db, beg_date)
        return _map_balance_sheet(end_bal, beg_bal, str(as_of), str(beg_date))

    # ── Income Statement (会企02表) ─────────────────────────────────────────

    def get_income_statement(self, date_from: date, date_to: date) -> IncomeStatement:
        """官方格式利润表（会企02表）。上期 = 上年同期。"""
        import calendar
        prev_from = date(date_from.year - 1, date_from.month, date_from.day)
        last_day  = calendar.monthrange(date_to.year - 1, date_to.month)[1]
        prev_to   = date(date_to.year - 1, date_to.month, min(date_to.day, last_day))

        def cur_fn(prefix, direction):
            return _sum_period(self._db, prefix, direction, date_from, date_to)

        def prev_fn(prefix, direction):
            return _sum_period(self._db, prefix, direction, prev_from, prev_to)

        return _map_income_statement(
            cur_fn, prev_fn,
            str(date_from), str(date_to),
            str(prev_from), str(prev_to),
        )
