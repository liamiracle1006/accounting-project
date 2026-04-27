"""
AgentLedger V4.0 — Batch Import API Routes (Sprint 3.5)

端点一览：
  POST  /api/batch/parse-preview           — 文件预解析，返回 JSON 数组供前端核对网格
  POST  /api/batch/execute                 — 提交核对后的票据，创建任务 + 触发后台流水线
  GET   /api/batch/task/{task_id}/progress — 实时进度轮询（供前端画进度条）
  GET   /api/batch/task/{task_id}/results  — 任务完成后的三色明细报告

文件路由规则：
  .xlsx / .xls / .csv → Excel 结构化解析引擎（services/excel_parser_service）
  图片（jpg/png/webp）/ PDF → Vision LLM 引擎（services/vision_service）
  同一批次可混合上传，结果合并返回（parse_engine="MIXED"）
"""
import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from database.connection import get_db
from models.batch_task import BatchImportTask, BatchImportRecord
from models.user_account import UserAccount
from schemas.batch_schemas import (
    BatchRecordOut,
    BatchResultsOut,
    ExecuteBatchInput,
    ExecuteBatchResponse,
    ParsePreviewResponse,
    StandardReceiptItem,
    TaskProgressOut,
)
from services.auth_service import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/batch", tags=["batch"])


# ── 上下文 helper ─────────────────────────────────────────────────────────────

def _get_ctx(db: Session = Depends(get_db)) -> tuple[int, int]:
    from database.tenant_context import get_current_tenant
    ctx = get_current_tenant()
    if ctx is None:
        raise HTTPException(status_code=400, detail="未设置租户上下文，请先登录")
    if ctx.account_set_id is None:
        raise HTTPException(status_code=400, detail="请先选择账套（account_set_id 未设置）")
    return ctx.tenant_id, ctx.account_set_id


def _is_excel(filename: str, content_type: str) -> bool:
    fn = (filename or "").lower()
    ct = (content_type or "").lower()
    return (
        fn.endswith((".xlsx", ".xls", ".csv"))
        or "spreadsheet" in ct
        or "csv" in ct
        or "excel" in ct
    )


# ══════════════════════════════════════════════════════════════════════════════
# 1. 文件预解析
# ══════════════════════════════════════════════════════════════════════════════

@router.post(
    "/parse-preview",
    response_model=ParsePreviewResponse,
    status_code=200,
    summary="文件预解析（不生成凭证），返回票据 JSON 供前端核对网格",
)
async def parse_preview(
    files: list[UploadFile] = File(..., description="上传 .xlsx/.csv 或图片/PDF"),
    ctx:   tuple            = Depends(_get_ctx),
) -> Any:
    """
    根据文件类型自动路由：
      .xlsx/.xls/.csv        → Excel 结构化解析引擎
      .jpg/.png/.webp/.pdf   → Vision LLM 解析引擎

    同一批次可混合上传（如 1 个 Excel + 几张图片），结果合并为统一 JSON 数组。

    ⚠️ 此接口不写入数据库，仅供前端"核对网格"展示和手动纠偏。
    """
    from services.excel_parser_service import parse_excel
    from services.vision_service import extract_from_images

    excel_files:  list[UploadFile] = []
    vision_files: list[UploadFile] = []

    for f in files:
        if _is_excel(f.filename or "", f.content_type or ""):
            excel_files.append(f)
        else:
            vision_files.append(f)

    items: list[StandardReceiptItem] = []
    engines_used: set[str] = set()

    if excel_files:
        for ef in excel_files:
            try:
                rows = await parse_excel(ef)
                items.extend(rows)
                engines_used.add("EXCEL")
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=f"Excel 解析失败: {exc}")

    if vision_files:
        rows = await extract_from_images(vision_files)
        items.extend(rows)
        engines_used.add("VISION")

    if len(engines_used) >= 2:
        engine = "MIXED"
    elif "VISION" in engines_used:
        engine = "VISION"
    else:
        engine = "EXCEL"

    return ParsePreviewResponse(items=items, total=len(items), parse_engine=engine)


# ══════════════════════════════════════════════════════════════════════════════
# 2. 执行批量入账
# ══════════════════════════════════════════════════════════════════════════════

