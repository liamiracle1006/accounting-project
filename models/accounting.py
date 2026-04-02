"""
AgentLedger V4.0 — 科目体系双表模型 (Sprint 2.1)

架构：模板表 + 租户实例表（彻底废弃"全局共享科目表"幻想）

┌─────────────────────────────────────────────────────────────────┐
│  SystemSubject（系统标准科目模板）                                 │
│  • 全局只读，不含 TenantMixin                                     │
│  • 按 standard_type 区分小企业准则/企业准则/通用                    │
│  • 存放 parent_code / level / category 完整树结构                  │
│  → 账套创建时，从此表全量克隆到 TenantSubject                       │
└─────────────────────────────────────────────────────────────────┘
              ↓ init_tenant_subjects (骨架软启动)
┌─────────────────────────────────────────────────────────────────┐
│  TenantSubject（租户科目实例 - 图谱核心节点）                       │
│  • 继承 TenantMixin（tenant_id + account_set_id）                 │
│  • UNIQUE (tenant_id, account_set_id, subject_code)              │
│  • node_features (JSON): 数量核算 / 外币 / 辅助维度                │
│    Sprint 3 中 GraphRetriever 将直接反序列化为 NetworkX 节点属性   │
│  • is_deleted (软删除)                                            │
└─────────────────────────────────────────────────────────────────┘

图节点 ID 契约（Graph ID Contract）：
  全局唯一节点标识 = f"{tenant_id}::{account_set_id}::{subject_code}"
  业务层和图引擎统一使用此格式，数据库自增 id 仅作内部 PK。
"""
import json
from datetime import datetime

from sqlalchemy import (
    BigInteger, Boolean, DateTime, Index, Integer,
    String, Text, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column

from database.connection import Base
from models.mixins import TenantMixin


# ── 枚举常量 ───────────────────────────────────────────────────────────────────

class SubjectCategory:
    """科目类别（对应会计要素）"""
    ASSET     = "资产"
    LIABILITY = "负债"
    EQUITY    = "权益"
    COST      = "成本"    # 主营/其他业务成本
    PROFIT    = "损益"    # 收入+费用（损益类）


class BalanceDirection:
    """余额方向"""
    DEBIT  = "借"
    CREDIT = "贷"


class StandardType:
    """适用的会计准则"""
    SMALL_BIZ = "SMALL_BIZ"   # 小企业会计准则
    GENERAL   = "GENERAL"     # 企业会计准则
    COMMON    = "COMMON"      # 两套准则均适用


# ── 默认 node_features 结构 ─────────────────────────────────────────────────────

DEFAULT_NODE_FEATURES: dict = {
    "quantity_accounting":  {"enabled": False, "unit": None},      # 数量核算
    "foreign_currency":     {"enabled": False, "currency": None},  # 外币核算
    "auxiliary_dimensions": [],   # 辅助核算维度：customer/supplier/employee/project/dept
}


# ══════════════════════════════════════════════════════════════════════════════
# 1. SystemSubject — 系统标准科目模板表（全局只读）
# ══════════════════════════════════════════════════════════════════════════════

class SystemSubject(Base):
    """
    系统内置标准科目库。
    只读，不参与 TenantSession 拦截（无 TenantMixin）。
    通过 SubjectService.init_tenant_subjects() 克隆到各租户账套。
    """
    __tablename__ = "system_subject"

    subject_code: Mapped[str] = mapped_column(
        String(20), primary_key=True,
        comment="科目编码，如 '1001'、'100201'"
    )
    subject_name: Mapped[str] = mapped_column(
        String(100), nullable=False,
        comment="科目名称，如'库存现金'、'银行存款'"
    )
    parent_code: Mapped[str | None] = mapped_column(
        String(20), nullable=True,
        comment="上级科目编码（一级科目为 NULL）"
    )
    category: Mapped[str] = mapped_column(
        String(10), nullable=False,
        comment="科目类别：资产/负债/权益/成本/损益"
    )
    balance_direction: Mapped[str] = mapped_column(
        String(2), nullable=False,
        comment="余额方向：借/贷"
    )
    level: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1,
        comment="科目层级：1=一级科目，2=二级科目，以此类推"
    )
    standard_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default=StandardType.COMMON,
        comment="适用准则：SMALL_BIZ / GENERAL / COMMON（两套均适用）"
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
        comment="排序序号（决定科目在报表中的显示顺序）"
    )
    created_at = mapped_column(DateTime, server_default=func.now())

    def __repr__(self) -> str:
        return f"<SystemSubject {self.subject_code} {self.subject_name}>"


