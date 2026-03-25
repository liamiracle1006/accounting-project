"""
AgentLedger — TransactionRouter（路由分发器）

核心职责：
  读取 enterprise_profile，判断一笔流水应该走哪条路径：
    AUTO   → 直接生成凭证（小额普通流水，95% 的场景）
    INTERCEPT → 挂起，等待老板决策（大额/敏感流水）

路由规则（任一条件触发 INTERCEPT）：
  1. 未找到激活的企业档案 → 走 AUTO（向下兼容，不影响现有功能）
  2. 金额 >= enterprise_profile.decision_threshold
  3. expense_type 命中敏感关键词列表

敏感关键词触发逻辑：
  无论金额大小，以下业务类型一律拦截，因为涉及复杂税务处理：
  - 固定资产类：设备/机器/车辆/房产/装修/固定资产
  - 研发类：研发/软件开发/技术开发/研究
  - 特殊税务：股权/分红/土地使用权
"""
import logging
from enum import Enum

from sqlalchemy.orm import Session

from ai.json_parser import ExtractedRecord
from models.enterprise_profile import EnterpriseProfile

logger = logging.getLogger(__name__)


class RouteDecision(str, Enum):
    AUTO      = "AUTO"       # 直接自动记账
    INTERCEPT = "INTERCEPT"  # 拦截，进入老板决策流


# 命中任意一个关键词 → 强制拦截，不受金额阈值限制
SENSITIVE_KEYWORDS: list[str] = [
    # 固定资产类
    "固定资产", "设备", "机器", "机械", "车辆", "汽车", "房产", "厂房", "装修", "改造",
    # 研发类
    "研发", "软件开发", "技术开发", "研究开发", "研究",
    # 特殊税务场景
    "股权", "分红", "土地使用权", "无形资产", "专利", "商标",
]


class TransactionRouter:
    def __init__(self, db: Session) -> None:
        self._db = db

    def get_active_profile(self) -> EnterpriseProfile | None:
        """获取当前激活的企业档案，不存在返回 None。"""
        return (
            self._db.query(EnterpriseProfile)
            .filter(EnterpriseProfile.is_active == 1)
            .first()
        )

    def decide(self, extracted: ExtractedRecord) -> tuple[RouteDecision, str]:
        """
        判断路由方向，返回 (RouteDecision, 拦截原因说明)。
        原因说明在 AUTO 时为空字符串，INTERCEPT 时说明触发原因。
        """
        profile = self.get_active_profile()

        if profile is None:
            logger.info(
                "No active enterprise_profile found, defaulting to AUTO for record amount=%.2f",
                extracted.amount,
            )
            return RouteDecision.AUTO, ""

        # 规则1：命中敏感关键词（优先级最高）
        matched_kw = self._match_sensitive_keyword(extracted.expense_type)
        if matched_kw:
            reason = f"业务类型'{extracted.expense_type}'命中敏感关键词'{matched_kw}'，需老板决策"
            logger.info("INTERCEPT triggered by keyword: %s", reason)
            return RouteDecision.INTERCEPT, reason

        # 规则2：金额超过决策阈值
        if extracted.amount >= float(profile.decision_threshold):
            reason = (
                f"金额 ¥{extracted.amount:,.2f} 超过决策阈值 "
                f"¥{float(profile.decision_threshold):,.2f}，需老板决策"
            )
            logger.info("INTERCEPT triggered by amount: %s", reason)
            return RouteDecision.INTERCEPT, reason

        return RouteDecision.AUTO, ""

    @staticmethod
    def _match_sensitive_keyword(expense_type: str) -> str | None:
        """返回命中的第一个敏感关键词，未命中返回 None。"""
        for kw in SENSITIVE_KEYWORDS:
            if kw in expense_type:
                return kw
        return None
