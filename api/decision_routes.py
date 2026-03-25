"""
AgentLedger — Boss Decision Card API

端点：
  GET  /api/decisions/{record_id}              获取（或生成）决策卡片
  POST /api/decisions/{decision_id}/choose     提交老板选择
  GET  /api/assets                             固定资产台账列表
  GET  /api/assets/{asset_id}                  单条资产详情
"""
import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database.connection import get_db
from models.boss_decision_log import BossDecisionLog, DecisionStatus
from models.asset_register import AssetRegister
from services.decision_service import DecisionService, DecisionServiceError
from ai.llm_client import LLMClientError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["decisions"])


# ── Request schemas ───────────────────────────────────────────────────────────

class ChoiceRequest(BaseModel):
    choice_id: str = Field(..., min_length=1, description="选中方案的 id，如 ONE_TIME、SL_10Y 等")


# ── Response helpers ──────────────────────────────────────────────────────────

def _decision_to_dict(d: BossDecisionLog) -> dict:
    try:
        options_data = json.loads(d.ai_options_json)
    except (json.JSONDecodeError, TypeError):
        options_data = {}

    return {
        "decision_id":        d.decision_id,
        "record_id":          d.record_id,
        "status":             d.status,
        "boss_choice":        d.boss_choice,
        "chosen_action_code": d.chosen_action_code,
        "expires_at":         str(d.expires_at) if d.expires_at else None,
        "decided_at":         str(d.decided_at) if d.decided_at else None,
        "created_at":         str(d.created_at) if d.created_at else None,
        # 核心内容：展开方案 JSON，方便前端直接使用
        "asset_category":        options_data.get("asset_category"),
        "tax_analysis":          options_data.get("tax_analysis"),
        "options":               options_data.get("options", []),
        "recommendation":        options_data.get("recommendation"),
        "recommendation_reason": options_data.get("recommendation_reason"),
        "not_recommended":       options_data.get("not_recommended", []),
        "not_recommended_reason":options_data.get("not_recommended_reason"),
        "financial_snapshot":    options_data.get("financial_snapshot", {}),
        "disclaimer":            options_data.get("disclaimer"),
    }


def _asset_to_dict(a: AssetRegister) -> dict:
    return {
        "asset_id":                   a.asset_id,
        "voucher_id":                 a.voucher_id,
        "decision_id":                a.decision_id,
        "asset_name":                 a.asset_name,
        "asset_category":             a.asset_category,
        "original_value":             float(a.original_value),
        "net_salvage_value":          float(a.net_salvage_value),
        "depreciation_method":        a.depreciation_method,
        "useful_life_months":         a.useful_life_months,
        "monthly_depreciation":       float(a.monthly_depreciation),
        "accumulated_depreciation":   float(a.accumulated_depreciation),
        "depreciation_months_elapsed":a.depreciation_months_elapsed,
        "net_book_value":             a.net_book_value,
        "status":                     a.status,
        "purchase_date":              str(a.purchase_date),
        "depreciation_start_month":   a.depreciation_start_month,
        "notes":                      a.notes,
    }


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/decisions/{record_id}")
def get_decision_card(record_id: int, db: Session = Depends(get_db)) -> Any:
    """
    获取指定流水的老板决策卡片。
    首次调用时自动触发 LLM 生成，后续直接读库（懒加载）。
    流水必须处于 PENDING_BOSS_DECISION 状态。
    """
    svc = DecisionService(db)
    try:
        card = svc.get_or_generate_card(record_id)
    except DecisionServiceError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except LLMClientError as exc:
        raise HTTPException(status_code=503, detail=f"AI 服务暂时不可用: {exc}")

    return _decision_to_dict(card)


@router.post("/decisions/{decision_id}/choose")
def submit_choice(
    decision_id: int,
    body:        ChoiceRequest,
    db:          Session = Depends(get_db),
) -> Any:
    """
    提交老板的方案选择，触发对应的凭证生成或建议记录。

    choice_id 必须是决策卡片 options 列表中某个方案的 id 字段值。

    返回执行结果，包含：
      - action：执行的动作类型
      - voucher_id：生成的凭证ID（如适用）
      - asset_id：创建的固定资产ID（如适用）
      - message：执行结果说明
    """
    svc = DecisionService(db)
    try:
        result = svc.execute_choice(decision_id, body.choice_id)
    except DecisionServiceError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return result


@router.get("/decisions")
def list_pending_decisions(
    status: str | None = Query(None, description="PENDING_DECISION / DECIDED / EXPIRED"),
    skip:   int        = Query(0, ge=0),
    limit:  int        = Query(50, ge=1, le=200),
    db:     Session    = Depends(get_db),
) -> Any:
    """
    列出所有决策记录（老板工作台用）。
    默认返回所有状态，可按 status 过滤。
    """
    q = db.query(BossDecisionLog)
    if status:
        q = q.filter(BossDecisionLog.status == status.upper())
    records = (
        q.order_by(BossDecisionLog.decision_id.desc())
        .offset(skip).limit(limit).all()
    )
    # 列表视图只返回摘要，不展开完整 options JSON
    return [
        {
            "decision_id":        d.decision_id,
            "record_id":          d.record_id,
            "status":             d.status,
            "boss_choice":        d.boss_choice,
            "chosen_action_code": d.chosen_action_code,
            "expires_at":         str(d.expires_at) if d.expires_at else None,
            "decided_at":         str(d.decided_at) if d.decided_at else None,
            "recommendation":     json.loads(d.ai_options_json).get("recommendation")
                                  if d.ai_options_json else None,
        }
        for d in records
    ]


@router.get("/assets")
def list_assets(
    status: str | None = Query(None, description="IN_USE / FULLY_DEPRECIATED / DISPOSED"),
    skip:   int        = Query(0, ge=0),
    limit:  int        = Query(100, ge=1, le=500),
    db:     Session    = Depends(get_db),
) -> Any:
    """固定资产台账列表。"""
    q = db.query(AssetRegister)
    if status:
        q = q.filter(AssetRegister.status == status.upper())
    assets = (
        q.order_by(AssetRegister.purchase_date.desc())
        .offset(skip).limit(limit).all()
    )
    return [_asset_to_dict(a) for a in assets]


@router.get("/assets/{asset_id}")
def get_asset(asset_id: int, db: Session = Depends(get_db)) -> Any:
    """单条固定资产详情。"""
    asset = db.get(AssetRegister, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail=f"资产 {asset_id} 不存在")
    return _asset_to_dict(asset)
