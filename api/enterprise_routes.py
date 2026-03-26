"""
AgentLedger — Enterprise Profile API

端点：
  POST /api/enterprise/profile        — 创建企业档案（首次使用必须先调用）
  GET  /api/enterprise/profile        — 获取当前激活的企业档案
  PUT  /api/enterprise/profile/{id}   — 更新企业档案（税率/阈值等）
  GET  /api/enterprise/route-preview  — 路由预览：输入金额和业务类型，返回会走哪条路
"""
import logging
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from database.connection import get_db
from models.enterprise_profile import (
    EnterpriseProfile,
    CompanyType,
    TaxPayerType,
    AccountingStandard,
)
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from services.transaction_router import TransactionRouter
from services.tax_annual_plan_service import TaxAnnualPlanService, TaxAnnualPlanServiceError
from models.tax_annual_plan import TaxAnnualPlan
from models.voucher_header import VoucherHeader
from models.voucher_line import VoucherLine
from ai.json_parser import ExtractedRecord
from ai.llm_client import LLMClientError
from sqlalchemy import func as sa_func

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/enterprise", tags=["enterprise"])


# ── 合法枚举值 ────────────────────────────────────────────────────────────────

VALID_COMPANY_TYPES     = {CompanyType.MICRO, CompanyType.STANDARD}
VALID_TAX_PAYER_TYPES   = {TaxPayerType.SMALL_SCALE, TaxPayerType.GENERAL}
VALID_ACCOUNTING_STDS   = {AccountingStandard.SMALL_BIZ, AccountingStandard.GENERAL}

VALID_INCOME_TAX_RATES  = {
    Decimal("0.2500"),  # 一般企业
    Decimal("0.2000"),  # 小型微利企业名义税率
    Decimal("0.1500"),  # 高新技术企业
    Decimal("0.0500"),  # 小型微利企业实际优惠税率（年利润≤300万）
}

VALID_VAT_RATES = {
    Decimal("0.0300"),  # 小规模纳税人
    Decimal("0.0500"),  # 小规模：不动产/金融服务
    Decimal("0.0600"),  # 一般纳税人：现代服务/金融/技术咨询
    Decimal("0.0900"),  # 一般纳税人：交通运输/建筑/农产品
    Decimal("0.1300"),  # 一般纳税人：货物销售/制造业
}


# ── Request schemas ───────────────────────────────────────────────────────────

class CreateProfileRequest(BaseModel):
    company_name:               str     = Field(..., min_length=1, max_length=200)
    company_type:               str     = Field(default=CompanyType.MICRO)
    industry_code:              str     = Field(default="通用", max_length=50)
    tax_payer_type:             str     = Field(default=TaxPayerType.SMALL_SCALE)
    applicable_income_tax_rate: Decimal = Field(default=Decimal("0.2000"))
    vat_rate:                   Decimal = Field(default=Decimal("0.0300"))
    decision_threshold:         Decimal = Field(default=Decimal("5000.00"), gt=0)
    accounting_standard:        str     = Field(default=AccountingStandard.SMALL_BIZ)

    @field_validator("company_type")
    @classmethod
    def validate_company_type(cls, v: str) -> str:
        if v not in VALID_COMPANY_TYPES:
            raise ValueError(f"company_type 必须是 {VALID_COMPANY_TYPES}")
        return v

    @field_validator("tax_payer_type")
    @classmethod
    def validate_tax_payer_type(cls, v: str) -> str:
        if v not in VALID_TAX_PAYER_TYPES:
            raise ValueError(f"tax_payer_type 必须是 {VALID_TAX_PAYER_TYPES}")
        return v

    @field_validator("applicable_income_tax_rate")
    @classmethod
    def validate_income_tax(cls, v: Decimal) -> Decimal:
        if v not in VALID_INCOME_TAX_RATES:
            raise ValueError(
                f"applicable_income_tax_rate 必须是合法税率之一："
                f"{sorted(VALID_INCOME_TAX_RATES)}"
            )
        return v

    @field_validator("vat_rate")
    @classmethod
    def validate_vat(cls, v: Decimal) -> Decimal:
        if v not in VALID_VAT_RATES:
            raise ValueError(
                f"vat_rate 必须是合法增值税率之一：{sorted(VALID_VAT_RATES)}"
            )
        return v

    @field_validator("accounting_standard")
    @classmethod
    def validate_std(cls, v: str) -> str:
        if v not in VALID_ACCOUNTING_STDS:
            raise ValueError(f"accounting_standard 必须是 {VALID_ACCOUNTING_STDS}")
        return v