# ══════════════════════════════════════════════════════════════════════════════
# 2. TenantSubject — 租户科目实例表（图谱核心节点）
# ══════════════════════════════════════════════════════════════════════════════

class TenantSubject(TenantMixin, Base):
    """
    租户专属科目实例，是整个图谱的核心节点。

    Graph ID 契约：
      node_id = f"{tenant_id}::{account_set_id}::{subject_code}"
      Sprint 3 的 NetworkX 图引擎将使用此格式作为节点唯一标识。

    node_features (JSON) 设计：
      {
        "quantity_accounting":  {"enabled": true,  "unit": "件"},
        "foreign_currency":     {"enabled": false, "currency": null},
        "auxiliary_dimensions": ["customer", "project"]
      }
      auxiliary_dimensions 的合法值：customer / supplier / employee / project / dept
      → 直接关联 auxiliary_entity 表的 entity_type 字段
    """
    __tablename__ = "tenant_subject"

    __table_args__ = (
        # 同一账套内科目编码唯一（图节点 ID 唯一性保障）
        UniqueConstraint(
            "tenant_id", "account_set_id", "subject_code",
            name="uq_ts_tenant_as_code",
        ),
        # 复合查询索引
        Index("idx_ts_tenant_as", "tenant_id", "account_set_id"),
        Index("idx_ts_parent",    "tenant_id", "account_set_id", "parent_code"),
    )

    # ── 主键 ────────────────────────────────────────────────────────────────
    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True,
        comment="内部自增主键（图引擎使用 subject_code 作为节点标识，非此字段）"
    )

    # ── 科目基础字段（与 SystemSubject 镜像）────────────────────────────────
    subject_code: Mapped[str] = mapped_column(
        String(20), nullable=False,
        comment="科目编码（在账套内唯一），如 '1001'、'100201'"
    )
    subject_name: Mapped[str] = mapped_column(
        String(100), nullable=False,
        comment="科目名称"
    )
    parent_code: Mapped[str | None] = mapped_column(
        String(20), nullable=True,
        comment="上级科目编码（NULL = 一级科目）"
    )
    category: Mapped[str] = mapped_column(
        String(10), nullable=False,
        comment="科目类别：资产/负债/权益/成本/损益"
    )
    balance_direction: Mapped[str] = mapped_column(
        String(2), nullable=False,
        comment="余额方向：借/贷（有凭证后禁止修改）"
    )
    level: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1,
        comment="科目层级：1=一级科目"
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
        comment="账套内排序序号"
    )

    # ── 追溯来源（可选，自定义科目为 NULL）─────────────────────────────────
    system_subject_code: Mapped[str | None] = mapped_column(
        String(20), nullable=True,
        comment="来源系统标准科目编码（自定义科目为 NULL）"
    )

    # ── 🔥 图节点动态属性（核心 JSONB 字段）────────────────────────────────
    # Sprint 3 中，GraphRetriever 直接将此字段反序列化为 NetworkX 节点 attributes
    # 存储格式见类文档中的 node_features 设计
    node_features: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="图节点动态属性 JSON：数量核算/外币核算/辅助核算维度配置"
    )

    # ── 状态与软删除 ─────────────────────────────────────────────────────
    is_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True,
        comment="是否启用（停用后不可用于新凭证，但历史凭证不受影响）"
    )
    is_deleted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
        comment="软删除标记（有发生额时禁止删除）"
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True,
        comment="软删除时间戳"
    )

    # ── 时间戳 ──────────────────────────────────────────────────────────
    created_at = mapped_column(DateTime, server_default=func.now())
    updated_at = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    # ── 属性助手 ────────────────────────────────────────────────────────

    @property
    def node_features_dict(self) -> dict:
        """反序列化 node_features JSON，未设置时返回默认结构（Sprint 3 图引擎入口）。"""
        if self.node_features:
            try:
                return json.loads(self.node_features)
            except (ValueError, TypeError):
                pass
        return dict(DEFAULT_NODE_FEATURES)

    @property
    def graph_node_id(self) -> str:
        """
        图谱节点全局唯一标识符（Graph ID Contract）。
        格式："{tenant_id}::{account_set_id}::{subject_code}"
        """
        return f"{self.tenant_id}::{self.account_set_id}::{self.subject_code}"

    def __repr__(self) -> str:
        return (
            f"<TenantSubject {self.subject_code} '{self.subject_name}' "
            f"[{self.category}/{self.balance_direction}] "
            f"tenant={self.tenant_id} as={self.account_set_id}>"
        )