@router.post(
    "/execute",
    response_model=ExecuteBatchResponse,
    status_code=202,
    summary="提交核对后的票据列表，异步触发批量凭证生成流水线（立即返回 task_id）",
)
def execute_batch(
    body:             ExecuteBatchInput,
    background_tasks: BackgroundTasks,
    ctx:              tuple       = Depends(_get_ctx),
    db:               Session     = Depends(get_db),
    current_user:     UserAccount = Depends(get_current_user),
) -> Any:
    """
    前端完整工作流：
      1. POST /parse-preview → 获得 StandardReceiptItem 列表
      2. 用户在"核对网格"中修改/删除行
      3. POST /execute → 提交确认后的数据
      4. 立即收到 task_id（202 Accepted），开始轮询 /progress
      5. 完成后调用 /results 获取三色明细

    后台流水线参数全部显式传入（tenant_id / account_set_id / creator_id），
    不依赖任何 ContextVar，安全规范与 Sprint 3.4 habit_service 保持一致。
    """
    from services.batch_service import create_batch_task, run_batch_pipeline

    tenant_id, account_set_id = ctx
    creator_id = current_user.id

    try:
        task = create_batch_task(db, tenant_id, account_set_id, body.items, creator_id)
        db.commit()
        db.refresh(task)
    except Exception as exc:
        db.rollback()
        logger.error("create_batch_task failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"创建批处理任务失败: {exc}")

    # ── 挂入后台任务，显式传所有参数，绝不依赖 ContextVar ──────────────────────
    background_tasks.add_task(
        run_batch_pipeline,
        task_id        = task.task_id,
        tenant_id      = tenant_id,
        account_set_id = account_set_id,
        creator_id     = creator_id,
        voucher_word   = body.voucher_word,
    )

    logger.info(
        "execute_batch: task_id=%d total=%d tenant=%d",
        task.task_id, task.total_count, tenant_id,
    )
    return ExecuteBatchResponse(task_id=task.task_id, total_count=task.total_count)


# ══════════════════════════════════════════════════════════════════════════════
# 3. 进度轮询
# ══════════════════════════════════════════════════════════════════════════════

@router.get(
    "/task/{task_id}/progress",
    response_model=TaskProgressOut,
    status_code=200,
    summary="实时进度轮询（供前端画进度条）",
)
def get_task_progress(
    task_id: int,
    ctx:     tuple   = Depends(_get_ctx),
    db:      Session = Depends(get_db),
) -> Any:
    tenant_id, account_set_id = ctx
    task = (
        db.query(BatchImportTask)
        .filter(
            BatchImportTask.task_id        == task_id,
            BatchImportTask.tenant_id      == tenant_id,
            BatchImportTask.account_set_id == account_set_id,
        )
        .first()
    )
    if task is None:
        raise HTTPException(status_code=404, detail=f"批处理任务 {task_id} 不存在")

    return TaskProgressOut(
        task_id             = task.task_id,
        status              = task.status,
        total_count         = task.total_count,
        success_count       = task.success_count,
        error_count         = task.error_count,
        needs_review_count  = task.needs_review_count,
        created_at          = task.created_at,
        updated_at          = task.updated_at,
    )


# ══════════════════════════════════════════════════════════════════════════════
# 4. 结果报告
# ══════════════════════════════════════════════════════════════════════════════

@router.get(
    "/task/{task_id}/results",
    response_model=BatchResultsOut,
    status_code=200,
    summary="任务完成后的三色明细报告（绿灯/黄灯/红灯分类汇总）",
)
def get_task_results(
    task_id: int,
    ctx:     tuple   = Depends(_get_ctx),
    db:      Session = Depends(get_db),
) -> Any:
    tenant_id, account_set_id = ctx
    task = (
        db.query(BatchImportTask)
        .filter(
            BatchImportTask.task_id        == task_id,
            BatchImportTask.tenant_id      == tenant_id,
            BatchImportTask.account_set_id == account_set_id,
        )
        .first()
    )
    if task is None:
        raise HTTPException(status_code=404, detail=f"批处理任务 {task_id} 不存在")

    records = (
        db.query(BatchImportRecord)
        .filter(BatchImportRecord.task_id == task_id)
        .order_by(BatchImportRecord.id)
        .all()
    )

    success_list:      list[BatchRecordOut] = []
    needs_review_list: list[BatchRecordOut] = []
    error_list:        list[BatchRecordOut] = []

    for r in records:
        out = _record_to_out(r)
        if out is None:
            continue
        if r.error_msg:
            error_list.append(out)
        else:
            success_list.append(out)
            if r.needs_review:
                needs_review_list.append(out)

    return BatchResultsOut(
        task_id      = task.task_id,
        status       = task.status,
        success      = success_list,
        needs_review = needs_review_list,
        errors       = error_list,
    )


# ── 辅助 ──────────────────────────────────────────────────────────────────────

def _record_to_out(record: BatchImportRecord) -> BatchRecordOut | None:
    try:
        raw_data = StandardReceiptItem.model_validate_json(record.raw_data)
    except Exception:
        return None
    return BatchRecordOut(
        id           = record.id,
        raw_data     = raw_data,
        confidence   = record.confidence,
        voucher_id   = record.voucher_id,
        needs_review = record.needs_review,
        error_msg    = record.error_msg,
    )
