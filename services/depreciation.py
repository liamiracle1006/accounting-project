"""
AgentLedger — DepreciationCalculator

纯数学函数，不依赖 LLM，不依赖数据库。
所有折旧金额均由此模块计算，保证数字准确性。

支持三种折旧方法：
  1. 直线法（年限平均法）
  2. 双倍余额递减法（加速折旧，后两年切直线）
  3. 一次性扣除（当月全额，500万以下设备适用）

tax_savings 计算说明：
  tax_savings = deductible_amount × income_tax_rate
  this_year_savings 受购入月份影响（11月购入只剩2个月可折）
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import NamedTuple


ONE_TIME_DEDUCTION_LIMIT = 5_000_000.00   # 一次性扣除政策上限（500万）


class MonthlySchedule(NamedTuple):
    """单月折旧计划条目"""
    month_index:   int    # 第几个折旧月（从1开始）
    depreciation:  float  # 本月折旧额
    book_value:    float  # 折旧后账面净值


@dataclass
class DepreciationSummary:
    """某种折旧方案的关键数字摘要，用于填充决策卡片"""
    method:                str
    useful_life_months:    int
    monthly_depreciation:  float   # 首月折旧额（加速折旧逐年递减）
    this_year_deduction:   float   # 购入当年可扣除金额（受购入月份影响）
    total_deduction:       float   # 合计可扣除金额（= 原值 - 残值）
    this_year_tax_savings: float   # 当年节税金额
    total_tax_savings:     float   # 合计节税金额


def straight_line(
    original_value:    float,
    salvage_value:     float,
    useful_life_months: int,
    purchase_date:     date,
    tax_rate:          float,
) -> DepreciationSummary:
    """
    直线法（年限平均法）。
    每月折旧 = (原值 - 残值) / 使用月数
    """
    depreciable = original_value - salvage_value
    monthly     = depreciable / useful_life_months

    # 当年剩余月数（购入当月不折旧，次月起开始）
    remaining_months_this_year = 12 - purchase_date.month
    this_year = monthly * remaining_months_this_year

    return DepreciationSummary(
        method                = "STRAIGHT_LINE",
        useful_life_months    = useful_life_months,
        monthly_depreciation  = round(monthly, 2),
        this_year_deduction   = round(this_year, 2),
        total_deduction       = round(depreciable, 2),
        this_year_tax_savings = round(this_year * tax_rate, 2),
        total_tax_savings     = round(depreciable * tax_rate, 2),
    )


def double_declining_balance(
    original_value:    float,
    salvage_value:     float,
    useful_life_months: int,
    purchase_date:     date,
    tax_rate:          float,
) -> DepreciationSummary:
    """
    双倍余额递减法（加速折旧）。
    年折旧率 = 2 / 使用年限
    最后两年切换为剩余净值的直线法。

    返回摘要中 monthly_depreciation 为第一年的月折旧额。
    """
    useful_life_years  = useful_life_months / 12
    annual_rate        = 2.0 / useful_life_years
    schedule           = _build_ddb_schedule(original_value, salvage_value,
                                              useful_life_months)

    # 首月折旧
    first_month_dep = schedule[0].depreciation if schedule else 0.0

    # 当年可扣除：从次月起到年末
    start_idx = purchase_date.month  # 次月在 schedule 中的 index（0-based）
    this_year_deduction = sum(
        s.depreciation
        for s in schedule[start_idx: start_idx + (12 - purchase_date.month)]
    )

    total_deduction = original_value - salvage_value

    return DepreciationSummary(
        method                = "ACCELERATED",
        useful_life_months    = useful_life_months,
        monthly_depreciation  = round(first_month_dep, 2),
        this_year_deduction   = round(this_year_deduction, 2),
        total_deduction       = round(total_deduction, 2),
        this_year_tax_savings = round(this_year_deduction * tax_rate, 2),
        total_tax_savings     = round(total_deduction * tax_rate, 2),
    )


def one_time_deduction(
    original_value: float,
    purchase_date:  date,
    tax_rate:       float,
) -> DepreciationSummary | None:
    """
    一次性扣除（500万以下设备适用，当年全额扣除）。
    超过500万返回 None（政策不允许）。
    """
    if original_value > ONE_TIME_DEDUCTION_LIMIT:
        return None

    return DepreciationSummary(
        method                = "ONE_TIME",
        useful_life_months    = 1,
        monthly_depreciation  = round(original_value, 2),
        this_year_deduction   = round(original_value, 2),
        total_deduction       = round(original_value, 2),
        this_year_tax_savings = round(original_value * tax_rate, 2),
        total_tax_savings     = round(original_value * tax_rate, 2),
    )


def get_all_summaries(
    original_value:  float,
    salvage_value:   float,
    tax_rate:        float,
    purchase_date:   date,
    candidate_lives: list[int],   # 候选使用年限（月数），如 [36, 60, 120]
) -> dict[str, DepreciationSummary]:
    """
    一次性计算所有候选方案的摘要数字，供 decision_service 填充决策卡片。
    返回 { action_code: DepreciationSummary }
    """
    results: dict[str, DepreciationSummary] = {}

    # 一次性扣除
    ot = one_time_deduction(original_value, purchase_date, tax_rate)
    if ot:
        results["FIXED_ASSET_ONE_TIME"] = ot

    for life_months in candidate_lives:
        years = life_months // 12

        sl = straight_line(original_value, salvage_value, life_months, purchase_date, tax_rate)
        results[f"FIXED_ASSET_STRAIGHT_LINE_{years}Y"] = sl

        acc = double_declining_balance(original_value, salvage_value, life_months, purchase_date, tax_rate)
        results[f"FIXED_ASSET_ACCELERATED_{years}Y"] = acc

    return results


# ── Internal helpers ──────────────────────────────────────────────────────────

def _build_ddb_schedule(
    original_value: float,
    salvage_value:  float,
    life_months:    int,
) -> list[MonthlySchedule]:
    """构建双倍余额递减法的完整月度折旧计划表。"""
    life_years   = life_months / 12
    annual_rate  = 2.0 / life_years
    monthly_rate = annual_rate / 12

    schedule    : list[MonthlySchedule] = []
    book_value   = original_value
    switch_month = life_months - 24   # 最后24个月切直线

    for i in range(1, life_months + 1):
        if i <= switch_month:
            dep = book_value * monthly_rate
        else:
            # 切换为直线：剩余净值在剩余月数内平均
            remaining_months = life_months - i + 1
            dep = (book_value - salvage_value) / remaining_months

        dep        = min(dep, book_value - salvage_value)
        book_value = book_value - dep
        schedule.append(MonthlySchedule(
            month_index  = i,
            depreciation = round(dep, 2),
            book_value   = round(book_value, 2),
        ))

    return schedule
