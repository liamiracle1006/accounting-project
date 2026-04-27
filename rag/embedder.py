"""
AgentLedger RAG — Embedder

Calls an OpenAI-compatible embedding API to convert text into vectors.

To switch to Qwen text-embedding-v3:
  EMBED_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
  EMBED_MODEL=text-embedding-v3
  EMBED_API_KEY=<your dashscope key>

To switch to any other provider, update the same three env vars.
No code changes needed.
"""
import logging
import time
from typing import Sequence

import httpx

from config.settings import (
    EMBED_API_KEY,
    EMBED_BASE_URL,
    EMBED_MODEL,
    EMBED_BATCH_SIZE,
)

logger = logging.getLogger(__name__)

_EMBED_URL = EMBED_BASE_URL.rstrip("/") + "/embeddings"


class EmbedderError(RuntimeError):
    pass


class Embedder:
    def __init__(self) -> None:
        if not EMBED_API_KEY:
            raise EmbedderError(
                "EMBED_API_KEY is not set. "
                "Add it to .env (can reuse LLM_API_KEY if same provider)."
            )
        self._headers = {
            "Authorization": f"Bearer {EMBED_API_KEY}",
            "Content-Type":  "application/json",
        }
        self._model = EMBED_MODEL
        self._batch = EMBED_BATCH_SIZE

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """
        Embed a list of texts. Automatically batches to avoid API limits.
        Returns list of float vectors, same order as input.
        """
        results: list[list[float]] = []
        batches = [texts[i:i + self._batch] for i in range(0, len(texts), self._batch)]

        for idx, batch in enumerate(batches):
            vectors = self._call_api(list(batch))
            results.extend(vectors)
            if len(batches) > 1:
                logger.debug("Embedded batch %d/%d", idx + 1, len(batches))

        return results

    def embed_one(self, text: str) -> list[float]:
        return self.embed([text])[0]

    def _call_api(self, texts: list[str], retries: int = 3) -> list[list[float]]:
        payload = {"model": self._model, "input": texts}
        for attempt in range(1, retries + 1):
            try:
                with httpx.Client(timeout=60) as client:
                    resp = client.post(_EMBED_URL, json=payload, headers=self._headers)
                resp.raise_for_status()
                data = resp.json()
                # Sort by index to preserve order (OpenAI spec)
                items = sorted(data["data"], key=lambda x: x["index"])
                return [item["embedding"] for item in items]
            except Exception as exc:
                logger.warning("Embedding attempt %d failed: %s", attempt, exc)
                if attempt == retries:
                    raise EmbedderError(f"Embedding API failed after {retries} attempts: {exc}") from exc
                time.sleep(2 ** attempt)
        return []  # unreachable
