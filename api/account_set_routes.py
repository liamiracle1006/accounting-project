"""
AgentLedger V4.0 — AccountSet API Routes (Sprint 1)

端点一览：
  POST   /api/account-sets/parse-license       — 营业执照一键解析（Vision LLM）
  GET    /api/account-sets                      — 账套列表（含回收站可选）
  POST   /api/account-sets                      — 创建账套
  GET    /api/account-sets/{id}                 — 查询单个账套
  PATCH  /api/account-sets/{id}                 — 更新账套（铁律二守门）
  POST   /api/account-sets/{id}/activate        — 激活账套（ONBOARDING → ACTIVE）
  DELETE /api/account-sets/{id}                 — 软删除（进回收站）
  POST   /api/account-sets/{id}/restore         — 从回收站恢复
  POST   /api/account-sets/{id}/clone           — 账套克隆
  GET    /api/account-sets/recycle-bin          — 查看回收站列表
"""
import logging
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database.connection import get_db
from models.account_set import AccountSet, AccountSetStatus
from services.account_set_service import (
    AccountSetCreateInput,
    AccountSetDeletedError,
    AccountSetLockedError,
    AccountSetNotFoundError,
    AccountSetService,
    AccountSetUpdateInput,
    CloneOptions,
    InvalidPeriodError,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/account-sets", tags=["account-sets"])


# ── Response helpers ────────────────────────────────────────────────────────────

def _serialize(obj: AccountSet) -> dict:
    """将 AccountSet ORM 对象序列化为 API 响应 dict。tax_password 脱敏。"""
    return {
        "account_set_id":          obj.account_set_id,
        "tenant_id":               obj.tenant_id,
        "account_set_name":        obj.account_set_name,
        "company_name":            obj.company_name,
        "start_period":            obj.start_period,
        "fiscal_year_start_month": obj.fiscal_year_start_month,
        "accounting_standard":     obj.accounting_standard,
        "taxpayer_type":           obj.taxpayer_type,
        "uscc":                    obj.uscc,
        "tax_bureau_region":       obj.tax_bureau_region,
        "has_tax_password":        obj.tax_password is not None,  # 脱敏：只告知是否已配置
        "module_settings":         obj.module_settings_dict,
        "status":                  obj.status,
        "is_deleted":              obj.is_deleted,
        "deleted_at":              obj.deleted_at.isoformat() if obj.deleted_at else None,
        "activated_at":            obj.activated_at.isoformat() if obj.activated_at else None,
        "created_at":              obj.created_at.isoformat() if obj.created_at else None,
        "updated_at":              obj.updated_at.isoformat() if obj.updated_at else None,
    }


def _svc_errors(exc: Exception) -> HTTPException:
    """将 Service 层异常统一转换为 HTTPException。"""
    if isinstance(exc, AccountSetNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, AccountSetLockedError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, AccountSetDeletedError):
        return HTTPException(status_code=410, detail=str(exc))
    if isinstance(exc, (InvalidPeriodError, ValueError)):
        return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


def _get_tenant_id(db: Session = Depends(get_db)) -> int:
    """
    占位依赖：从 TenantContext（ContextVar）读取当前租户 ID。
    完整 JWT 中间件接入后，此处改为从 get_current_user() 提取。
    """
    from database.tenant_context import get_current_tenant
    ctx = get_current_tenant()
    if ctx is None:
        raise HTTPException(status_code=401, detail="未设置租户上下文，请先登录")
    return ctx.tenant_id


# ── 1. 营业执照一键解析 ─────────────────────────────────────────────────────────

@router.post("/parse-license", summary="营业执照一键解析（Vision LLM）")
async def parse_license(
    file: UploadFile = File(..., description="营业执照图片（JPEG / PNG / WEBP）"),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(_get_tenant_id),
) -> Any:
    """
    上传营业执照图片，调用 Vision LLM 提取结构化信息。

    Iron Law 1 流程：
      ① 检索该租户历史账套习惯（accounting_standard / taxpayer_type 多数派）
      ② 将历史习惯作为 few-shot 约束注入 prompt
      ③ LLM 从图片提取字段并给出推荐值
      ④ 返回数据供前端表单预填，用户确认后调用 POST /api/account-sets 正式创建

    返回字段均为"建议值"，用户可在前端修改后再提交。
    """
    content_type = file.content_type or "image/jpeg"
    if content_type not in ("image/jpeg", "image/png", "image/webp"):
        raise HTTPException(
            status_code=415,
            detail=f"不支持的图片类型：{content_type}。请上传 JPEG / PNG / WEBP",
        )

    image_bytes = await file.read()
    if len(image_bytes) > 10 * 1024 * 1024:  # 10 MB 上限
        raise HTTPException(status_code=413, detail="图片文件不得超过 10 MB")

    svc = AccountSetService(db)
    try:
        result = svc.parse_license(tenant_id, image_bytes, content_type)
    except Exception as exc:
        logger.error("营业执照解析异常: %s", exc)
        raise HTTPException(status_code=500, detail=f"营业执照解析失败：{exc}")

    return result.model_dump(exclude={"raw_text"})


# ── 2. 账套列表 ─────────────────────────────────────────────────────────────────

@router.get("", summary="账套列表")
def list_account_sets(
    include_recycled: bool = Query(False, description="是否包含回收站中的账套"),
    db: Session = Depends(get_db),
    tenant_id: int = Depends(_get_tenant_id),
) -> Any:
    svc = AccountSetService(db)
    sets = svc.list_account_sets(tenant_id, include_recycled=include_recycled)
    return [_serialize(s) for s in sets]


# ── 3. 创建账套 ─────────────────────────────────────────────────────────────────

@router.post("", status_code=201, summary="创建账套")
def create_account_set(
    body: AccountSetCreateInput,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(_get_tenant_id),
) -> Any:
    """
    创建新账套。

    防呆设计：
      - start_period 必须为合法 YYYY-MM 格式（如 '2026-01'）
      - accounting_standard 必须为枚举值：小企业会计准则 / 企业会计准则
      - taxpayer_type 必须为枚举值：小规模纳税人 / 一般纳税人
    """
    svc = AccountSetService(db)
    try:
        obj = svc.create_account_set(tenant_id, body)
    except Exception as exc:
        raise _svc_errors(exc)
    return _serialize(obj)


# ── 4. 查询单个账套 ─────────────────────────────────────────────────────────────

@router.get("/recycle-bin", summary="回收站列表")
def list_recycle_bin(
    db: Session = Depends(get_db),
    tenant_id: int = Depends(_get_tenant_id),
) -> Any:
    """查看当前租户回收站中的账套（is_deleted=True 的账套）。"""
    svc = AccountSetService(db)
    sets = svc.list_recycled(tenant_id)
    return [_serialize(s) for s in sets]


@router.get("/{account_set_id}", summary="查询单个账套")
def get_account_set(
    account_set_id: int,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(_get_tenant_id),
) -> Any:
    svc = AccountSetService(db)
    try:
        obj = svc.get_account_set(tenant_id, account_set_id)
    except Exception as exc:
        raise _svc_errors(exc)
    return _serialize(obj)


# ── 5. 更新账套 ─────────────────────────────────────────────────────────────────

@router.patch("/{account_set_id}", summary="更新账套（铁律二守门）")
def update_account_set(
    account_set_id: int,
    body: AccountSetUpdateInput,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(_get_tenant_id),
) -> Any:
    """
    更新账套信息。

    Iron Law 2 守门：
      - 若账套已产生有效凭证，start_period 和 accounting_standard 的修改请求
        将被拒绝（HTTP 409 Conflict），防止全盘账务崩溃。
    """
    svc = AccountSetService(db)
    try:
        obj = svc.update_account_set(tenant_id, account_set_id, body)
    except Exception as exc:
        raise _svc_errors(exc)
    return _serialize(obj)


# ── 6. 激活账套 ─────────────────────────────────────────────────────────────────

@router.post("/{account_set_id}/activate", summary="激活账套（ONBOARDING → ACTIVE）")
def activate_account_set(
    account_set_id: int,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(_get_tenant_id),
) -> Any:
    """将账套从建账期（ONBOARDING）推进为正式启用（ACTIVE）。"""
    svc = AccountSetService(db)
    try:
        obj = svc.activate_account_set(tenant_id, account_set_id)
    except Exception as exc:
        raise _svc_errors(exc)
    return _serialize(obj)


# ── 7. 软删除（进回收站）──────────────────────────────────────────────────────

@router.delete("/{account_set_id}", summary="软删除账套（进回收站）")
def soft_delete_account_set(
    account_set_id: int,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(_get_tenant_id),
) -> Any:
    """
    账套软删除：绝不执行 SQL DELETE。

    执行效果：
      - is_deleted = True
      - status = RECYCLED
      - deleted_at = 当前时间
    所有业务查询（凭证、报表等）自动过滤已删除账套，实现"防穿透"。
    可通过 POST /{id}/restore 从回收站恢复。
    """
    svc = AccountSetService(db)
    try:
        obj = svc.soft_delete(tenant_id, account_set_id)
    except Exception as exc:
        raise _svc_errors(exc)
    return {"message": f"账套 {account_set_id} 已移入回收站", "account_set": _serialize(obj)}


# ── 8. 从回收站恢复 ─────────────────────────────────────────────────────────────

@router.post("/{account_set_id}/restore", summary="从回收站恢复账套")
def restore_account_set(
    account_set_id: int,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(_get_tenant_id),
) -> Any:
    svc = AccountSetService(db)
    try:
        obj = svc.restore(tenant_id, account_set_id)
    except Exception as exc:
        raise _svc_errors(exc)
    return {"message": f"账套 {account_set_id} 已从回收站恢复", "account_set": _serialize(obj)}


# ── 9. 账套克隆 ─────────────────────────────────────────────────────────────────

@router.post("/{account_set_id}/clone", status_code=201, summary="账套克隆")
def clone_account_set(
    account_set_id: int,
    body: CloneOptions,
    db: Session = Depends(get_db),
    tenant_id: int = Depends(_get_tenant_id),
) -> Any:
    """
    账套克隆（代账公司模板复制场景）。

    clone_options 支持：
      - "settings"            — 复制会计准则、纳税人类型、功能开关等配置
      - "accounting_subjects" — 预留（Sprint 2 落地）：复制科目树自定义项

    禁止克隆：历史凭证、银行流水、期初余额（避免财务数据污染）。
    克隆后的新账套始终处于 ONBOARDING 状态，需重新导入期初余额后激活。
    """
    svc = AccountSetService(db)
    try:
        obj = svc.clone(tenant_id, account_set_id, body)
    except Exception as exc:
        raise _svc_errors(exc)
    return _serialize(obj)
