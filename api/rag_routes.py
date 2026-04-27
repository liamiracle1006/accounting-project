"""
AgentLedger — RAG Knowledge Management API (S3-E)

端点：
  GET    /api/rag/stats               — 知识库统计（切片总数）
  GET    /api/rag/slices              — 列出所有切片 ID
  POST   /api/rag/slices              — 新增单个策略切片（并向量化入库）
  PUT    /api/rag/slices/{id}         — 更新已有切片（全量替换）
  DELETE /api/rag/slices/{id}         — 删除切片
  POST   /api/rag/reload              — 从 JSON 文件重新加载所有知识（等同 seed_loader）
  POST   /api/rag/search              — 语义检索测试（调试用）
"""
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database.connection import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/rag", tags=["rag"])


# ── Request / Response schemas ─────────────────────────────────────────────────

class SliceMetadataIn(BaseModel):
    applicable_taxpayer: list[str] = Field(default_factory=lambda: ["ALL"])
    applicable_industry: list[str] = Field(default_factory=lambda: ["ALL"])
    region_scope:        str       = Field(default="NATIONAL")
    applicable_regions:  list[str] = Field(default_factory=list)
    profit_range:        dict      = Field(default_factory=lambda: {"min": 0, "max": 99999999})
    optimal_timing:      str       = Field(default="ANY")
    valid_from:          str       = Field(default="2020-01-01")
    valid_until:         str       = Field(default="2099-12-31")
    source_doc:          str       = Field(default="")
    confidence:          float     = Field(default=1.0, ge=0.0, le=1.0)


class SliceIn(BaseModel):
    strategy_id:        str            = Field(..., min_length=1, max_length=50)
    title:              str            = Field(..., min_length=1, max_length=100)
    scenario:           str            = Field(..., min_length=1)
    core_content:       str            = Field(..., min_length=1)
    metadata:           SliceMetadataIn
    trigger_keywords:   list[str]      = Field(default_factory=list)
    action_suggestions: list[str]      = Field(default_factory=list)
    risk_notes:         str            = Field(default="")


class SearchRequest(BaseModel):
    query:         str   = Field(..., min_length=1, description="检索查询文本")
    taxpayer_type: str   = Field(default="ALL")
    industry_code: str   = Field(default="ALL")
    province:      str   = Field(default="")
    city:          str   = Field(default="")
    ytd_profit:    float = Field(default=0.0, ge=0)
    top_k:         int   = Field(default=5, ge=1, le=20)


class AskRequest(BaseModel):
    question: str       = Field(..., min_length=1, description="自由问题，如：研发费加计扣除怎么用？")
    history:  list[dict]= Field(default_factory=list, description="对话历史 [{role, content}]")
    top_k:    int       = Field(default=5, ge=1, le=15)


# ── RAG availability guard ────────────────────────────────────────────────────

def _require_rag() -> None:
    """Raise HTTP 503 if chromadb is not installed."""
    from rag.chroma_store import _CHROMADB_AVAILABLE
    if not _CHROMADB_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail="RAG 功能不可用：chromadb 未安装。请先安装 C++ Build Tools 后执行 pip install chromadb。",
        )


# ── Helpers ────────────────────────────────────────────────────────────────────

def _build_slice(body: SliceIn):
    """Convert SliceIn request model → StrategySlice domain object."""
    from rag.schema import StrategySlice, SliceMetadata, ProfitRange
    pr = body.metadata.profit_range
    meta = SliceMetadata(
        applicable_taxpayer = body.metadata.applicable_taxpayer,
        applicable_industry = body.metadata.applicable_industry,
        region_scope        = body.metadata.region_scope,
        applicable_regions  = body.metadata.applicable_regions,
        profit_range        = ProfitRange(
            min=float(pr.get("min", 0)),
            max=float(pr.get("max", 99_999_999)),
        ),
        optimal_timing = body.metadata.optimal_timing,
        valid_from     = body.metadata.valid_from,
        valid_until    = body.metadata.valid_until,
        source_doc     = body.metadata.source_doc,
        confidence     = body.metadata.confidence,
    )
    return StrategySlice(
        strategy_id        = body.strategy_id,
        title              = body.title,
        scenario           = body.scenario,
        core_content       = body.core_content,
        metadata           = meta,
        trigger_keywords   = body.trigger_keywords,
        action_suggestions = body.action_suggestions,
        risk_notes         = body.risk_notes,
    )


def _upsert_slice(body: SliceIn) -> dict:
    """Embed and upsert one slice into ChromaDB. Returns summary dict."""
    from rag.embedder import Embedder
    from rag.chroma_store import ChromaStore

    sl      = _build_slice(body)
    embedder = Embedder()
    store    = ChromaStore()
    vector   = embedder.embed_one(sl.embed_text())
    store.upsert([sl], [vector])
    return {
        "strategy_id": sl.strategy_id,
        "title":       sl.title,
        "embed_chars": len(sl.embed_text()),
    }


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/stats")
def get_stats() -> Any:
    """返回知识库统计信息。"""
    _require_rag()
    from rag.chroma_store import ChromaStore
    store = ChromaStore()
    return {
        "total_slices":    store.count(),
        "collection_name": __import__("config.settings", fromlist=["CHROMA_COLLECTION"]).CHROMA_COLLECTION,
        "chroma_path":     __import__("config.settings", fromlist=["CHROMA_PATH"]).CHROMA_PATH,
    }


@router.get("/slices")
def list_slices() -> Any:
    """列出知识库中所有切片的 ID。"""
    _require_rag()
    from rag.chroma_store import ChromaStore
    store = ChromaStore()
    ids = store.get_all_ids()
    return {"count": len(ids), "ids": sorted(ids)}


