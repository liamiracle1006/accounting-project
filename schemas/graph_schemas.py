"""
AgentLedger V4.0 — Graph RAG 标准数据契约 (Sprint 2.2 Graph ACL)

防腐层（Anti-Corruption Layer）核心数据契约。
LLM 业务层（ai_voucher_service 等）只允许接触 GraphSlice，
绝对不允许直接操作 NetworkX 对象或执行 SQL。

架构原则：
  业务层 → GraphSlice（本文件）→ BaseGraphRetriever（graph_engine/base.py）
       ↕                              ↕
  LLM / Prompt                  具体实现（NetworkX / Neo4j / NebulaGraph）

未来迁移路径：
  当前实现  → services/graph_engine/networkx_retriever.py (NetworkX + SQLAlchemy)
  生产迁移  → services/graph_engine/neo4j_retriever.py    (Neo4j)
  只需替换注入实现，业务层零改动。
"""
from typing import Any, Dict, List
from pydantic import BaseModel, Field


class GraphSlice(BaseModel):
    """
    图切片：供 LLM 消费的纯净上下文。

    由 BaseGraphRetriever.get_subgraph_slice() 填充，
    传递给 ai_voucher_service（业务层）后拼装 Few-Shot Prompt。

    字段说明
    --------
    matched_nodes
        命中的科目节点列表。每个 dict 包含图节点的核心属性，如：
        {"subject_code": "6602", "subject_name": "管理费用",
         "category": "损益", "balance_direction": "借",
         "frequency": 12}       ← 该账套历史使用频率

    causal_edges
        节点间的因果/关联边列表。每个 dict 描述一条有向边，如：
        {"from": "1002", "to": "6602", "relation": "payment_method→expense",
         "weight": 0.85}

    confidence_score
        本次图谱检索的置信度（0.0-1.0）。
        由具体引擎实现根据路径长度、命中率、历史频次等综合计算。
        业务层可用此值决定是否追加 fallback 提示词。

    context_summary
        预处理好的、可直接塞入 LLM Prompt 的纯文本摘要。
        格式示例：
          "根据历史记录，该类费用最常用科目为 6602（管理费用），
           贷方通常为 1002（银行存款），历史匹配置信度 87%。"
    """
    matched_nodes:    List[Dict[str, Any]] = Field(
        default_factory=list,
        description="命中的历史高频科目节点列表"
    )
    causal_edges:     List[Dict[str, Any]] = Field(
        default_factory=list,
        description="节点间的因果/关联边（借贷配对历史）"
    )
    confidence_score: float = Field(
        default=0.0,
        ge=0.0, le=1.0,
        description="图谱检索置信度（0.0-1.0）"
    )
    context_summary:  str = Field(
        default="",
        description="供 LLM 直接使用的纯文本上下文摘要"
    )
