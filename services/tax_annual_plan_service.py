"""
AgentLedger — TaxAnnualPlanService

生成和查询年度税务筹划路线图。

流程：
  1. 查询企业画像（激活档案）
  2. 从凭证表统计今年 YTD 利润和收入
  3. 调用 LLM 生成 Q1-Q4 JSON 路线图
  4. 存入 tax_annual_plan 表（ACTIVE），旧规划标记 OUTDATED
"""
import json
import logging
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from models.enterprise_profile import EnterpriseProfile
from models.tax_annual_plan import TaxAnnualPlan, PlanStatus
from models.voucher_header import VoucherHeader
from models.voucher_line import VoucherLine
from ai.llm_client import LLMClient, LLMClientError
from ai.annual_plan_prompts import build_annual_plan_prompt
from models.asset_register import AssetRegister, AssetStatus

logger = logging.getLogger(__name__)


class TaxAnnualPlanServiceError(Exception):
    pass


class TaxAnnualPlanService:
    def __init__(self, db: Session) -> None:
        self._db  = db
        self._llm = LLMClient()

    # ── Public API ─────────────────────────────────────────────────────────────

    def get_active_plan(self, year: int) -> TaxAnnualPlan | None:
        """返回指定年份当前生效的规划，无则返回 None。"""
        return (
            self._db.query(TaxAnnualPlan)
            .filter(
                TaxAnnualPlan.year   == year,
                TaxAnnualPlan.status == PlanStatus.ACTIVE,
            )
            .order_by(TaxAnnualPlan.plan_id.desc())
            .first()
        )

    def generate_plan(self, year: int) -> TaxAnnualPlan:
        """
        为指定年份生成新规划。
        - 旧 ACTIVE 规划标记为 OUTDATED
        - 调用 LLM 生成 JSON，验证格式后存库
        """
        profile = self._get_active_profile()

        # 统计 YTD 财务数据
        ytd_profit, ytd_revenue = self._calc_ytd(year)
        asset_count              = self._count_assets()
        current_month            = datetime.now().month if datetime.now().year == year else 12

        # 构造 LLM 提示词
        user_prompt = build_annual_plan_prompt(
            year            = year,
            company_name    = profile.company_name,
            company_type    = profile.company_type,
            industry_code   = profile.industry_code,
            tax_payer_type  = profile.tax_payer_type,
            income_tax_rate = float(profile.applicable_income_tax_rate),
            vat_rate        = float(profile.vat_rate),
            ytd_profit      = float(ytd_profit),
            ytd_revenue     = float(ytd_revenue),
            current_month   = current_month,
            asset_count     = asset_count,
        )

        # 调用 LLM
        try:
            raw_json = self._llm.generate_annual_plan(user_prompt)
        except LLMClientError as exc:
            raise TaxAnnualPlanServiceError(f"LLM 调用失败: {exc}") from exc

        # 验证 JSON 可解析且含必要字段
        try:
            plan_data = json.loads(raw_json)
            if "quarters" not in plan_data or len(plan_data["quarters"]) != 4:
                raise ValueError("quarters 字段缺失或不足4个季度")
        except (json.JSONDecodeError, ValueError) as exc:
            raise TaxAnnualPlanServiceError(f"LLM 输出格式错误: {exc}") from exc

        # 旧规划 OUTDATED
        self._db.query(TaxAnnualPlan).filter(
            TaxAnnualPlan.year   == year,
            TaxAnnualPlan.status == PlanStatus.ACTIVE,
            TaxAnnualPlan.company_id == profile.company_id,
        ).update({"status": PlanStatus.OUTDATED})

        # 存新规划
        plan = TaxAnnualPlan(
            company_id = profile.company_id,
            year       = year,
            plan_json  = raw_json,
            status     = PlanStatus.ACTIVE,
        )
        self._db.add(plan)
        self._db.commit()
        self._db.refresh(plan)
        logger.info("Annual tax plan generated: plan_id=%s year=%s", plan.plan_id, year)
        return plan

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _get_active_profile(self) -> EnterpriseProfile:
        profile = (
            self._db.query(EnterpriseProfile)
            .filter(EnterpriseProfile.is_active == 1)
            .first()
        )
        if not profile:
            raise TaxAnnualPlanServiceError(
                "未找到企业档案，请先在企业设置中创建档案"
            )
        return profile

    def _calc_ytd(self, year: int) -> tuple[Decimal, Decimal]:
        """
        从凭证明细粗算 YTD 利润和收入。
        收入 = 6001(主营业务收入) 贷方合计
        成本 = 6401(主营业务成本) 借方合计
        利润 = 收入 - 成本（简化计算，不计其他费用）
        """
        from models.voucher_line import VoucherLine
        from models.voucher_header import VoucherHeader

        year_prefix = f"{year}-%"

        # 收入：科目 6001，贷方
        revenue_row = (
            self._db.query(func.sum(VoucherLine.amount))
            .join(VoucherHeader, VoucherLine.voucher_id == VoucherHeader.voucher_id)
            .filter(
                VoucherLine.subject_code.like("6001%"),
                VoucherLine.direction == "CREDIT",
                VoucherHeader.voucher_date.cast(text("CHAR")).like(year_prefix),
            )
            .scalar()
        )
        ytd_revenue = Decimal(str(revenue_row or 0))

        # 成本：科目 6401，借方
        cost_row = (
            self._db.query(func.sum(VoucherLine.amount))
            .join(VoucherHeader, VoucherLine.voucher_id == VoucherHeader.voucher_id)
            .filter(
                VoucherLine.subject_code.like("6401%"),
                VoucherLine.direction == "DEBIT",
                VoucherHeader.voucher_date.cast(text("CHAR")).like(year_prefix),
            )
            .scalar()
        )
        ytd_cost = Decimal(str(cost_row or 0))

        ytd_profit = ytd_revenue - ytd_cost
        return ytd_profit, ytd_revenue

    def _count_assets(self) -> int:
        """统计当前 IN_USE 固定资产数量。"""
        return (
            self._db.query(AssetRegister)
            .filter(AssetRegister.status == AssetStatus.IN_USE)
            .count()
        )
