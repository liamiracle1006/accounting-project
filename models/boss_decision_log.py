"""
AgentLedger — BossDecisionLog model

记录 AI 针对某笔大额/敏感流水生成的多个处理方案，以及老板的最终选择。

ai_options_json 结构（完整示例见 ai/decision_prompts.py）：
{
  "asset_category": "通用机械设备",
  "tax_analysis": "...",
  "options": [
    {
      "id": "ONE_TIME",
      "label": "方案一",
      "title": "一次性全额扣除",
      "action_code": "FIXED_ASSET_ONE_TIME",
      "useful_life_months": 0,
      "savings_this_year": 70000,
      "savings_total": 70000,
      "plain_text": "...",
      "suitable_when": "...",
      "risk": "..."
    },
    ...
  ],
  "recommendation": "ONE_TIME",
  "recommendation_reason": "...",
  "financial_snapshot": { "ytd_profit": 620000, "current_cash": 890000 }
}

status 流转：
  PENDING_DECISION → DECIDED（老板选择后）
  PENDING_DECISION → EXPIRED（超时未决策）
"""
from datetime import datetime, timedelta

from sqlalchemy import BigInteger, Text, String, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from database.connection import Base


class DecisionStatus:
    PENDING_DECISION = "PENDING_DECISION"
    DECIDED          = "DECIDED"
    EXPIRED          = "EXPIRED"


class BossDecisionLog(Base):
    __tablename__ = "boss_decision_log"

    decision_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    record_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False,
        comment="FK → operational_record"
    )

    ai_options_json: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="AI 生成的完整方案 JSON（含所有选项、财务快照、推荐理由）"
    )

    boss_choice: Mapped[str | None] = mapped_column(
        String(50), nullable=True,
        comment="老板选择的方案 id（如 ONE_TIME、STRAIGHT_10Y 等）"
    )

    chosen_action_code: Mapped[str | None] = mapped_column(
        String(50), nullable=True,
        comment="选中方案对应的 action_code，后端据此执行凭证生成"
    )

    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default=DecisionStatus.PENDING_DECISION,
        comment="PENDING_DECISION / DECIDED / EXPIRED"
    )

    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True,
        comment="决策有效期，超时自动标记为 EXPIRED"
    )

    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True,
        comment="老板做出决策的时间"
    )

    created_at = mapped_column(DateTime, server_default=func.now())

    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return datetime.utcnow() > self.expires_at

    def __repr__(self) -> str:
        return (
            f"<BossDecisionLog id={self.decision_id} "
            f"record={self.record_id} status={self.status}>"
        )
