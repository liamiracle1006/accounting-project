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
from ai.import_prompts import HEADER_MAPPING_SYSTEM_PROMPT, SUBJECT_MATCHING_SYSTEM_PROMPT

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

    def map_excel_headers(self, preview_json: str) -> str:
        """
        分析旧 Excel 的列名和前 N 行预览数据，返回标准字段 → 实际列名 的映射 JSON。
        preview_json 格式：
          {"source_system": "金蝶", "columns": [...], "preview": [{...}, ...]}
        返回 JSON string，由调用方 json.loads() 解析。
        """
        payload: dict[str, Any] = {
            "model":           LLM_MODEL,
            "max_tokens":      512,
            "temperature":     0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": HEADER_MAPPING_SYSTEM_PROMPT},
                {"role": "user",   "content": preview_json},
            ],
        }

        logger.debug("Calling LLM for Excel header mapping: model=%s", LLM_MODEL)

        try:
            with httpx.Client(timeout=LLM_TIMEOUT) as client:
                response = client.post(self._url, headers=self._headers,
                                       content=json.dumps(payload))
        except httpx.TimeoutException as exc:
            raise LLMClientError(f"Header mapping LLM timeout after {LLM_TIMEOUT}s") from exc
        except httpx.RequestError as exc:
            raise LLMClientError(f"Header mapping LLM network error: {exc}") from exc

        if response.status_code != 200:
            raise LLMClientError(
                f"Header mapping LLM returned HTTP {response.status_code}: {response.text[:300]}"
            )

        try:
            body      = response.json()
            json_text = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError) as exc:
            raise LLMClientError(
                f"Unexpected header mapping LLM response structure: {response.text[:300]}"
            ) from exc

        logger.debug("Header mapping LLM raw response: %s", json_text[:500])
        return json_text

    def tool_call_completion(
        self,
        messages: list[dict],
        tools: list[dict],
    ) -> dict:
        """
        发起支持工具调用（Function Calling）的 Chat Completion 请求。

        与其他方法不同，此方法返回完整的 API 响应 dict（不解包 content），
        由 AgentRunner 负责检测 finish_reason 并决定是否继续循环。

        参数：
          messages — 完整的消息历史（含 system / user / assistant / tool 角色）
          tools    — OpenAI Tool 定义列表，每项格式：
                     {"type": "function", "function": {"name":..., "description":..., "parameters":...}}
        返回：
          完整的 /chat/completions 响应 dict，包含 choices[0].message 和 finish_reason
        """
        payload: dict[str, Any] = {
            "model":       LLM_MODEL,
            "max_tokens":  LLM_MAX_TOKENS,
            "temperature": 0,
            "tools":       tools,
            "tool_choice": "auto",
            "messages":    messages,
        }

        logger.debug("Calling LLM with tool_call: model=%s turns=%d", LLM_MODEL, len(messages))

        try:
            with httpx.Client(timeout=LLM_TIMEOUT) as client:
                response = client.post(self._url, headers=self._headers,
                                       content=json.dumps(payload))
        except httpx.TimeoutException as exc:
            raise LLMClientError(f"Tool call LLM timeout after {LLM_TIMEOUT}s") from exc
        except httpx.RequestError as exc:
            raise LLMClientError(f"Tool call LLM network error: {exc}") from exc

        if response.status_code != 200:
            raise LLMClientError(
                f"Tool call LLM returned HTTP {response.status_code}: {response.text[:300]}"
            )

        try:
            return response.json()
        except ValueError as exc:
            raise LLMClientError(
                f"Tool call LLM returned non-JSON body: {response.text[:300]}"
            ) from exc

    def match_subjects(self, matching_json: str) -> str:
        """
        将旧系统科目列表与新系统科目树做语义模糊匹配，返回带置信度的匹配结果 JSON。
        matching_json 格式：
          {"to_match": [{staging_id, raw_code, raw_name},...],
           "system_subjects": [{subject_code, subject_name, balance_direction, category},...]}
        返回 JSON string，由调用方 json.loads() 解析。
        """
        payload: dict[str, Any] = {
            "model":           LLM_MODEL,
            "max_tokens":      2048,
            "temperature":     0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SUBJECT_MATCHING_SYSTEM_PROMPT},
                {"role": "user",   "content": matching_json},
            ],
        }

        logger.debug("Calling LLM for subject matching: model=%s", LLM_MODEL)

        try:
            with httpx.Client(timeout=LLM_TIMEOUT) as client:
                response = client.post(self._url, headers=self._headers,
                                       content=json.dumps(payload))
        except httpx.TimeoutException as exc:
            raise LLMClientError(f"Subject matching LLM timeout after {LLM_TIMEOUT}s") from exc
        except httpx.RequestError as exc:
            raise LLMClientError(f"Subject matching LLM network error: {exc}") from exc

        if response.status_code != 200:
            raise LLMClientError(
                f"Subject matching LLM returned HTTP {response.status_code}: {response.text[:300]}"
            )

        try:
            body      = response.json()
            json_text = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError) as exc:
            raise LLMClientError(
                f"Unexpected subject matching LLM response structure: {response.text[:300]}"
            ) from exc

        logger.debug("Subject matching LLM raw response: %s", json_text[:500])
        return json_text
