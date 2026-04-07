"""
AgentLedger V4.0 — AIVoucherService（双层推理引擎 + 悬账断路器）(Sprint 3.1)

架构职责：
  这是 Sprint 3.1 的核心大脑，编排整个 Bi-level Reasoning Pipeline：

  ┌─────────────────────────────────────────────────────────────┐
  │  Upper-level（预检索层）                                      │
  │    HabitRetriever.find_matching_rules() → DAG 模板           │
  │    HabitRetriever.sniff_open_balances() → 状态切片            │
  │    动态组装 System Prompt + State Slice                      │
  └──────────────────────────┬──────────────────────────────────┘
                             ↓
  ┌─────────────────────────────────────────────────────────────┐
  │  Lower-level（Agent 执行层）                                  │
  │    AgentRunner.run() 多轮 Tool Calling 循环                   │
  │      LLM 调用 drill_down_subject() 下钻科目树                 │
  │      LLM 输出最终凭证 JSON                                    │
  └──────────────────────────┬──────────────────────────────────┘
                             ↓
  ┌─────────────────────────────────────────────────────────────┐
  │  悬账断路器（硬编码 Python，不可绕过）                          │
  │    Sum(DEBIT) == Sum(CREDIT) ?                               │
  │      ✓ 平衡 → review_status=DRAFT                            │
  │      ✗ 不平 → 差额挂 1221/2241 → DRAFT_PENDING_REVIEW        │
  └─────────────────────────────────────────────────────────────┘

Sprint 3.1 边界：只生成草稿 JSON，不写数据库。
  数据库落库由 Sprint 3.2 的"确认入账"端点负责。

自定义异常：
  HabitRuleNotFoundError  — 404
  HabitRuleConflictError  — 409
  VoucherGenerationError  — 500（LLM 失败或 JSON 解析失败）
"""
import json
import logging
import re
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from ai.agent_runner import AgentRunner
from ai.llm_client import LLMClient, LLMClientError
from ai.voucher_prompts import VOUCHER_GENERATION_SYSTEM_PROMPT
from models.tenant_habit_rule import TenantHabitRule
from schemas.voucher_ai_schemas import (
    GenerateVoucherInput,
    HabitRuleCreateInput,
    HabitRuleUpdateInput,
    HabitRuleOut,
    VoucherDraftOut,
    VoucherLineOut,
)
from services.graph_engine import DRILL_DOWN_TOOL_DEF, HabitRetriever, SubjectRetriever

logger = logging.getLogger(__name__)


# ── 悬账科目常量 ──────────────────────────────────────────────────────────────
SUSPENSE_DEBIT_CODE  = "1221"   # 其他应收款-待查明（借方差额挂此）
SUSPENSE_CREDIT_CODE = "2241"   # 其他应付款-待查明（贷方差额挂此）
SUSPENSE_DEBIT_NAME  = "其他应收款-待查明"
SUSPENSE_CREDIT_NAME = "其他应付款-待查明"

# 浮点比较精度阈值（0.005 元 = 0.5 分，低于此视为平衡）
BALANCE_TOLERANCE = 0.005


# ── 自定义异常 ────────────────────────────────────────────────────────────────

class HabitRuleNotFoundError(Exception):
    pass

class HabitRuleConflictError(Exception):
    pass

class VoucherGenerationError(Exception):
    pass


# ══════════════════════════════════════════════════════════════════════════════
# AIVoucherService
# ══════════════════════════════════════════════════════════════════════════════

