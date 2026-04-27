"""
AgentLedger V4.0 — Initial Balance (期初余额) API Routes (Sprint 2.2)

端点一览：
  POST   /api/initial-balances              — 保存单条期初余额
  POST   /api/initial-balances/batch-save   — 批量保存
  GET    /api/initial-balances/with-subjects — 科目树 + 余额联合查询
  GET    /api/initial-balances/trial-balance — 本位币四维度试算平衡
  GET    /api/initial-balances/foreign-trial-balance — 外币试算平衡
  POST   /api/initial-balances/complete     — 完成建账（海绵熔断）
  POST   /api/initial-balances/reopen       — 重新开账
  GET    /api/initial-balances/export-template — 下载 Excel 模板
  POST   /api/initial-balances/import       — 导入 Excel

Context 注入：同 subject_routes 的 _get_ctx() 模式。
异常映射：InitialBalanceLockedError → 409，SubjectNotFoundError → 404，ValueError → 422。
openpyxl 未安装 → 503。
"""
import io
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from database.connection import get_db
from schemas.initial_balance_schemas import (
    BatchSaveInput,
    InitialBalanceInput,
)
from services.initial_balance_service import (
    InitialBalanceLockedError,
    InitialBalanceService,
)
from services.subject_service import SubjectNotFoundError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/initial-balances", tags=["initial-balances"])


# ── Context helper ──────────────────────────────────────────────────────────────

def _get_ctx(db: Session = Depends(get_db)) -> tuple[int, int]:
    """从 TenantContext ContextVar 读取 (tenant_id, account_set_id)。"""
    from database.tenant_context import get_current_tenant
    ctx = get_current_tenant()
    if ctx is None:
        raise HTTPException(status_code=400, detail="未设置租户上下文，请先登录")
    if ctx.account_set_id is None:
        raise HTTPException(status_code=400, detail="请先选择账套（account_set_id 未设置）")
    return ctx.tenant_id, ctx.account_set_id


def _svc_error(exc: Exception) -> HTTPException:
    """统一异常 → HTTP 状态码映射。"""
    if isinstance(exc, SubjectNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, InitialBalanceLockedError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, ImportError):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


# ── 保存单条期初余额 ────────────────────────────────────────────────────────────

@router.post("", status_code=200, summary="保存单条期初余额")
def save_balance(
    body: InitialBalanceInput,
    ctx: tuple = Depends(_get_ctx),
    db: Session = Depends(get_db),
) -> Any:
    """
    保存（或更新）单条期初余额。
    - year_start_balance 由后端推导，无需传入。
    - 1月开账时 ytd_debit / ytd_credit 自动归零。
    - 余额方向异常仅产生 warning，不阻塞保存。
    """
    tenant_id, account_set_id = ctx
    svc = InitialBalanceService(db)
    try:
        result = svc.save_balance(tenant_id, account_set_id, body)
        db.commit()
        return result.model_dump()
    except Exception as exc:
        db.rollback()
        raise _svc_error(exc)


# ── 批量保存 ────────────────────────────────────────────────────────────────────

@router.post("/batch-save", status_code=200, summary="批量保存期初余额")
def batch_save(
    body: BatchSaveInput,
    ctx: tuple = Depends(_get_ctx),
    db: Session = Depends(get_db),
) -> Any:
    """
    批量提交期初余额。整体事务：一行失败则全部回滚。
    返回 {saved: int, warnings: list[str]}。
    """
    tenant_id, account_set_id = ctx
    svc = InitialBalanceService(db)
    try:
        return svc.batch_save(tenant_id, account_set_id, body)
    except Exception as exc:
        raise _svc_error(exc)


# ── 科目树 + 余额联合查询 ────────────────────────────────────────────────────────

@router.get("/with-subjects", summary="科目树 + 期初余额联合查询")
def get_balances_with_subjects(
    ctx: tuple = Depends(_get_ctx),
    db: Session = Depends(get_db),
) -> Any:
    """
    返回树状结构，每节点含期初余额字段。
    只含 auxiliary_hash="" 的汇总记录（不展开辅助明细）。
    """
    tenant_id, account_set_id = ctx
    svc = InitialBalanceService(db)
    try:
        tree = svc.get_balances_with_subjects(tenant_id, account_set_id)
        return [node.model_dump() for node in tree]
    except Exception as exc:
        raise _svc_error(exc)


# ── 本位币试算平衡 ──────────────────────────────────────────────────────────────

