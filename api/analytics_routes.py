"""
AgentLedger — Financial Analytics API (Stage 4)

S4-A: GET /api/analytics/health  — 6 financial health ratios with ratings
S4-B: GET /api/analytics/alerts  — intelligent alert & deadline system
"""
import json
import logging
import re
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, or_, extract
from sqlalchemy.orm import Session

from database.connection import get_db
from models.voucher_header import VoucherHeader, VoucherReviewStatus
from models.voucher_line import VoucherLine
from models.operational_record import OperationalRecord, RecordStatus
from models.enterprise_profile import EnterpriseProfile
from models.tax_annual_plan import TaxAnnualPlan, PlanStatus

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/analytics", tags=["analytics"])


# ── Low-level balance helpers ─────────────────────────────────────────────────

def _net_balance(db: Session, prefixes: list[str], normal_dir: str) -> Decimal:
    """
    Sum posted voucher lines for given account code prefixes.
    normal_dir = "DEBIT"  → assets  (debit increases)
    normal_dir = "CREDIT" → liabilities/equity/income
    """
    rows = (
        db.query(VoucherLine.direction, func.sum(VoucherLine.amount))
        .join(VoucherHeader, VoucherLine.voucher_id == VoucherHeader.voucher_id)
        .filter(
            VoucherHeader.review_status == VoucherReviewStatus.POSTED,
            or_(*[VoucherLine.subject_code.like(p + "%") for p in prefixes]),
        )
        .group_by(VoucherLine.direction)
        .all()
    )
    totals = {d: Decimal(str(v)) for d, v in rows}
    debit  = totals.get("DEBIT",  Decimal("0"))
    credit = totals.get("CREDIT", Decimal("0"))
    return (debit - credit) if normal_dir == "DEBIT" else (credit - debit)


def _monthly_pl(db: Session, year: int, month: int) -> tuple[Decimal, Decimal]:
    """Return (net_profit, revenue) for a given calendar month from posted vouchers."""
    INCOME_CODES = {"6001", "6051", "6101", "6111", "6117", "6301"}
    rows = (
        db.query(VoucherLine.subject_code, VoucherLine.direction, func.sum(VoucherLine.amount))
        .join(VoucherHeader, VoucherLine.voucher_id == VoucherHeader.voucher_id)
        .filter(
            VoucherHeader.review_status == VoucherReviewStatus.POSTED,
            VoucherLine.subject_code >= "6001",
            VoucherLine.subject_code <= "6899",
            extract("year",  VoucherHeader.voucher_date) == year,
            extract("month", VoucherHeader.voucher_date) == month,
        )
        .group_by(VoucherLine.subject_code, VoucherLine.direction)
        .all()
    )
    inc = exp = rev = Decimal("0")
    for code, direction, total in rows:
        v = Decimal(str(total))
        if code[:4] in INCOME_CODES:
            if direction == "CREDIT":
                inc += v
                if code[:4] == "6001":
                    rev += v
            else:
                inc -= v
        else:
            if direction == "DEBIT":
                exp += v
            else:
                exp -= v
    return inc - exp, rev


# ── S4-A: Financial Health ────────────────────────────────────────────────────

def _rating(value: float | None, thresholds: list[tuple[float, str]], higher_is_better: bool = True) -> str:
    """
    Assign GOOD / WARNING / DANGER rating.
    thresholds: [(cutoff, label), ...] sorted descending (for higher_is_better)
    or ascending (for higher_is_worse like debt ratio).
    """
    if value is None:
        return "N/A"
    for cutoff, label in thresholds:
        if higher_is_better:
            if value >= cutoff:
                return label
        else:
            if value <= cutoff:
                return label
    return thresholds[-1][1]