class AIVoucherService:
    """
    AI 凭证生成服务。

    包含两类功能：
      A. generate_voucher()      — 核心 AI 生成流程
      B. CRUD for TenantHabitRule — 习惯规则管理
    """

    def __init__(self, db: Session) -> None:
        self._db  = db
        self._llm = LLMClient()

    # ══════════════════════════════════════════════════════════════════════════
    # A. 核心 AI 凭证生成
    # ══════════════════════════════════════════════════════════════════════════

    def generate_voucher(
        self,
        body:          GenerateVoucherInput,
        tenant_id:     int,
        account_set_id: int,
    ) -> VoucherDraftOut:
        """
        双层 Pipeline 入口：接收业务描述 → 返回凭证草稿。

        Step 1 — Upper-level 预检索
          • HabitRetriever 关键词匹配 → DAG 模板列表
          • HabitRetriever SQL 嗅探   → 进行中余额状态切片
          • 动态组装注入内容丰富的 User Prompt

        Step 2 — Lower-level Agent 执行
          • AgentRunner 驱动 LLM 多轮 Tool Calling
          • LLM 调用 drill_down_subject 查询科目树
          • LLM 输出最终凭证 JSON 字符串

        Step 3 — 悬账断路器
          • 校验 Sum(DEBIT) == Sum(CREDIT)
          • 不平：差额挂 1221 或 2241，锁定 DRAFT_PENDING_REVIEW
          • 平衡：返回 DRAFT
        """
        description  = body.description
        voucher_date = str(body.voucher_date)

        # ── Step 1: Upper-level ───────────────────────────────────────────────
        habit_retriever = HabitRetriever(self._db, tenant_id, account_set_id)

        matched_rules = habit_retriever.find_matching_rules(description)
        logger.info(
            "AIVoucherService: matched %d habit rules for '%s'",
            len(matched_rules), description[:30],
        )

        # 嗅探关键词：取描述前20字（避免太长降低精度）
        sniff_keywords = self._extract_sniff_keywords(description)
        open_balances  = habit_retriever.sniff_open_balances(sniff_keywords)
        logger.info(
            "AIVoucherService: sniffed %d open balances", len(open_balances)
        )

        # ── 组装 User Prompt ──────────────────────────────────────────────────
        user_content = self._build_user_prompt(
            description, voucher_date, matched_rules, open_balances
        )

        messages = [
            {"role": "system", "content": VOUCHER_GENERATION_SYSTEM_PROMPT},
            {"role": "user",   "content": user_content},
        ]

        # ── Step 2: Lower-level Agent Runner ─────────────────────────────────
        subject_retriever = SubjectRetriever(self._db, tenant_id, account_set_id)
        runner = AgentRunner(self._llm)

        try:
            raw_output = runner.run(
                messages     = messages,
                tools_def    = [DRILL_DOWN_TOOL_DEF],
                tool_registry= subject_retriever.tool_registry,
            )
        except LLMClientError as exc:
            raise VoucherGenerationError(f"AI 引擎调用失败: {exc}") from exc

        # ── 解析 LLM 输出 ─────────────────────────────────────────────────────
        lines_raw, memo = self._parse_llm_output(raw_output, description)

        # ── Step 3: 悬账断路器 ────────────────────────────────────────────────
        return self._apply_circuit_breaker(lines_raw, memo, voucher_date)

    # ── 内部辅助方法 ──────────────────────────────────────────────────────────

    @staticmethod
    def _extract_sniff_keywords(description: str) -> list[str]:
        """
        从业务描述中提取嗅探关键词。
        策略：分词取前3个中文词组（每组2-6字）+ 完整描述截断到20字。
        """
        keywords = []
        # 提取中文词组（2-6个汉字的连续片段）
        cn_words = re.findall(r'[\u4e00-\u9fff]{2,6}', description)
        keywords.extend(cn_words[:3])
        # 兜底：用描述前20字作为一个整体关键词
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
        """
        动态组装注入了 DAG + State Slice 的 User Prompt。

        场景一（无习惯规则 + 无余额）：
          纯描述，LLM 依靠 System Prompt 知识生成分录

        场景二（有习惯规则 + 无余额）：
          注入 DAG，提示 LLM 这是全新业务的起始动作（N1）

        场景三（有习惯规则 + 有余额）：
          注入 DAG + State Slice，让 LLM 判断走 N1 还是 N2
        """
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
            # 有规则但无余额：明确告知 LLM 这是全新业务
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
        """
        将 LLM 输出字符串解析为 (lines_raw, memo)。
        支持三种格式：
          1. 纯 JSON 字符串
          2. Markdown 代码块包裹的 JSON
          3. 文本中嵌入的 JSON（用正则提取）
        """
        text = raw_output.strip()

        # 尝试直接解析
        parsed = _try_parse_json(text)

        # 尝试从 ```json ... ``` 提取
        if parsed is None:
            m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
            if m:
                parsed = _try_parse_json(m.group(1).strip())

        # 尝试提取最外层 {...}
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
        """
        悬账断路器（硬编码 Python，绝对红线）。

        规则：
          1. 计算 Sum(DEBIT) 和 Sum(CREDIT)
          2. 若差额 > BALANCE_TOLERANCE：
             gap > 0（借方多）→ 补贷方 2241
             gap < 0（贷方多）→ 补借方 1221
             锁定 DRAFT_PENDING_REVIEW
          3. 构造 VoucherDraftOut 返回

        ⚠️ 绝对禁止篡改业务流水（不得修改原有行的金额）。
           只能追加悬账行，不能修改已有行。
        """
        # 规范化 lines（容忍 LLM 大小写/命名不一致）
        lines: list[dict] = []
        for raw in lines_raw:
            direction = str(raw.get("direction", "")).upper()
            if direction not in ("DEBIT", "CREDIT"):
                # 尝试中文兼容
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
                logger.warning("断路器: 无效 amount '%s'，跳过此行: %s", raw.get("amount"), exc)
                continue

            # auxiliary_data: 只保留合法 key，防止 LLM 注入非法维度
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
                # 借方多 → 补贷方悬账
                lines.append({
                    "subject_code": SUSPENSE_CREDIT_CODE,
                    "subject_name": SUSPENSE_CREDIT_NAME,
                    "direction":    "CREDIT",
                    "amount":       abs(gap),
                    "memo":         "⚠️ AI 断路器自动挂账，待查明差额",
                })
            else:
                # 贷方多 → 补借方悬账
                lines.append({
                    "subject_code": SUSPENSE_DEBIT_CODE,
                    "subject_name": SUSPENSE_DEBIT_NAME,
                    "direction":    "DEBIT",
                    "amount":       abs(gap),
                    "memo":         "⚠️ AI 断路器自动挂账，待查明差额",
                })

            # 重新计算（追加悬账行后应已平衡）
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
    # B. TenantHabitRule CRUD
    # ══════════════════════════════════════════════════════════════════════════

    def list_habit_rules(self, tenant_id: int, account_set_id: int) -> list[HabitRuleOut]:
        """返回账套下所有习惯规则（含停用）。"""
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
        self,
        tenant_id:     int,
        account_set_id: int,
        body:          HabitRuleCreateInput,
    ) -> HabitRuleOut:
        """创建新的习惯规则。"""
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
        self,
        rule_id:       int,
        tenant_id:     int,
        account_set_id: int,
        body:          HabitRuleUpdateInput,
    ) -> HabitRuleOut:
        """更新习惯规则（部分更新，None 字段跳过）。"""
        rule = self._get_rule_or_404(rule_id, tenant_id, account_set_id)

        if body.rule_name   is not None:
            rule.rule_name   = body.rule_name
        if body.description is not None:
            rule.description = body.description
        if body.keywords    is not None:
            rule.keywords    = json.dumps(body.keywords, ensure_ascii=False)
        if body.rule_json   is not None:
            rule.rule_json   = json.dumps(body.rule_json, ensure_ascii=False)
        if body.is_active   is not None:
            rule.is_active   = body.is_active

        self._db.flush()
        return _rule_to_out(rule)

    def delete_habit_rule(
        self,
        rule_id:       int,
        tenant_id:     int,
        account_set_id: int,
    ) -> None:
        """永久删除习惯规则（DAG 模板不影响已生成的凭证，可直接硬删）。"""
        rule = self._get_rule_or_404(rule_id, tenant_id, account_set_id)
        self._db.delete(rule)
        self._db.flush()

    def _get_rule_or_404(
        self, rule_id: int, tenant_id: int, account_set_id: int
    ) -> TenantHabitRule:
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
    """尝试将字符串解析为 dict，失败返回 None。"""
    try:
        result = json.loads(text)
        return result if isinstance(result, dict) else None
    except (json.JSONDecodeError, ValueError):
        return None


def _rule_to_out(rule: TenantHabitRule) -> HabitRuleOut:
    """将 ORM 模型转换为 HabitRuleOut Pydantic 对象。"""
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