@router.get("/trial-balance", summary="本位币四维度试算平衡")
def trial_balance(
    ctx: tuple = Depends(_get_ctx),
    db: Session = Depends(get_db),
) -> Any:
    """
    对一级科目做四维度试算平衡：
    期初余额 / 本年累计借方 / 本年累计贷方 / 年初余额，
    每维度计算借贷合计及差额。
    """
    tenant_id, account_set_id = ctx
    svc = InitialBalanceService(db)
    try:
        result = svc.calculate_trial_balance(tenant_id, account_set_id)
        return result.model_dump()
    except Exception as exc:
        raise _svc_error(exc)


# ── 外币试算平衡 ────────────────────────────────────────────────────────────────

@router.get("/foreign-trial-balance", summary="外币独立试算平衡")
def foreign_trial_balance(
    currency_code: str = Query(..., description="外币币种代码，如 USD / EUR / HKD"),
    ctx: tuple = Depends(_get_ctx),
    db: Session = Depends(get_db),
) -> Any:
    """
    对指定币种的原币金额（foreign_currency_amount）做借贷平衡检查。
    """
    tenant_id, account_set_id = ctx
    svc = InitialBalanceService(db)
    try:
        result = svc.calculate_foreign_trial_balance(tenant_id, account_set_id, currency_code)
        return result.model_dump()
    except Exception as exc:
        raise _svc_error(exc)


# ── 完成建账（海绵熔断） ─────────────────────────────────────────────────────────

@router.post("/complete", status_code=200, summary="完成建账（海绵熔断）")
def complete_account_setup(
    ctx: tuple = Depends(_get_ctx),
    db: Session = Depends(get_db),
) -> Any:
    """
    触发完成建账流程：
    1. 试算平衡检查
    2. 不平衡 → 静默写入 1901（待处理财产损溢）配平，is_ai_sponge=True
    3. 账套状态置为 ACTIVE
    返回 CompleteAccountSetupResult，含 sponge_amount 和 was_balanced。
    """
    tenant_id, account_set_id = ctx
    svc = InitialBalanceService(db)
    try:
        result = svc.complete_account_setup(tenant_id, account_set_id)
        return result.model_dump()
    except Exception as exc:
        raise _svc_error(exc)


# ── 重新开账 ────────────────────────────────────────────────────────────────────

@router.post("/reopen", status_code=200, summary="重新开账")
def reopen_account_setup(
    ctx: tuple = Depends(_get_ctx),
    db: Session = Depends(get_db),
) -> Any:
    """
    将已激活账套重置回建账状态（ONBOARDING）。
    前提：账套为 ACTIVE 且无任何凭证记录（有凭证则返回 409）。
    """
    tenant_id, account_set_id = ctx
    svc = InitialBalanceService(db)
    try:
        return svc.reopen_account_setup(tenant_id, account_set_id)
    except Exception as exc:
        raise _svc_error(exc)


# ── 导出 Excel 模板 ─────────────────────────────────────────────────────────────

@router.get("/export-template", summary="下载期初余额 Excel 模板")
def export_template(
    ctx: tuple = Depends(_get_ctx),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """
    生成含当前账套科目的 Excel 模板。
    父科目行灰色背景并标注"汇总行，请勿手工填写"；叶子科目行空白待填。
    需安装 openpyxl==3.1.5（未安装返回 503）。
    """
    tenant_id, account_set_id = ctx
    svc = InitialBalanceService(db)
    try:
        content = svc.export_template(tenant_id, account_set_id)
    except ImportError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        raise _svc_error(exc)

    return StreamingResponse(
        content=io.BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=initial_balance_template.xlsx"},
    )


# ── 导入 Excel ──────────────────────────────────────────────────────────────────

@router.post("/import", status_code=200, summary="从 Excel 导入期初余额")
async def import_from_excel(
    file: UploadFile = File(..., description="期初余额 Excel 文件（.xlsx）"),
    ctx: tuple = Depends(_get_ctx),
    db: Session = Depends(get_db),
) -> Any:
    """
    解析上传的 Excel 文件，按科目编码逐行匹配并保存期初余额。
    - 找不到科目编码：记录错误，继续处理其他行
    - 汇总行（灰色提示行）自动跳过
    返回 {imported: int, errors: [{row, reason}], warnings: [str]}。
    需安装 openpyxl==3.1.5（未安装返回 503）。
    """
    tenant_id, account_set_id = ctx
    file_bytes = await file.read()
    svc = InitialBalanceService(db)
    try:
        result = svc.import_from_excel(tenant_id, account_set_id, file_bytes)
        if result["imported"] > 0:
            db.commit()
        return result
    except ImportError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        db.rollback()
        raise _svc_error(exc)
