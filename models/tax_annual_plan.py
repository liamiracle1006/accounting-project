"""
AgentLedger — TaxAnnualPlan model

年度税务规划表。AI 在年初（或首次激活时）根据企业画像生成全年节税路线图。
决策卡片触发时会关联本年规划，提供「符合/偏离规划」的判断上下文。

plan_json 结构：
{
  "year": 2026,
  "profile_summary": "软件服务业·小规模纳税人·所得税20%",
  "estimated_annual_revenue": 1800000,
  "estimated_annual_profit":  600000,
  "estimated_tax_baseline":   120000,
  "total_potential_savings":  80000,
  "quarters": [
    {
      "quarter": "Q1",
      "months": "1-3月",
      "actions": [
        {
          "title": "整理研发支出申报加计扣除",
          "priority": "HIGH",
          "potential_saving": 30000,
          "deadline": "3月31日",
          "detail": "..."
        }
      ]
    },
    ...
  ],
  "key_thresholds": {
    "one_time_deduction_limit": 5000000,
    "small_profit_income_limit": 3000000,
    "current_income_tax_rate": 0.20
  }
}
"""
from sqlalchemy import String, Text, Integer, DateTime, func, SmallInteger
from sqlalchemy.orm import Mapped, mapped_column

from database.connection import Base


class PlanStatus:
    ACTIVE   = "ACTIVE"    # 当前生效的规划
    OUTDATED = "OUTDATED"  # 已被新规划替代
    DRAFT    = "DRAFT"     # 草稿（生成中）


class TaxAnnualPlan(Base):
    __tablename__ = "tax_annual_plan"

    plan_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    company_id: Mapped[int] = mapped_column(
        Integer, nullable=False,
        comment="FK → enterprise_profile.company_id"
    )

    year: Mapped[int] = mapped_column(
        Integer, nullable=False,
        comment="规划年份，如 2026"
    )

    plan_json: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="AI 生成的完整年度规划 JSON"
    )

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=PlanStatus.ACTIVE,
        comment="ACTIVE / OUTDATED / DRAFT"
    )

    generated_at = mapped_column(DateTime, server_default=func.now())
    updated_at   = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    def __repr__(self) -> str:
        return f"<TaxAnnualPlan id={self.plan_id} year={self.year} status={self.status}>"
