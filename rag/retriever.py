"""
AgentLedger RAG — Dual-Layer Retriever

Layer 1: Metadata hard-filter (taxpayer type, industry, region, profit range, validity)
Layer 2: Semantic similarity TopK

Usage
─────
    from rag.retriever import TaxStrategyRetriever, RetrievalContext

    ctx = RetrievalContext(
        taxpayer_type  = "GENERAL",          # from EnterpriseProfile
        industry_code  = "制造业",
        province       = "广东省",
        city           = "深圳市",
        ytd_profit     = 1_500_000,          # from _calc_ytd()
        query_text     = "公司今年广告投入超过营收15%怎么处理",
        top_k          = 6,
        query_date     = "2026-03-27",
    )
    results = retriever.retrieve(ctx)
    # results: list of StrategyHit, ranked by relevance
"""
import logging
from dataclasses import dataclass
from datetime import date
from typing import Any

from rag.embedder import Embedder
from rag.chroma_store import ChromaStore

logger = logging.getLogger(__name__)


@dataclass
class RetrievalContext:
    query_text:    str
    taxpayer_type: str          = "ALL"   # "SMALL_SCALE" | "GENERAL" | "ALL"
    industry_code: str          = "ALL"
    province:      str          = ""
    city:          str          = ""
    ytd_profit:    float        = 0.0
    top_k:         int          = 6
    query_date:    str          = ""      # "YYYY-MM-DD", defaults to today


@dataclass
class StrategyHit:
    strategy_id:        str
    title:              str
    core_content:       str       # = document text
    action_suggestions: str
    risk_notes:         str
    source_doc:         str
    optimal_timing:     str
    confidence:         float
    similarity_score:   float     # 1 - cosine_distance


class TaxStrategyRetriever:
    def __init__(self) -> None:
        self._embedder = Embedder()
        self._store    = ChromaStore()

    def retrieve(self, ctx: RetrievalContext) -> list[StrategyHit]:
        """
        Full dual-layer retrieval pipeline.
        Returns up to ctx.top_k hits, ranked best-first.
        """
        today = ctx.query_date or str(date.today())

        # ── Layer 1: Build metadata where-filter ────────────────────────────
        where = self._build_where(ctx, today)

        # ── Layer 2: Embed query and semantic search ─────────────────────────
        query_vec = self._embedder.embed_one(ctx.query_text)
        raw_hits  = self._store.query(
            query_vector = query_vec,
            where        = where,
            n_results    = ctx.top_k,
        )

        # If hard-filter returns nothing, fall back to no-filter semantic search
        if not raw_hits:
            logger.info("Retriever: no hits with filter, falling back to semantic-only")
            raw_hits = self._store.query(
                query_vector = query_vec,
                n_results    = ctx.top_k,
            )

        return [self._to_hit(h) for h in raw_hits]

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _build_where(self, ctx: RetrievalContext, today: str) -> dict[str, Any] | None:
        """
        Build ChromaDB where-filter.

        ChromaDB supports: $eq, $ne, $gt, $gte, $lt, $lte, $in, $nin, $and, $or
        We use $and to combine multiple conditions.
        """
        conditions: list[dict] = []

        # 1. Validity date
        conditions.append({"valid_from":  {"$lte": today}})
        conditions.append({"valid_until": {"$gte": today}})

        # 2. Profit range (ytd_profit must fall within slice's range)
        if ctx.ytd_profit > 0:
            conditions.append({"profit_min": {"$lte": ctx.ytd_profit}})
            conditions.append({"profit_max": {"$gte": ctx.ytd_profit}})

        # 3. Taxpayer type (slice applies to ALL or this specific type)
        if ctx.taxpayer_type and ctx.taxpayer_type != "ALL":
            conditions.append({
                "$or": [
                    {"applicable_taxpayer": {"$eq": "ALL"}},
                    {"applicable_taxpayer": {"$eq": ctx.taxpayer_type}},
                    # CSV stored — check both positions
                    {"applicable_taxpayer": {"$eq": f"ALL,{ctx.taxpayer_type}"}},
                    {"applicable_taxpayer": {"$eq": f"{ctx.taxpayer_type},ALL"}},
                ]
            })

        # 4. Region (NATIONAL always matches; PROVINCIAL/CITY must match)
        region_filters: list[dict] = [
            {"region_scope": {"$eq": "NATIONAL"}}
        ]
        if ctx.province:
            region_filters.append({
                "$and": [
                    {"region_scope":         {"$eq": "PROVINCIAL"}},
                    {"applicable_regions":   {"$eq": ctx.province}},
                ]
            })
        if ctx.city:
            region_filters.append({
                "$and": [
                    {"region_scope":         {"$eq": "CITY"}},
                    {"applicable_regions":   {"$eq": ctx.city}},
                ]
            })
        conditions.append({"$or": region_filters})

        if len(conditions) == 1:
            return conditions[0]
        return {"$and": conditions}

    @staticmethod
    def _to_hit(raw: dict) -> StrategyHit:
        meta = raw["metadata"]
        return StrategyHit(
            strategy_id        = raw["id"],
            title              = meta.get("title", ""),
            core_content       = raw["document"],
            action_suggestions = meta.get("action_suggestions", ""),
            risk_notes         = meta.get("risk_notes", ""),
            source_doc         = meta.get("source_doc", ""),
            optimal_timing     = meta.get("optimal_timing", "ANY"),
            confidence         = float(meta.get("confidence", 1.0)),
            similarity_score   = round(1.0 - float(raw.get("distance", 0)), 4),
        )

    def batch_retrieve_for_annual_plan(
        self,
        taxpayer_type: str,
        industry_code: str,
        province:      str,
        city:          str,
        ytd_profit:    float,
        query_date:    str = "",
    ) -> dict[str, list[StrategyHit]]:
        """
        Annual plan mode: retrieve all applicable strategies,
        grouped by optimal_timing quarter.
        Returns { "Q1": [...], "Q2": [...], "Q3": [...], "Q4": [...], "ANY": [...] }
        """
        ctx = RetrievalContext(
            query_text    = "年度税务筹划全面策略",
            taxpayer_type = taxpayer_type,
            industry_code = industry_code,
            province      = province,
            city          = city,
            ytd_profit    = ytd_profit,
            top_k         = 40,
            query_date    = query_date,
        )
        hits = self.retrieve(ctx)
        grouped: dict[str, list[StrategyHit]] = {"Q1": [], "Q2": [], "Q3": [], "Q4": [], "ANY": []}
        for h in hits:
            key = h.optimal_timing if h.optimal_timing in grouped else "ANY"
            grouped[key].append(h)
        return grouped
