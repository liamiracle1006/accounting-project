"""
AgentLedger — 年度税务规划 LLM 提示词 (S3 RAG-enhanced)

变更：
  - build_annual_plan_prompt 接收 rag_hits_by_quarter: dict[str, list[StrategyHit]]
  - RAG 命中按季度分组注入提示词，让 LLM 的行动计划有真实政策依据
  - 输出 schema 增加 policy_references、source_doc、calculation_basis
"""
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rag.retriever import StrategyHit


ANNUAL_PLAN_SYSTEM_PROMPT = """
你是一位服务中国中小企业的资深税务CFO顾问。
你的任务是根据企业税收画像、当前财务状况，以及系统检索到的真实税收政策，
生成一份完整、可执行的年度税务筹划路线图。

【核心要求】
1. 每个行动计划必须有具体的数字支撑（预计节税金额要有计算依据）
2. detail 字段要说清楚"做什么、怎么做"，不要只说"了解政策"
3. 优先使用检索到的政策，在行动中引用政策文号
4. 已过去的季度标注"当季补救"或跳过不适用行动
5. potential_saving 基于实际税率和财务数据估算，不要随意捏造

【输出要求】
只输出一个合法的 JSON 对象，不要有任何额外文字或 Markdown 代码块。

【输出 JSON 结构】
{
  "year": 年份整数,
  "profile_summary": "一句话描述企业类型、纳税人身份和核心税务特征",
  "estimated_annual_profit": 预估全年利润（元），
  "estimated_tax_baseline": 按当前税率应交税额（元），
  "total_potential_savings": 通过筹划可节省的税额上限（元），
  "quarters": [
    {
      "quarter": "Q1",
      "months": "1-3月",
      "theme": "本季度核心主题（10字内）",
      "actions": [
        {
          "id": "唯一标识如 Q1_RD_DEDUCTION",
          "title": "行动标题（15字内）",
          "priority": "HIGH / MEDIUM / LOW",
          "potential_saving": 预计节税金额（元），
          "deadline": "截止时间（如：3月31日）",
          "category": "研发/折旧/增值税/薪酬/资质认定/地方政策/其他",
          "detail": "具体操作说明（80字内，可执行的步骤描述）",
          "calculation_basis": "节税金额计算依据（如：研发费100万×75%×20%税率=节税15万）",
          "trigger_condition": "适用条件（20字内）",
          "source_doc": "政策依据文号（有则填，无则填''）"
        }
      ]
    }
  ],
  "key_thresholds": {
    "one_time_deduction_limit": 5000000,
    "small_profit_income_limit": 3000000,
    "vat_exempt_quarterly": 300000,
    "current_income_tax_rate": 所得税率小数,
    "rd_deduction_rate": 研发加计扣除比例小数（如0.75或1.0）
  },
  "policy_references": ["规划中引用的政策文号列表"],
  "disclaimer": "本规划基于现行税法和系统检索的政策自动生成，仅供参考，重大决策建议咨询专业税务师"
}
""".strip()


def _format_quarter_hits(hits: list["StrategyHit"], quarter: str) -> str:
    """格式化单个季度的 RAG 命中策略。"""
    if not hits:
        return f"（{quarter} 无专项政策检索结果）"
    lines: list[str] = []
    for h in hits:
        lines.append(f"  · [{h.source_doc}] {h.title}：{h.core_content[:120]}")
    return "\n".join(lines)


def build_annual_plan_prompt(
    year:            int,
    company_name:    str,
    company_type:    str,
    industry_code:   str,
    tax_payer_type:  str,
    income_tax_rate: float,
    vat_rate:        float,
    ytd_profit:      float,
    ytd_revenue:     float,
    current_month:   int,
    asset_count:     int,
    is_hnte:         bool = False,
    rd_eligible:     bool = False,
    province:        str  = "",
    city:            str  = "",
    rag_hits_by_quarter: "dict[str, list[StrategyHit]] | None" = None,
) -> str:
    """
    构造年度税务规划 LLM 用户消息。

    rag_hits_by_quarter 格式：{ "Q1": [...], "Q2": [...], "Q3": [...], "Q4": [...], "ANY": [...] }
    """
    months_remaining = 12 - current_month + 1
    location = f"{province}{city}".strip() or "未配置"
    hnte_str = "是（15%税率 + 100%研发加计扣除）" if is_hnte else "否"
    rd_str   = "是（具备研发费用加计扣除资格）" if rd_eligible else "否"

    # 按季度格式化 RAG 命中结果
    hits_map = rag_hits_by_quarter or {}
    any_hits = hits_map.get("ANY", [])

    q1_section = _format_quarter_hits(hits_map.get("Q1", []) + any_hits, "Q1")
    q2_section = _format_quarter_hits(hits_map.get("Q2", []) + any_hits, "Q2")
    q3_section = _format_quarter_hits(hits_map.get("Q3", []) + any_hits, "Q3")
    q4_section = _format_quarter_hits(hits_map.get("Q4", []) + any_hits, "Q4")

    # 所有命中的政策文号汇总
    all_hits = [h for qs in hits_map.values() for h in qs]
    all_sources = list(dict.fromkeys(h.source_doc for h in all_hits if h.source_doc))
    sources_str = "、".join(all_sources) if all_sources else "（未检索到特定政策）"

    return f"""
请为以下企业生成 {year} 年度税务筹划路线图：

【企业画像】
公司名称：{company_name}
企业类型：{company_type}（MICRO=小微/个体户，STANDARD=一般企业）
所属行业：{industry_code}
注册地：{location}
纳税人身份：{tax_payer_type}（SMALL_SCALE=小规模，GENERAL=一般纳税人）
企业所得税率：{income_tax_rate * 100:.0f}%
增值税率：{vat_rate * 100:.0f}%
高新技术企业（HNTE）：{hnte_str}
研发加计扣除资格：{rd_str}

【当前财务快照】
当前月份：{current_month} 月（全年剩余 {months_remaining} 个月）
今年累计利润：¥{ytd_profit:,.0f}
今年累计收入：¥{ytd_revenue:,.0f}
当前固定资产数量：{asset_count} 件

【系统检索到的适用政策（按季度最优时机分组）】

Q1 适用政策（1-3月）：
{q1_section}

Q2 适用政策（4-6月）：
{q2_section}

Q3 适用政策（7-9月）：
{q3_section}

Q4 适用政策（10-12月）：
{q4_section}

本次检索涉及政策文号：{sources_str}

【生成要求】
1. 充分利用以上检索到的政策，每个行动尽量填写 source_doc
2. calculation_basis 要展示完整公式，如：研发费估算¥XX万 × 75% × {income_tax_rate * 100:.0f}% = 节税¥XX万
3. 已过去的月份（当前 {current_month} 月），对应季度行动标注"当季补救"或跳过
4. 每季度 3-5 个行动，不凑数
5. potential_saving 基于该企业税率（{income_tax_rate * 100:.0f}%）计算，不随意捏造
""".strip()
