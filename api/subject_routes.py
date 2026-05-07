"""
AgentLedger V4.0 — Subject (科目) API Routes (Sprint 2.1)

端点一览：
  GET    /api/subjects                        — 科目平铺列表
  GET    /api/subjects/tree                   — 科目树（层级JSON）
  GET    /api/subjects/refactor-suggestions   — AI 重构建议
  POST   /api/subjects/seed-system            — 初始化系统标准科目库（运维接口）
  POST   /api/subjects/init/{account_set_id}  — 账套骨架软启动（补调接口）
  POST   /api/subjects                        — 新增自定义科目
  GET    /api/subjects/{subject_code}         — 查询单个科目
  PATCH  /api/subjects/{subject_code}         — 更新科目（铁律二守门）
  DELETE /api/subjects/{subject_code}         — 软删除科目

所有接口均通过 Depends(_get_ctx) 从 TenantContext 读取
tenant_id + account_set_id，自动注入，不需要调用方传参。
"""
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database.connection import get_db
from models.accounting import TenantSubject
from schemas.subject_schemas import (
    NodeFeatures,
    SubjectCreate,
    SubjectResponse,
    SubjectUpdate,
)
from services.subject_service import (
    SubjectCodeConflictError,
    SubjectCodeRuleError,
    SubjectHasBalanceError,
    SubjectLockedError,
    SubjectNotFoundError,
    SubjectService,
)
from models.user_account import UserAccount
from services.auth_service import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/subjects", tags=["subjects"])


# ── Context helpers ─────────────────────────────────────────────────────────────

def _get_ctx(
    user: UserAccount = Depends(get_current_user),
    db:   Session     = Depends(get_db),
) -> tuple[int, int]:
    """从已登录 user 解析 (tenant_id, account_set_id)。"""
    from services.tenant_resolver import resolve_tenant_ctx
    return resolve_tenant_ctx(db, user)


def _svc_error(exc: Exception) -> HTTPException:
    if isinstance(exc, SubjectNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, SubjectLockedError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, SubjectHasBalanceError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, (SubjectCodeConflictError, SubjectCodeRuleError, ValueError)):
        return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


def _serialize(s: TenantSubject) -> dict:
    """序列化 TenantSubject，node_features 反序列化为 dict。"""
    return {
        "id":                  s.id,
        "subject_code":        s.subject_code,
        "subject_name":        s.subject_name,
        "parent_code":         s.parent_code,
        "category":            s.category,
        "balance_direction":   s.balance_direction,
        "level":               s.level,
        "sort_order":          s.sort_order,
        "is_enabled":          s.is_enabled,
        "is_deleted":          s.is_deleted,
        "node_features":       s.node_features_dict,
        "graph_node_id":       s.graph_node_id,
        "system_subject_code": s.system_subject_code,
        "created_at":          s.created_at.isoformat() if s.created_at else None,
        "updated_at":          s.updated_at.isoformat() if s.updated_at else None,
    }


# ── 运维接口：系统科目库初始化 ────────────────────────────────────────────────

@router.post("/seed-system", summary="初始化系统标准科目库（运维接口，幂等）")
def seed_system_subjects(db: Session = Depends(get_db)) -> Any:
    """
    将内置标准科目数据写入 system_subject 表。
    幂等：重复调用只写入缺失条目。
    通常仅在首次部署时调用一次；账套创建时如系统库为空也会自动触发。
    """
    svc = SubjectService(db)
    count = svc.seed_system_subjects()
    return {"message": f"系统科目库初始化完成，写入 {count} 条记录"}


@router.post("/init/{account_set_id}", summary="账套科目骨架软启动（补调接口）")
def init_tenant_subjects(
    account_set_id: int,
    db: Session = Depends(get_db),
) -> Any:
    """
    补调接口：对已存在但科目为空的账套重新执行骨架初始化。
    正常情况下账套创建时自动调用，此接口供手动补救使用。
    """
    from database.tenant_context import get_current_tenant
    ctx = get_current_tenant()
    if ctx is None:
        raise HTTPException(status_code=400, detail="未设置租户上下文")

    from models.account_set import AccountSet
    account_set = db.get(AccountSet, account_set_id)
    if not account_set or account_set.tenant_id != ctx.tenant_id:
        raise HTTPException(status_code=404, detail=f"账套 {account_set_id} 不存在")

    svc = SubjectService(db)
    count = svc.init_tenant_subjects(
        tenant_id           = ctx.tenant_id,
        account_set_id      = account_set_id,
        accounting_standard = account_set.accounting_standard,
    )
    return {"message": f"账套 {account_set_id} 科目骨架初始化完成，克隆 {count} 条科目"}


# ── 科目列表 ─────────────────────────────────────────────────────────────────