@router.get("/health")
def get_financial_health(db: Session = Depends(get_db)) -> Any:
    """
    实时计算6大财务健康比率，附带评级和行业基准说明。
    数据来源：所有 POSTED 状态凭证的借贷方向余额。
    """
    today = date.today()

    # ── Asset balances ───────────────────────────────────────────────────────
    cash        = _net_balance(db, ["1001","1002","1012"],                              "DEBIT")
    receivable  = _net_balance(db, ["1121","1122","1123","1231"],                       "DEBIT")
    inventory   = _net_balance(db, ["1403","1404","1405","1406","1407","1408","1409"],  "DEBIT")
    other_curr  = _net_balance(db, ["1201","1511","1801"],                             "DEBIT")
    fixed_gross = _net_balance(db, ["1601"],                                           "DEBIT")
    accum_dep   = abs(_net_balance(db, ["1602"],                                       "CREDIT"))
    intang_gross= _net_balance(db, ["1701"],                                           "DEBIT")
    accum_amort = abs(_net_balance(db, ["1703"],                                       "CREDIT"))
    noncurr_inv = _net_balance(db, ["1501","1502"],                                    "DEBIT")

    fixed_net   = max(Decimal("0"), fixed_gross  - accum_dep)
    intang_net  = max(Decimal("0"), intang_gross - accum_amort)

    current_assets    = cash + receivable + inventory + other_curr
    noncurrent_assets = fixed_net + intang_net + noncurr_inv
    total_assets      = current_assets + noncurrent_assets

    # ── Liability balances ───────────────────────────────────────────────────
    current_liab = _net_balance(
        db,
        ["2101","2111","2201","2202","2203","2205","2211","2221","2241","2281"],
        "CREDIT",
    )
    noncurr_liab = _net_balance(db, ["2501","2502","2511","2401"], "CREDIT")
    total_liab   = current_liab + noncurr_liab

    # ── P&L (YTD) ────────────────────────────────────────────────────────────
    ytd_profit, ytd_revenue = _monthly_pl(db, today.year, 0)  # 0 = whole year

    # Re-do YTD with year-range filter (not month filter)
    from sqlalchemy import text as sqltxt
    year_prefix = f"{today.year}-%"
    INCOME_CODES = {"6001", "6051", "6101", "6111", "6117", "6301"}
    ytd_rows = (
        db.query(VoucherLine.subject_code, VoucherLine.direction, func.sum(VoucherLine.amount))
        .join(VoucherHeader, VoucherLine.voucher_id == VoucherHeader.voucher_id)
        .filter(
            VoucherHeader.review_status == VoucherReviewStatus.POSTED,
            VoucherLine.subject_code >= "6001",
            VoucherLine.subject_code <= "6899",
            VoucherHeader.voucher_date.cast(sqltxt("CHAR")).like(year_prefix),
        )
        .group_by(VoucherLine.subject_code, VoucherLine.direction)
        .all()
    )
    ytd_inc = ytd_exp = ytd_rev = Decimal("0")
    for code, direction, total in ytd_rows:
        v = Decimal(str(total))
        if code[:4] in INCOME_CODES:
            if direction == "CREDIT":
                ytd_inc += v
                if code[:4] == "6001":
                    ytd_rev += v
            else:
                ytd_inc -= v
        else:
            if direction == "DEBIT":
                ytd_exp += v
            else:
                ytd_exp -= v
    net_profit_ytd = ytd_inc - ytd_exp

    # ── Month-over-month revenue growth ──────────────────────────────────────
    curr_m_profit, curr_m_rev = _monthly_pl(db, today.year, today.month)
    prev_month = today.month - 1 if today.month > 1 else 12
    prev_year  = today.year    if today.month > 1 else today.year - 1
    prev_m_profit, prev_m_rev = _monthly_pl(db, prev_year, prev_month)

    mom_growth_pct = None
    if prev_m_rev > 0:
        mom_growth_pct = round(float((curr_m_rev - prev_m_rev) / prev_m_rev * 100), 1)

    # ── Calculate ratios ─────────────────────────────────────────────────────
    def _ratio(a: Decimal, b: Decimal) -> float | None:
        return float(a / b) if b and b != 0 else None

    current_ratio  = _ratio(current_assets, current_liab)
    quick_ratio    = _ratio(current_assets - inventory, current_liab)
    cash_ratio     = _ratio(cash, current_liab)
    debt_ratio_raw = _ratio(total_liab, total_assets) if total_assets > 0 else None
    profit_margin  = _ratio(net_profit_ytd, ytd_rev) if ytd_rev > 0 else None

    debt_ratio_pct    = round(debt_ratio_raw * 100, 1)  if debt_ratio_raw  is not None else None
    profit_margin_pct = round(profit_margin  * 100, 2)  if profit_margin   is not None else None

    ratios = [
        {
            "key":         "current_ratio",
            "name":        "流动比率",
            "value":       round(current_ratio, 2) if current_ratio is not None else None,
            "unit":        "倍",
            "rating":      _rating(current_ratio, [(2.0,"GOOD"),(1.0,"WARNING")]),
            "description": "流动资产 ÷ 流动负债，衡量短期偿债能力",
            "benchmark":   "≥2 良好 · 1-2 关注 · <1 危险",
        },
        {
            "key":         "quick_ratio",
            "name":        "速动比率",
            "value":       round(quick_ratio, 2) if quick_ratio is not None else None,
            "unit":        "倍",
            "rating":      _rating(quick_ratio, [(1.0,"GOOD"),(0.5,"WARNING")]),
            "description": "（流动资产 − 存货）÷ 流动负债",
            "benchmark":   "≥1 良好 · 0.5-1 关注 · <0.5 危险",
        },
        {
            "key":         "cash_ratio",
            "name":        "现金比率",
            "value":       round(cash_ratio, 2) if cash_ratio is not None else None,
            "unit":        "倍",
            "rating":      _rating(cash_ratio, [(0.2,"GOOD"),(0.1,"WARNING")]),
            "description": "（库存现金 + 银行存款）÷ 流动负债",
            "benchmark":   "≥0.2 良好 · 0.1-0.2 关注 · <0.1 危险",
        },
        {
            "key":         "debt_ratio",
            "name":        "资产负债率",
            "value":       debt_ratio_pct,
            "unit":        "%",
            "rating":      _rating(debt_ratio_raw, [(0.6,"GOOD"),(0.8,"WARNING")], higher_is_better=False),
            "description": "总负债 ÷ 总资产，衡量财务杠杆风险",
            "benchmark":   "≤60% 良好 · 60-80% 关注 · >80% 危险",
        },
        {
            "key":         "profit_margin",
            "name":        "净利润率",
            "value":       profit_margin_pct,
            "unit":        "%",
            "rating":      _rating(profit_margin, [(0.1,"GOOD"),(0.05,"WARNING")]),
            "description": "净利润 ÷ 主营业务收入（年初至今）",
            "benchmark":   "≥10% 良好 · 5-10% 关注 · <5% 危险",
        },
        {
            "key":         "mom_growth",
            "name":        "营收环比增长",
            "value":       mom_growth_pct,
            "unit":        "%",
            "rating":      _rating(mom_growth_pct, [(5.0,"GOOD"),(-10.0,"WARNING")]),
            "description": "本月主营收入 vs 上月对比增长率",
            "benchmark":   "≥5% 良好 · -10%~5% 关注 · <-10% 危险",
        },
    ]

    # Overall health score
    valid_ratings = [r["rating"] for r in ratios if r["rating"] != "N/A"]
    danger_count  = valid_ratings.count("DANGER")
    warn_count    = valid_ratings.count("WARNING")
    if   danger_count >= 2:                    overall = "DANGER"
    elif danger_count == 1 or warn_count >= 2: overall = "WARNING"
    else:                                      overall = "GOOD"

    return {
        "overall_rating": overall,
        "ratios": ratios,
        "snapshot": {
            "total_assets":       float(total_assets),
            "total_liabilities":  float(total_liab),
            "current_assets":     float(current_assets),
            "current_liabilities": float(current_liab),
            "cash":               float(cash),
            "net_profit_ytd":     float(net_profit_ytd),
            "ytd_revenue":        float(ytd_rev),
            "curr_month_revenue": float(curr_m_rev),
            "prev_month_revenue": float(prev_m_rev),
        },
        "computed_at": datetime.utcnow().isoformat(),
    }


