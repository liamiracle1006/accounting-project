"""
AgentLedger V4.0 — AI 凭证生成 API Routes (Sprint 3.1 / 3.2)

端点一览：
  POST   /api/voucher-ai/generate                       — AI 生成凭证草稿（双层 Pipeline）
  POST   /api/voucher-ai/confirm                        — 将 AI 草稿确认入账（写入数据库）
  GET    /api/voucher-ai/habit-rules                    — 列出所有业务习惯规则
  POST   /api/voucher-ai/habit-rules                    — 创建业务习惯规则（DAG 模板）
  PUT    /api/voucher-ai/habit-rules/{rule_id}          — 更新业务习惯规则
  DELETE /api/voucher-ai/habit-rules/{rule_id}          — 删除业务习惯规则

Context 注入：同 import_routes 的 _get_ctx() 模式。
异常映射：
  HabitRuleNotFoundError  → 404
  VoucherGenerationError  → 500
  ValueError              → 422
"""
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database.connection import get_db
from schemas.voucher_ai_schemas import (
    ConfirmVoucherInput,
    GenerateVoucherInput,
    HabitRuleCreateInput,
    HabitRuleUpdateInput,
    HabitRuleOut,
    VoucherDraftOut,
)
from schemas.voucher_schemas import VoucherOut
from services.ai_voucher_service import (
    AIVoucherService,
    HabitRuleNotFoundError,
    VoucherGenerationError,
)
from services.voucher_service import VoucherService
from services.auth_service import get_current_user
from models.user_account import UserAccount

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/voucher-ai", tags=["voucher-ai"])


# ── Context helper ────────────────────────────────────────────────────────────

def _get_ctx(db: Session = Depends(get_db)) -> tuple[int, int]:
    from database.tenant_context import get_current_tenant
    ctx = get_current_tenant()
    if ctx is None:
        raise HTTPException(status_code=401, detail="未设置租户上下文，请先登录")
    if ctx.account_set_id is None:
        raise HTTPException(status_code=400, detail="请先选择账套（account_set_id 未设置）")
    return ctx.tenant_id, ctx.account_set_id