@router.get("", summary="科目平铺列表")
def list_subjects(
    category:     str  | None = Query(None, description="按类别过滤：资产/负债/权益/成本/损益"),
    enabled_only: bool        = Query(True,  description="仅返回已启用科目"),
    ctx: tuple    = Depends(_get_ctx),
    db:  Session  = Depends(get_db),
) -> Any:
    tenant_id, account_set_id = ctx
    svc = SubjectService(db)
    subjects = svc.list_subjects(tenant_id, account_set_id, category, enabled_only)
    return [_serialize(s) for s in subjects]


# ── 科目树 ───────────────────────────────────────────────────────────────────

@router.get("/tree", summary="科目树（层级 JSON 结构）")
def get_subject_tree(
    enabled_only: bool    = Query(True),
    ctx: tuple    = Depends(_get_ctx),
    db:  Session  = Depends(get_db),
) -> Any:
    """
    返回递归树结构，每个节点含 children 数组。
    一次 SELECT 后在 Python 内存中构建，无 N+1 问题。
    前端可直接渲染为科目树组件（对标柠檬云科目列表页）。
    """
    tenant_id, account_set_id = ctx
    svc = SubjectService(db)
    return svc.get_subject_tree(tenant_id, account_set_id, enabled_only)


# ── AI 重构建议 ───────────────────────────────────────────────────────────────

@router.get("/refactor-suggestions", summary="AI 科目重构建议")
def get_refactor_suggestions(
    threshold: int   = Query(10, ge=3, description="触发建议的子科目数量阈值，默认10"),
    ctx: tuple = Depends(_get_ctx),
    db:  Session = Depends(get_db),
) -> Any:
    """
    AI 侦测引擎：扫描当前账套的科目树，找出使用传统明细记账的科目。
    若某科目下挂了超过 threshold 个子科目，返回"升级为辅助核算"建议。

    典型触发场景（对标柠檬云痛点）：
      1122 应收账款 下有 30 个客户名称子科目
      → 建议升级为 auxiliary_dimensions: ["customer"]

    返回数据供前端弹出 AI 向导对话框。
    """
    tenant_id, account_set_id = ctx
    svc = SubjectService(db)
    suggestions = svc.detect_refactor_opportunity(tenant_id, account_set_id, threshold)
    return [s.model_dump() for s in suggestions]


# ── 新增科目 ─────────────────────────────────────────────────────────────────

@router.post("", status_code=201, summary="新增自定义科目")
def create_subject(
    body: SubjectCreate,
    ctx:  tuple   = Depends(_get_ctx),
    db:   Session = Depends(get_db),
) -> Any:
    """
    新增科目。
    防呆校验：
      - 编码规范（subject_code_rule，如 '4-2-2-2-2'）
      - 父科目必须存在
      - 同账套内编码唯一
      - 同父级下名称不重复
    """
    tenant_id, account_set_id = ctx
    svc = SubjectService(db)
    try:
        obj = svc.create_subject(tenant_id, account_set_id, body)
    except Exception as exc:
        raise _svc_error(exc)
    return _serialize(obj)


# ── 查询单科目 ────────────────────────────────────────────────────────────────

@router.get("/{subject_code}", summary="查询单个科目")
def get_subject(
    subject_code: str,
    ctx:  tuple   = Depends(_get_ctx),
    db:   Session = Depends(get_db),
) -> Any:
    tenant_id, account_set_id = ctx
    svc = SubjectService(db)
    try:
        obj = svc.get_subject(tenant_id, account_set_id, subject_code)
    except Exception as exc:
        raise _svc_error(exc)
    return _serialize(obj)


# ── 更新科目 ─────────────────────────────────────────────────────────────────

@router.patch("/{subject_code}", summary="更新科目（铁律二守门）")
def update_subject(
    subject_code: str,
    body: SubjectUpdate,
    ctx:  tuple   = Depends(_get_ctx),
    db:   Session = Depends(get_db),
) -> Any:
    """
    Iron Law 2 守门：
    若该科目已有凭证发生记录，balance_direction 和 category 修改请求
    被拒绝（HTTP 409），防止历史报表逻辑崩溃。
    """
    tenant_id, account_set_id = ctx
    svc = SubjectService(db)
    try:
        obj = svc.update_subject(tenant_id, account_set_id, subject_code, body)
    except Exception as exc:
        raise _svc_error(exc)
    return _serialize(obj)


# ── 软删除科目 ────────────────────────────────────────────────────────────────

@router.delete("/{subject_code}", summary="软删除科目")
def delete_subject(
    subject_code: str,
    ctx:  tuple   = Depends(_get_ctx),
    db:   Session = Depends(get_db),
) -> Any:
    """
    软删除科目。
    拒绝条件：
      - 科目在 voucher_line 有发生额（建议改为停用）
      - 科目下仍有未删除的子科目
    """
    tenant_id, account_set_id = ctx
    svc = SubjectService(db)
    try:
        obj = svc.delete_subject(tenant_id, account_set_id, subject_code)
    except Exception as exc:
        raise _svc_error(exc)
    return {
        "message": f"科目 {subject_code} 已软删除",
        "subject": _serialize(obj),
    }
