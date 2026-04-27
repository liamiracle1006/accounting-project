"""
AgentLedger V4.0 — AI 凭证生成 Schemas (Sprint 3.1 / 3.2 / 3.4)

输入/输出结构定义：
  GenerateVoucherInput  — 前端调用"生成凭证"接口的请求体
  VoucherLineOut        — 单条凭证行（借或贷）
  VoucherDraftOut       — AI 生成的凭证草稿（含断路器状态）

  RecommendationItem    — 双轨制单条推荐（Sprint 3.4 新增）
  DualTrackResponse     — /generate 返回体，含 Track A + Track B（Sprint 3.4 新增）

  HabitRuleCreateInput / HabitRuleUpdateInput / HabitRuleOut
    → 已迁移至 schemas/habit_schemas.py（Sprint 3.4 拆分）
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
# 双轨制推荐（Sprint 3.4 新增）
# ══════════════════════════════════════════════════════════════════════════════

class RecommendationItem(BaseModel):
    """
    双轨制单条推荐。

    Track A（HABIT）：基于历史习惯 DAG 重建的草稿，附带确定性置信度。
    Track B（AI_RULE）：LLM 零样本推理生成的草稿，兜底方案。

    前端工作流：
      1. 展示 recommendations 数组（最多 2 条：A + B，或仅 B）
      2. 用户选择其中一条
      3. POST /confirm 时带上该条的 habit_rule_id（Track A 非 None，Track B 为 None）
    """

    track: Literal["A", "B"] = Field(..., description="推荐轨道：A=历史习惯，B=AI准则")
    source: Literal["HABIT", "AI_RULE"] = Field(..., description="来源标识")
    confidence: Literal["HIGH", "MEDIUM", "LOW"] = Field(
        ...,
        description=(
            "置信度：\n"
            "  HIGH   — weight>3 且金额在历史区间，可进入批量自动处理\n"
            "  MEDIUM — 有历史路径但金额突变或样本少，需人工扫一眼\n"
            "  LOW    — 纯新业务/Track B，绝不允许静默入库"
        ),
    )
    habit_rule_id: Optional[int] = Field(
        None,
        description="Track A 的规则 ID，/confirm 时原样传回用于学习溯源；Track B 为 None",
    )
    draft: VoucherDraftOut = Field(..., description="凭证草稿")


class DualTrackResponse(BaseModel):
    """
    POST /api/voucher-ai/generate 的返回体（Sprint 3.4 新格式）。

    冷启动（无历史习惯）：recommendations 只含 Track B（1 条）。
    有历史习惯：recommendations 含 Track A + Track B（2 条），Track A 排在前面。
    """

    recommendations: list[RecommendationItem] = Field(
        ...,
        description="推荐列表（1-2 条），前端按顺序展示给财务人员选择",
    )


# ══════════════════════════════════════════════════════════════════════════════
# 确认入账：将 AI 草稿写入数据库（Sprint 3.2 新增）
# ══════════════════════════════════════════════════════════════════════════════

class ConfirmLineIn(BaseModel):
    """
    确认入账时的单条凭证行。
    直接复用 AI 草稿的 lines 字段，前端透传即可。
    """

    subject_code: str = Field(..., description="科目编码")
    direction: Literal["DEBIT", "CREDIT"]
    amount: float = Field(..., gt=0, description="金额（正数）")
    memo: Optional[str] = None
    auxiliary_data: Optional[Dict[str, str]] = Field(
        None,
        description=(
            "辅助核算数据，由后端转换为 auxiliary_entity_id。"
            "合法 key：customer / supplier / employee / project / dept"
        ),
    )


class ConfirmVoucherInput(BaseModel):
    """
    POST /api/voucher-ai/confirm 请求体。

    前端收到 /generate 的草稿后，让用户确认，
    连同原始业务描述（用于创建 OperationalRecord）一起提交。
    """

    description: str = Field(
        ...,
        min_length=2,
        max_length=500,
        description="原始业务描述，写入 OperationalRecord.raw_text",
    )
    voucher_date: date = Field(..., description="凭证日期")
    voucher_word: str = Field("记", max_length=10, description="凭证字（记/收/付/转）")
    memo: str = Field(..., max_length=500, description="凭证摘要（来自草稿的 memo）")
    lines: list[ConfirmLineIn] = Field(..., min_length=2, description="凭证分录行")
    habit_rule_id: Optional[int] = Field(
        None,
        description=(
            "用户选择了 Track A（历史习惯）时，传入对应的 habit_rule_id。\n"
            "Track B（AI 准则）确认时留 None，后端将自动创建新习惯规则。"
        ),
    )
