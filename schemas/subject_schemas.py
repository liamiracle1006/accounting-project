"""
AgentLedger V4.0 — 科目 Pydantic Schemas (Sprint 2.1)

Pydantic V2 风格。
node_features 使用子模型做强类型校验，前端传错字段立即 422。
"""
from __future__ import annotations

from typing import Literal, Optional
from pydantic import BaseModel, Field, field_validator, model_validator


# ── node_features 子模型 ───────────────────────────────────────────────────────

AuxDimension = Literal["customer", "supplier", "employee", "project", "dept"]


class QuantityAccounting(BaseModel):
    """数量核算配置"""
    enabled: bool = False
    unit:    Optional[str] = Field(default=None, max_length=10, description="计量单位，如'件'、'kg'")


class ForeignCurrency(BaseModel):
    """外币核算配置"""
    enabled:  bool = False
    currency: Optional[str] = Field(default=None, max_length=10, description="币种代码，如'USD'、'EUR'")


class NodeFeatures(BaseModel):
    """
    科目图节点动态属性（对标柠檬云的科目高级设置）。
    直接对应 TenantSubject.node_features JSON 字段的完整结构。
    Sprint 3 图引擎将此结构反序列化为 NetworkX 节点属性。
    """
    quantity_accounting:  QuantityAccounting = Field(default_factory=QuantityAccounting)
    foreign_currency:     ForeignCurrency    = Field(default_factory=ForeignCurrency)
    auxiliary_dimensions: list[AuxDimension] = Field(
        default_factory=list,
        description="辅助核算维度列表，合法值：customer/supplier/employee/project/dept"
    )

    @field_validator("auxiliary_dimensions")
    @classmethod
    def no_duplicate_dimensions(cls, v: list) -> list:
        if len(v) != len(set(v)):
            raise ValueError("auxiliary_dimensions 中不允许重复的维度值")
        return v


# ── 请求 Schemas ──────────────────────────────────────────────────────────────

class SubjectCreate(BaseModel):
    """创建科目请求体"""
    subject_code:     str = Field(min_length=1, max_length=20, description="科目编码")
    subject_name:     str = Field(min_length=1, max_length=100, description="科目名称")
    parent_code:      Optional[str] = Field(default=None, max_length=20, description="上级科目编码")
    category:         Literal["资产", "负债", "权益", "成本", "损益"] = Field(
                          description="科目类别"
                      )
    balance_direction: Literal["借", "贷"] = Field(description="余额方向")
    node_features:    NodeFeatures = Field(default_factory=NodeFeatures, description="图节点属性")
    sort_order:       int = Field(default=0, description="排序序号")

    @field_validator("subject_code")
    @classmethod
    def code_digits_only(cls, v: str) -> str:
        v = v.strip()
        if not v.isdigit():
            raise ValueError("subject_code 只允许数字字符，如 '100201'")
        return v

    @field_validator("subject_name")
    @classmethod
    def name_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("subject_name 不能为空白字符串")
        return v


class SubjectUpdate(BaseModel):
    """
    更新科目请求体。
    balance_direction / category 若账套有凭证则由 Service 层拒绝修改。
    """
    subject_name:      Optional[str]           = Field(default=None, max_length=100)
    balance_direction: Optional[Literal["借", "贷"]] = None
    category:          Optional[Literal["资产", "负债", "权益", "成本", "损益"]] = None
    node_features:     Optional[NodeFeatures]  = None
    is_enabled:        Optional[bool]          = None
    sort_order:        Optional[int]           = None


class SubjectBatchImportRow(BaseModel):
    """
    批量导入单行（支持非标格式，AI Header Mapping 预处理后使用）。
    AI 将用户上传的自由格式 Excel 列名映射到此 Schema。
    """
    subject_code:      str
    subject_name:      str
    parent_code:       Optional[str] = None
    category:          Optional[str] = None   # AI 推断后填充
    balance_direction: Optional[str] = None   # AI 推断后填充
    sort_order:        int = 0


# ── 响应 Schemas ──────────────────────────────────────────────────────────────

class SubjectResponse(BaseModel):
    """单个科目响应"""
    id:               int
    subject_code:     str
    subject_name:     str
    parent_code:      Optional[str]
    category:         str
    balance_direction: str
    level:            int
    sort_order:       int
    is_enabled:       bool
    is_deleted:       bool
    node_features:    NodeFeatures
    graph_node_id:    str = Field(description="图节点全局唯一标识：tenant_id::account_set_id::subject_code")
    system_subject_code: Optional[str] = None
    created_at:       Optional[str] = None
    updated_at:       Optional[str] = None

    model_config = {"from_attributes": True}


class SubjectTreeNode(BaseModel):
    """科目树节点（递归结构，用于树形展示）"""
    id:               int
    subject_code:     str
    subject_name:     str
    category:         str
    balance_direction: str
    level:            int
    is_enabled:       bool
    node_features:    NodeFeatures
    graph_node_id:    str
    children:         list["SubjectTreeNode"] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class RefactorSuggestion(BaseModel):
    """AI 科目重构建议（detect_refactor_opportunity 返回）"""
    subject_code:    str
    subject_name:    str
    child_count:     int
    suggestion:      str = Field(description="建议描述，如'建议升级为客户辅助核算'")
    suggested_dimension: str = Field(description="建议的辅助维度：customer/supplier/employee/project/dept")
