"""
AgentLedger — EnterpriseProfile model

存储企业的税收画像与系统行为参数，是整个系统的参数中枢。
所有税率计算、路由分发、模式判断均读取此表。

company_type:
  MICRO    — 小微企业 / 个体户：走老板决策卡片流程，适用小企业会计准则
  STANDARD — 一般企业（50-100人级别）：走审批流程，适用企业会计准则

tax_payer_type:
  SMALL_SCALE — 小规模纳税人，增值税征收率 3%（部分业务 5%）
  GENERAL     — 一般纳税人，按行业适用 6% / 9% / 13%

applicable_income_tax_rate:
  0.25 — 一般企业
  0.20 — 小型微利企业（名义税率，实际执行优惠见税法）
  0.15 — 高新技术企业 / 技术先进型服务企业

decision_threshold:
  金额超过此值 OR 命中敏感关键词 → 拦截进入老板决策流
  默认 5000.00 元，可按企业体量调整
"""
from decimal import Decimal

from sqlalchemy import String, Numeric, DateTime, func, SmallInteger
from sqlalchemy.orm import Mapped, mapped_column

from database.connection import Base


class CompanyType:
    MICRO    = "MICRO"
    STANDARD = "STANDARD"


class TaxPayerType:
    SMALL_SCALE = "SMALL_SCALE"   # 小规模纳税人
    GENERAL     = "GENERAL"       # 一般纳税人


class AccountingStandard:
    SMALL_BIZ = "SMALL_BIZ"   # 小企业会计准则
    GENERAL   = "GENERAL"     # 企业会计准则


class EnterpriseProfile(Base):
    __tablename__ = "enterprise_profile"

    company_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    company_name: Mapped[str] = mapped_column(String(200), nullable=False)

    company_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default=CompanyType.MICRO,
        comment="MICRO=小微/个体户, STANDARD=一般企业"
    )

    industry_code: Mapped[str] = mapped_column(
        String(50), nullable=False, default="通用",
        comment="行业代码：制造业/软件服务业/批发零售业/餐饮住宿业/建筑业/通用"
    )

    tax_payer_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default=TaxPayerType.SMALL_SCALE,
        comment="SMALL_SCALE=小规模纳税人, GENERAL=一般纳税人"
    )

    applicable_income_tax_rate: Mapped[Decimal] = mapped_column(
        Numeric(5, 4), nullable=False, default=Decimal("0.2000"),
        comment="企业所得税率：0.25/0.20/0.15/0.05"
    )

    vat_rate: Mapped[Decimal] = mapped_column(
        Numeric(5, 4), nullable=False, default=Decimal("0.0300"),
        comment="增值税率：0.03/0.06/0.09/0.13"
    )

    decision_threshold: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=Decimal("5000.00"),
        comment="老板决策触发阈值（元），超过此金额的流水进入决策流"
    )

    accounting_standard: Mapped[str] = mapped_column(
        String(20), nullable=False, default=AccountingStandard.SMALL_BIZ,
        comment="SMALL_BIZ=小企业会计准则, GENERAL=企业会计准则"
    )

    is_active: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=1,
        comment="1=当前激活的企业档案（系统同时只有一条激活记录）"
    )

    created_at = mapped_column(DateTime, server_default=func.now())
    updated_at = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    def __repr__(self) -> str:
        return (
            f"<EnterpriseProfile id={self.company_id} "
            f"name='{self.company_name}' type={self.company_type}>"
        )
