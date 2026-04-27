"""
AgentLedger V4.0 — HabitRetriever（时间业务流检索器）(Sprint 3.1)

职责：
  1. find_matching_rules(text)     — 关键词匹配，从 TenantHabitRule 取出 DAG 模板 JSON
  2. sniff_open_balances(keywords) — SQL 嗅探，检测与关键词相关的进行中余额

核心设计哲学（首席架构师原话）：
  "绝对不让 LLM 凭空去'猜'状态。
   我们通过后端的 SQL 查询，把系统当前的状态切片（State Slice）
   连同 DAG 规则一起喂给 LLM。LLM 只负责做它最擅长的事：逻辑判断与阅读理解。"

Template vs Instance 区分逻辑：
  • TenantHabitRule 存储的是 DAG「模板」（路径规则）
  • sniff_open_balances 检测是否有该场景的「实例」（进行中的账务）
  • Python 注入 State Slice → LLM 自行判断走 N1（新起点）还是 N2（后续流转）
"""
import json
import logging
from typing import Any

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from models.tenant_habit_rule import TenantHabitRule
from models.voucher_line import VoucherLine

logger = logging.getLogger(__name__)


class HabitRetriever:
    """
    业务习惯规则检索器。

    持有 db session + 当前租户上下文，
    提供两个方法：DAG 模板匹配 + 余额状态嗅探。
    """

    def __init__(self, db: Session, tenant_id: int, account_set_id: int) -> None:
        self._db             = db
        self._tenant_id      = tenant_id
        self._account_set_id = account_set_id

    # ── 方法一：关键词匹配 DAG 模板 ───────────────────────────────────────────

    def find_matching_rules(self, text: str) -> list[dict[str, Any]]:
        """
        从 TenantHabitRule 中找出与输入文本关键词匹配的 DAG 模板。

        匹配策略：
          • 加载该账套下所有启用规则（通常数量很少，全量加载 OK）
          • 对每条规则的 keywords JSON 数组，检查是否有任一关键词出现在 text 中
          • 大小写不敏感匹配
          • 若 keywords 或 rule_json 格式非法，跳过该规则并记录警告

        返回：
          [{"rule_name": "...", "dag": {...}}, ...]  按数据库顺序
        """
        rules = (
            self._db.query(TenantHabitRule)
            .filter(
                TenantHabitRule.tenant_id      == self._tenant_id,
                TenantHabitRule.account_set_id == self._account_set_id,
                TenantHabitRule.is_active      == True,
            )
            .all()
        )

        text_lower = text.lower()
        matched: list[dict[str, Any]] = []

        for rule in rules:
            # 解析关键词列表
            try:
                keywords: list[str] = json.loads(rule.keywords)
                if not isinstance(keywords, list):
                    raise ValueError("keywords 不是 JSON 数组")
            except (json.JSONDecodeError, ValueError) as exc:
                logger.warning(
                    "HabitRetriever: rule_id=%d keywords 格式非法，跳过: %s",
                    rule.id, exc,
                )
                continue

            # 检查是否有命中关键词
            if not any(kw.lower() in text_lower for kw in keywords if kw):
                continue

            # 解析 DAG JSON
            try:
                dag = json.loads(rule.rule_json)
                if not isinstance(dag, dict):
                    raise ValueError("rule_json 不是 JSON 对象")
            except (json.JSONDecodeError, ValueError) as exc:
                logger.warning(
                    "HabitRetriever: rule_id=%d rule_json 格式非法，跳过: %s",
                    rule.id, exc,
                )
                continue

            matched.append({
                "rule_id":   rule.id,       # Sprint 3.4: 学习溯源用
                "rule_name": rule.rule_name,
                "dag":       dag,
            })
            logger.debug(
                "HabitRetriever: matched rule '%s' for text=%r",
                rule.rule_name, text[:30],
            )

        return matched

    # ── 方法二：SQL 嗅探进行中余额 ────────────────────────────────────────────

    def sniff_open_balances(self, keywords: list[str]) -> list[dict[str, Any]]:
        """
        通过 VoucherLine.memo 关键词嗅探，检测与业务相关的进行中科目净余额。

        用途：
          区分"全新业务（走 DAG N1）"vs"后续流转（走 DAG N2）"。
          例如：上个月已挂了"阿里云"的 1801 长期待摊，今天的摊销应走 N2。

        实现：
          • 在 VoucherLine 表里找 memo 包含任一关键词的记录
          • 按 subject_code + direction 聚合金额
          • 计算净余额（借方为正，贷方为负）
          • 只返回 |净余额| > 0.01 的科目（已结清的不返回）

        注意：
          • 此查询不受 TenantMixin 拦截器保护（VoucherLine 继承 TenantMixin，
            但拦截器通过 ContextVar 注入，这里通过显式 tenant_id 过滤）
          • 关键词列表为空时直接返回 []

        返回：
          [
            {
              "subject_code": "1801",
              "net_balance": 3600.0,
              "direction_note": "借方余额 3600.00 元（资产挂账，尚未结清）"
            },
            ...
          ]
        """
        if not keywords:
            return []

        # 至少要有一个非空关键词
        valid_kws = [kw.strip() for kw in keywords if kw and kw.strip()]
        if not valid_kws:
            return []

        # ── 构造关键词 OR 过滤条件 ────────────────────────────────────────────
        memo_filters = [VoucherLine.memo.contains(kw) for kw in valid_kws]

        rows = (
            self._db.query(
                VoucherLine.subject_code,
                VoucherLine.direction,
                func.sum(VoucherLine.amount).label("total"),
            )
            .filter(
                VoucherLine.tenant_id      == self._tenant_id,
                VoucherLine.account_set_id == self._account_set_id,
                or_(*memo_filters),
            )
            .group_by(VoucherLine.subject_code, VoucherLine.direction)
            .all()
        )

        # ── 计算净余额（借方正，贷方负）──────────────────────────────────────
        net_by_code: dict[str, float] = {}
        for row in rows:
            sign = 1.0 if row.direction == "DEBIT" else -1.0
            net_by_code[row.subject_code] = (
                net_by_code.get(row.subject_code, 0.0) + sign * float(row.total)
            )

        result: list[dict[str, Any]] = []
        for code, net in net_by_code.items():
            if abs(net) < 0.01:
                continue   # 已结清，不需要告知 LLM

            if net > 0:
                direction_note = f"借方余额 {net:.2f} 元（资产/费用类挂账，尚未结清）"
            else:
                direction_note = f"贷方余额 {abs(net):.2f} 元（负债/预收类挂账，尚未结清）"

            result.append({
                "subject_code":  code,
                "net_balance":   round(net, 2),
                "direction_note": direction_note,
            })
            logger.debug(
                "HabitRetriever sniff: subject=%s net=%.2f", code, net
            )

        return result