@router.post("/slices", status_code=201)
def create_slice(body: SliceIn) -> Any:
    """
    新增单个策略切片并向量化入库。
    若 strategy_id 已存在则覆盖更新（ChromaDB upsert 语义）。
    """
    try:
        result = _upsert_slice(body)
    except Exception as exc:
        logger.exception("Failed to upsert slice %s", body.strategy_id)
        raise HTTPException(status_code=500, detail=f"切片入库失败: {exc}") from exc
    logger.info("Slice created/updated via API: %s", body.strategy_id)
    return {"status": "ok", **result}


@router.put("/slices/{strategy_id}")
def update_slice(strategy_id: str, body: SliceIn) -> Any:
    """全量替换指定 strategy_id 的切片（重新向量化）。"""
    if body.strategy_id != strategy_id:
        raise HTTPException(
            status_code=422,
            detail="URL 中的 strategy_id 与请求体中的 strategy_id 不一致",
        )
    try:
        result = _upsert_slice(body)
    except Exception as exc:
        logger.exception("Failed to update slice %s", strategy_id)
        raise HTTPException(status_code=500, detail=f"切片更新失败: {exc}") from exc
    logger.info("Slice updated via API: %s", strategy_id)
    return {"status": "ok", **result}


@router.delete("/slices/{strategy_id}", status_code=200)
def delete_slice(strategy_id: str) -> Any:
    """从知识库中删除指定切片。"""
    _require_rag()
    from rag.chroma_store import ChromaStore
    store = ChromaStore()
    existing = store.get_all_ids()
    if strategy_id not in existing:
        raise HTTPException(status_code=404, detail=f"切片 '{strategy_id}' 不存在")
    store.delete(strategy_id)
    logger.info("Slice deleted via API: %s", strategy_id)
    return {"status": "ok", "deleted": strategy_id}


@router.post("/reload")
def reload_knowledge() -> Any:
    """
    从 rag/knowledge/ 下所有 JSON 文件重新加载知识库（等同运行 seed_loader）。
    已有切片会覆盖更新（幂等），新增切片会自动入库。
    """
    try:
        from rag.seed_loader import load_all
        stats = load_all(dry_run=False)
    except Exception as exc:
        logger.exception("Knowledge reload failed")
        raise HTTPException(status_code=500, detail=f"知识库重载失败: {exc}") from exc
    logger.info("Knowledge base reloaded via API: %s", stats)
    return {"status": "ok", **stats}


@router.post("/ask")
def ask_advisor(
    body: AskRequest,
    db:   Session = Depends(get_db),
) -> Any:
    """
    AI 财税顾问自由问答。
    - 先用 RAG 检索相关政策（Layer 1 硬过滤 + Layer 2 语义匹配）
    - 将政策上下文 + 对话历史注入 LLM，用自然语言回答
    - 返回 answer（纯文本）和 sources（引用的政策列表）
    """
    from models.enterprise_profile import EnterpriseProfile
    from rag.retriever import TaxStrategyRetriever, RetrievalContext
    from ai.llm_client import LLMClient, LLMClientError
    from ai.advisor_prompts import build_advisor_context

    # 读取激活企业档案（可选，无档案时退化为通用检索）
    profile = db.query(EnterpriseProfile).filter(EnterpriseProfile.is_active == 1).first()

    # RAG 检索
    retriever = TaxStrategyRetriever()
    ctx = RetrievalContext(
        query_text    = body.question,
        taxpayer_type = profile.tax_payer_type if profile else "ALL",
        industry_code = profile.industry_code  if profile else "ALL",
        province      = (profile.province or "") if profile else "",
        city          = (profile.city     or "") if profile else "",
        top_k         = body.top_k,
    )
    try:
        hits = retriever.retrieve(ctx)
    except Exception as exc:
        logger.warning("RAG retrieval failed for advisor: %s", exc)
        hits = []

    rag_context = build_advisor_context(hits)

    # LLM 回答
    llm = LLMClient()
    try:
        answer = llm.answer_tax_question(body.question, rag_context, body.history)
    except LLMClientError as exc:
        raise HTTPException(status_code=503, detail=f"AI 服务暂时不可用: {exc}") from exc

    sources = [
        {
            "strategy_id":   h.strategy_id,
            "title":         h.title,
            "source_doc":    h.source_doc,
            "similarity":    h.similarity_score,
            "optimal_timing": h.optimal_timing,
        }
        for h in hits
    ]

    logger.info("Advisor Q&A: question_len=%d hits=%d answer_len=%d",
                len(body.question), len(hits), len(answer))
    return {"answer": answer, "sources": sources}


@router.post("/search")
def search_slices(body: SearchRequest) -> Any:
    """
    语义检索接口（调试/测试用）。
    返回最相关的策略切片列表，可用于验证知识库检索效果。
    """
    from rag.retriever import TaxStrategyRetriever, RetrievalContext

    retriever = TaxStrategyRetriever()
    ctx = RetrievalContext(
        query_text    = body.query,
        taxpayer_type = body.taxpayer_type,
        industry_code = body.industry_code,
        province      = body.province,
        city          = body.city,
        ytd_profit    = body.ytd_profit,
        top_k         = body.top_k,
    )
    try:
        hits = retriever.retrieve(ctx)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"检索失败: {exc}") from exc

    return {
        "query":  body.query,
        "count":  len(hits),
        "hits": [
            {
                "strategy_id":    h.strategy_id,
                "title":          h.title,
                "similarity":     h.similarity_score,
                "confidence":     h.confidence,
                "optimal_timing": h.optimal_timing,
                "source_doc":     h.source_doc,
                "core_content":   h.core_content[:300],
                "action_suggestions": h.action_suggestions,
                "risk_notes":     h.risk_notes,
            }
            for h in hits
        ],
    }
