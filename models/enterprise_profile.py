"""
AgentLedger — EnterpriseProfile model

存储企业的税收画像与系统行为参数，是整个系统的参数中枢。
所有税率计算、路由分发、模式判断均读取此表。

S3 新增字段（用于 RAG 精准过滤）：
  province        — 省份，如"广东省"，对应 RAG regional 切片过滤
  city            — 城市，如"深圳市"，对应 RAG city-level 切片过滤
  is_hnte         — 是否高新技术企业（影响税率和研发加计比例）
  rd_eligible     — 是否具备研发加计扣除资格
  employee_count  — 员工人数（判断小微资格）
  annual_revenue_estimate — 上年度营收估算（判断小微/小规模资格、广告费限额基数）
"""
from decimal import Decimal

from sqlalchemy import String, Numeric, DateTime, func, SmallInteger, Integer
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
        comment="行业代码：制造业/科技/软件服务业/批发零售业/餐饮住宿业/建筑业/通用"
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

    # ── S3 新增：RAG 精准过滤字段 ────────────────────────────────────────────

    province: Mapped[str | None] = mapped_column(
        String(50), nullable=True, default=None,
        comment="省份，如'广东省'，用于 RAG 省级政策过滤"
    )

    city: Mapped[str | None] = mapped_column(
        String(50), nullable=True, default=None,
        comment="城市，如'深圳市'，用于 RAG 城市级政策过滤（前海/临港等园区政策）"
    )

    is_hnte: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0,
        comment="是否高新技术企业：1=是（适用15%税率+100%研发加计），0=否"
    )

    rd_eligible: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0,
        comment="是否具备研发加计扣除资格：1=是，0=否"
    )

    employee_count: Mapped[int | None] = mapped_column(
        Integer, nullable=True, default=None,
        comment="员工人数，用于判断小微企业资格（≤300人）"
    )

    annual_revenue_estimate: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2), nullable=True, default=None,
        comment="上年度营收估算（元），用于广告费限额基数、小微资格判断"
    )

    # ─────────────────────────────────────────────────────────────────────────

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
