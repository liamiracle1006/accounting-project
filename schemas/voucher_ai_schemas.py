"""
AgentLedger V4.0 — AI 凭证生成 Schemas (Sprint 3.1)

输入/输出结构定义：
  GenerateVoucherInput  — 前端调用"生成凭证"接口的请求体
  VoucherLineOut        — 单条凭证行（借或贷）
  VoucherDraftOut       — AI 生成的凭证草稿（含断路器状态）

  HabitRuleCreateInput  — 创建业务习惯规则（DAG 模板）
  HabitRuleUpdateInput  — 更新业务习惯规则
  HabitRuleOut          — 规则返回体
"""
from datetime import date, datetime
from typing import Dict, Literal, Optional

from pydantic import BaseModel, Field, field_validator


# ══════════════════════════════════════════════════════════════════════════════
# 凭证生成：输入
# ══════════════════════════════════════════════════════════════════════════════

class GenerateVoucherInput(BaseModel):
    """调用 AI 凭证生成引擎的请求体。"""

    description: str = Field(
        ...,
        min_length=2,
        max_length=500,
        description="业务描述，如'阿里云服务器费用 3600元'、'报销星巴克咖啡 50元'",
    )
    voucher_date: date = Field(
        ...,
        description="凭证日期（决定摊销计算的时间基准）",
    )


# ══════════════════════════════════════════════════════════════════════════════
# 凭证生成：输出
# ══════════════════════════════════════════════════════════════════════════════

class VoucherLineOut(BaseModel):
    """凭证单行（借方或贷方）。"""

    subject_code: str = Field(..., description="科目编码")
    subject_name: Optional[str] = Field(None, description="科目名称（LLM 填写，仅供展示）")
    direction: Literal["DEBIT", "CREDIT"] = Field(
        ..., description="方向：DEBIT=借方，CREDIT=贷方"
    )
    amount: float = Field(..., gt=0, description="金额（正数）")
    memo: Optional[str] = Field(None, description="行备注")
    auxiliary_data: Optional[Dict[str, str]] = Field(
        None,
        description=(
            "辅助核算数据。仅当该科目开启了辅助核算维度时才需填写。"
            "例：应收账款挂客户 → {\"customer\": \"腾讯科技\"}；"
            "应付账款挂供应商 → {\"supplier\": \"阿里巴巴\"}；"
            "费用挂部门 → {\"dept\": \"技术部\"}。"
        ),
    )


class VoucherDraftOut(BaseModel):
    """
    AI 生成的凭证草稿。

    Sprint 3.1 阶段只输出 JSON，不写入数据库。
    Sprint 3.2 将在此基础上增加"确认入账"端点。

    review_status 含义：
      DRAFT               — 借贷平衡，可直接提交财务审核
      DRAFT_PENDING_REVIEW — 断路器触发（借贷不平），已挂入待查明科目，必须人工复核
    """

    memo: str = Field(..., description="凭证摘要")
    voucher_date: str = Field(..., description="凭证日期（YYYY-MM-DD）")
    lines: list[VoucherLineOut] = Field(..., description="凭证分录行列表")
    total_debit: float = Field(..., description="借方合计")
    total_credit: float = Field(..., description="贷方合计")
    is_balanced: bool = Field(..., description="借贷是否平衡")
    review_status: Literal["DRAFT", "DRAFT_PENDING_REVIEW"] = Field(
        ..., description="草稿状态"
    )
    circuit_breaker_triggered: bool = Field(
        False, description="是否触发了悬账断路器"
    )
    pending_review_reason: Optional[str] = Field(
        None, description="断路器触发原因（供财务人员参考）"
    )


# ══════════════════════════════════════════════════════════════════════════════
# 业务习惯规则（DAG 模板）：CRUD Schemas
# ══════════════════════════════════════════════════════════════════════════════

class HabitRuleCreateInput(BaseModel):
    """创建 DAG 业务习惯规则。"""

    rule_name: str = Field(
        ..., min_length=2, max_length=100,
        description="规则名称，如'阿里云服务器年费摊销'",
    )
    description: Optional[str] = Field(
        None, max_length=500,
        description="规则说明（帮助用户理解规则用途）",
    )
    keywords: list[str] = Field(
        ..., min_length=1,
        description="触发关键词列表，如 ['阿里云', '服务器', 'ECS']",
    )
    rule_json: dict = Field(
        ...,
        description=(
            "DAG 规则 JSON，格式：\n"
            "{\n"
            "  'nodes': [{'id':'N1','label':'...','subject_hint':'1801','action':'...'}],\n"
            "  'edges': [{'from':'N1','to':'N2','condition':'...'}]\n"
            "}"
        ),
    )
    is_active: bool = Field(True, description="是否立即启用")

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
