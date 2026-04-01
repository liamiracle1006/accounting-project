"""
AgentLedger — TaxAnnualPlan model

年度税务规划表。AI 在年初（或首次激活时）根据企业画像生成全年节税路线图。
"""
from sqlalchemy import String, Text, Integer, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from database.connection import Base
from models.mixins import TenantMixin


class PlanStatus:
    ACTIVE   = "ACTIVE"    # 当前生效的规划
    OUTDATED = "OUTDATED"  # 已被新规划替代
    DRAFT    = "DRAFT"     # 草稿（生成中）


class TaxAnnualPlan(TenantMixin, Base):
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