class UpdateProfileRequest(BaseModel):
    company_name:               str     | None = Field(default=None, min_length=1, max_length=200)
    company_type:               str     | None = None
    industry_code:              str     | None = Field(default=None, max_length=50)
    tax_payer_type:             str     | None = None
    applicable_income_tax_rate: Decimal | None = None
    vat_rate:                   Decimal | None = None
    decision_threshold:         Decimal | None = Field(default=None, gt=0)
    accounting_standard:        str     | None = None


class RoutePreviewRequest(BaseModel):
    amount:       float = Field(..., gt=0, description="流水金额（元）")
    expense_type: str   = Field(..., min_length=1, description="业务类型，如'办公用品'、'购买设备'")


# ── Response helper ───────────────────────────────────────────────────────────

def _profile_to_dict(p: EnterpriseProfile) -> dict:
    return {
        "company_id":                   p.company_id,
        "company_name":                 p.company_name,
        "company_type":                 p.company_type,
        "industry_code":                p.industry_code,
        "tax_payer_type":               p.tax_payer_type,
        "applicable_income_tax_rate":   float(p.applicable_income_tax_rate),
        "vat_rate":                     float(p.vat_rate),
        "decision_threshold":           float(p.decision_threshold),
        "accounting_standard":          p.accounting_standard,
        "is_active":                    bool(p.is_active),
        "created_at":                   str(p.created_at) if p.created_at else None,
        "updated_at":                   str(p.updated_at) if p.updated_at else None,
    }


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/profile", status_code=201)
def create_profile(
    body: CreateProfileRequest,
    db:   Session = Depends(get_db),
) -> Any:
    """
    创建企业档案。
    创建时自动将所有已有档案 is_active 置为 0，新档案设为激活状态。
    系统同时只有一条激活记录。
    """
    # 停用旧档案
    db.query(EnterpriseProfile).filter(EnterpriseProfile.is_active == 1).update(
        {"is_active": 0}
    )

    profile = EnterpriseProfile(
        company_name               = body.company_name,
        company_type               = body.company_type,
        industry_code              = body.industry_code,
        tax_payer_type             = body.tax_payer_type,
        applicable_income_tax_rate = body.applicable_income_tax_rate,
        vat_rate                   = body.vat_rate,
        decision_threshold         = body.decision_threshold,
        accounting_standard        = body.accounting_standard,
        is_active                  = 1,
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    logger.info("EnterpriseProfile created: id=%s name=%s", profile.company_id, profile.company_name)
    return _profile_to_dict(profile)


@router.get("/profile")
def get_active_profile(db: Session = Depends(get_db)) -> Any:
    """获取当前激活的企业档案。"""
    profile = db.query(EnterpriseProfile).filter(EnterpriseProfile.is_active == 1).first()
    if not profile:
        raise HTTPException(
            status_code=404,
            detail="未找到企业档案，请先调用 POST /api/enterprise/profile 创建档案"
        )
    return _profile_to_dict(profile)


@router.put("/profile/{company_id}")
def update_profile(
    company_id: int,
    body:       UpdateProfileRequest,
    db:         Session = Depends(get_db),
) -> Any:
    """更新企业档案（部分更新，只传需要修改的字段）。"""
    profile = db.get(EnterpriseProfile, company_id)
    if not profile:
        raise HTTPException(status_code=404, detail=f"企业档案 {company_id} 不存在")

    update_data = body.model_dump(exclude_none=True)

    # 逐项校验并更新
    if "company_type" in update_data and update_data["company_type"] not in VALID_COMPANY_TYPES:
        raise HTTPException(status_code=422, detail=f"company_type 非法值")
    if "tax_payer_type" in update_data and update_data["tax_payer_type"] not in VALID_TAX_PAYER_TYPES:
        raise HTTPException(status_code=422, detail=f"tax_payer_type 非法值")
    if "applicable_income_tax_rate" in update_data:
        rate = Decimal(str(update_data["applicable_income_tax_rate"]))
        if rate not in VALID_INCOME_TAX_RATES:
            raise HTTPException(status_code=422, detail="applicable_income_tax_rate 非法税率")
        update_data["applicable_income_tax_rate"] = rate
    if "vat_rate" in update_data:
        rate = Decimal(str(update_data["vat_rate"]))
        if rate not in VALID_VAT_RATES:
            raise HTTPException(status_code=422, detail="vat_rate 非法增值税率")
        update_data["vat_rate"] = rate

    for field, value in update_data.items():
        setattr(profile, field, value)

    db.commit()
    db.refresh(profile)
    logger.info("EnterpriseProfile updated: id=%s fields=%s", company_id, list(update_data.keys()))
    return _profile_to_dict(profile)


@router.post("/route-preview")
def route_preview(
    body: RoutePreviewRequest,
    db:   Session = Depends(get_db),
) -> Any:
    """
    路由预览接口（调试/前端提示用）。
    输入金额和业务类型，返回该笔流水会走哪条路径，以及触发原因。
    不写入任何数据。
    """
    router_svc = TransactionRouter(db)

    # 构造最小化 ExtractedRecord 供路由判断
    mock_extracted = ExtractedRecord(
        amount         = body.amount,
        currency       = "CNY",
        expense_type   = body.expense_type,
        payment_method = "未指定",
        payer_name     = None,
        counterparty   = None,
        memo           = "",
        confidence     = 1.0,
        raw_json       = "{}",
    )

    decision, reason = router_svc.decide(mock_extracted)
    profile          = router_svc.get_active_profile()

    return {
        "input": {
            "amount":       body.amount,
            "expense_type": body.expense_type,
        },
        "decision": decision.value,
        "reason":   reason or "金额未超阈值且无敏感关键词，自动记账",
        "threshold": float(profile.decision_threshold) if profile else None,
        "profile_active": profile is not None,
    }


# ── Annual Tax Plan endpoints ──────────────────────────────────────────────────

def _plan_to_dict(plan: TaxAnnualPlan) -> dict:
    import json as _json
    try:
        plan_data = _json.loads(plan.plan_json)
    except Exception:
        plan_data = {}
    return {
        "plan_id":      plan.plan_id,
        "company_id":   plan.company_id,
        "year":         plan.year,
        "status":       plan.status,
        "generated_at": str(plan.generated_at) if plan.generated_at else None,
        "updated_at":   str(plan.updated_at)   if plan.updated_at   else None,
        **plan_data,
    }


@router.get("/annual-plan/{year}")
def get_annual_plan(year: int, db: Session = Depends(get_db)) -> Any:
    """
    获取指定年份的当前生效年度税务规划。
    若该年份尚无规划，返回 404。
    """
    svc  = TaxAnnualPlanService(db)
    plan = svc.get_active_plan(year)
    if not plan:
        raise HTTPException(
            status_code=404,
            detail=f"{year} 年度规划尚未生成，请调用 POST /api/enterprise/annual-plan/{year}/generate"
        )
    return _plan_to_dict(plan)


@router.post("/annual-plan/{year}/generate", status_code=201)
def generate_annual_plan(year: int, db: Session = Depends(get_db)) -> Any:
    """
    （重新）生成指定年份的年度税务筹划路线图。
    - 调用 LLM 生成 Q1-Q4 四季度行动计划
    - 旧规划自动标记为 OUTDATED
    - 需要先配置企业档案
    """
    if year < 2020 or year > 2030:
        raise HTTPException(status_code=422, detail="year 必须在 2020-2030 范围内")

    svc = TaxAnnualPlanService(db)
    try:
        plan = svc.generate_plan(year)
    except TaxAnnualPlanServiceError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except LLMClientError as exc:
        raise HTTPException(status_code=503, detail=f"AI 服务暂时不可用: {exc}")

    return _plan_to_dict(plan)


# ── Threshold recommendation endpoint ─────────────────────────────────────────

@router.get("/threshold-recommendation")
def get_threshold_recommendation(db: Session = Depends(get_db)) -> Any:
    """
    基于当前财务数据推荐决策阈值。

    公式：
      base     = 近3个月月均收入 × 3%
      clamped  = max(2000, min(100000, base))
      final    = min(clamped, 现金余额 × 20%)  # 仅当现金 < clamped × 3 时触发
    """
    today     = date.today()
    three_ago = date(
        today.year if today.month > 3 else today.year - 1,
        (today.month - 3) % 12 or 12,
        1,
    )

    # 近3个月月均收入（科目 6001%，贷方）
    revenue_row = (
        db.query(sa_func.sum(VoucherLine.amount))
        .join(VoucherHeader, VoucherLine.voucher_id == VoucherHeader.voucher_id)
        .filter(
            VoucherLine.subject_code.like("6001%"),
            VoucherLine.direction == "CREDIT",
            VoucherHeader.voucher_date >= three_ago,
        )
        .scalar()
    )
    total_3m_revenue    = Decimal(str(revenue_row or 0))
    avg_monthly_revenue = (total_3m_revenue / 3).quantize(Decimal("1"), rounding=ROUND_HALF_UP)

    # 银行存款余额（科目 1002，借方 - 贷方）
    cash_debit = db.query(sa_func.sum(VoucherLine.amount)).filter(
        VoucherLine.subject_code == "1002", VoucherLine.direction == "DEBIT"
    ).scalar() or 0
    cash_credit = db.query(sa_func.sum(VoucherLine.amount)).filter(
        VoucherLine.subject_code == "1002", VoucherLine.direction == "CREDIT"
    ).scalar() or 0
    cash_balance = max(Decimal("0"), Decimal(str(cash_debit)) - Decimal(str(cash_credit)))

    # 公式
    FLOOR   = Decimal("2000")
    CEILING = Decimal("100000")
    base    = (avg_monthly_revenue * Decimal("0.03")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    clamped = max(FLOOR, min(CEILING, base))

    cash_safety_triggered = False
    cash_limit            = Decimal("0")
    final                 = clamped

    if cash_balance > 0 and cash_balance < clamped * 3:
        cash_limit            = (cash_balance * Decimal("0.20")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        final                 = min(clamped, cash_limit)
        cash_safety_triggered = True

    final = max(FLOOR, final)

    # 说明文字
    if avg_monthly_revenue == 0:
        rule = "暂无收入数据，使用最低保护值 ¥2,000"
    elif cash_safety_triggered:
        rule = f"现金偏低（¥{int(cash_balance):,}），安全兜底：现金 × 20%"
    elif base < FLOOR:
        rule = f"月均收入 × 3% = ¥{int(base):,}，低于下限，取 ¥2,000"
    elif base > CEILING:
        rule = f"月均收入 × 3% = ¥{int(base):,}，超过上限，取 ¥100,000"
    else:
        rule = f"月均收入 ¥{int(avg_monthly_revenue):,} × 3% = ¥{int(base):,}"

    return {
        "recommended_threshold": int(final),
        "formula_detail": {
            "avg_monthly_revenue_3m": int(avg_monthly_revenue),
            "cash_balance":           int(cash_balance),
            "base_3pct":              int(base),
            "floor":                  int(FLOOR),
            "ceiling":                int(CEILING),
            "cash_safety_triggered":  cash_safety_triggered,
            "cash_limit_20pct":       int(cash_limit) if cash_safety_triggered else None,
        },
        "rule_applied": rule,
    }
