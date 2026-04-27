"""
AgentLedger V4.0 — 旧账导入 API Routes (Sprint 2.3)

端点一览：
  POST   /api/imports/sessions                           — 创建导入会话
  GET    /api/imports/export-guide/{source_system}       — 旧系统导出操作向导
  POST   /api/imports/{session_id}/upload-raw-data       — 上传 Excel + 物理清洗 + AI 表头映射
  POST   /api/imports/{session_id}/map-subjects          — AI 科目匹配引擎
  GET    /api/imports/{session_id}/abnormal-subjects     — 获取 PENDING_REVIEW 科目列表
  POST   /api/imports/{session_id}/confirm-subject/{staging_id} — 人工确认科目映射
  POST   /api/imports/{session_id}/skip-subject/{staging_id}    — 人工跳过该行
  POST   /api/imports/{session_id}/execute-import        — 正式结转落库（海绵兜底）

Context 注入：同 subject_routes 的 _get_ctx() 模式。
异常映射：
  ImportSessionNotFoundError  → 404
  ImportStagingNotFoundError  → 404
  ImportSessionStatusError    → 409
  ImportError (pandas 缺失)  → 503
  ValueError                  → 422
"""
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session

from database.connection import get_db
from schemas.import_schemas import (
    CreateSessionInput,
    ConfirmSubjectInput,
    SkipSubjectInput,
)
from services.import_service import (
    ImportService,
    ImportSessionNotFoundError,
    ImportSessionStatusError,
    ImportStagingNotFoundError,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/imports", tags=["imports"])


# ── Context helper ──────────────────────────────────────────────────────────────

def _get_ctx(db: Session = Depends(get_db)) -> tuple[int, int]:
    from database.tenant_context import get_current_tenant
    ctx = get_current_tenant()
    if ctx is None:
        raise HTTPException(status_code=400, detail="未设置租户上下文，请先登录")
    if ctx.account_set_id is None:
        raise HTTPException(status_code=400, detail="请先选择账套（account_set_id 未设置）")
    return ctx.tenant_id, ctx.account_set_id


def _svc_error(exc: Exception) -> HTTPException:
    if isinstance(exc, (ImportSessionNotFoundError, ImportStagingNotFoundError)):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ImportSessionStatusError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, ImportError):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


# ── 阶段一：会话创建 + 导出向导 ────────────────────────────────────────────────

@router.post("/sessions", status_code=201, summary="创建导入会话")
def create_session(
    body: CreateSessionInput,
    ctx: tuple = Depends(_get_ctx),
    db: Session = Depends(get_db),
) -> Any:
    """
    创建一次新的旧账导入会话。
    返回 session_id，后续所有操作均携带此 ID。
    """
    tenant_id, account_set_id = ctx
    svc = ImportService(db)
    try:
        session = svc.create_session(tenant_id, account_set_id, body)
        db.commit()
        return {
            "session_id":        session.session_id,
            "source_system":     session.source_system,
            "status":            session.status,
            "original_filename": session.original_filename,
            "header_mapping":    session.header_mapping,
        }
    except Exception as exc:
        db.rollback()
        raise _svc_error(exc)


@router.get("/export-guide/{source_system}", summary="旧系统导出操作向导")
def get_export_guide(
    source_system: str,
    ctx: tuple = Depends(_get_ctx),
    db: Session = Depends(get_db),
) -> Any:
    """
    返回指定旧系统的 Excel 导出步骤提示和典型列名示例。
    不访问数据库，纯静态内容。
    """
    svc = ImportService(db)
    return svc.get_export_guide(source_system)


# ── 阶段二：文件上传 + 物理清洗 + AI 表头映射 ──────────────────────────────────

@router.post(
    "/{session_id}/upload-raw-data",
    status_code=200,
    summary="上传 Excel + Pandas 清洗 + AI 表头映射",
)
async def upload_raw_data(
    session_id: int,
    file: UploadFile = File(..., description="旧系统导出的 Excel 文件（.xlsx / .xls）"),
    ctx: tuple = Depends(_get_ctx),
    db: Session = Depends(get_db),
) -> Any:
    """
    1. 接收上传的 Excel 文件
    2. Pandas 物理清洗：dropna(how='all') + ffill 解决合并单元格
    3. 提取前 20 行喂给 LLM，AI 推断列名映射
    4. 全量数据写入 ImportStaging（旧值保留在 raw_* 字段）
    5. 会话状态 → MAPPING
    需安装 pandas>=2.2.0（未安装返回 503）。
    """
    tenant_id, account_set_id = ctx
    file_bytes = await file.read()
    svc = ImportService(db)
    try:
        result = svc.upload_and_clean(session_id, tenant_id, account_set_id, file_bytes)
        db.commit()
        return result
    except ImportError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        db.rollback()
        raise _svc_error(exc)


