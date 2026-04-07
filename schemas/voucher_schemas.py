"""
AgentLedger V4.0 — 凭证 CRUD Schemas (Sprint 3.2)

结构总览：
  ── 输入 ──────────────────────────────────────────────────────────────────────
  VoucherLineIn       手工录入单条凭证行（借或贷）
  VoucherCreateInput  手工新建凭证（头+行）
  VoucherUpdateInput  更新凭证（草稿状态，所有字段可选）
  VoucherReviewInput  审核/反审核补充参数（审核意见）
  ReorganizeInput     断号整理请求体

  ── 输出 ──────────────────────────────────────────────────────────────────────
  VoucherLineOut      凭证行返回体
  VoucherOut          凭证完整返回体（含行列表）
  VoucherListItem     凭证列表条目（不含行，轻量）
  PaginatedVouchers   分页凭证列表
  ReorganizeResult    断号整理执行结果

  ── 查询参数 ──────────────────────────────────────────────────────────────────
  VoucherQuery        GET /api/vouchers 的查询参数（用作 Depends()）
"""
from datetime import date, datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, model_validator


# ══════════════════════════════════════════════════════════════════════════════
# 凭证行
# ══════════════════════════════════════════════════════════════════════════════

class VoucherLineIn(BaseModel):
    """手工录入的单条凭证分录行。"""

    subject_code: str = Field(..., description="科目编码，必须是末级科目")
    direction: Literal["DEBIT", "CREDIT"] = Field(
        ..., description="方向：DEBIT=借方，CREDIT=贷方"
    )
    amount: float = Field(..., gt=0, description="金额（正数，精确到两位小数）")
    memo: Optional[str] = Field(None, max_length=200, description="行备注")
    auxiliary_entity_id: Optional[int] = Field(
        None, description="辅助核算实体 ID（查 /api/auxiliary-entities）"
    )


class VoucherLineOut(BaseModel):
    """凭证分录行返回体。"""

    line_id: int
    subject_code: str
    direction: Literal["DEBIT", "CREDIT"]
    amount: float
    memo: Optional[str]
    auxiliary_entity_id: Optional[int]

    model_config = {"from_attributes": True}


# ══════════════════════════════════════════════════════════════════════════════
# 凭证头：输入
# ══════════════════════════════════════════════════════════════════════════════

class VoucherCreateInput(BaseModel):
    """手工新建凭证请求体。"""

    voucher_date: date = Field(..., description="凭证日期")
    voucher_word: str = Field("记", max_length=10, description="凭证字（记/收/付/转）")
    memo: Optional[str] = Field(None, max_length=500, description="凭证摘要")
    lines: List[VoucherLineIn] = Field(..., min_length=2, description="分录行，至少借贷各一行")

    @model_validator(mode="after")
    def check_balanced(self) -> "VoucherCreateInput":
        debit  = sum(l.amount for l in self.lines if l.direction == "DEBIT")
        credit = sum(l.amount for l in self.lines if l.direction == "CREDIT")
        if abs(debit - credit) > 0.005:
            raise ValueError(
                f"借贷不平衡：借方合计 {debit:.2f} ≠ 贷方合计 {credit:.2f}。"
                "请检查各行金额。"
            )
        return self


class VoucherUpdateInput(BaseModel):
    """更新凭证请求体（仅草稿/待审状态允许修改）。"""

    voucher_date: Optional[date] = None
    voucher_word: Optional[str] = Field(None, max_length=10)
    memo: Optional[str] = Field(None, max_length=500)
    lines: Optional[List[VoucherLineIn]] = Field(
        None, min_length=2, description="若提供则完整替换所有行"
    )

    @model_validator(mode="after")
    def check_balanced_if_lines(self) -> "VoucherUpdateInput":
        if self.lines is not None:
            debit  = sum(l.amount for l in self.lines if l.direction == "DEBIT")
            credit = sum(l.amount for l in self.lines if l.direction == "CREDIT")
            if abs(debit - credit) > 0.005:
                raise ValueError(
                    f"借贷不平衡：借方合计 {debit:.2f} ≠ 贷方合计 {credit:.2f}。"
                )
        return self


