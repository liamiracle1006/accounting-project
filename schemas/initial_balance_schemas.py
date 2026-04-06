"""
AgentLedger V4.0 — 期初余额 Pydantic Schemas (Sprint 2.2)
"""
from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field, model_validator


# ── 辅助核算条目 ───────────────────────────────────────────────────────────────

class AuxiliaryEntry(BaseModel):
    """辅助核算的单个维度条目"""
    type: str   = Field(description="维度类型：customer/supplier/employee/project/dept")
    id:   int   = Field(description="auxiliary_entity.entity_id")
    name: str   = Field(description="实体名称（冗余存储，避免联查）")


# ── 单条期初录入 ──────────────────────────────────────────────────────────────

class InitialBalanceInput(BaseModel):
    """
    单条期初余额录入。
    year_start_balance 禁止传入，由后端推导。
    1月开账时 ytd_debit / ytd_credit 传入值会被强制归零。
    """
    subject_code:            str   = Field(description="科目编码")
    initial_balance:         float = Field(default=0.0, description="期初余额（本位币）")
    ytd_debit:               float = Field(default=0.0, description="本年累计借方（1月开账自动归零）")
    ytd_credit:              float = Field(default=0.0, description="本年累计贷方（1月开账自动归零）")
    # 外币维度
    currency_code:           Optional[str]   = Field(default=None)
    foreign_currency_amount: Optional[float] = Field(default=None)
    exchange_rate:           Optional[float] = Field(default=None)
    # 数量维度
    quantity:                Optional[float] = Field(default=None)
    unit_price:              Optional[float] = Field(default=None)
    # 辅助核算
    auxiliary_details:       list[AuxiliaryEntry] = Field(default_factory=list)

    @model_validator(mode="after")
    def non_negative_amounts(self) -> "InitialBalanceInput":
        for field in ("initial_balance", "ytd_debit", "ytd_credit"):
            if getattr(self, field) < 0:
                raise ValueError(f"{field} 不能为负数，请填写绝对值")
        return self


class BatchSaveInput(BaseModel):
    """批量保存期初余额（对应 UI 整张表格一次提交）"""
    rows: list[InitialBalanceInput] = Field(min_length=1)


# ── 响应 ─────────────────────────────────────────────────────────────────────

class InitialBalanceResponse(BaseModel):
    id:                      int
    subject_code:            str
    subject_name:            str
    balance_direction:       str
    initial_balance:         float
    ytd_debit:               float
    ytd_credit:              float
    year_start_balance:      float
    currency_code:           Optional[str]
    foreign_currency_amount: Optional[float]
    exchange_rate:           Optional[float]
    quantity:                Optional[float]
    unit_price:              Optional[float]
    auxiliary_details:       list[AuxiliaryEntry]
    auxiliary_hash:          str
    is_ai_sponge:            bool
    direction_warning:       Optional[str] = Field(
        default=None,
        description="余额方向异常警告（借方科目出现贷方余额），不阻塞保存"
    )


class SubjectWithBalance(BaseModel):
    """科目树节点 + 期初余额（主页面联合查询）"""
    subject_code:      str
    subject_name:      str
    category:          str
    balance_direction: str
    level:             int
    has_children:      bool
    initial_balance:   float = 0.0
    ytd_debit:         float = 0.0
    ytd_credit:        float = 0.0
    year_start_balance: float = 0.0
    is_ai_sponge:      bool = False
    children:          list["SubjectWithBalance"] = Field(default_factory=list)


# ── 试算平衡 ──────────────────────────────────────────────────────────────────

class TrialBalanceLine(BaseModel):
    dimension:     str   = Field(description="期初余额 / 累计借方 / 累计贷方 / 年初余额")
    total_debit:   float
    total_credit:  float
    difference:    float
    is_balanced:   bool


class TrialBalanceResult(BaseModel):
    """本位币综合试算平衡"""
    lines:       list[TrialBalanceLine]
    is_balanced: bool
    sponge_amount: float = Field(
        default=0.0,
        description="借贷差额（完成建账时将写入 1901），0 表示平衡"
    )


class ForeignTrialBalanceLine(BaseModel):
    currency_code: str
    total_debit:   float
    total_credit:  float
    difference:    float
    is_balanced:   bool


# ── 完成建账 ──────────────────────────────────────────────────────────────────

class CompleteAccountSetupResult(BaseModel):
    success:          bool
    account_set_id:   int
    final_status:     str
    was_balanced:     bool
    sponge_amount:    float = 0.0
    sponge_subject:   Optional[str] = None
    message:          str
