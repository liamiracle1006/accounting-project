"""
AgentLedger V4.0 — TenantHabitRule 模型 (Sprint 3.1)

设计理念：
  每条规则是一个「DAG 模板」，描述某类业务的标准记账路径。
  物理存储：MySQL JSON 字段 → Python dict → LLM 阅读推理。
  LLM 本身就是图遍历引擎，rule_json 是它的"业务地图"。

rule_json 标准格式：
  {
    "nodes": [
      {"id": "N1", "label": "首付挂长期待摊", "subject_hint": "1801", "action": "首次付款时执行"},
      {"id": "N2", "label": "次月起每月摊销", "subject_hint": "6602", "action": "次月1日起每月执行"}
    ],
    "edges": [
      {"from": "N1", "to": "N2", "condition": "次月1日起按月摊销，至金额归零"}
    ]
  }

keywords 标准格式（JSON 数组字符串）：
  ["阿里云", "服务器", "云服务", "ECS"]
"""
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from database.connection import Base
from models.mixins import TenantMixin


class TenantHabitRule(TenantMixin, Base):
    """
    租户业务习惯规则表（DAG 模板仓库）。

    每条记录代表一个「业务场景 → 记账路径」的映射规则。
    HabitRetriever 通过关键词匹配找到相关规则，将 rule_json 注入 LLM Prompt。
    """
    __tablename__ = "tenant_habit_rule"

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True,
        comment="规则自增主键"
    )

    # ── 规则标识 ─────────────────────────────────────────────────────────────
    rule_name: Mapped[str] = mapped_column(
        String(100), nullable=False,
        comment="规则名称，如'阿里云服务器年费摊销'"
    )
    description: Mapped[str | None] = mapped_column(
        String(500), nullable=True,
        comment="规则说明（显示给用户，帮助理解规则用途）"
    )

    # ── 触发关键词（JSON 数组存为文本）──────────────────────────────────────
    keywords: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="触发关键词 JSON 数组，如 [\"阿里云\",\"服务器\",\"ECS\"]"
    )

    # ── DAG 规则核心（JSON 存为文本）────────────────────────────────────────
    rule_json: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="DAG 规则 JSON：{nodes:[{id,label,subject_hint,action}], edges:[{from,to,condition}]}"
    )

    # ── 状态 ─────────────────────────────────────────────────────────────────
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True,
        comment="是否启用（停用后不参与关键词匹配）"
    )

    # ── 时间戳 ──────────────────────────────────────────────────────────────
    created_at = mapped_column(DateTime, server_default=func.now())
    updated_at = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return (
            f"<TenantHabitRule id={self.id} '{self.rule_name}' "
            f"tenant={self.tenant_id} as={self.account_set_id} "
            f"active={self.is_active}>"
        )