class VoucherReviewInput(BaseModel):
    """审核 / 反审核操作的补充参数。"""

    review_note: Optional[str] = Field(None, max_length=500, description="审核意见（可选）")


# ══════════════════════════════════════════════════════════════════════════════
# 凭证头：输出
# ══════════════════════════════════════════════════════════════════════════════

class VoucherListItem(BaseModel):
    """凭证列表条目（轻量，不含分录行详情）。"""

    voucher_id: int
    voucher_number: Optional[int]
    voucher_word: Optional[str]
    voucher_date: str           # YYYY-MM-DD
    memo: Optional[str]
    total_amount: float
    review_status: str
    creator_id: Optional[int]
    reviewer_id: Optional[int]
    is_deleted: bool
    line_count: int             # Python 端计算，不存 DB
    created_at: str             # ISO datetime

    model_config = {"from_attributes": True}


class VoucherOut(BaseModel):
    """凭证完整返回体（含所有分录行）。"""

    voucher_id: int
    voucher_number: Optional[int]
    voucher_word: Optional[str]
    voucher_date: str
    memo: Optional[str]
    total_amount: float
    review_status: str
    creator_id: Optional[int]
    reviewer_id: Optional[int]
    review_note: Optional[str]
    reviewed_at: Optional[str]
    is_deleted: bool
    created_at: str
    lines: List[VoucherLineOut]

    model_config = {"from_attributes": True}


# ══════════════════════════════════════════════════════════════════════════════
# 分页
# ══════════════════════════════════════════════════════════════════════════════

class PaginatedVouchers(BaseModel):
    """分页凭证列表返回体。"""

    total: int = Field(..., description="总条数（未分页）")
    page: int = Field(..., description="当前页码（从 1 开始）")
    page_size: int = Field(..., description="每页条数")
    items: List[VoucherListItem]


# ══════════════════════════════════════════════════════════════════════════════
# 查询参数（作为 FastAPI Depends() 使用）
# ══════════════════════════════════════════════════════════════════════════════

class VoucherQuery(BaseModel):
    """
    GET /api/vouchers 查询参数。
    用法：q: VoucherQuery = Depends()
    """

    period_year:     Optional[int]   = Field(None, description="会计年度，如 2024")
    period_month:    Optional[int]   = Field(None, ge=1, le=12, description="会计月份 1-12")
    voucher_word:    Optional[str]   = Field(None, description="凭证字精确匹配，如 '记'")
    summary_keyword: Optional[str]   = Field(None, description="摘要关键词模糊搜索")
    subject_code:    Optional[str]   = Field(None, description="科目编码前缀匹配（如 1002 匹配 100201）")
    min_amount:      Optional[float] = Field(None, ge=0, description="金额下限（对 total_amount 过滤）")
    max_amount:      Optional[float] = Field(None, ge=0, description="金额上限")
    include_deleted: bool            = Field(False, description="是否包含软删除的凭证（默认 False）")
    page:            int             = Field(1, ge=1, description="页码")
    page_size:       int             = Field(20, ge=1, le=200, description="每页条数，上限 200")


# ══════════════════════════════════════════════════════════════════════════════
# 断号整理
# ══════════════════════════════════════════════════════════════════════════════

class ReorganizeInput(BaseModel):
    """POST /api/vouchers/reorganize 请求体。"""

    period_year:  int = Field(..., ge=2000, le=2099, description="会计年度")
    period_month: int = Field(..., ge=1, le=12, description="会计月份")


class ReorganizeResult(BaseModel):
    """断号整理执行结果。"""

    period: str = Field(..., description="执行的会计期间，如 '2024-06'")
    updated_count: int = Field(..., description="重新编号的凭证条数")
    message: str
