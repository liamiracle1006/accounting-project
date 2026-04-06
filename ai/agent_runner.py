"""
AgentLedger V4.0 — AgentRunner (Sprint 3.1)

职责：
  驱动 LLM 的多轮工具调用（Tool Use）循环，直到 LLM 输出最终答案。

工作流程：
  1. 将 messages + tools 发送给 LLM
  2. 若 LLM 返回 finish_reason="tool_calls"：
       a. 遍历 tool_calls，本地执行对应函数
       b. 将 tool_result 追加到 messages
       c. 重新发送给 LLM（下一轮）
  3. 若 LLM 返回正常文本（finish_reason="stop"）：
       返回最终 content 字符串

安全限制：
  MAX_TURNS = 8 —— 超过则抛出 LLMClientError，防止无限循环。
  每个工具调用失败时，返回 {"error": "..."} 而不是崩溃，让 LLM 自行决策。
"""
import json
import logging
from typing import Any, Callable

from ai.llm_client import LLMClient, LLMClientError

logger = logging.getLogger(__name__)

# 最大工具调用轮次（防止 LLM 陷入死循环）
MAX_TURNS = 8


class AgentRunner:
    """
    多轮 Tool Calling 执行引擎。

    设计选择：
      - 同步执行（与现有 LLMClient 保持一致）
      - 工具注册表（tool_registry）由调用方传入，AgentRunner 本身无状态
      - 每轮 tool_call 的执行结果以 role="tool" 消息追加到对话历史

    用法示例：
      runner = AgentRunner(llm_client)
      result = runner.run(
          messages=[{"role": "system", ...}, {"role": "user", ...}],
          tools_def=[DRILL_DOWN_TOOL_DEF],
          tool_registry={"drill_down_subject": subject_retriever.drill_down_subject},
      )
    """

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    def run(
        self,
        messages: list[dict],
        tools_def: list[dict],
        tool_registry: dict[str, Callable],
    ) -> str:
        """
        驱动 LLM 工具调用循环，返回 LLM 最终输出的字符串（通常是 JSON）。

        参数：
          messages     — 初始消息列表（含 system + user，不含 assistant/tool）
          tools_def    — OpenAI 格式的工具定义列表
          tool_registry— {工具名: Python 可调用函数} 映射

        返回：
          LLM 最终输出的字符串（Sprint 3.1 中为凭证 JSON）

        异常：
          LLMClientError — API 失败或超过最大轮次
        """
        # 防止修改调用方的 messages 列表
        messages = list(messages)

        for turn in range(1, MAX_TURNS + 1):
            logger.debug("AgentRunner turn=%d messages=%d", turn, len(messages))

            # ── 调用 LLM ──────────────────────────────────────────────────────
            raw_resp = self._llm.tool_call_completion(messages, tools_def)

            try:
                choice     = raw_resp["choices"][0]
                msg        = choice["message"]
                finish     = choice.get("finish_reason", "")
            except (KeyError, IndexError) as exc:
                raise LLMClientError(
                    f"AgentRunner: unexpected API response structure: {str(raw_resp)[:200]}"
                ) from exc

            tool_calls = msg.get("tool_calls") or []

            # ── 判断是否需要工具调用 ───────────────────────────────────────────
            if tool_calls:
                # 将 assistant 消息（含 tool_calls）追加到历史
                messages.append({
                    "role":       "assistant",
                    "content":    msg.get("content"),   # 通常为 null
                    "tool_calls": tool_calls,
                })

                # 逐一执行工具
                for tc in tool_calls:
                    tool_name = tc["function"]["name"]
                    call_id   = tc["id"]

                    try:
                        fn_args = json.loads(tc["function"]["arguments"])
                    except (json.JSONDecodeError, KeyError):
                        fn_args = {}

                    logger.debug(
                        "AgentRunner executing tool=%s args=%s", tool_name, fn_args
                    )

                    fn = tool_registry.get(tool_name)
                    if fn is None:
                        tool_result: Any = {
                            "error": f"工具 '{tool_name}' 未注册，请检查工具名称"
                        }
                    else:
                        try:
                            tool_result = fn(**fn_args)
                        except TypeError as exc:
                            tool_result = {"error": f"工具调用参数错误: {exc}"}
                        except Exception as exc:
                            logger.warning(
                                "AgentRunner tool %s raised: %s", tool_name, exc
                            )
                            tool_result = {"error": str(exc)}

                    # 将工具结果追加到消息历史
                    messages.append({
                        "role":         "tool",
                        "tool_call_id": call_id,
                        "content":      json.dumps(tool_result, ensure_ascii=False),
                    })

            else:
                # ── LLM 给出最终答案 ───────────────────────────────────────────
                content = msg.get("content") or ""
                logger.debug(
                    "AgentRunner finished after %d turn(s), output length=%d",
                    turn, len(content),
                )
                return content

        raise LLMClientError(
            f"AgentRunner: 超过最大工具调用轮次 ({MAX_TURNS})，请检查 LLM 是否陷入循环"
        )
