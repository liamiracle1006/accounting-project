"""
AgentLedger — LLM HTTP Client (OpenAI-compatible API)
Responsibility: send raw_text → receive JSON string from LLM.
The LLM is ONLY a text parser; all arithmetic stays in backend code.
"""
import json
import logging
from typing import Any

import httpx

from config.settings import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, LLM_TIMEOUT, LLM_MAX_TOKENS
from ai.prompts import SYSTEM_PROMPT
from ai.decision_prompts import DECISION_SYSTEM_PROMPT
from ai.annual_plan_prompts import ANNUAL_PLAN_SYSTEM_PROMPT
from ai.advisor_prompts import ADVISOR_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


class LLMClientError(Exception):
    """Raised when the LLM API call fails or returns an unexpected structure."""


class LLMClient:
    """Thin wrapper around any OpenAI-compatible chat completions endpoint."""

    def __init__(self) -> None:
        self._headers = {
            "Authorization": f"Bearer {LLM_API_KEY}",
            "Content-Type": "application/json",
        }
        self._url = f"{LLM_BASE_URL.rstrip('/')}/chat/completions"

    def extract_business_data(self, raw_text: str) -> str:
        """
        Send raw_text to LLM and return the raw JSON *string* extracted.
        Raises LLMClientError on any failure.
        """
        payload: dict[str, Any] = {
            "model": LLM_MODEL,
            "max_tokens": LLM_MAX_TOKENS,
            "temperature": 0,           # deterministic output
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": raw_text},
            ],
        }

        logger.debug("Calling LLM: model=%s url=%s", LLM_MODEL, self._url)

        try:
            with httpx.Client(timeout=LLM_TIMEOUT) as client:
                response = client.post(self._url, headers=self._headers,
                                       content=json.dumps(payload))
        except httpx.TimeoutException as exc:
            raise LLMClientError(f"LLM API timeout after {LLM_TIMEOUT}s") from exc
        except httpx.RequestError as exc:
            raise LLMClientError(f"LLM API network error: {exc}") from exc

        if response.status_code != 200:
            raise LLMClientError(
                f"LLM API returned HTTP {response.status_code}: {response.text[:300]}"
            )

        try:
            body = response.json()
            json_text: str = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError) as exc:
            raise LLMClientError(
                f"Unexpected LLM response structure: {response.text[:300]}"
            ) from exc

        logger.debug("LLM raw response: %s", json_text)
        return json_text

    def generate_decision_options(self, user_prompt: str) -> str:
        """
        调用 LLM 生成老板决策卡片的多方案 JSON。
        使用独立的 DECISION_SYSTEM_PROMPT，与流水解析互不干扰。
        """
        payload: dict[str, Any] = {
            "model":           LLM_MODEL,
            "max_tokens":      2048,
            "temperature":     0.2,    # 允许少量创造性，但保持稳定
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": DECISION_SYSTEM_PROMPT},
                {"role": "user",   "content": user_prompt},
            ],
        }

        logger.debug("Calling LLM for decision card: model=%s", LLM_MODEL)

        try:
            with httpx.Client(timeout=LLM_TIMEOUT) as client:
                response = client.post(self._url, headers=self._headers,
                                       content=json.dumps(payload))
        except httpx.TimeoutException as exc:
            raise LLMClientError(f"Decision LLM timeout after {LLM_TIMEOUT}s") from exc
        except httpx.RequestError as exc:
            raise LLMClientError(f"Decision LLM network error: {exc}") from exc

        if response.status_code != 200:
            raise LLMClientError(
                f"Decision LLM returned HTTP {response.status_code}: {response.text[:300]}"
            )

        try:
            body      = response.json()
            json_text = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError) as exc:
            raise LLMClientError(
                f"Unexpected decision LLM response structure: {response.text[:300]}"
            ) from exc

        logger.debug("Decision LLM raw response: %s", json_text[:500])
        return json_text

    def generate_annual_plan(self, user_prompt: str) -> str:
        """
        调用 LLM 生成年度税务筹划路线图 JSON。
        使用 ANNUAL_PLAN_SYSTEM_PROMPT，输出 Q1-Q4 四季度行动计划。
        """
        payload: dict[str, Any] = {
            "model":           LLM_MODEL,
            "max_tokens":      3000,
            "temperature":     0.3,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": ANNUAL_PLAN_SYSTEM_PROMPT},
                {"role": "user",   "content": user_prompt},
            ],
        }

        logger.debug("Calling LLM for annual tax plan: model=%s", LLM_MODEL)

        try:
            with httpx.Client(timeout=LLM_TIMEOUT) as client:
                response = client.post(self._url, headers=self._headers,
                                       content=json.dumps(payload))
        except httpx.TimeoutException as exc:
            raise LLMClientError(f"Annual plan LLM timeout after {LLM_TIMEOUT}s") from exc
        except httpx.RequestError as exc:
            raise LLMClientError(f"Annual plan LLM network error: {exc}") from exc

        if response.status_code != 200:
            raise LLMClientError(
                f"Annual plan LLM returned HTTP {response.status_code}: {response.text[:300]}"
            )

        try:
            body      = response.json()
            json_text = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError) as exc:
            raise LLMClientError(
                f"Unexpected annual plan LLM response structure: {response.text[:300]}"
            ) from exc

        logger.debug("Annual plan LLM raw response: %s", json_text[:500])
        return json_text

    def answer_tax_question(
        self,
        question:    str,
        rag_context: str,
        history:     list[dict],
    ) -> str:
        """
        自由问答模式：基于 RAG 检索到的政策上下文，用自然语言回答企业税务问题。
        输出纯文本（不强制 JSON），支持多轮对话历史。
        history 格式：[{"role": "user"/"assistant", "content": "..."}]
        """
        messages: list[dict] = [{"role": "system", "content": ADVISOR_SYSTEM_PROMPT}]

        # 最多保留最近 6 条历史（3轮对话）避免 token 超限
        for msg in history[-6:]:
            role = msg.get("role", "user")
            if role in ("user", "assistant"):
                messages.append({"role": role, "content": msg["content"]})

        # 当前问题：将 RAG 上下文和问题合并为 user 消息
        if rag_context:
            user_content = f"{rag_context}\n\n---\n用户问题：{question}"
        else:
            user_content = question
        messages.append({"role": "user", "content": user_content})

        payload: dict = {
            "model":       LLM_MODEL,
            "max_tokens":  1500,
            "temperature": 0.4,
            # 纯文本输出，不使用 json_object
            "messages": messages,
        }

        logger.debug("Calling LLM for advisor Q&A: model=%s", LLM_MODEL)

        try:
            with httpx.Client(timeout=LLM_TIMEOUT) as client:
                response = client.post(self._url, headers=self._headers,
                                       content=json.dumps(payload))
        except httpx.TimeoutException as exc:
            raise LLMClientError(f"Advisor LLM timeout after {LLM_TIMEOUT}s") from exc
        except httpx.RequestError as exc:
            raise LLMClientError(f"Advisor LLM network error: {exc}") from exc

        if response.status_code != 200:
            raise LLMClientError(
                f"Advisor LLM returned HTTP {response.status_code}: {response.text[:300]}"
            )

        try:
            body   = response.json()
            answer = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError) as exc:
            raise LLMClientError(
                f"Unexpected advisor LLM response structure: {response.text[:300]}"
            ) from exc

        logger.debug("Advisor LLM answer length: %d chars", len(answer))
        return answer
