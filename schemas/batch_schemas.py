"""
AgentLedger V4.0 — Batch Import Schemas (Sprint 3.5)

统一票据中间态：
  StandardReceiptItem  — 解析引擎（Excel/Vision）的统一输出格式，
                         无论来自结构化表格还是图片 OCR，都归一化为此格式。

批处理任务 API：
  ParsePreviewResponse  — parse-preview 返回体
  ExecuteBatchInput     — execute 请求体（前端核对完毕后提交）
  ExecuteBatchResponse  — execute 立即返回 task_id
  TaskProgressOut       — progress 轮询端点返回体
  BatchRecordOut        — 单条记录详情（含凭证 ID、置信度、是否需复核）
  BatchResultsOut       — results 端点返回体（三色分类汇总）

三色置信度含义（由 Sprint 3.4 calculate_confidence 输出，此处仅透传）：
  HIGH   — 绿灯，静默入库，needs_review=False
  MEDIUM — 黄灯，入库但 needs_review=True，前端标黄
  LOW    — 黄灯（Track B 冷启动），入库但 needs_review=True
"""
from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


# ══════════════════════════════════════════════════════════════════════════════
# 中间态票据结构
# ══════════════════════════════════════════════════════════════════════════════

class StandardReceiptItem(BaseModel):
    """
    解析引擎的统一输出中间态。

    无论来自 Excel 行还是图片 OCR，最终都转换为此格式，
    供前端"核对网格"展示和用户手动纠偏，再提交给批量入账流水线。
    """
    date:         date             = Field(..., description="票据日期")
    amount:       float            = Field(..., gt=0, description="金额（正数，元）")
    counterparty: Optional[str]    = Field(None, max_length=200, description="对方单位名称")
    summary:      str              = Field(..., min_length=1, max_length=300,
                                          description="业务摘要/品名/用途")
    file_url:     Optional[str]    = Field(None, description="原始文件 URL（可选，用于追溯）")


# ══════════════════════════════════════════════════════════════════════════════
# 阶段 1：预览解析
# ══════════════════════════════════════════════════════════════════════════════

class ParsePreviewResponse(BaseModel):
    """POST /api/batch/parse-preview 返回体。"""
    items:        list[StandardReceiptItem] = Field(..., description="解析出的票据列表")
    total:        int                       = Field(..., description="总条数")
    parse_engine: Literal["EXCEL", "VISION", "MIXED"] = Field(
        ...,
        description=(
            "实际使用的解析引擎：\n"
            "  EXCEL  — 结构化表格（xlsx/csv）\n"
            "  VISION — 视觉 LLM（图片/PDF）\n"
            "  MIXED  — 本批次同时含两种文件类型"
        ),
    )


# ══════════════════════════════════════════════════════════════════════════════
# 阶段 4：执行入账
# ══════════════════════════════════════════════════════════════════════════════

class ExecuteBatchInput(BaseModel):
    """POST /api/batch/execute 请求体（前端在核对网格修改后提交）。"""
    items:        list[StandardReceiptItem] = Field(
        ..., min_length=1, description="用户核对后的票据列表"
    )
    voucher_word: str = Field("记", max_length=10, description="凭证字（记/收/付/转）")


class ExecuteBatchResponse(BaseModel):
    """POST /api/batch/execute 立即返回体（202 Accepted）。"""
    task_id:     int = Field(..., description="批处理任务 ID，用于轮询 /progress")
    total_count: int = Field(..., description="本次任务包含的票据总条数")


# ══════════════════════════════════════════════════════════════════════════════
# 进度 & 结果
# ══════════════════════════════════════════════════════════════════════════════

class TaskProgressOut(BaseModel):
    """GET /api/batch/task/{task_id}/progress 返回体。"""
    task_id:            int
    status:             Literal["PENDING", "PROCESSING", "COMPLETED", "FAILED"]
    total_count:        int
    success_count:      int  = Field(..., description="已成功入账的条数（绿灯 + 黄灯）")
    error_count:        int  = Field(..., description="处理失败的条数（红灯）")
    needs_review_count: int  = Field(..., description="需人工复核的条数（黄灯，是 success 的子集）")
    created_at:         datetime
    updated_at:         Optional[datetime] = None


class BatchRecordOut(BaseModel):
    """单条批处理记录详情。"""
    id:           int
    raw_data:     StandardReceiptItem             = Field(..., description="原始票据数据")
    confidence:   Optional[Literal["HIGH", "MEDIUM", "LOW"]] = Field(
        None, description="AI 置信度（处理成功后才有）"
    )
    voucher_id:   Optional[int]                  = Field(None, description="生成的凭证 ID")
    needs_review: bool                           = Field(False, description="是否需人工复核")
    error_msg:    Optional[str]                  = Field(None, description="处理失败原因（红灯）")


class BatchResultsOut(BaseModel):
    """GET /api/batch/task/{task_id}/results 返回体（三色分类汇总）。"""
    task_id:      int
    status:       Literal["PENDING", "PROCESSING", "COMPLETED", "FAILED"]
    success:      list[BatchRecordOut] = Field(..., description="成功入账（绿灯 + 黄灯）")
    needs_review: list[BatchRecordOut] = Field(..., description="需复核（黄灯，是 success 的子集）")
    errors:       list[BatchRecordOut] = Field(..., description="处理失败（红灯）")
