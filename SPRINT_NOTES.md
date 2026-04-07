# AgentLedger V4.0 — Sprint 进度笔记

Branch: `claude/gemini-numeric-engine-UmAem`

---

## 已完成

### Sprint 0 — 多租户地基 ✅
TenantMixin + TenantContext + SQLAlchemy 拦截器（tenant_id + account_set_id 双层隔离）

### Sprint 1 — 基础会计功能 ✅
OperationalRecord + VoucherHeader + VoucherLine 雏形

### Sprint 2.1 — 科目体系 ✅
SystemSubject + TenantSubject + SubjectService（科目树 CRUD、编码规范校验）

### Sprint 2.2 — 期初余额 ✅
InitialBalance + `complete_account_setup()`（试算平衡 + 1901 海绵配平 + 账套 ACTIVE）

### Sprint 2.3 — 旧账导入 ✅ (commit: `685defa`)
ImportSession + ImportStaging + ImportService
- Phase 1：会话创建 + 旧系统导出向导
- Phase 2：Pandas 物理清洗 + LLM 表头映射 → ImportStaging
- Phase 3：AI 科目匹配（精确匹配 / LLM 高置信度自动确认 / 人工复核）
- Phase 4：CONFIRMED 行 → InitialBalance + `complete_account_setup()`（复用海绵）

### Sprint 3.1 — AI 凭证生成引擎 ✅ (commit: `8c7c1b0`)

**架构：关系型存储 + 内存 JSON 组装 + Agentic Tool Call（彻底放弃向量数据库）**

#### 新建文件

| 文件 | 作用 |
|---|---|
| `models/tenant_habit_rule.py` | DAG 模板表：存储账套业务习惯规则（关键词 + rule_json） |
| `ai/voucher_prompts.py` | 凭证生成 System Prompt：约束 LLM 必须用工具查科目、必须借贷平衡 |
| `ai/agent_runner.py` | 多轮 Tool Calling 循环引擎（MAX_TURNS=8，安全防死循环） |
| `services/graph_engine/subject_retriever.py` | `drill_down_subject` 工具：LLM 像文件管理器一样逐层下钻科目树 |
| `services/graph_engine/habit_retriever.py` | 关键词 DAG 匹配 + SQL 余额嗅探（区分新业务 vs 后续流转） |
| `services/ai_voucher_service.py` | 双层 Pipeline 编排 + 悬账断路器（挂 1221/2241，锁 DRAFT_PENDING_REVIEW） |
| `schemas/voucher_ai_schemas.py` | GenerateVoucherInput / VoucherDraftOut / HabitRuleOut |
| `api/voucher_ai_routes.py` | 5 个端点（见下） |

#### 修改文件
- `ai/llm_client.py`：新增 `tool_call_completion()` 支持原生 Function Calling
- `models/__init__.py`：注册 TenantHabitRule
- `main.py`：注册 voucher_ai_router

#### API 端点（`/api/voucher-ai`）

```
POST   /generate                 — AI 生成凭证草稿（双层 Pipeline 核心）
GET    /habit-rules              — 列出 DAG 业务习惯规则
POST   /habit-rules              — 创建规则
PUT    /habit-rules/{rule_id}    — 更新规则
DELETE /habit-rules/{rule_id}    — 删除规则
```

#### Sprint 3.1 边界
**只生成凭证 JSON 草稿，不写入数据库。** Sprint 3.2 的"确认入账"端点负责落库。

#### 回家验证命令
```bash
python3 -c "
from models.tenant_habit_rule import TenantHabitRule
from ai.agent_runner import AgentRunner
from ai.llm_client import LLMClient
from services.graph_engine import SubjectRetriever, HabitRetriever, DRILL_DOWN_TOOL_DEF
from services.ai_voucher_service import AIVoucherService, SUSPENSE_DEBIT_CODE
from schemas.voucher_ai_schemas import GenerateVoucherInput, VoucherDraftOut
from api.voucher_ai_routes import router
print('Sprint 3.1 imports OK')
"
```

