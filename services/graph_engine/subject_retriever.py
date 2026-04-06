"""
AgentLedger V4.0 — SubjectRetriever（空间导航器）(Sprint 3.1)

职责：
  为 AgentRunner 提供 drill_down_subject 工具的 Python 实现。
  LLM 通过调用此工具，像使用文件管理器一样逐层浏览科目树，
  找到末级科目编码后用于构造凭证分录。

核心设计：
  • 从 TenantSubject 表（Sprint 2.1 建立）查询，确保只读账套内实际存在的科目。
  • 每次只返回直接子节点，用 has_children 标志告诉 LLM 是否需要继续下钻。
  • 返回的 list[dict] 由 AgentRunner 序列化为 JSON 字符串塞入 tool_result 消息。
"""
import logging
from typing import Any

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from models.accounting import TenantSubject

logger = logging.getLogger(__name__)

# ── OpenAI Tool 定义（AgentRunner 需要的格式）────────────────────────────────

DRILL_DOWN_TOOL_DEF: dict = {
    "type": "function",
    "function": {
        "name": "drill_down_subject",
        "description": (
            "查询科目树。"
            "传入父科目编码获取其直接子科目列表；"
            "传入空字符串 \"\" 获取所有一级科目。"
            "返回包含 subject_code、subject_name、category、balance_direction、"
            "level、has_children 字段的列表。"
            "has_children=true 表示该科目还有子科目，需继续下钻；"
            "has_children=false 表示末级科目，可直接用于凭证分录。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "parent_code": {
                    "type": "string",
                    "description": (
                        "父科目编码。"
                        "传空字符串 \"\" 查询所有一级科目；"
                        "传具体编码（如 \"1002\"）查询其直接子科目。"
                    ),
                }
            },
            "required": ["parent_code"],
        },
    },
}


class SubjectRetriever:
    """
    科目树下钻服务。

    持有 db session + 当前租户上下文，
    暴露 drill_down_subject() 方法供 AgentRunner 工具注册表使用。
    """

    def __init__(self, db: Session, tenant_id: int, account_set_id: int) -> None:
        self._db             = db
        self._tenant_id      = tenant_id
        self._account_set_id = account_set_id

    def drill_down_subject(self, parent_code: str) -> list[dict[str, Any]]:
        """
        查询指定父科目的直接子科目列表。

        parent_code="" → 查询所有一级科目（parent_code IS NULL）
        parent_code="1002" → 查询 1002 的直接子科目

        返回：
          [
            {
              "subject_code": "1002",
              "subject_name": "银行存款",
              "category": "资产",
              "balance_direction": "借",
              "level": 1,
              "has_children": true
            },
            ...
          ]
        """
        # ── 查询目标层科目 ────────────────────────────────────────────────────
        base_filter = [
            TenantSubject.tenant_id      == self._tenant_id,
            TenantSubject.account_set_id == self._account_set_id,
            TenantSubject.is_deleted     == False,
            TenantSubject.is_enabled     == True,
        ]

        if parent_code == "":
            base_filter.append(TenantSubject.parent_code.is_(None))
        else:
            base_filter.append(TenantSubject.parent_code == parent_code)

        subjects = (
            self._db.query(TenantSubject)
            .filter(*base_filter)
            .order_by(TenantSubject.sort_order, TenantSubject.subject_code)
            .all()
        )

        if not subjects:
            logger.debug(
                "drill_down_subject: no subjects found for parent=%r tenant=%d as=%d",
                parent_code, self._tenant_id, self._account_set_id,
            )
            return []

        # ── 批量检查哪些科目有子节点（一次查询，避免 N+1）───────────────────
        child_codes_subq = (
            select(TenantSubject.parent_code)
            .where(
                TenantSubject.tenant_id      == self._tenant_id,
                TenantSubject.account_set_id == self._account_set_id,
                TenantSubject.is_deleted     == False,
                TenantSubject.parent_code.in_([s.subject_code for s in subjects]),
            )
            .distinct()
        )
        rows_with_children: set[str] = {
            row[0]
            for row in self._db.execute(child_codes_subq).fetchall()
            if row[0] is not None
        }

        result = []
        for s in subjects:
            result.append({
                "subject_code":     s.subject_code,
                "subject_name":     s.subject_name,
                "category":         s.category,
                "balance_direction": s.balance_direction,
                "level":            s.level,
                "has_children":     s.subject_code in rows_with_children,
            })

        logger.debug(
            "drill_down_subject: parent=%r → %d subjects returned",
            parent_code, len(result),
        )
        return result

    @property
    def tool_registry(self) -> dict[str, Any]:
        """返回供 AgentRunner 使用的工具注册表。"""
        return {"drill_down_subject": self.drill_down_subject}
