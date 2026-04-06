# services/graph_engine — Graph RAG 防腐层（Anti-Corruption Layer）
#
# 所有具体图引擎实现必须继承 BaseGraphRetriever（base.py）。
# 业务层只通过 BaseGraphRetriever 接口交互，不直接 import 具体实现。