# ── S4-B: Intelligent Alerts ──────────────────────────────────────────────────

@router.get("/alerts")
def get_alerts(db: Session = Depends(get_db)) -> Any:
    """
    智能预警系统：汇总所有需要关注的财务和税务问题。
    每条预警：level (DANGER/WARNING/INFO), category, title, detail, action
    排序：DANGER > WARNING > INFO
    """
    alerts: list[dict] = []
    today   = date.today()
    profile = db.query(EnterpriseProfile).filter(EnterpriseProfile.is_active == 1).first()

    # ── 1. 现金预警 ─────────────────────────────────────────────────────────
    cash      = _net_balance(db, ["1001","1002","1012"], "DEBIT")
    threshold = Decimal(str(profile.decision_threshold)) if profile else Decimal("5000")

    if cash < threshold:
        alerts.append({
            "level": "DANGER", "category": "现金流",
            "title": f"现金余额极低 ¥{float(cash):,.0f}",
            "detail": f"当前账面现金 ¥{float(cash):,.0f}，低于决策阈值 ¥{float(threshold):,.0f}，请立即安排资金",
            "action": "检查银行存款余额，跟进应收账款回款，必要时安排短期融资",
        })
    elif cash < threshold * 3:
        alerts.append({
            "level": "WARNING", "category": "现金流",
            "title": f"现金余额偏低 ¥{float(cash):,.0f}",
            "detail": f"当前现金不足决策阈值3倍（¥{float(threshold*3):,.0f}），建议关注资金状况",
            "action": "检查近期应收账款，跟进客户回款进度",
        })

    # ── 2. 流水积压预警 ──────────────────────────────────────────────────────
    stale_cutoff = datetime.combine(today - timedelta(days=3), datetime.min.time())
    stale_count  = (
        db.query(func.count(OperationalRecord.record_id))
        .filter(
            OperationalRecord.status == RecordStatus.PENDING,
            OperationalRecord.created_at < stale_cutoff,
        )
        .scalar() or 0
    )
    if stale_count > 0:
        alerts.append({
            "level": "WARNING", "category": "流水处理",
            "title": f"{stale_count} 条流水滞留超3天",
            "detail": f"有 {stale_count} 条业务流水处于 PENDING 状态超过3天，可能存在解析异常",
            "action": "前往「流水记录」筛选 PENDING 状态，人工检查原因",
        })

    # ── 3. 凭证待审核积压 ────────────────────────────────────────────────────
    pending_review = (
        db.query(func.count(VoucherHeader.voucher_id))
        .filter(VoucherHeader.review_status == VoucherReviewStatus.PENDING_REVIEW)
        .scalar() or 0
    )
    if pending_review >= 5:
        level = "DANGER" if pending_review >= 10 else "WARNING"
        alerts.append({
            "level": level, "category": "凭证审核",
            "title": f"{pending_review} 张凭证待审核",
            "detail": f"财务工作台积压 {pending_review} 张待审核凭证，影响报表准确性",
            "action": "前往「财务工作台」进行批量审核，确保凭证及时入账",
        })
    elif pending_review > 0:
        alerts.append({
            "level": "INFO", "category": "凭证审核",
            "title": f"{pending_review} 张凭证待审核",
            "detail": f"有 {pending_review} 张凭证等待审核确认",
            "action": "前往「财务工作台」审核",
        })

    # ── 4. 当月利润预警 ──────────────────────────────────────────────────────
    curr_profit, curr_rev = _monthly_pl(db, today.year, today.month)
    prev_m = today.month - 1 if today.month > 1 else 12
    prev_y = today.year    if today.month > 1 else today.year - 1
    prev_profit, _ = _monthly_pl(db, prev_y, prev_m)

    if curr_profit < 0:
        alerts.append({
            "level": "WARNING", "category": "盈利状况",
            "title": f"本月净亏损 ¥{float(abs(curr_profit)):,.0f}",
            "detail": f"{today.year}年{today.month}月累计亏损 ¥{float(abs(curr_profit)):,.0f}，需排查异常支出",
            "action": "分析费用科目，识别可压缩项；考虑提前启动年度税务规划",
        })
    elif prev_profit > 0:
        drop = float((curr_profit - prev_profit) / prev_profit * 100)
        if drop < -30:
            alerts.append({
                "level": "INFO", "category": "盈利状况",
                "title": f"净利润环比下降 {abs(drop):.0f}%",
                "detail": f"上月利润 ¥{float(prev_profit):,.0f} → 本月 ¥{float(curr_profit):,.0f}，降幅超过30%",
                "action": "对比两月费用明细，排查非经常性大额支出",
            })

    # ── 5. 税务截止日预警（来自最新年度规划） ─────────────────────────────────
    plan = (
        db.query(TaxAnnualPlan)
        .filter(TaxAnnualPlan.year == today.year, TaxAnnualPlan.status == PlanStatus.ACTIVE)
        .order_by(TaxAnnualPlan.plan_id.desc())
        .first()
    )
    if plan:
        try:
            plan_data = json.loads(plan.plan_json)
            Q_MONTHS  = {"Q1":[1,2,3],"Q2":[4,5,6],"Q3":[7,8,9],"Q4":[10,11,12]}
            for q in plan_data.get("quarters", []):
                q_months = Q_MONTHS.get(q.get("quarter",""), [])
                # Show current quarter and next quarter alerts
                if today.month not in q_months and (today.month + 1) not in q_months:
                    continue
                for action in q.get("actions", []):
                    if action.get("priority") not in ("HIGH", "MEDIUM"):
                        continue
                    deadline_str = action.get("deadline","")
                    if not deadline_str:
                        continue
                    m_match = re.search(r"(\d+)月(\d+)日", deadline_str)
                    if not m_match:
                        continue
                    try:
                        dl_date   = date(today.year, int(m_match.group(1)), int(m_match.group(2)))
                        days_left = (dl_date - today).days
                        if 0 <= days_left <= 45:
                            lvl = "DANGER" if days_left <= 7 else "WARNING" if days_left <= 21 else "INFO"
                            alerts.append({
                                "level": lvl, "category": "税务截止",
                                "title": f"⏰ {action.get('title','')} — 还剩 {days_left} 天",
                                "detail": f"截止：{deadline_str}。{action.get('detail','')[:80]}",
                                "action": action.get("source_doc","") or "参见年度规划",
                            })
                    except (ValueError, OverflowError):
                        pass
        except (json.JSONDecodeError, Exception) as exc:
            logger.warning("Alert: failed to parse annual plan: %s", exc)

    # Sort by severity
    _order = {"DANGER": 0, "WARNING": 1, "INFO": 2}
    alerts.sort(key=lambda a: _order.get(a["level"], 9))

    return {
        "alerts":        alerts,
        "alert_count":   len(alerts),
        "danger_count":  sum(1 for a in alerts if a["level"] == "DANGER"),
        "warning_count": sum(1 for a in alerts if a["level"] == "WARNING"),
        "info_count":    sum(1 for a in alerts if a["level"] == "INFO"),
        "computed_at":   datetime.utcnow().isoformat(),
    }
