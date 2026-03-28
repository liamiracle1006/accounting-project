"""
AgentLedger — DecisionService

核心职责：
  1. get_or_generate_card(record_id)
     — 懒加载：首次调用时触发 LLM 生成方案，之后直接读库
     — 财务快照查询（今年利润 + 当前现金）注入到 LLM Prompt
     — Python depreciation.py 重新计算税务数字，覆盖 LLM 输出，保证准确性

  2. execute_choice(decision_id, choice_id)
     — 读取选中方案的 action_code，分支执行：
       FIXED_ASSET_* → 生成固定资产凭证 + 写入 asset_register
       EXPENSE_DIRECT → 生成普通费用凭证
       SUGGEST_LEASE / DEFER_PURCHASE → 不生成凭证，记录处理结果
     — 更新 boss_decision_log 和 operational_record 状态

action_code → 凭证科目映射：
  固定资产购入：借 1601 固定资产 / 贷 1002 银行存款（或 2202 应付账款）
  直接费用化：   按原有 accounting_engine 逻辑处理
"""
import json
import logging
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from ai.llm_client import LLMClient, LLMClientError
from ai.decision_prompts import build_decision_user_prompt
from ai.json_parser import parse_llm_output
from rag.retriever import TaxStrategyRetriever, RetrievalContext
from models.operational_record import OperationalRecord, RecordStatus
from models.boss_decision_log import BossDecisionLog, DecisionStatus
from models.asset_register import AssetRegister, DepreciationMethod, AssetStatus
from models.voucher_header import VoucherHeader, VoucherReviewStatus
from models.voucher_line import VoucherLine
from models.account_subject import AccountSubject
from models.enterprise_profile import EnterpriseProfile
from services.depreciation import get_all_summaries, DepreciationSummary
from services.accounting_engine import AccountingEngineService, AccountingError

logger = logging.getLogger(__name__)

# 决策卡片有效期（天）
DECISION_EXPIRY_DAYS = 30

# action_code 中包含这些前缀 → 固定资产流程
FIXED_ASSET_PREFIXES = ("FIXED_ASSET_",)

# action_code → 折旧方法 + 年限（月）解析
_STRAIGHT_LINE_CODES = {
    "FIXED_ASSET_STRAIGHT_LINE_3Y":  (DepreciationMethod.STRAIGHT_LINE,  36),
    "FIXED_ASSET_STRAIGHT_LINE_4Y":  (DepreciationMethod.STRAIGHT_LINE,  48),
    "FIXED_ASSET_STRAIGHT_LINE_5Y":  (DepreciationMethod.STRAIGHT_LINE,  60),
    "FIXED_ASSET_STRAIGHT_LINE_10Y": (DepreciationMethod.STRAIGHT_LINE, 120),
    "FIXED_ASSET_STRAIGHT_LINE_20Y": (DepreciationMethod.STRAIGHT_LINE, 240),
}
_ACCELERATED_CODES = {
    "FIXED_ASSET_ACCELERATED_3Y": (DepreciationMethod.ACCELERATED,  36),
    "FIXED_ASSET_ACCELERATED_5Y": (DepreciationMethod.ACCELERATED,  60),
}


class DecisionServiceError(ValueError):
    pass


