"""
AgentLedger RAG — Strategy Slice Schema

Each "slice" is one atomic tax strategy unit stored in ChromaDB.
The text field is used for semantic embedding; metadata fields are
used for hard pre-filtering before similarity ranking.

How to add a new slice
──────────────────────
1. Open the appropriate JSON file under rag/knowledge/:
     national/  → policies that apply nationwide
     industry/  → sector-specific policies
     regional/  → city or province-specific policies

2. Append a new object following the StrategySlice structure below.
   Mandatory fields: strategy_id, title, scenario, core_content, metadata
   Optional  fields: trigger_keywords, action_suggestions, risk_notes

3. Run the seed loader to push new slices into ChromaDB:
     python -m rag.seed_loader --incremental

4. The retriever picks up new slices immediately on next query.

Field reference
───────────────
strategy_id         Unique ID, format: <CATEGORY>-<NNN>
                    e.g. CIT-001, VAT-023, REG-SZ-005
title               Short name shown on the boss decision card
trigger_keywords    Chinese keywords that help coarse matching
scenario            One-sentence description of when this applies
core_content        The actual policy substance (quoted numbers, rates, limits)
action_suggestions  Concrete steps the company should take
risk_notes          Common pitfalls or compliance traps (optional)

metadata.applicable_taxpayer  List from: ["SMALL_SCALE","GENERAL","ALL"]
metadata.applicable_industry  List of industry codes, or ["ALL"]
metadata.region_scope         "NATIONAL" | "PROVINCIAL" | "CITY"
metadata.applicable_regions   [] for national; ["广东省"] or ["深圳市"] for local
metadata.profit_range         {"min": 0, "max": 99999999} in yuan (0 = no limit)
metadata.optimal_timing       "Q1" | "Q2" | "Q3" | "Q4" | "ANY"
metadata.valid_from           "YYYY-MM-DD"
metadata.valid_until          "YYYY-MM-DD"  (use "2099-12-31" if open-ended)
metadata.source_doc           Official document number, e.g. "财税〔2023〕6号"
metadata.confidence           0.0–1.0  (1.0 = verified; 0.7 = estimated/inferred)
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ProfitRange:
    min: float = 0.0
    max: float = 99_999_999.0


@dataclass
class SliceMetadata:
    applicable_taxpayer:  list[str]    # ["SMALL_SCALE","GENERAL"] or ["ALL"]
    applicable_industry:  list[str]    # ["ALL"] or ["制造业","科技"]
    region_scope:         str          # "NATIONAL" | "PROVINCIAL" | "CITY"
    applicable_regions:   list[str]    # [] for national
    profit_range:         ProfitRange
    optimal_timing:       str          # "Q1"..."Q4" | "ANY"
    valid_from:           str          # "YYYY-MM-DD"
    valid_until:          str          # "YYYY-MM-DD"
    source_doc:           str          # official document number
    confidence:           float = 1.0


@dataclass
class StrategySlice:
    strategy_id:        str
    title:              str
    scenario:           str
    core_content:       str
    metadata:           SliceMetadata
    trigger_keywords:   list[str]      = field(default_factory=list)
    action_suggestions: list[str]      = field(default_factory=list)
    risk_notes:         str            = ""

    def embed_text(self) -> str:
        """
        The text that gets vectorised.
        Combines title + scenario + core_content + keywords for richer semantics.
        """
        kw = " ".join(self.trigger_keywords)
        return (
            f"{self.title}\n"
            f"适用场景：{self.scenario}\n"
            f"政策要点：{self.core_content}\n"
            f"关键词：{kw}"
        )

    def to_chroma_metadata(self) -> dict[str, Any]:
        """Flatten metadata into a ChromaDB-compatible flat dict."""
        m = self.metadata
        return {
            "strategy_id":           self.strategy_id,
            "title":                 self.title,
            "region_scope":          m.region_scope,
            "applicable_regions":    ",".join(m.applicable_regions),   # stored as CSV
            "applicable_taxpayer":   ",".join(m.applicable_taxpayer),
            "applicable_industry":   ",".join(m.applicable_industry),
            "profit_min":            m.profit_range.min,
            "profit_max":            m.profit_range.max,
            "optimal_timing":        m.optimal_timing,
            "valid_from":            m.valid_from,
            "valid_until":           m.valid_until,
            "source_doc":            m.source_doc,
            "confidence":            m.confidence,
            "action_suggestions":    " | ".join(self.action_suggestions),
            "risk_notes":            self.risk_notes,
        }


def slice_from_dict(d: dict) -> StrategySlice:
    """Deserialise a JSON dict (from knowledge/*.json) into a StrategySlice."""
    m = d["metadata"]
    pr = m.get("profit_range", {})
    meta = SliceMetadata(
        applicable_taxpayer = m["applicable_taxpayer"],
        applicable_industry = m["applicable_industry"],
        region_scope        = m["region_scope"],
        applicable_regions  = m.get("applicable_regions", []),
        profit_range        = ProfitRange(
            min=float(pr.get("min", 0)),
            max=float(pr.get("max", 99_999_999)),
        ),
        optimal_timing = m.get("optimal_timing", "ANY"),
        valid_from     = m["valid_from"],
        valid_until    = m["valid_until"],
        source_doc     = m["source_doc"],
        confidence     = float(m.get("confidence", 1.0)),
    )
    return StrategySlice(
        strategy_id        = d["strategy_id"],
        title              = d["title"],
        scenario           = d["scenario"],
        core_content       = d["core_content"],
        metadata           = meta,
        trigger_keywords   = d.get("trigger_keywords", []),
        action_suggestions = d.get("action_suggestions", []),
        risk_notes         = d.get("risk_notes", ""),
    )