# ── 阶段三：AI 科目匹配引擎 ────────────────────────────────────────────────────

@router.post(
    "/{session_id}/map-subjects",
    status_code=200,
    summary="AI 科目匹配引擎",
)
def map_subjects(
    session_id: int,
    ctx: tuple = Depends(_get_ctx),
    db: Session = Depends(get_db),
) -> Any:
    """
    对 ImportStaging 中所有 PENDING_REVIEW 行执行科目匹配：
    - 精确编码匹配 → CONFIRMED（无需 LLM）
    - LLM 高置信度（>95%）→ CONFIRMED
    - LLM 中置信度（85~95%，可派生）→ 尝试自动创建子科目 → CONFIRMED 或降级
    - LLM 低置信度（<85%）→ PENDING_REVIEW（需人工复核）
    返回 {confirmed, pending_review, auto_created_subjects, skipped, session_status}。
    """
    tenant_id, account_set_id = ctx
    svc = ImportService(db)
    try:
        result = svc.map_subjects(session_id, tenant_id, account_set_id)
        db.commit()
        return result
    except Exception as exc:
        db.rollback()
        raise _svc_error(exc)


@router.get(
    "/{session_id}/abnormal-subjects",
    status_code=200,
    summary="获取待人工复核的科目列表",
)
def get_abnormal_subjects(
    session_id: int,
    ctx: tuple = Depends(_get_ctx),
    db: Session = Depends(get_db),
) -> Any:
    """
    返回所有 PENDING_REVIEW 的暂存行。
    每行附带 AI 给出的最多 3 个候选科目建议，供人工选择。
    """
    tenant_id, account_set_id = ctx
    svc = ImportService(db)
    try:
        return svc.get_abnormal_subjects(session_id, tenant_id, account_set_id)
    except Exception as exc:
        raise _svc_error(exc)


@router.post(
    "/{session_id}/confirm-subject/{staging_id}",
    status_code=200,
    summary="人工确认科目映射",
)
def confirm_subject(
    session_id: int,
    staging_id: int,
    body: ConfirmSubjectInput,
    ctx: tuple = Depends(_get_ctx),
    db: Session = Depends(get_db),
) -> Any:
    """
    人工为 PENDING_REVIEW 行指定最终科目编码，状态置为 CONFIRMED。
    若复核完成后无剩余 PENDING_REVIEW 行，会话自动退出 REVIEWING 状态。
    """
    tenant_id, account_set_id = ctx
    svc = ImportService(db)
    try:
        row = svc.confirm_subject(staging_id, tenant_id, account_set_id, body.subject_code)
        db.commit()
        return {
            "staging_id":          row.id,
            "match_status":        row.match_status,
            "system_subject_code": row.system_subject_code,
        }
    except Exception as exc:
        db.rollback()
        raise _svc_error(exc)


@router.post(
    "/{session_id}/skip-subject/{staging_id}",
    status_code=200,
    summary="人工跳过该行（不导入）",
)
def skip_subject(
    session_id: int,
    staging_id: int,
    body: SkipSubjectInput,
    ctx: tuple = Depends(_get_ctx),
    db: Session = Depends(get_db),
) -> Any:
    """
    将暂存行标记为 SKIPPED，execute_import 时将忽略该行。
    """
    tenant_id, account_set_id = ctx
    svc = ImportService(db)
    try:
        row = svc.skip_subject(staging_id, tenant_id, account_set_id, body.reason)
        db.commit()
        return {
            "staging_id":  row.id,
            "match_status": row.match_status,
            "skip_reason":  row.skip_reason,
        }
    except Exception as exc:
        db.rollback()
        raise _svc_error(exc)


# ── 阶段四：正式结转落库 + 海绵决战 ───────────────────────────────────────────

@router.post(
    "/{session_id}/execute-import",
    status_code=200,
    summary="正式结转落库（海绵兜底）",
)
def execute_import(
    session_id: int,
    ctx: tuple = Depends(_get_ctx),
    db: Session = Depends(get_db),
) -> Any:
    """
    将所有 CONFIRMED 的暂存行批量转换为 InitialBalance 记录，
    然后调用 complete_account_setup()：
      1. 试算平衡检查
      2. 不平 → 静默写入 1901（待处理财产损溢）配平，is_ai_sponge=True
      3. 账套状态置为 ACTIVE
    前提：无剩余 PENDING_REVIEW 行（否则返回 409）。
    """
    tenant_id, account_set_id = ctx
    svc = ImportService(db)
    try:
        result = svc.execute_import(session_id, tenant_id, account_set_id)
        db.commit()
        return result
    except Exception as exc:
        db.rollback()
        raise _svc_error(exc)
