"""
AgentLedger V4.0 — 业务习惯规则 Schemas (Sprint 3.4)

从 voucher_ai_schemas.py 拆分独立，高内聚低耦合。

Sprint 3.4 扩展：edge 新增三个字段（存于 rule_json.edges[*]）：
  weight           int          — 命中频次，默认 1，每次学习确认 +1
  last_used_at     ISO str      — 最后使用时间
  context_features dict        — 触发环境特征：
    subject_combo  list[str]   — 科目+方向组合，如 ["6602-DEBIT","1002-CREDIT"]
    line_templates list[dict]  — 凭证行模板 {subject_code, direction, ratio, memo_hint}
    min_amount     float       — 历史最小金额
    max_amount     float       — 历史最大金额

以上字段均存在 TEXT 列（rule_json）里，无需改表结构。
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class HabitRuleCreateInput(BaseModel):
    """创建 DAG 业务习惯规则。"""

    rule_name: str = Field(
        ..., min_length=2, max_length=100,
        description="规则名称，如'阿里云服务器年费摊销'",
    )
    description: Optional[str] = Field(None, max_length=500)
    keywords: list[str] = Field(..., min_length=1)
    rule_json: dict = Field(
        ...,
        description=(
            "DAG 规则 JSON：{nodes:[...], edges:[...]}\n"
            "Sprint 3.4 edge 可选扩展字段：weight / last_used_at / context_features"
        ),
    )
    is_active: bool = Field(True)

    @field_validator("keywords")
    @classmethod
    def keywords_not_empty(cls, v: list[str]) -> list[str]:
        cleaned = [kw.strip() for kw in v if kw.strip()]
        if not cleaned:
            raise ValueError("keywords 列表中至少需要一个非空关键词")
        return cleaned


class HabitRuleUpdateInput(BaseModel):
    """更新 DAG 业务习惯规则（所有字段可选）。"""

    rule_name: Optional[str] = Field(None, min_length=2, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    keywords: Optional[list[str]] = None
    rule_json: Optional[dict] = None
    is_active: Optional[bool] = None

    @field_validator("keywords")
    @classmethod
    def keywords_not_empty(cls, v: Optional[list[str]]) -> Optional[list[str]]:
        if v is None:
            return v
        cleaned = [kw.strip() for kw in v if kw.strip()]
        if not cleaned:
            raise ValueError("keywords 列表中至少需要一个非空关键词")
        return cleaned


class HabitRuleOut(BaseModel):
    """业务习惯规则返回体。"""

    id: int
    rule_name: str
    description: Optional[str]
    keywords: list[str]
    rule_json: dict
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
