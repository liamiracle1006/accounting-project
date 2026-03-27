"""
AgentLedger — 老板决策卡片 LLM 提示词 (S3 RAG-enhanced)

变更：
  - build_decision_user_prompt 接收 rag_hits: list[StrategyHit]
  - RAG 命中的政策以结构化参考块注入提示词
  - 输出 schema 扩展：analysis（无字数限制）、tax_calculation（含公式）、
    steps（可执行步骤列表）、risk_level（LOW/MEDIUM/HIGH）
  - Python 端仍重算 savings_this_year / savings_total 覆盖 LLM 输出
"""
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rag.retriever import StrategyHit


DECISION_SYSTEM_PROMPT = """
你是一位服务中国中小企业的资深CFO顾问，精通中国税法和企业财务筹划。
你需要分析一笔大额流水，结合系统提供的税收政策知识库检索结果，
为企业老板生成专业、有深度的处理方案。

【核心要求】
1. 你的分析必须像CFO向老板汇报：数字精确、逻辑清晰、操作具体
2. 每个方案必须展示计算过程，让老板知道"这个数字是怎么来的"
3. 每个方案必须列出可执行的操作步骤（3-5步），不是口号
4. 风险评估必须具体，指明"什么情况下可能出问题"以及规避方式
5. 最终税务数字由后端Python精确计算覆盖，你的计算用于判断方向

【输出要求】
只输出一个合法的 JSON 对象，不要有任何额外文字、解释或 Markdown 代码块。

【合法 action_code 枚举（只能从以下值中选择）】
FIXED_ASSET_ONE_TIME          一次性全额扣除（500万以下设备，财税[2018]54号）
FIXED_ASSET_ACCELERATED_3Y   加速折旧3年（高新技术企业技术类设备）
FIXED_ASSET_ACCELERATED_5Y   加速折旧5年（制造业主要生产设备）
FIXED_ASSET_STRAIGHT_LINE_3Y  直线法3年（电子设备：电脑/服务器/手机等）
FIXED_ASSET_STRAIGHT_LINE_4Y  直线法4年（车辆）
FIXED_ASSET_STRAIGHT_LINE_5Y  直线法5年（电子/通用设备短年限）
FIXED_ASSET_STRAIGHT_LINE_10Y 直线法10年（通用机械、工具设备）
FIXED_ASSET_STRAIGHT_LINE_20Y 直线法20年（建筑物、大型装修）
EXPENSE_DIRECT                直接费用化（单价低或可不作固定资产的支出）
SUGGEST_LEASE                 建议改为租赁（不生成凭证，给建议）
DEFER_PURCHASE                建议暂缓购买（不生成凭证，给建议）

【选项生成规则】
- 金额 ≤ 500万：必须包含 FIXED_ASSET_ONE_TIME
- 金额 > 500万：不得包含 FIXED_ASSET_ONE_TIME
- 企业亏损或利润 < 资产金额×50%：必须包含 DEFER_PURCHASE 或 SUGGEST_LEASE
- 总选项数：3-6个，不加无意义选项
- 优先引用检索到的政策，在 analysis 和 steps 中体现具体政策条款

【输出 JSON 结构】
{
  "asset_category": "资产分类（电子设备/通用机械/车辆/建筑装修/其他）",
  "tax_analysis": "整体税务形势分析（200字以内），引用具体政策条款",
  "options": [
    {
      "id": "方案唯一标识（大写英文，如 ONE_TIME、SL_10Y、LEASE）",
      "label": "方案一",
      "title": "方案标题（10字以内）",
      "action_code": "合法枚举值",
      "useful_life_months": 月数整数（一次性扣除和非固定资产填0）,
      "salvage_rate": 残值率小数（如0.05；一次性扣除填0）,
      "analysis": "CFO风格分析（150字以内）：核心逻辑、对利润和现金流的影响",
      "tax_calculation": "节税计算过程（展示公式）。例：¥48万 × 25%税率 = 当年节税¥12万；或：加速折旧前3年多扣¥20万，节税¥4万",
      "steps": [
        "第1步：具体操作",
        "第2步：具体操作",
        "第3步：具体操作"
      ],
      "risk_level": "LOW 或 MEDIUM 或 HIGH",
      "risk_detail": "风险详情（50字以内）：什么情况下有风险，如何规避；无风险填'合规风险低'",
      "best_for": "最适合的企业情况（20字以内）",
      "savings_this_year": 0,
      "savings_total": 0
    }
  ],
  "recommendation": "推荐方案id",
  "recommendation_reason": "推荐理由（100字以内），结合企业利润/现金/税率，引用政策依据",
  "not_recommended": ["不推荐方案id列表，可为空"],
  "not_recommended_reason": "不推荐原因（有则填，否则填''）",
  "policy_references": ["方案中引用的政策文号，如：财税[2018]54号"]
}
""".strip()


