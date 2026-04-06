"""
AgentLedger V4.0 — 旧账导入 Pydantic Schemas (Sprint 2.3)

覆盖所有 /api/imports/* 端点的请求体和响应体。
"""
from __future__ import annotations

from typing import Any, Literal, Optional
from pydantic import BaseModel, Field


# ── 会话相关 ───────────────────────────────────────────────────────────────────

class CreateSessionInput(BaseModel):
    source_system: Literal["金蝶", "用友", "管家婆", "其他Excel"] = Field(
        description="旧系统类型"
    )
    original_filename: Optional[str] = Field(default=None, max_length=255)


class ImportSessionResponse(BaseModel):
    session_id:        int
    source_system:     str
    status:            str
    original_filename: Optional[str]
    header_mapping:    Optional[dict]


# ── 向导提示（阶段一） ─────────────────────────────────────────────────────────

class ExportGuideResponse(BaseModel):
    source_system: str
    tips:          list[str] = Field(description="导出操作提示列表")
    sample_columns: list[str] = Field(description="该系统典型导出列名示例")


# ── 上传清洗结果（阶段二） ─────────────────────────────────────────────────────

class UploadRawDataResponse(BaseModel):
    session_id:    int
    rows_loaded:   int    = Field(description="写入 ImportStaging 的行数")
    columns_found: list[str] = Field(description="Excel 中检测到的列名")
    header_mapping: dict[str, Any] = Field(description="LLM 推断的列名映射")
    warnings:      list[str] = Field(default_factory=list)


# ── 科目匹配结果（阶段三） ─────────────────────────────────────────────────────

class MapSubjectsResponse(BaseModel):
    session_id:             int
    confirmed:              int  = Field(description="自动 CONFIRMED 的行数")
    pending_review:         int  = Field(description="需要人工复核的行数")
    auto_created_subjects:  int  = Field(description="智能派生自动创建的子科目数")
    skipped:                int  = Field(description="因数据缺失自动跳过的行数")
    session_status:         str  = Field(description="会话新状态")


class AbnormalSubjectItem(BaseModel):
    staging_id:    int
    row_number:    int
    raw_code:      Optional[str]
    raw_name:      Optional[str]
    ai_suggestions: list[dict] = Field(default_factory=list,
                                       description="AI 建议的最多3个候选科目")


class ConfirmSubjectInput(BaseModel):
    subject_code: str = Field(description="人工选定的系统科目编码")


class SkipSubjectInput(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=200,
                                  description="跳过原因说明（可选）")


# ── 正式结转（阶段四） ─────────────────────────────────────────────────────────

class ExecuteImportResponse(BaseModel):
    session_id:     int
    imported:       int    = Field(description="成功写入 InitialBalance 的行数")
    skipped:        int    = Field(description="SKIPPED 行数（不计入）")
    was_balanced:   bool   = Field(description="结转后试算平衡是否平")
    sponge_amount:  float  = Field(description="1901 海绵补差金额（0.0 表示已平）")
    errors:         list[dict] = Field(default_factory=list,
                                       description="逐行错误列表 [{staging_id, reason}]")