def _svc_error(exc: Exception) -> HTTPException:
    if isinstance(exc, HabitRuleNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, VoucherGenerationError):
        return HTTPException(status_code=500, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


# ── AI 凭证生成 ───────────────────────────────────────────────────────────────

@router.post(
    "/generate",
    response_model=VoucherDraftOut,
    status_code=200,
    summary="AI 生成凭证草稿（双层 Pipeline）",
)
def generate_voucher(
    body: GenerateVoucherInput,
    ctx:  tuple = Depends(_get_ctx),
    db:   Session = Depends(get_db),
) -> Any:
    """
    输入业务描述 → AI 生成标准借贷凭证草稿。

    Pipeline：
    1. 上层：关键词匹配 DAG 习惯规则 + SQL 嗅探进行中余额（State Slice）
    2. 下层：LLM 多轮 Tool Calling，通过 drill_down_subject 下钻科目树
    3. 断路器：Sum(借) != Sum(贷) 时挂入待查明科目，锁定 DRAFT_PENDING_REVIEW

    Sprint 3.1 只返回 JSON 草稿，不写入数据库。
    """
    tenant_id, account_set_id = ctx
    svc = AIVoucherService(db)
    try:
        return svc.generate_voucher(body, tenant_id, account_set_id)
    except Exception as exc:
        raise _svc_error(exc)


# ── AI 草稿确认入账 ───────────────────────────────────────────────────────────

@router.post(
    "/confirm",
    response_model=VoucherOut,
    status_code=201,
    summary="确认 AI 草稿入账（写入数据库）",
)
def confirm_voucher(
    body:         ConfirmVoucherInput,
    ctx:          tuple       = Depends(_get_ctx),
    db:           Session     = Depends(get_db),
    current_user: UserAccount = Depends(get_current_user),
) -> Any:
    """
    将 /generate 返回的凭证草稿持久化到数据库。

    前端工作流：
      1. POST /api/voucher-ai/generate   → 获得草稿 JSON
      2. 财务人员确认草稿内容
      3. POST /api/voucher-ai/confirm    → 写入数据库，返回 VoucherOut

    入库后凭证处于 DRAFT 状态，财务人员可通过 POST /api/vouchers/{id}/review 正式过账。

    字段说明：
      description  — 原始业务描述，写入 OperationalRecord.raw_text（建立业务→凭证可追溯链路）
      voucher_date — 凭证日期（通常与生成时的 voucher_date 一致，允许手动调整）
      voucher_word — 凭证字（默认"记"）
      memo         — 凭证摘要（来自草稿的 memo 字段）
      lines        — 分录行（来自草稿的 lines，auxiliary_data 由后端自动转换为 entity_id）
    """
    tenant_id, account_set_id = ctx
    svc = VoucherService(db)
    try:
        vh = svc.confirm_ai_draft(
            tenant_id, account_set_id, body, creator_id=current_user.id
        )
        db.commit()
        db.refresh(vh)
        return svc.get_voucher(vh.voucher_id, tenant_id, account_set_id)
    except Exception as exc:
        db.rollback()
        raise _svc_error(exc)


# ── 业务习惯规则 CRUD ─────────────────────────────────────────────────────────

@router.get(
    "/habit-rules",
    response_model=list[HabitRuleOut],
    status_code=200,
    summary="列出所有业务习惯规则（DAG 模板库）",
)
def list_habit_rules(
    ctx: tuple = Depends(_get_ctx),
    db:  Session = Depends(get_db),
) -> Any:
    """
    返回当前账套下所有业务习惯规则（含停用规则）。
    规则按 id 升序排列。
    """
    tenant_id, account_set_id = ctx
    svc = AIVoucherService(db)
    try:
        return svc.list_habit_rules(tenant_id, account_set_id)
    except Exception as exc:
        raise _svc_error(exc)


@router.post(
    "/habit-rules",
    response_model=HabitRuleOut,
    status_code=201,
    summary="创建业务习惯规则（DAG 模板）",
)
def create_habit_rule(
    body: HabitRuleCreateInput,
    ctx:  tuple = Depends(_get_ctx),
    db:   Session = Depends(get_db),
) -> Any:
    """
    创建一条 DAG 业务习惯规则。

    rule_json 必须符合以下格式：
    {
      "nodes": [
        {"id": "N1", "label": "首付挂长期待摊", "subject_hint": "1801", "action": "首次付款时执行"},
        {"id": "N2", "label": "次月起每月摊销", "subject_hint": "6602", "action": "次月1日起每月执行"}
      ],
      "edges": [
        {"from": "N1", "to": "N2", "condition": "次月1日起按月摊销，至金额归零"}
      ]
    }
    """
    tenant_id, account_set_id = ctx
    svc = AIVoucherService(db)
    try:
        rule = svc.create_habit_rule(tenant_id, account_set_id, body)
        db.commit()
        return rule
    except Exception as exc:
        db.rollback()
        raise _svc_error(exc)


@router.put(
    "/habit-rules/{rule_id}",
    response_model=HabitRuleOut,
    status_code=200,
    summary="更新业务习惯规则",
)
def update_habit_rule(
    rule_id: int,
    body:    HabitRuleUpdateInput,
    ctx:     tuple = Depends(_get_ctx),
    db:      Session = Depends(get_db),
) -> Any:
    """
    部分更新习惯规则。所有字段均为可选，未提供的字段保持不变。
    常用场景：临时停用规则（is_active=false），或调整关键词范围。
    """
    tenant_id, account_set_id = ctx
    svc = AIVoucherService(db)
    try:
        rule = svc.update_habit_rule(rule_id, tenant_id, account_set_id, body)
        db.commit()
        return rule
    except Exception as exc:
        db.rollback()
        raise _svc_error(exc)


@router.delete(
    "/habit-rules/{rule_id}",
    status_code=204,
    summary="删除业务习惯规则",
)
def delete_habit_rule(
    rule_id: int,
    ctx:     tuple = Depends(_get_ctx),
    db:      Session = Depends(get_db),
) -> None:
    """
    永久删除习惯规则。
    注意：删除规则不影响已生成的凭证（规则只在生成时使用，不存在外键依赖）。
    """
    tenant_id, account_set_id = ctx
    svc = AIVoucherService(db)
    try:
        svc.delete_habit_rule(rule_id, tenant_id, account_set_id)
        db.commit()
    except Exception as exc:
        db.rollback()
        raise _svc_error(exc)