---

### Sprint 3.2 — 凭证管理 CRUD（柠檬云凭证管理复刻）✅

#### 新建文件

| 文件 | 作用 |
|---|---|
| `schemas/voucher_schemas.py` | 凭证 CRUD 全量 Schema（输入/输出/查询参数/分页/断号整理） |
| `services/voucher_service.py` | 凭证完整生命周期：列表、新建、更新、软删除、还原、状态机、断号整理、确认入账 |
| `api/voucher_routes.py` | 12 个 REST 端点（见下） |

#### 修改文件
- `models/voucher_header.py`：新增 `voucher_number`、`voucher_word`、`is_deleted`、`creator_id`
- `services/audit_guard.py`：开放 POSTED → PENDING_REVIEW 通道（反审核），其余 POSTED 降级仍阻断
- `schemas/voucher_ai_schemas.py`：新增 `ConfirmLineIn`、`ConfirmVoucherInput`（Sprint 3.1→3.2 桥梁）
- `api/voucher_ai_routes.py`：新增 `POST /api/voucher-ai/confirm`
- `main.py`：注册 voucher_router

#### API 端点（`/api/vouchers`）

```
GET    /                        — 凭证列表（多维过滤 + 分页）
GET    /trash                   — 回收站列表
GET    /{id}                    — 凭证详情（含分录行）
POST   /                        — 手工新建凭证
PUT    /{id}                    — 更新凭证（DRAFT/REJECTED 状态）
POST   /{id}/review             — 审核（→ POSTED）
POST   /{id}/unreview           — 反审核（POSTED → PENDING_REVIEW）
DELETE /{id}                    — 软删除（DRAFT 状态移入回收站）
POST   /{id}/restore            — 从回收站还原
POST   /reorganize              — 断号整理（指定期间重新顺序编号）
POST   /api/voucher-ai/confirm  — AI 草稿确认入账（3.1→3.2 桥梁）
```

#### 架构要点
- `record_id` FK 由 Service 内部自动创建 `OperationalRecord`（raw_text=业务描述或摘要），对调用方透明
- `auxiliary_data` dict（AI 草稿格式）→ `auxiliary_entity_id` FK，通过 upsert `AuxiliaryEntity` 实现
- 状态机：DRAFT ↔ PENDING_REVIEW ↔ POSTED（AuditGuard 保护），REJECTED 可重新提交
- 软删除不触发 AuditGuard `before_delete` 事件（仅标记 `is_deleted=True`）
- 断号整理在单事务内完成，失败自动回滚

---

## 待做

### Sprint 3.2 — 凭证管理 CRUD（已完成，见上）

**目标：** 为 VoucherHeader + VoucherLine 实现完整的后台管理接口。

**已完成，见 Sprint 3.2 章节。**

---

### Sprint 3.3 — 凭证模板

**目标：** 可复用的凭证模板库（类似柠檬云"常用凭证"快捷录入）

**需新建：**
- `models/voucher_template.py` — 模板头 + 模板行
- `services/voucher_template_service.py`
- `api/voucher_template_routes.py`

---

## 架构备忘

### 悬账断路器科目
- `1221` 其他应收款-待查明（借方差额）
- `2241` 其他应付款-待查明（贷方差额）
- 触发时状态锁定为 `DRAFT_PENDING_REVIEW`，必须人工复核

### DAG rule_json 标准格式
```json
{
  "nodes": [
    {"id": "N1", "label": "首付挂长期待摊", "subject_hint": "1801", "action": "首次付款时执行"},
    {"id": "N2", "label": "次月起每月摊销", "subject_hint": "6602", "action": "次月1日起每月执行"}
  ],
  "edges": [
    {"from": "N1", "to": "N2", "condition": "次月1日起按月摊销，至金额归零"}
  ]
}
```
