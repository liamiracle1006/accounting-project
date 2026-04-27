"""
AgentLedger V4.0 — AccountSet model (账套) — Sprint 1 扩展

每个 tenant（SaaS 租户）可持有多个 AccountSet，每个账套是一个独立的
物理数据隔离边界（凭证、报表、资产全部归属于账套）。

生命周期（Iron Law 2 - Financial Continuity）：
  ONBOARDING  → 建账期：海绵容错允许借贷不平，差额走 1901
  ACTIVE      → 正式启用：日常分录必须严格借贷相等
  RECYCLED    → 软删除回收站（is_deleted=True）
  SUSPENDED   → 暂停（欠费/归档）

铁律二关键约束：
  start_period 和 accounting_standard 一旦产生有效 Voucher 或
  AccountBalance 后，绝对禁止修改（否则引发全盘账务崩溃）。
  此约束在 Service 层强制校验，本模型仅声明字段。
"""
import json
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from database.connection import Base


# ── 枚举常量 ────────────────────────────────────────────────────────────────────

class AccountSetStatus:
    ONBOARDING = "ONBOARDING"   # 建账期：海绵容错
    ACTIVE     = "ACTIVE"       # 正式启用（原 READY_FOR_VOUCHERS）
    RECYCLED   = "RECYCLED"     # 软删除回收站
    SUSPENDED  = "SUSPENDED"    # 暂停


class AccountingStandard:
    SMALL_BIZ = "小企业会计准则"
    GENERAL   = "企业会计准则"

    ALL = [SMALL_BIZ, GENERAL]


class TaxpayerType:
    SMALL_SCALE = "小规模纳税人"
    GENERAL     = "一般纳税人"

    ALL = [SMALL_SCALE, GENERAL]


# ── ORM Model ───────────────────────────────────────────────────────────────────

class AccountSet(Base):
    __tablename__ = "account_set"

    # ── 主键 & 租户隔离 ────────────────────────────────────────────────────────
    account_set_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True,
    )
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, index=True,
        comment="FK → tenant.tenant_id — 顶层租户隔离"
    )

    # ── 基础核算信息 (Basic Info) ──────────────────────────────────────────────
    account_set_name: Mapped[str] = mapped_column(
        String(200), nullable=False,
        comment="账套显示名称，如'2026年度账'、'香港子公司'"
    )
    company_name: Mapped[str] = mapped_column(
        String(200), nullable=False,
        comment="公司全称（来自营业执照或手工填写）"
    )
    start_period: Mapped[str] = mapped_column(
        String(7), nullable=False,
        comment="启用年月 YYYY-MM。铁律二：产生凭证/余额后禁止修改"
    )
    fiscal_year_start_month: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1,
        comment="会计年度起始月份（中国默认1月）"
    )
    accounting_standard: Mapped[str] = mapped_column(
        String(30), nullable=False, default=AccountingStandard.SMALL_BIZ,
        comment="小企业会计准则 / 企业会计准则。铁律二：产生凭证后禁止修改"
    )
    taxpayer_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default=TaxpayerType.SMALL_SCALE,
        comment="小规模纳税人 / 一般纳税人"
    )

    # ── 税务与直连信息 (Tax & Compliance) ────────────────────────────────────
    uscc: Mapped[str | None] = mapped_column(
        String(18), nullable=True,
        comment="统一社会信用代码（18位）— AI 查验发票合规性的核心依据"
    )
    tax_bureau_region: Mapped[str | None] = mapped_column(
        String(100), nullable=True,
        comment="报税地区（如'北京市朝阳区'）"
    )
    tax_password: Mapped[str | None] = mapped_column(
        String(500), nullable=True,
        comment="电子申报密码（Fernet AES-128-CBC 加密后存储）"
    )

    # ── 功能开关 (Feature Toggles - JSON) ─────────────────────────────────────
    # 使用 Text 存储 JSON 字符串，兼容所有 MySQL 版本
    # 标准结构：{"asset_module": bool, "fund_module": bool, "decimals": int}
    module_settings: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment='JSON 功能开关：{"asset_module":true,"fund_module":false,"decimals":2}'
    )

    # ── 科目编码规则 (Subject Code Rule) - Sprint 2.1 ─────────────────────────
    # 格式："一级位数-二级延伸位数-三级延伸位数-..."
    # 默认 "4-2-2-2-2"：一级4位(1001)，二级+2位(100101)，三级+2位(10010101)
    # SubjectService.create_subject() 依赖此字段校验新建科目的编码长度规范
    subject_code_rule: Mapped[str] = mapped_column(
        String(30), nullable=False, default="4-2-2-2-2",
        comment="科目编码分级规则，如 '4-2-2-2-2'，影响子科目编码长度校验"
    )

    # ── 生命周期 & 回收站 (Lifecycle & Recycle Bin) ───────────────────────────
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default=AccountSetStatus.ONBOARDING,
        comment="ONBOARDING / ACTIVE / RECYCLED / SUSPENDED"
    )
    is_deleted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
        comment="软删除标记。True = 账套在回收站，所有业务查询自动过滤"
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True,
        comment="软删除时间戳（进入回收站时记录）"
    )
    activated_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True,
        comment="账套正式启用时间（状态切为 ACTIVE 时记录）"
    )

    # ── 时间戳 ────────────────────────────────────────────────────────────────
    created_at = mapped_column(
        DateTime, server_default=func.now(),
        comment="创建时间"
    )
    updated_at = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(),
        comment="最后更新时间"
    )

    # ── 属性助手 ──────────────────────────────────────────────────────────────

    @property
    def module_settings_dict(self) -> dict:
        """解析 module_settings JSON，未设置时返回系统默认值。"""
        if self.module_settings:
            try:
                return json.loads(self.module_settings)
            except (ValueError, TypeError):
                pass
        return {"asset_module": False, "fund_module": False, "decimals": 2}

    @property
    def is_active(self) -> bool:
        """账套是否处于可正常记账状态。"""
        return self.status == AccountSetStatus.ACTIVE and not self.is_deleted

    def __repr__(self) -> str:
        return (
            f"<AccountSet id={self.account_set_id} "
            f"company='{self.company_name}' "
            f"period={self.start_period} status={self.status}>"
        )
