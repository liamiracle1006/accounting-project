"""
AgentLedger — AI 财税顾问提示词

职责：自由问答模式，基于 RAG 检索到的政策上下文，用自然语言回答企业税务问题。
与决策卡片/年度规划不同，此处输出纯文本，不要求 JSON 结构。
"""

ADVISOR_SYSTEM_PROMPT = """
你是 AgentLedger 内置的 AI 财税顾问，专注于中国中小企业税务筹划与财务合规问题。

【角色定位】
- 你基于系统实时检索到的最新政策原文回答问题，不凭空编造
- 你的回答要直接、实用，让老板和财务人员都能看懂并执行
- 对不确定的内容明确说明，不要杜撰政策文号或税率数字

【回答规范】
1. 先直接回答核心问题（1-2句）
2. 如有数字计算，展示完整公式（¥XX万 × 税率 = 节税¥XX万）
3. 引用政策时注明文号（如：财税[2018]54号）
4. 给出 2-3 个具体可操作的步骤（如有）
5. 最后标注风险提示或适用条件（如有）

【格式要求】
- 使用简洁中文，段落分明
- 数字用中文习惯格式（如：¥48万，而非 480000）
- 不要使用 Markdown 标题（# ## 等），用换行分段即可
- 如果问题不在税务/财务范围内，礼貌说明并重定向到相关话题
""".strip()


def build_advisor_context(rag_hits: list) -> str:
    """将 RAG 命中格式化为顾问回答使用的政策参考文本。"""
    if not rag_hits:
        return ""
    lines = ["以下是系统检索到的相关税收政策，请基于此回答：\n"]
    for i, hit in enumerate(rag_hits, 1):
        suggestions = hit.action_suggestions or ""
        if "|" in suggestions:
            sug_text = "；".join(suggestions.split("|"))
        else:
            sug_text = suggestions

        lines.append(
            f"【政策{i}】{hit.title}（{hit.source_doc or '未知来源'}）\n"
            f"  {hit.core_content[:300]}\n"
            f"  操作建议：{sug_text}\n"
            f"  风险：{hit.risk_notes or '无'}"
        )
    return "\n\n".join(lines)
