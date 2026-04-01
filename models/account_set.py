"""
AgentLedger V4.0 — AccountSet model (账套)

One tenant can have multiple account sets (e.g. separate books for
different legal entities or fiscal years).

Onboarding lifecycle:
  ONBOARDING        → 期初余额导入阶段（允许借贷不平，差额走 1901）
  READY_FOR_VOUCHERS → 正式启用，日常分录必须严格借贷相等
  SUSPENDED         → 暂停（欠费/归档）
"""
from sqlalchemy import BigInteger, String, Integer, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from database.connection import Base


class AccountSetStatus:
    ONBOARDING         = "ONBOARDING"          # 建账期：允许不平衡
    READY_FOR_VOUCHERS = "READY_FOR_VOUCHERS"  # 正式启用：日常严格平衡
    SUSPENDED          = "SUSPENDED"           # 暂停


class AccountSet(Base):
    __tablename__ = "account_set"

    account_set_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, index=True,
        comment="FK → tenant.tenant_id"
    )
    account_set_name: Mapped[str] = mapped_column(
        String(200), nullable=False,
        comment="账套名称，如'2026年度账'、'子公司账套'"
    )
    fiscal_year_start_month: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1,
        comment="会计年度起始月份（中国一般为1月）"
    )
    accounting_standard: Mapped[str] = mapped_column(
        String(20), nullable=False, default="SMALL_BIZ",
        comment="SMALL_BIZ=小企业会计准则 / GENERAL=企业会计准则"
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default=AccountSetStatus.ONBOARDING,
        comment="ONBOARDING / READY_FOR_VOUCHERS / SUSPENDED"
    )
    activated_at: Mapped[DateTime | None] = mapped_column(
        DateTime, nullable=True,
        comment="账套正式启用时间（状态切为 READY_FOR_VOUCHERS 时记录）"
    )
    created_at = mapped_column(DateTime, server_default=func.now())
    updated_at = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    def __repr__(self) -> str:
        return (
            f"<AccountSet id={self.account_set_id} "
            f"name='{self.account_set_name}' status={self.status}>"
        )
