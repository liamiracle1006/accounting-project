"""
AgentLedger V4.0 — AIVoucherService（双轨推荐引擎 + 确定性置信度）(Sprint 3.1 / 3.4)

架构职责：
  Sprint 3.1 原始双层 Pipeline 保持不变，在其上叠加 Sprint 3.4 的双轨制：

  ┌─────────────────────────────────────────────────────────────┐
  │  Track A（历史习惯轨道）                                      │
  │    find_matching_rules() → 找有 context_features 的最佳 edge │
  │    calculate_confidence(amount, edge) → HIGH/MEDIUM          │
  │    _reconstruct_draft_from_edge() → 重建凭证草稿              │
  └──────────────────────────┬──────────────────────────────────┘
                             │  并行（不互相阻塞）
  ┌──────────────────────────▼──────────────────────────────────┐
  │  Track B（AI 准则轨道，原 Sprint 3.1 Pipeline 不变）          │
  │    HabitRetriever.sniff_open_balances() → State Slice        │
  │    AgentRunner.run() → LLM 多轮 Tool Calling                 │
  │    悬账断路器 → review_status                                 │
  └──────────────────────────┬──────────────────────────────────┘
                             ↓
  ┌─────────────────────────────────────────────────────────────┐
  │  DualTrackResponse                                           │
  │    [Track A（可选，冷启动时无）, Track B（必有）]              │
  └─────────────────────────────────────────────────────────────┘

置信度判定（确定性三档，无浮点计算）：
  HIGH   — edge.weight > 3 且 amount 在 [min_amount, max_amount]
  MEDIUM — Track A 存在但不满足 HIGH 条件（金额突变或样本少）
  LOW    — 无 Track A（纯 Track B），绝不允许静默入库

TenantHabitRule CRUD 由本 Service 的 B 部分负责（同 Sprint 3.1）。
Habit Schema 已迁移至 schemas/habit_schemas.py（Sprint 3.4 拆分）。

自定义异常：
  HabitRuleNotFoundError  — 404
  HabitRuleConflictError  — 409
  VoucherGenerationError  — 500
"""
import json
import logging
import re
from datetime import date
from typing import Any, Literal, Optional

from sqlalchemy.orm import Session

from ai.agent_runner import AgentRunner
from ai.llm_client import LLMClient, LLMClientError
from ai.voucher_prompts import VOUCHER_GENERATION_SYSTEM_PROMPT
from models.tenant_habit_rule import TenantHabitRule
from schemas.habit_schemas import HabitRuleCreateInput, HabitRuleUpdateInput, HabitRuleOut
from schemas.voucher_ai_schemas import (
    DualTrackResponse,
    GenerateVoucherInput,
    RecommendationItem,
    VoucherDraftOut,
    VoucherLineOut,
)
from services.graph_engine import DRILL_DOWN_TOOL_DEF, HabitRetriever, SubjectRetriever

logger = logging.getLogger(__name__)


# ── 悬账科目常量 ──────────────────────────────────────────────────────────────
SUSPENSE_DEBIT_CODE  = "1221"
SUSPENSE_CREDIT_CODE = "2241"
SUSPENSE_DEBIT_NAME  = "其他应收款-待查明"
SUSPENSE_CREDIT_NAME = "其他应付款-待查明"

# 浮点比较精度阈值（0.005 元 = 0.5 分）
BALANCE_TOLERANCE = 0.005


# ── 自定义异常 ────────────────────────────────────────────────────────────────

class HabitRuleNotFoundError(Exception):
    pass

class HabitRuleConflictError(Exception):
    pass

class VoucherGenerationError(Exception):
    pass


# ══════════════════════════════════════════════════════════════════════════════
# 确定性置信度引擎（模块级函数，可独立测试）
# ══════════════════════════════════════════════════════════════════════════════

def calculate_confidence(
    amount: float,
    edge:   dict,
) -> Literal["HIGH", "MEDIUM"]:
    """
    对 Track A 的单条 edge 做确定性置信度判定。

    HIGH（可进入批量自动处理）：
      - edge.weight > 3（样本充足）
      - 且当前金额在历史区间 [min_amount, max_amount] 内

    MEDIUM（需人工扫一眼）：
      - edge 存在，但 weight ≤ 3 或金额超出历史区间

    注意：LOW 由调用方在无 Track A 时直接设定，此函数不处理 LOW。

    参数：
      amount — 本次业务金额（正数）
      edge   — 包含 weight + context_features 的 DAG edge dict
    """
    weight = edge.get("weight", 0)
    cf     = edge.get("context_features", {})

    min_amount = cf.get("min_amount")
    max_amount = cf.get("max_amount")

    amount_in_range = (
        min_amount is not None
        and max_amount is not None
        and float(min_amount) <= amount <= float(max_amount)
    )

    if weight > 3 and amount_in_range:
        return "HIGH"
    return "MEDIUM"


