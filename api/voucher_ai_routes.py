"""
AgentLedger V4.0 — AI 凭证生成 API Routes (Sprint 3.1 / 3.2 / 3.4)

端点一览：
  POST   /api/voucher-ai/generate                — AI 双轨推荐（Sprint 3.4 新格式）
  POST   /api/voucher-ai/confirm                 — 确认草稿入账 + 触发学习钩子
  GET    /api/voucher-ai/habit-rules             — 列出所有业务习惯规则
  POST   /api/voucher-ai/habit-rules             — 创建业务习惯规则
  PUT    /api/voucher-ai/habit-rules/{rule_id}   — 更新业务习惯规则
  DELETE /api/voucher-ai/habit-rules/{rule_id}   — 删除业务习惯规则

Sprint 3.4 变更：
  /generate：返回体从 VoucherDraftOut → DualTrackResponse
  /confirm ：请求体新增 habit_rule_id（Optional），确认后异步触发学习循环
  Habit CRUD schema 从 voucher_ai_schemas 迁移至 habit_schemas
"""
import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from database.connection import get_db
from schemas.habit_schemas import HabitRuleCreateInput, HabitRuleUpdateInput, HabitRuleOut
from schemas.voucher_ai_schemas import (
    ConfirmVoucherInput,
    DualTrackResponse,
    GenerateVoucherInput,
)
from schemas.voucher_schemas import VoucherOut
from services.ai_voucher_service import (
    AIVoucherService,
    HabitRuleNotFoundError,
    VoucherGenerationError,
)
from services.habit_service import learn_from_voucher_async
from services.voucher_service import VoucherService
from services.auth_service import get_current_user
from models.user_account import UserAccount

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/voucher-ai", tags=["voucher-ai"])


# ── Context helper ────────────────────────────────────────────────────────────

def _get_ctx(
    user: UserAccount = Depends(get_current_user),
    db:   Session     = Depends(get_db),
) -> tuple[int, int]:
    from services.tenant_resolver import resolve_tenant_ctx
    return resolve_tenant_ctx(db, user)


def _svc_error(exc: Exception) -> HTTPException:
    if isinstance(exc, HabitRuleNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, VoucherGenerationError):
        return HTTPException(status_code=500, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


# ── AI 双轨推荐 ───────────────────────────────────────────────────────────────

@router.post(
    "/generate",
    response_model=DualTrackResponse,
    status_code=200,
    summary="AI 双轨推荐（历史习惯 + AI准则）",
)
def generate_voucher(
    body: GenerateVoucherInput,
    ctx:  tuple = Depends(_get_ctx),
    db:   Session = Depends(get_db),
) -> Any:
    """
    双轨制凭证生成。

    返回 recommendations 数组（1-2 条）：
    - Track A（HABIT）：基于历史习惯重建，冷启动时不存在
    - Track B（AI_RULE）：LLM 零样本推理，永远存在

    置信度说明：
    - HIGH   → weight>3 且金额在历史区间，可进入批量处理（Sprint 3.5）
    - MEDIUM → 有历史路径但样本少或金额突变，需人工确认
    - LOW    → 纯 AI 推断，绝不允许静默入库
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
    summary="确认 AI 草稿入账 + 触发学习循环",
)
def confirm_voucher(
    body:             ConfirmVoucherInput,
    background_tasks: BackgroundTasks,
    ctx:              tuple       = Depends(_get_ctx),
    db:               Session     = Depends(get_db),
    current_user:     UserAccount = Depends(get_current_user),
) -> Any:
    """
    将选定的凭证草稿持久化到数据库，并异步触发习惯学习循环。

    前端工作流：
      1. POST /generate → 获得 DualTrackResponse
      2. 财务人员选择 Track A 或 Track B
      3. POST /confirm，带上选定 draft 的内容 + habit_rule_id

    habit_rule_id 说明：
      - 选了 Track A → 传对应的 habit_rule_id（后端精准 weight++）
      - 选了 Track B → 不传（None），后端自动创建或更新匹配的规则

    学习循环在后台异步执行，使用独立 DB Session，任何报错均不影响本次入账。
    """
    tenant_id, account_set_id = ctx
    svc = VoucherService(db)
    try:
        vh = svc.confirm_ai_draft(
            tenant_id, account_set_id, body, creator_id=current_user.id
        )
        db.commit()
        db.refresh(vh)

        # ── 异步学习钩子（独立 Session，不复用此处的 db）────────────────────
        background_tasks.add_task(
            learn_from_voucher_async,
            voucher_id    = vh.voucher_id,
            habit_rule_id = body.habit_rule_id,
            description   = body.description,
        )

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
    tenant_id, account_set_id = ctx
    svc = AIVoucherService(db)
    try:
        svc.delete_habit_rule(rule_id, tenant_id, account_set_id)
        db.commit()
    except Exception as exc:
        db.rollback()
        raise _svc_error(exc)
