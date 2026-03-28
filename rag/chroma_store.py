"""
AgentLedger RAG — ChromaDB Store

Wraps the ChromaDB client for reading and writing strategy slices.
All slices share one collection (configurable via CHROMA_COLLECTION).

If chromadb is not installed (e.g. Windows without C++ Build Tools),
ChromaStore will raise RAGUnavailableError on instantiation.
All callers should catch this and degrade gracefully.
"""
import logging
from typing import Any

from config.settings import CHROMA_PATH, CHROMA_COLLECTION
from rag.schema import StrategySlice

logger = logging.getLogger(__name__)

try:
    import chromadb
    from chromadb.config import Settings as ChromaSettings
    _CHROMADB_AVAILABLE = True
except ImportError:
    _CHROMADB_AVAILABLE = False
    logger.warning(
        "chromadb is not installed — RAG/vector-store features are disabled. "
        "To enable: pip install chromadb"
    )


class RAGUnavailableError(RuntimeError):
    """Raised when chromadb is not installed."""


class ChromaStore:
    def __init__(self) -> None:
        if not _CHROMADB_AVAILABLE:
            raise RAGUnavailableError(
                "chromadb is not installed. RAG features are unavailable. "
                "Install with: pip install chromadb"
            )
        self._client = chromadb.PersistentClient(
            path=CHROMA_PATH,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self._col = self._client.get_or_create_collection(
            name=CHROMA_COLLECTION,
            metadata={"hnsw:space": "cosine"},   # cosine similarity
        )
        logger.info(
            "ChromaStore ready: path=%s collection=%s count=%d",
            CHROMA_PATH, CHROMA_COLLECTION, self._col.count(),
        )

    # ── Write ────────────────────────────────────────────────────────────────

    def upsert(self, slices: list[StrategySlice], vectors: list[list[float]]) -> None:
        """
        Insert or update slices. Uses strategy_id as the document ID,
        so re-running the loader is safe (idempotent).
        """
        if not slices:
            return
        self._col.upsert(
            ids        = [s.strategy_id for s in slices],
            embeddings = vectors,
            documents  = [s.embed_text() for s in slices],
            metadatas  = [s.to_chroma_metadata() for s in slices],
        )
        logger.info("Upserted %d slices into ChromaDB", len(slices))

    def delete(self, strategy_id: str) -> None:
        self._col.delete(ids=[strategy_id])
        logger.info("Deleted slice %s from ChromaDB", strategy_id)

    def count(self) -> int:
        return self._col.count()

    # ── Read ─────────────────────────────────────────────────────────────────

    def query(
        self,
        query_vector:    list[float],
        where:           dict[str, Any] | None = None,
        n_results:       int = 8,
    ) -> list[dict]:
        """
        Semantic search with optional metadata pre-filter.

        Returns list of dicts:
          { id, document, metadata, distance }
        sorted by ascending cosine distance (most similar first).
        """
        kwargs: dict[str, Any] = {
            "query_embeddings": [query_vector],
            "n_results": n_results,
            "include": ["documents", "metadatas", "distances"],
        }
        if where:
            kwargs["where"] = where

        try:
            raw = self._col.query(**kwargs)
        except Exception as exc:
            # ChromaDB raises if n_results > collection size
            logger.warning("ChromaDB query error: %s — retrying without filter", exc)
            kwargs.pop("where", None)
            kwargs["n_results"] = min(n_results, self._col.count())
            if kwargs["n_results"] == 0:
                return []
            raw = self._col.query(**kwargs)

        results = []
        ids        = raw["ids"][0]
        documents  = raw["documents"][0]
        metadatas  = raw["metadatas"][0]
        distances  = raw["distances"][0]

        for sid, doc, meta, dist in zip(ids, documents, metadatas, distances):
            results.append({
                "id":       sid,
                "document": doc,
                "metadata": meta,
                "distance": dist,
            })
        return results

    def get_all_ids(self) -> list[str]:
        result = self._col.get(include=[])
        return result["ids"]