# ══════════════════════════════════════════════════════════════════════════════
# AIVoucherService
# ══════════════════════════════════════════════════════════════════════════════

class AIVoucherService:
    """
    AI 凭证生成服务。

    A. generate_voucher()  — 双轨推荐引擎（Sprint 3.4）
    B. CRUD for TenantHabitRule — 习惯规则管理（Sprint 3.1 不变）
    """

    def __init__(self, db: Session) -> None:
        self._db  = db
        self._llm = LLMClient()

    # ══════════════════════════════════════════════════════════════════════════
    # A. 双轨推荐引擎
    # ══════════════════════════════════════════════════════════════════════════

    def generate_voucher(
        self,
        body:           GenerateVoucherInput,
        tenant_id:      int,
        account_set_id: int,
    ) -> DualTrackResponse:
        """
        双轨制凭证生成入口。

        返回 DualTrackResponse：
          冷启动：recommendations = [Track B]
          有历史：recommendations = [Track A, Track B]

        Track A 只有在历史 edge 里有 context_features.line_templates 时才出现。
        Track B 永远存在（LLM 兜底）。
        """
        description  = body.description
        voucher_date = str(body.voucher_date)

        # ── 关键词匹配（现在带 rule_id）────────────────────────────────────
        habit_retriever = HabitRetriever(self._db, tenant_id, account_set_id)
        matched_rules   = habit_retriever.find_matching_rules(description)
        logger.info(
            "AIVoucherService: matched %d habit rules for '%s'",
            len(matched_rules), description[:30],
        )

        # ── 提取金额（用于置信度判定）────────────────────────────────────────
        amount = self._extract_amount(description)

        # ── Track A：从历史 edge 重建草稿 ─────────────────────────────────────
        track_a = self._try_build_track_a(matched_rules, amount, description, voucher_date)

        # ── Track B：原 Sprint 3.1 LLM Pipeline ──────────────────────────────
        track_b = self._run_track_b(
            description, voucher_date, matched_rules, habit_retriever,
        )

        # ── 组装双轨响应 ──────────────────────────────────────────────────────
        recommendations: list[RecommendationItem] = []
        if track_a is not None:
            recommendations.append(track_a)
        recommendations.append(track_b)

        return DualTrackResponse(recommendations=recommendations)

    # ── Track A 构建 ──────────────────────────────────────────────────────────

    def _try_build_track_a(
        self,
        matched_rules: list[dict],
        amount:        float,
        description:   str,
        voucher_date:  str,
    ) -> Optional[RecommendationItem]:
        """
        在已匹配的规则里找权重最高的 learned edge。
        若无 line_templates（冷启动），返回 None。
        """
        best_weight = -1
        best_edge:    Optional[dict] = None
        best_rule_id: Optional[int]  = None

        for rule_match in matched_rules:
            rule_id = rule_match["rule_id"]
            dag     = rule_match["dag"]
            for edge in dag.get("edges", []):
                cf = edge.get("context_features", {})
                if not cf.get("line_templates"):
                    continue   # 无历史模板，跳过
                w = edge.get("weight", 0)
                if w > best_weight:
                    best_weight = w
                    best_edge   = edge
                    best_rule_id = rule_id

        if best_edge is None:
            return None   # 冷启动，无 Track A

        confidence = calculate_confidence(amount, best_edge)
        memo       = description[:100]  # 用描述作为摘要占位
        draft      = self._reconstruct_draft_from_edge(best_edge, amount, memo, voucher_date)

        return RecommendationItem(
            track         = "A",
            source        = "HABIT",
            confidence    = confidence,
            habit_rule_id = best_rule_id,
            draft         = draft,
        )

    @staticmethod
    def _reconstruct_draft_from_edge(
        edge:         dict,
        amount:       float,
        memo:         str,
        voucher_date: str,
    ) -> VoucherDraftOut:
        """
        用 edge.context_features.line_templates 和当前金额重建凭证草稿。

        ratio = 历史行金额 / 历史总金额，重建时乘以当前金额。
        经过悬账断路器兜底，确保借贷平衡。
        """
        templates = edge.get("context_features", {}).get("line_templates", [])
        lines_raw: list[dict] = []
        for t in templates:
            line_amount = round(amount * float(t.get("ratio", 1.0)), 2)
            if line_amount <= 0:
                continue
            lines_raw.append({
                "subject_code":  t.get("subject_code", ""),
                "subject_name":  None,
                "direction":     t.get("direction", "DEBIT"),
                "amount":        line_amount,
                "memo":          t.get("memo_hint") or memo,
                "auxiliary_data": None,
            })
        return AIVoucherService._apply_circuit_breaker(lines_raw, memo, voucher_date)

    # ── Track B：LLM Pipeline（Sprint 3.1 不变，封装为私有方法）─────────────

    def _run_track_b(
        self,
        description:    str,
        voucher_date:   str,
        matched_rules:  list[dict],
        habit_retriever: HabitRetriever,
    ) -> RecommendationItem:
        """
        原 Sprint 3.1 双层 Pipeline，封装为 Track B。
        永远返回（不抛异常到外层），错误时通过断路器产生悬账草稿。
        """
        sniff_keywords = self._extract_sniff_keywords(description)
        open_balances  = habit_retriever.sniff_open_balances(sniff_keywords)

        user_content = self._build_user_prompt(
            description, voucher_date, matched_rules, open_balances
        )
        messages = [
            {"role": "system", "content": VOUCHER_GENERATION_SYSTEM_PROMPT},
            {"role": "user",   "content": user_content},
        ]

        subject_retriever = SubjectRetriever(self._db,
                                              habit_retriever._tenant_id,
                                              habit_retriever._account_set_id)
        runner = AgentRunner(self._llm)

        try:
            raw_output = runner.run(
                messages      = messages,
                tools_def     = [DRILL_DOWN_TOOL_DEF],
                tool_registry = subject_retriever.tool_registry,
            )
        except LLMClientError as exc:
            raise VoucherGenerationError(f"AI 引擎调用失败: {exc}") from exc

        lines_raw, memo = self._parse_llm_output(raw_output, description)
        draft = self._apply_circuit_breaker(lines_raw, memo, voucher_date)

        return RecommendationItem(
            track         = "B",
            source        = "AI_RULE",
            confidence    = "LOW",   # Track B 永远 LOW，绝不静默入库
            habit_rule_id = None,
            draft         = draft,
        )

    # ── 内部辅助方法（Sprint 3.1 原方法保留）─────────────────────────────────

    @staticmethod
    def _extract_amount(description: str) -> float:
        """从描述中提取金额（正则匹配数字，取最大值）。"""
        nums = re.findall(r'[\d,]+(?:\.\d+)?', description.replace('，', ','))
        amounts: list[float] = []
        for n in nums:
            try:
                v = float(n.replace(',', ''))
                if v > 0:
                    amounts.append(v)
            except ValueError:
                pass
        return max(amounts) if amounts else 0.0

    @staticmethod
    def _extract_sniff_keywords(description: str) -> list[str]:
        keywords = []
        cn_words = re.findall(r'[\u4e00-\u9fff]{2,6}', description)
        keywords.extend(cn_words[:3])
        short = description[:20].strip()
        if short and short not in keywords:
            keywords.append(short)
        return keywords

    @staticmethod
    def _build_user_prompt(
        description:   str,
        voucher_date:  str,
        matched_rules: list[dict],
        open_balances: list[dict],
    ) -> str:
        parts = [
            f"【单据描述】{description}",
            f"【凭证日期】{voucher_date}",
        ]
        if matched_rules:
            dag_json = json.dumps(matched_rules, ensure_ascii=False, indent=2)
            parts.append(
                f"\n【业务习惯规则（DAG 路线图）】\n"
                f"以下是本账套针对此类业务的记账路径规则，请严格遵守：\n"
                f"{dag_json}"
            )
        if open_balances:
            bal_json = json.dumps(open_balances, ensure_ascii=False, indent=2)
            parts.append(
                f"\n【系统检测到相关进行中余额（State Slice）】\n"
                f"{bal_json}\n"
                f"⚠️ 请根据上述余额信息，判断当前业务是否为后续流转动作（DAG 中的 N2+ 节点），"
                f"而非全新起始动作（N1）。"
            )
        elif matched_rules:
            parts.append(
                "\n【系统状态提示】\n"
                "系统未检测到该业务的进行中余额。"
                "请将此笔业务视为全新起始动作（DAG 起点节点 N1），从头开始记账。"
            )
        return "\n".join(parts)

    @staticmethod
    def _parse_llm_output(
        raw_output: str,
        fallback_memo: str,
    ) -> tuple[list[dict], str]:
        text = raw_output.strip()
        parsed = _try_parse_json(text)
        if parsed is None:
            m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
            if m:
                parsed = _try_parse_json(m.group(1).strip())
        if parsed is None:
            m = re.search(r"\{[\s\S]*\}", text)
            if m:
                parsed = _try_parse_json(m.group())
        if parsed is None:
            raise VoucherGenerationError(
                f"LLM 输出无法解析为 JSON，原始内容: {raw_output[:300]}"
            )
        lines_raw = parsed.get("lines", [])
        memo      = parsed.get("memo") or fallback_memo
        if not lines_raw:
            raise VoucherGenerationError(
                f"LLM 输出的凭证 lines 为空，原始内容: {raw_output[:300]}"
            )
        return lines_raw, memo

    @staticmethod
    def _apply_circuit_breaker(
        lines_raw:    list[dict],
        memo:         str,
        voucher_date: str,
    ) -> VoucherDraftOut:
        """悬账断路器（硬编码 Python，绝对红线）。"""
        lines: list[dict] = []
        for raw in lines_raw:
            direction = str(raw.get("direction", "")).upper()
            if direction not in ("DEBIT", "CREDIT"):
                d_raw = str(raw.get("direction", ""))
                if d_raw in ("借", "Dr", "借方"):
                    direction = "DEBIT"
                elif d_raw in ("贷", "Cr", "贷方"):
                    direction = "CREDIT"
                else:
                    logger.warning("断路器: 未知 direction '%s'，跳过此行", d_raw)
                    continue

            try:
                amount = round(float(raw["amount"]), 2)
                if amount <= 0:
                    raise ValueError("amount 必须为正数")
            except (KeyError, TypeError, ValueError) as exc:
                logger.warning("断路器: 无效 amount '%s'，跳过: %s", raw.get("amount"), exc)
                continue

            raw_aux = raw.get("auxiliary_data")
            auxiliary_data = None
            if isinstance(raw_aux, dict):
                valid_keys = {"customer", "supplier", "employee", "project", "dept"}
                auxiliary_data = {
                    k: str(v) for k, v in raw_aux.items() if k in valid_keys
                } or None

            lines.append({
                "subject_code":  str(raw.get("subject_code", "")),
                "subject_name":  raw.get("subject_name"),
                "direction":     direction,
                "amount":        amount,
                "memo":          raw.get("memo"),
                "auxiliary_data": auxiliary_data,
            })

        total_debit  = sum(l["amount"] for l in lines if l["direction"] == "DEBIT")
        total_credit = sum(l["amount"] for l in lines if l["direction"] == "CREDIT")
        gap = round(total_debit - total_credit, 2)

        circuit_triggered  = False
        pending_reason: str | None = None

        if abs(gap) > BALANCE_TOLERANCE:
            circuit_triggered = True
            pending_reason = (
                f"LLM 输出借贷不平，差额 {gap:+.2f} 元（借方{'多' if gap > 0 else '少'}）。"
                f"已自动挂入待查明科目，请财务人员核实后补充真实单据。"
            )
            logger.warning("悬账断路器触发: gap=%.2f  memo=%s", gap, memo)
            if gap > 0:
                lines.append({
                    "subject_code": SUSPENSE_CREDIT_CODE,
                    "subject_name": SUSPENSE_CREDIT_NAME,
                    "direction":    "CREDIT",
                    "amount":       abs(gap),
                    "memo":         "⚠️ AI 断路器自动挂账，待查明差额",
                })
            else:
                lines.append({
                    "subject_code": SUSPENSE_DEBIT_CODE,
                    "subject_name": SUSPENSE_DEBIT_NAME,
                    "direction":    "DEBIT",
                    "amount":       abs(gap),
                    "memo":         "⚠️ AI 断路器自动挂账，待查明差额",
                })
            total_debit  = sum(l["amount"] for l in lines if l["direction"] == "DEBIT")
            total_credit = sum(l["amount"] for l in lines if l["direction"] == "CREDIT")

        is_balanced   = abs(total_debit - total_credit) <= BALANCE_TOLERANCE
        review_status = "DRAFT_PENDING_REVIEW" if circuit_triggered else "DRAFT"

        return VoucherDraftOut(
            memo                      = memo,
            voucher_date              = voucher_date,
            lines                     = [VoucherLineOut(**l) for l in lines],
            total_debit               = round(total_debit, 2),
            total_credit              = round(total_credit, 2),
            is_balanced               = is_balanced,
            review_status             = review_status,
            circuit_breaker_triggered = circuit_triggered,
            pending_review_reason     = pending_reason,
        )

    # ══════════════════════════════════════════════════════════════════════════
    # B. TenantHabitRule CRUD（Sprint 3.1 不变，仅更新 import 来源）
    # ══════════════════════════════════════════════════════════════════════════

    def list_habit_rules(self, tenant_id: int, account_set_id: int) -> list[HabitRuleOut]:
        rules = (
            self._db.query(TenantHabitRule)
            .filter(
                TenantHabitRule.tenant_id      == tenant_id,
                TenantHabitRule.account_set_id == account_set_id,
            )
            .order_by(TenantHabitRule.id)
            .all()
        )
        return [_rule_to_out(r) for r in rules]

    def create_habit_rule(
        self, tenant_id: int, account_set_id: int, body: HabitRuleCreateInput,
    ) -> HabitRuleOut:
        rule = TenantHabitRule(
            tenant_id      = tenant_id,
            account_set_id = account_set_id,
            rule_name      = body.rule_name,
            description    = body.description,
            keywords       = json.dumps(body.keywords, ensure_ascii=False),
            rule_json      = json.dumps(body.rule_json, ensure_ascii=False),
            is_active      = body.is_active,
        )
        self._db.add(rule)
        self._db.flush()
        return _rule_to_out(rule)

    def update_habit_rule(
        self, rule_id: int, tenant_id: int, account_set_id: int, body: HabitRuleUpdateInput,
    ) -> HabitRuleOut:
        rule = self._get_rule_or_404(rule_id, tenant_id, account_set_id)
        if body.rule_name   is not None: rule.rule_name   = body.rule_name
        if body.description is not None: rule.description = body.description
        if body.keywords    is not None: rule.keywords    = json.dumps(body.keywords, ensure_ascii=False)
        if body.rule_json   is not None: rule.rule_json   = json.dumps(body.rule_json, ensure_ascii=False)
        if body.is_active   is not None: rule.is_active   = body.is_active
        self._db.flush()
        return _rule_to_out(rule)

    def delete_habit_rule(self, rule_id: int, tenant_id: int, account_set_id: int) -> None:
        rule = self._get_rule_or_404(rule_id, tenant_id, account_set_id)
        self._db.delete(rule)
        self._db.flush()

    def _get_rule_or_404(self, rule_id: int, tenant_id: int, account_set_id: int) -> TenantHabitRule:
        rule = (
            self._db.query(TenantHabitRule)
            .filter(
                TenantHabitRule.id             == rule_id,
                TenantHabitRule.tenant_id      == tenant_id,
                TenantHabitRule.account_set_id == account_set_id,
            )
            .first()
        )
        if rule is None:
            raise HabitRuleNotFoundError(f"习惯规则 id={rule_id} 不存在")
        return rule


# ── 模块级辅助函数 ────────────────────────────────────────────────────────────

def _try_parse_json(text: str) -> dict | None:
    try:
        result = json.loads(text)
        return result if isinstance(result, dict) else None
    except (json.JSONDecodeError, ValueError):
        return None


def _rule_to_out(rule: TenantHabitRule) -> HabitRuleOut:
    try:
        keywords = json.loads(rule.keywords)
    except (json.JSONDecodeError, TypeError):
        keywords = []
    try:
        rule_json_dict = json.loads(rule.rule_json)
    except (json.JSONDecodeError, TypeError):
        rule_json_dict = {}
    return HabitRuleOut(
        id          = rule.id,
        rule_name   = rule.rule_name,
        description = rule.description,
        keywords    = keywords,
        rule_json   = rule_json_dict,
        is_active   = rule.is_active,
        created_at  = rule.created_at,
        updated_at  = rule.updated_at,
    )