def _format_rag_hits(rag_hits: list["StrategyHit"]) -> str:
    """将 RAG 检索结果格式化为 LLM 可读的政策参考块。"""
    if not rag_hits:
        return "（本次未检索到特别适用的地方性或专项政策，请基于通用税法生成方案）"

    blocks: list[str] = []
    for i, hit in enumerate(rag_hits, 1):
        # action_suggestions 在 ChromaDB 中以 "|" 分隔存储
        suggestions = hit.action_suggestions or ""
        if "|" in suggestions:
            suggestion_lines = "\n    · ".join(suggestions.split("|"))
            suggestion_text = f"\n    · {suggestion_lines}"
        else:
            suggestion_text = f" {suggestions}" if suggestions else "（无）"

        blocks.append(
            f"【政策{i}】{hit.title}  （相关度 {hit.similarity_score:.0%}）\n"
            f"  核心内容：{hit.core_content[:200]}\n"
            f"  操作建议：{suggestion_text}\n"
            f"  风险提示：{hit.risk_notes or '无'}\n"
            f"  政策依据：{hit.source_doc or '未知'}"
        )
    return "\n\n".join(blocks)


def build_decision_user_prompt(
    expense_type:    str,
    amount:          float,
    raw_text:        str,
    company_type:    str,
    industry_code:   str,
    income_tax_rate: float,
    ytd_profit:      float,
    current_cash:    float,
    current_month:   int,
    rag_hits:        "list[StrategyHit] | None" = None,
    is_hnte:         bool = False,
    rd_eligible:     bool = False,
    province:        str  = "",
    city:            str  = "",
) -> str:
    """
    构造发给 LLM 的用户消息。

    包含完整业务上下文、企业画像、财务快照和 RAG 检索到的相关税收政策。
    数字（savings_this_year / savings_total）由 Python depreciation.py 覆盖。
    """
    profit_status = (
        "亏损" if ytd_profit < 0
        else "微利（低于资产价值50%）" if ytd_profit < amount * 0.5
        else "盈利良好"
    )
    cash_status = (
        "现金紧张（不足资产价值1.5倍）" if current_cash < amount * 1.5
        else "现金充裕"
    )
    months_left = 13 - current_month   # 含当月的剩余可折旧月数

    hnte_str = "是（可叠加15%税率 + 100%研发加计扣除）" if is_hnte else "否"
    rd_str   = "是（具备研发费用加计扣除资格）" if rd_eligible else "否"
    location = f"{province}{city}".strip() or "未配置"

    policy_section = _format_rag_hits(rag_hits or [])

    return f"""
请分析以下这笔需要老板决策的大额流水，结合检索到的政策知识，生成专业处理方案。

【业务信息】
原始描述：{raw_text}
业务类型：{expense_type}
金额：¥{amount:,.2f} 元
当前月份：{current_month} 月（当年剩余可折旧月数：{months_left} 个月）

【企业画像】
企业类型：{company_type}
所属行业：{industry_code}
注册地：{location}
企业所得税率：{income_tax_rate * 100:.0f}%
高新技术企业（HNTE）：{hnte_str}
研发加计扣除资格：{rd_str}

【当前财务快照】
今年累计利润：¥{ytd_profit:,.2f} 元（{profit_status}）
当前现金余额：¥{current_cash:,.2f} 元（{cash_status}）

【系统检索到的相关税收政策（请充分利用）】
{policy_section}

【生成要求】
1. analysis 要基于该企业税率（{income_tax_rate * 100:.0f}%）分析，不要用通用税率
2. tax_calculation 必须展示完整公式，如：¥{amount/10000:.0f}万 × {income_tax_rate * 100:.0f}% = ¥XX万
3. steps 每步10字以内，共3-5步，可立即操作
4. 引用上方政策文号填入 policy_references
5. savings_this_year 和 savings_total 填0，后端精确算法覆盖
""".strip()