class DecisionService:
    def __init__(self, db: Session) -> None:
        self._db       = db
        self._llm      = LLMClient()
        self._retriever = TaxStrategyRetriever()

    # ── Public: 获取或生成决策卡片 ─────────────────────────────────────────────

    def get_or_generate_card(self, record_id: int) -> BossDecisionLog:
        """
        懒加载决策卡片。
        已有未过期卡片 → 直接返回。
        无卡片或已过期 → 重新生成。
        """
        existing = (
            self._db.query(BossDecisionLog)
            .filter(BossDecisionLog.record_id == record_id)
            .order_by(BossDecisionLog.decision_id.desc())
            .first()
        )
        if existing and existing.status == DecisionStatus.PENDING_DECISION and not existing.is_expired():
            logger.info("Decision card cache hit for record_id=%s", record_id)
            return existing

        return self._generate_card(record_id)

    # ── Public: 执行老板选择 ───────────────────────────────────────────────────

    def execute_choice(self, decision_id: int, choice_id: str) -> dict:
        """
        执行老板的选择，返回执行结果摘要。
        """
        decision = self._db.get(BossDecisionLog, decision_id)
        if not decision:
            raise DecisionServiceError(f"Decision {decision_id} 不存在")
        if decision.status == DecisionStatus.DECIDED:
            raise DecisionServiceError("该决策已执行，不能重复选择")
        if decision.is_expired():
            decision.status = DecisionStatus.EXPIRED
            self._db.commit()
            raise DecisionServiceError("决策卡片已过期，请重新获取")

        # 从 JSON 中找到对应选项
        options_data = json.loads(decision.ai_options_json)
        chosen_option = next(
            (o for o in options_data.get("options", []) if o["id"] == choice_id),
            None,
        )
        if not chosen_option:
            raise DecisionServiceError(f"选项 '{choice_id}' 不在本决策卡片中")

        action_code = chosen_option["action_code"]
        record      = self._db.get(OperationalRecord, decision.record_id)
        extracted   = parse_llm_output(record.extracted_json)

        result = self._execute_action(action_code, chosen_option, record, extracted, decision)

        # 更新决策记录
        decision.boss_choice        = choice_id
        decision.chosen_action_code = action_code
        decision.status             = DecisionStatus.DECIDED
        decision.decided_at         = datetime.utcnow()

        # 将同一流水的其他 PENDING 重复卡片标为 EXPIRED（防止双击产生孤儿卡）
        self._db.query(BossDecisionLog).filter(
            BossDecisionLog.record_id  == decision.record_id,
            BossDecisionLog.decision_id != decision_id,
            BossDecisionLog.status     == DecisionStatus.PENDING_DECISION,
        ).update({"status": DecisionStatus.EXPIRED})

        # 审计日志：老板决策执行
        from services.audit_guard import audit_boss_decision
        audit_boss_decision(self._db, decision_id, choice_id)

        self._db.commit()

        logger.info(
            "Decision executed: decision_id=%s choice=%s action=%s",
            decision_id, choice_id, action_code,
        )
        return result

    # ── Internal: 生成决策卡片 ─────────────────────────────────────────────────

    def _generate_card(self, record_id: int) -> BossDecisionLog:
        record = self._db.get(OperationalRecord, record_id)
        if not record:
            raise DecisionServiceError(f"Record {record_id} 不存在")
        if record.status != RecordStatus.PENDING_BOSS_DECISION:
            raise DecisionServiceError(
                f"Record {record_id} 状态为 {record.status}，不在待决策状态"
            )

        extracted = parse_llm_output(record.extracted_json)
        profile   = self._get_active_profile()
        snapshot  = self._get_financial_snapshot()

        # RAG 检索：根据企业画像 + 业务描述获取相关政策
        rag_hits = []
        try:
            rag_ctx = RetrievalContext(
                query_text    = f"{extracted.expense_type} {record.raw_text}",
                taxpayer_type = profile.tax_payer_type if profile else "ALL",
                industry_code = profile.industry_code  if profile else "ALL",
                province      = profile.province or "" if profile else "",
                city          = profile.city     or "" if profile else "",
                ytd_profit    = snapshot["ytd_profit"],
                top_k         = 5,
                query_date    = str(date.today()),
            )
            rag_hits = self._retriever.retrieve(rag_ctx)
            logger.info("RAG retrieved %d hits for decision card", len(rag_hits))
        except Exception as exc:
            logger.warning("RAG retrieval failed, continuing without policy context: %s", exc)

        # 调用 LLM 生成方案结构
        user_prompt = build_decision_user_prompt(
            expense_type    = extracted.expense_type,
            amount          = float(extracted.amount),
            raw_text        = record.raw_text,
            company_type    = profile.company_type if profile else "MICRO",
            industry_code   = profile.industry_code if profile else "通用",
            income_tax_rate = float(profile.applicable_income_tax_rate) if profile else 0.20,
            ytd_profit      = snapshot["ytd_profit"],
            current_cash    = snapshot["current_cash"],
            current_month   = datetime.now().month,
            rag_hits        = rag_hits,
            is_hnte         = bool(profile.is_hnte)    if profile else False,
            rd_eligible     = bool(profile.rd_eligible) if profile else False,
            province        = profile.province or ""   if profile else "",
            city            = profile.city     or ""   if profile else "",
        )

        try:
            raw_json = self._llm.generate_decision_options(user_prompt)
            options_data = json.loads(raw_json)
        except (LLMClientError, json.JSONDecodeError) as exc:
            raise DecisionServiceError(f"LLM 生成决策卡片失败: {exc}") from exc

        # Python 重算税务数字，覆盖 LLM 输出（保证数字准确）
        tax_rate = float(profile.applicable_income_tax_rate) if profile else 0.20
        options_data = self._recalculate_savings(
            options_data, float(extracted.amount), tax_rate, date.today()
        )

        # 注入财务快照（供前端展示）
        options_data["financial_snapshot"] = snapshot
        options_data["disclaimer"] = "以上方案基于现行税法自动生成，重大决策（单笔超50万）建议咨询专业税务师确认"

        log = BossDecisionLog(
            record_id       = record_id,
            ai_options_json = json.dumps(options_data, ensure_ascii=False),
            status          = DecisionStatus.PENDING_DECISION,
            expires_at      = datetime.utcnow() + timedelta(days=DECISION_EXPIRY_DAYS),
        )
        self._db.add(log)
        self._db.commit()
        self._db.refresh(log)
        logger.info("Decision card generated: decision_id=%s record_id=%s options=%d",
                    log.decision_id, record_id, len(options_data.get("options", [])))
        return log

    # ── Internal: 财务快照 ─────────────────────────────────────────────────────

    def _get_financial_snapshot(self) -> dict:
        """
        实时查询当年利润和当前现金余额。
        收入科目 6001-6399 贷方 - 费用科目 6400-6899 借方 = 年度利润
        资产科目 1001+1002+1012 借贷差额 = 当前现金
        """
        current_year = datetime.now().year

        # 年度收入（科目 6001-6399，贷方）
        income_total = float(
            self._db.query(func.sum(VoucherLine.amount))
            .join(VoucherHeader, VoucherHeader.voucher_id == VoucherLine.voucher_id)
            .filter(
                VoucherLine.subject_code >= "6001",
                VoucherLine.subject_code <  "6400",
                VoucherLine.direction == "CREDIT",
                func.year(VoucherHeader.voucher_date) == current_year,
            )
            .scalar() or 0
        )

        # 年度费用（科目 6400-6899，借方）
        expense_total = float(
            self._db.query(func.sum(VoucherLine.amount))
            .join(VoucherHeader, VoucherHeader.voucher_id == VoucherLine.voucher_id)
            .filter(
                VoucherLine.subject_code >= "6400",
                VoucherLine.subject_code <  "6900",
                VoucherLine.direction == "DEBIT",
                func.year(VoucherHeader.voucher_date) == current_year,
            )
            .scalar() or 0
        )

        ytd_profit = income_total - expense_total

        # 当前现金余额（1001 库存现金 + 1002 银行存款 + 1012 其他货币资金）
        cash_debit = float(
            self._db.query(func.sum(VoucherLine.amount))
            .join(VoucherHeader, VoucherHeader.voucher_id == VoucherLine.voucher_id)
            .filter(
                VoucherLine.subject_code.in_(["1001", "1002", "1012"]),
                VoucherLine.direction == "DEBIT",
            )
            .scalar() or 0
        )
        cash_credit = float(
            self._db.query(func.sum(VoucherLine.amount))
            .join(VoucherHeader, VoucherHeader.voucher_id == VoucherLine.voucher_id)
            .filter(
                VoucherLine.subject_code.in_(["1001", "1002", "1012"]),
                VoucherLine.direction == "CREDIT",
            )
            .scalar() or 0
        )
        current_cash = cash_debit - cash_credit

        return {
            "ytd_profit":    round(ytd_profit, 2),
            "current_cash":  round(current_cash, 2),
            "snapshot_year": current_year,
        }

    # ── Internal: 重算税务数字 ─────────────────────────────────────────────────

    def _recalculate_savings(
        self,
        options_data: dict,
        amount:       float,
        tax_rate:     float,
        today:        date,
    ) -> dict:
        """
        用 Python depreciation.py 重新计算每个选项的节税数字，
        覆盖 LLM 给出的 savings_this_year 和 savings_total。
        """
        # 确定候选年限（从 options 中提取 useful_life_months）
        candidate_lives = list({
            o["useful_life_months"]
            for o in options_data.get("options", [])
            if o.get("useful_life_months", 0) > 0
        })

        salvage_value = amount * 0.05   # 默认5%残值，一次性扣除时为0

        summaries = get_all_summaries(
            original_value  = amount,
            salvage_value   = salvage_value,
            tax_rate        = tax_rate,
            purchase_date   = today,
            candidate_lives = candidate_lives,
        )

        for option in options_data.get("options", []):
            action_code = option.get("action_code", "")
            summary: DepreciationSummary | None = summaries.get(action_code)
            if summary:
                option["savings_this_year"] = summary.this_year_tax_savings
                option["savings_total"]     = summary.total_tax_savings
                option["monthly_dep_first"] = summary.monthly_depreciation
                # 一次性扣除残值为0
                if action_code == "FIXED_ASSET_ONE_TIME":
                    option["salvage_rate"] = 0

        return options_data

    # ── Internal: 执行 action ─────────────────────────────────────────────────

    def _execute_action(
        self,
        action_code:    str,
        chosen_option:  dict,
        record:         OperationalRecord,
        extracted,
        decision:       BossDecisionLog,
    ) -> dict:
        """根据 action_code 分支执行对应的业务逻辑。"""

        if action_code == "FIXED_ASSET_ONE_TIME":
            return self._post_fixed_asset(
                record, extracted, decision,
                dep_method     = DepreciationMethod.ONE_TIME,
                life_months    = 1,
                salvage_rate   = 0.0,
                asset_category = self._get_asset_category(decision),
            )

        if action_code in _STRAIGHT_LINE_CODES:
            method, life = _STRAIGHT_LINE_CODES[action_code]
            return self._post_fixed_asset(
                record, extracted, decision,
                dep_method     = method,
                life_months    = life,
                salvage_rate   = chosen_option.get("salvage_rate", 0.05),
                asset_category = self._get_asset_category(decision),
            )

        if action_code in _ACCELERATED_CODES:
            method, life = _ACCELERATED_CODES[action_code]
            return self._post_fixed_asset(
                record, extracted, decision,
                dep_method     = method,
                life_months    = life,
                salvage_rate   = chosen_option.get("salvage_rate", 0.05),
                asset_category = self._get_asset_category(decision),
            )

        if action_code == "EXPENSE_DIRECT":
            return self._post_direct_expense(record, extracted)

        if action_code in ("SUGGEST_LEASE", "DEFER_PURCHASE"):
            # 不生成凭证，记录老板决定不购买/改租赁
            record.status = RecordStatus.PROCESSED
            record.error_message = f"老板决策：{chosen_option.get('title', action_code)}"
            return {"action": action_code, "voucher_id": None,
                    "message": chosen_option.get("plain_text", "")}

        raise DecisionServiceError(f"未知 action_code: {action_code}")

    def _post_fixed_asset(
        self,
        record,
        extracted,
        decision:      BossDecisionLog,
        dep_method:    str,
        life_months:   int,
        salvage_rate:  float,
        asset_category: str,
    ) -> dict:
        """
        固定资产购入：
          借 1601 固定资产
          贷 1002 银行存款（或 2202 应付账款）
        同时写入 asset_register。
        """
        amount        = float(extracted.amount)
        salvage_value = amount * salvage_rate if dep_method != DepreciationMethod.ONE_TIME else 0.0

        # 计算月折旧额
        from services.depreciation import straight_line, double_declining_balance, one_time_deduction
        profile   = self._get_active_profile()
        tax_rate  = float(profile.applicable_income_tax_rate) if profile else 0.20

        if dep_method == DepreciationMethod.ONE_TIME:
            summary = one_time_deduction(amount, date.today(), tax_rate)
            monthly_dep = amount
        elif dep_method == DepreciationMethod.STRAIGHT_LINE:
            summary = straight_line(amount, salvage_value, life_months, date.today(), tax_rate)
            monthly_dep = summary.monthly_depreciation
        else:
            summary = double_declining_balance(amount, salvage_value, life_months, date.today(), tax_rate)
            monthly_dep = summary.monthly_depreciation

        # 信用科目：银行转账/支付宝/微信 → 1002；未指定/应付 → 2202
        credit_code = "2202" if extracted.payment_method in ("未指定",) else "1002"

        # 生成凭证
        header = VoucherHeader(
            record_id     = record.record_id,
            voucher_date  = date.today(),
            total_amount  = Decimal(str(amount)),
            memo          = f"购入固定资产：{extracted.expense_type}",
            review_status = VoucherReviewStatus.POSTED,
        )
        self._db.add(header)
        self._db.flush()

        for subject_code, direction in [("1601", "DEBIT"), (credit_code, "CREDIT")]:
            self._db.add(VoucherLine(
                voucher_id   = header.voucher_id,
                subject_code = subject_code,
                direction    = direction,
                amount       = Decimal(str(amount)),
                memo         = extracted.memo,
            ))

        # 验证科目存在
        for code in ["1601", credit_code]:
            if not self._db.query(AccountSubject).filter_by(subject_code=code).first():
                raise AccountingError(f"科目 {code} 不存在，请执行 dml.sql 初始化数据")

        # 下个月开始折旧
        today = date.today()
        if today.month == 12:
            dep_start = f"{today.year + 1}-01"
        else:
            dep_start = f"{today.year}-{today.month + 1:02d}"

        asset = AssetRegister(
            voucher_id                = header.voucher_id,
            decision_id               = decision.decision_id,
            asset_name                = extracted.expense_type,
            asset_category            = asset_category,
            original_value            = Decimal(str(amount)),
            net_salvage_value         = Decimal(str(salvage_value)),
            depreciation_method       = dep_method,
            useful_life_months        = life_months,
            monthly_depreciation      = Decimal(str(round(monthly_dep, 2))),
            accumulated_depreciation  = Decimal("0.00"),
            status                    = AssetStatus.IN_USE,
            purchase_date             = date.today(),
            depreciation_start_month  = dep_start,
            notes                     = f"来源决策: decision_id={decision.decision_id}",
        )
        self._db.add(asset)

        record.status = RecordStatus.PROCESSED
        self._db.flush()

        return {
            "action":      dep_method,
            "voucher_id":  header.voucher_id,
            "asset_id":    asset.asset_id,
            "monthly_dep": round(monthly_dep, 2),
            "message":     f"固定资产已入账，月折旧 ¥{monthly_dep:,.2f}，从 {dep_start} 起计提",
        }

    def _post_direct_expense(self, record, extracted) -> dict:
        """直接费用化：走原有记账引擎逻辑。"""
        engine = AccountingEngineService(self._db)
        header = engine.generate_voucher(record, extracted)
        record.status = RecordStatus.PROCESSED
        return {
            "action":     "EXPENSE_DIRECT",
            "voucher_id": header.voucher_id,
            "message":    "已作费用直接入账",
        }

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _get_active_profile(self) -> EnterpriseProfile | None:
        return (
            self._db.query(EnterpriseProfile)
            .filter(EnterpriseProfile.is_active == 1)
            .first()
        )

    def _get_asset_category(self, decision: BossDecisionLog) -> str:
        try:
            data = json.loads(decision.ai_options_json)
            return data.get("asset_category", "通用设备")
        except (json.JSONDecodeError, AttributeError):
            return "通用设备"
