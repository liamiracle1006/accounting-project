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

### Sprint 3.3 — 期末引擎与自动化履带 ✅

**架构：纯财务数学确定性引擎（不依赖 LLM）**

#### 新建文件

| 文件 | 作用 |
|---|---|
| `schemas/period_schemas.py` | PeriodOut / TransferPnLResult / CloseResult / UncloseResult |
| `api/period_routes.py` | 4 个期间管理端点 |

#### 修改文件
- `services/period_closing_service.py`：完整重写（修复多租户Bug + 拆分三大模块 + 移除内部 commit）
- `services/voucher_service.py`：新增 `_check_period_open()`，注入全部写操作
- `main.py`：注册 `period_router`

#### 三大模块

**模块一：全局期间锁（`_check_period_open`）**
- 注入 VoucherService 的 `create_voucher` / `update_voucher` / `soft_delete` / `review` / `unreview` / `confirm_ai_draft`
- 凭证日期所属期间 status == CLOSED → 抛 403，禁止所有写操作
- 期间记录不存在则默认允许（兼容未建期间的账套）

**模块二：结转本期损益（`transfer_pnl`）**
- 幂等防重：`closing_voucher_id` 已存在则先软删除旧凭证再重新生成
- 扫描 `INCOME_ACCOUNTS`（6001/6051/6101/6111/6117/6301）+ `EXPENSE_ACCOUNTS`（6401-6801）
- 直接构造 ORM，凭证状态直接设为 `POSTED`，`voucher_word="转"`
- 12月年结：额外计算全年 4103 本年利润余额，追加借 4103/贷 4104 分录实现年末清零
- 不修改 `period.status`（仍为 OPEN），仅更新 `closing_voucher_id`

**模块三：守门员结账（`close_period`）**
1. 断号自动修复：静默调用 `VoucherService.reorganize()`
2. 未审核拦截：检查 DRAFT/PENDING_REVIEW 凭证 → 存在则 400
3. 损益未结平拦截：扫描 6xxx 期末余额不为零 → 400（"请先执行结转损益"）
4. 全量试算平衡兜底：POSTED 凭证借方 ≠ 贷方 → 500 系统告警
5. 全部通过 → `status=CLOSED`，自动创建下期 OPEN

**反结账（`unclose_period`）**
- 仅允许最后一个 CLOSED 期间回退
- 软删除 `closing_voucher_id` 对应的结转凭证
- 清空 `closed_at / closed_by / closing_voucher_id`，status 回退 OPEN
- 若下期 period 无凭证则物理删除该空白记录

#### API 端点（`/api/period`）

```
GET    /                              — 列出所有会计期间（按年月倒序，最多24条）
POST   /{year}/{month}/transfer-pnl   — 结转本期损益（幂等）
POST   /{year}/{month}/close          — 结账（四道守门员防线）
POST   /{year}/{month}/unclose        — 反结账（仅最后一个CLOSED期间）
```

#### 验证命令
```bash
python3 -c "
from models.accounting_period import AccountingPeriod, PeriodStatus
from schemas.period_schemas import PeriodOut, TransferPnLResult, CloseResult, UncloseResult
from services.period_closing_service import (
    PeriodClosingService, PeriodClosingError,
    PeriodAlreadyClosedError, PeriodNotClosedError,
)
from services.voucher_service import VoucherService
from api.period_routes import router
print('Sprint 3.3 imports OK')
print('PeriodStatus:', PeriodStatus.OPEN, PeriodStatus.CLOSED)
"
```

---

### Sprint 3.4 — Graph RAG 双轨推荐引擎 + 动态分叉学习 ✅

**架构升级：DAG Edge 扩展 + 确定性置信度 + 双轨制推荐 + 异步学习钩子**

#### 新建文件

| 文件 | 作用 |
|---|---|
| `schemas/habit_schemas.py` | HabitRule CRUD Schema（从 voucher_ai_schemas 拆分，保持职责单一） |
| `services/habit_service.py` | 动态分叉学习算法：`learn_from_voucher_async()`，独立 Session，异常全吞 |

#### 修改文件

| 文件 | 变更内容 |
|---|---|
| `services/graph_engine/habit_retriever.py` | `find_matching_rules()` 返回体新增 `rule_id`（学习溯源用） |
| `services/ai_voucher_service.py` | 完整重写：`generate_voucher()` → `DualTrackResponse`；新增 `calculate_confidence()`、`_try_build_track_a()`、`_reconstruct_draft_from_edge()`、`_extract_amount()` |
| `schemas/voucher_ai_schemas.py` | 新增 `RecommendationItem`、`DualTrackResponse`；`ConfirmVoucherInput` 新增 `habit_rule_id` 字段；移除 HabitRule Schema（迁至 habit_schemas） |
| `api/voucher_ai_routes.py` | `/generate` 返回类型改为 `DualTrackResponse`；`/confirm` 增加 `BackgroundTasks` 参数，确认后异步触发学习钩子 |

#### 核心设计

**DAG Edge Sprint 3.4 扩展字段**（向后兼容，旧 edge 无这些字段时为冷启动）
```json
{
  "from": "N1", "to": "N2",
  "condition": "...",
  "weight": 5,
  "last_used_at": "2025-03-15T08:00:00+00:00",
  "context_features": {
    "subject_combo":  ["1001-DEBIT", "6602-CREDIT"],
    "line_templates": [
      {"subject_code": "6602", "direction": "DEBIT",  "ratio": 1.0, "memo_hint": "摊销"},
      {"subject_code": "1001", "direction": "CREDIT", "ratio": 1.0, "memo_hint": null}
    ],
    "min_amount": 3000.0,
    "max_amount": 4200.0
  }
}
```

**确定性三档置信度（无 ML，无向量，纯规则）**
| 置信度 | 条件 | 处理 |
|--------|------|------|
| HIGH   | `weight > 3` 且 `amount ∈ [min_amount, max_amount]` | 可进批量自动处理 |
| MEDIUM | Track A 存在但不满足 HIGH（样本少/金额突变） | 人工扫一眼 |
| LOW    | 无 Track A（纯 Track B 冷启动） | 绝不静默入库 |

**双轨推荐响应结构**
```
DualTrackResponse.recommendations:
  [0] Track A（HABIT）— 历史习惯重建草稿，可能不存在（冷启动）
  [1] Track B（AI_RULE）— LLM 零样本推理草稿，永远存在
```

**动态分叉学习算法（habit_service._learn_track_a）**
- 命中（subject_combo 集合完全一致）→ `weight++`，扩宽金额区间 `[min, max]`
- 未命中（新科目组合）→ 追加新 edge（绝不删除/覆盖旧 edge，新枝发芽原则）

**Track B 学习路径（habit_service._learn_track_b）**
- 从 description 提取关键词 → 扫描现有规则关键词集合
- 有交集 → 复用旧规则，调用 `_learn_track_a` 更新 edge
- 无交集 → 自动创建全新 `TenantHabitRule`（rule_name = description[:40]）

**BackgroundTask Session 安全设计**
- `learn_from_voucher_async` 使用独立 `SessionLocal()`，绝不复用路由层 Session
- 所有异常均被 `try-except` 吞掉，绝不阻塞主流程凭证保存
- `finally: db.close()` 保证连接归还

#### API 端点变更（`/api/voucher-ai`）

```
POST   /generate    — 返回体：DualTrackResponse（含 Track A + Track B 双推荐）
POST   /confirm     — 请求体新增 habit_rule_id；确认后异步触发 learn_from_voucher_async
```
Habit CRUD 端点（`/habit-rules`）保持不变。

---

### Sprint 3.5 — 全渠道批处理与三色漏斗异步流水线 ✅

**架构：解耦解析层（Excel/Vision）+ 批处理状态机 + 三色漏斗异步引擎**

#### 新建文件

| 文件 | 作用 |
|---|---|
| `schemas/batch_schemas.py` | `StandardReceiptItem`（统一中间态）+ 全部批处理 Request/Response Schema |
| `models/batch_task.py` | `BatchImportTask`（任务级状态机）+ `BatchImportRecord`（票据级记录），均继承 TenantMixin |
| `services/excel_parser_service.py` | pandas 双引擎（xlsx/xls/csv），两轮列名嗅探（精确匹配 → 子串模糊匹配） |
| `services/vision_service.py` | 复用 `ocr_service._call_vision_llm()`，注入批量票据专用 Prompt，输出 `StandardReceiptItem` |
| `services/batch_service.py` | `create_batch_task()` + 三色漏斗 `run_batch_pipeline()`（独立 Session，显式参数） |
| `api/batch_routes.py` | 4 个端点（parse-preview / execute / progress / results） |

#### 修改文件

| 文件 | 变更内容 |
|---|---|
| `services/ocr_service.py` | `_call_vision_llm()` 新增 `prompt: str \| None = None` 参数；自定义 Prompt 时无 API Key 返回 `"[]"`；max_tokens 随 prompt 类型动态调整（512/1024） |
| `models/__init__.py` | 追加 `BatchImportTask`、`BatchImportRecord` |
| `database/connection.py` | `init_db()` 导入列表加入 `batch_task` |
| `main.py` | 注册 `batch_router`（带 JWT 鉴权） |

#### 核心设计

**统一中间态 StandardReceiptItem**
```python
class StandardReceiptItem(BaseModel):
    date:         date           # 票据日期
    amount:       float          # 金额（正数，元）
    counterparty: Optional[str]  # 对方单位
    summary:      str            # 业务摘要/品名
    file_url:     Optional[str]  # 原始文件 URL（可选追溯）
```

**文件路由规则（parse-preview 自动分流）**
| 文件类型 | 引擎 | 说明 |
|---------|------|------|
| `.xlsx / .xls / .csv` | Excel 引擎 | pandas 解析，两轮列名嗅探 |
| `.jpg / .png / .webp / .pdf` | Vision 引擎 | `_call_vision_llm()` + 批量票据 Prompt |
| 混合上传 | MIXED | 各文件独立路由，结果合并 |

**三色漏斗逻辑（run_batch_pipeline）**
| 颜色 | 触发条件 | 处理 |
|------|---------|------|
| 🟢 绿灯 | confidence == HIGH | 正常入库，`needs_review=False` |
| 🟡 黄灯 | confidence == MEDIUM 或 LOW | 同样入库，`needs_review=True`，前端标黄 |
| 🔴 红灯 | 任何 Exception 抛出 | 不生成凭证，`error_msg` 写入 Record |

**关键实现决策**
- **金额拼接**：`description = f"{counterparty} {summary} {amount}元"` → 解决 `_extract_amount()` 正则无法从纯文字里提取金额的冲突（复用 Sprint 3.4 引擎，零侵入）
- **置信度取首位**：`best = response.recommendations[0]`（Track A 在前；冷启动时首位是 Track B，天然 LOW）
- **`needs_review` 仅在 BatchImportRecord**：VoucherHeader 保持标准 DRAFT 状态，零 DB 迁移
- **显式参数传递**：`run_batch_pipeline(task_id, tenant_id, account_set_id, creator_id, voucher_word)`，不依赖任何 ContextVar
- **防熔断**：`time.sleep(0.5)` 间隔（第一条跳过），防 API 速率限制（HTTP 429）
- **单条隔离**：红灯 `db.rollback()` 后重新取对象更新 `error_msg`，不影响其余记录

**BatchImportTask 状态机**
```
PENDING → PROCESSING → COMPLETED
                     ↘ FAILED（整批流水线崩溃时）
```

#### API 端点（`/api/batch`）

```
POST  /parse-preview              — 文件预解析（不写 DB），返回 JSON 数组供前端核对网格
POST  /execute                    — 提交核对后数据，创建任务 + 触发后台流水线（202 立即返回 task_id）
GET   /task/{task_id}/progress    — 实时进度轮询（status / total / success / error / needs_review 计数）
GET   /task/{task_id}/results     — 三色明细报告（success 列表 / needs_review 子集 / errors 列表）
```

---

---

### Sprint 3.6 — AI 规则控制台与沉淀闭环 ✅ (commit: `08c0543`)

**架构：前端沉淀弹窗 + 后端学习钩子打通完整 AI → 入账 → 学习闭环**

#### 核心实现（均在前端 React 组件）

| 功能 | 实现 |
|------|------|
| 习惯规则编辑修复 | 表格行新增 [编辑] 按钮；`_habitRulesCache` 缓存规则数据；`openHabitModal(id)` 从缓存预填字段；`saveHabitRule()` 自动分流 POST（新建）/ PUT（更新） |
| 权重列 | 规则表格新增"权重"列，提取 `rule_json.edges[*].weight` 最大值；weight ≥ 5 显示 🔥 橙色高亮 |
| 沉淀弹窗（核心） | `selectTrack()` 选轨时快照 `_aiOriginalLineCodes`；`confirmVoucher()` 入账前比对科目变化；有修改 → 弹沉淀弹窗；[是，更新规则并保存] → 保留 `habit_rule_id` 触发后端学习；[仅修改本次] → 强制 `habit_rule_id=null` 不污染 DAG |

#### 完整 AI 闭环
```
AI 生成草稿 → 财务人员选轨/修改 → 沉淀弹窗 → 确认入账
                                          ↓
                              habit_rule_id → 后端 BackgroundTask
                                          → learn_from_voucher_async()
                                          → DAG edge weight++ / 新枝发芽
```

---

### Sprint 3.x React 迁移 ✅ (commit: `69fc5d1`)

**架构：Vite 5 + React 18 + TypeScript strict + Tailwind CSS + Zustand + React Router v6**

将 `static/index.html`（5500+ 行单文件）完整迁移为现代化前端工程：

| 层 | 技术选型 |
|----|---------|
| 构建 | Vite 5，HMR 极速 |
| UI | React 18 + TypeScript strict |
| 路由 | React Router v6 + RequireAuth 权限守卫 |
| 状态 | Zustand（4 个 store：auth / voucher / batch / toast） |
| 样式 | Tailwind CSS v3 |
| API | 原生 fetch 封装，401 自动登出 |

**目录结构**：`frontend/src/` 按 Feature-Sliced 思路拆分，约 54 个文件：

```
api/          ← 15 个 API 模块（全强类型）
store/        ← 4 个 Zustand store
components/   ← 公共组件（Toast, Modal, Spinner, Sidebar 等）
features/     ← 20 个业务页面（按域拆分）
types/        ← 所有 API 类型（1:1 映射后端 schema）
```

---

## Epic 4.0 — 极速算盘与报表引擎 ✅

### Sprint 4.1 — 万能算盘引擎 + 科目余额表 ✅ (commit: `7827ebd`)

**架构：确定性六列余额引擎（InitialBalance + VoucherLine 双数据源，有符号中间值滚算）**

#### 新建文件

| 文件 | 作用 |
|------|------|
| `services/ledger_service.py` | `LedgerService.calculate_period_balances()` — 万能算盘核心引擎 |
| `frontend/src/features/reports/TrialBalancePage.tsx` | 科目余额表前端页面 |

#### 修改文件
- `api/report_routes.py`：新增 `GET /api/reports/trial-balance` 端点

#### 核心算法

**`TrialBalanceItem`（六列数据类）**
```python
@dataclass
class TrialBalanceItem:
    code, name, level, direction, parent_code
    opening_debit, opening_credit   # 期初余额
    current_debit, current_credit   # 本期发生额
    closing_debit, closing_credit   # 期末余额
    _opening_signed, _closing_signed  # 内部有符号值（父级滚算用）
```

**计算公式（有符号中间值，正=借，负=贷）**
```
yr_signed    = year_start_balance（正负取决于 balance_direction）
pre_signed   = yr_signed + Σ(pre_DEBIT) - Σ(pre_CREDIT)  ← 年初→期前
cur_delta    = Σ(cur_DEBIT) - Σ(cur_CREDIT)               ← 期内发生额
closing_sig  = pre_signed + cur_delta

# 最终拆回借/贷列：正值→借方；负值→贷方
```

**父级滚算（多级科目汇总）**
1. 叶节点直接计算
2. 父级 = Σ子级 `_closing_signed`，再拆回借/贷列
3. 全程有符号传递，不丢符号信息

**试算平衡断言**（后端执行）
- `Σopening_debit == Σopening_credit`
- `Σcurrent_debit == Σcurrent_credit`
- `Σclosing_debit == Σclosing_credit`
- 不平时返回 `balanced: false` + 警告，不报错（财务人员需感知）

#### 前端功能
- 期间选择器（`date_from` / `date_to`，YYYY-MM-DD）
- 六列表格：期初借/贷、本期借/贷、期末借/贷
- 科目层级缩进（`level * 12px`）
- 试算不平衡红色 Banner
- Excel 导出（`xlsx` 库）、打印按钮
- 零余额隐藏开关、最大层级过滤、科目范围过滤

#### API 端点

```
GET /api/reports/trial-balance
  ?date_from=YYYY-MM-DD
  &date_to=YYYY-MM-DD
  &max_level=2        ← 可选，限制科目层级
  &hide_zero=true     ← 可选，隐藏零余额
  &start_subject_code=1001  ← 可选，科目范围
  &end_subject_code=1999
```

---

### Sprint 4.2 — 穿透查账与明细账 ✅ (commit: `0be5e1e`)

**架构：Running Balance 逐笔流水引擎（复用 Sprint 4.1 同一算盘公式，严禁重复聚合）**

#### 新建文件

| 文件 | 作用 |
|------|------|
| `services/ledger_detail_service.py` | `LedgerDetailService.get_detailed_ledger()` — 逐笔余额引擎 |
| `frontend/src/features/reports/DetailedLedgerPage.tsx` | 明细账主页面（左主表 + 右快速切换面板） |
| `frontend/src/components/common/VoucherViewerModal.tsx` | 只读凭证弹窗（复用现有 Modal 组件） |

#### 修改文件
- `api/report_routes.py`：新增 `GET /api/reports/detailed-ledger` 端点
- `frontend/src/types/index.ts`：追加 `DetailedLedgerRow / Response / Params` 类型
- `frontend/src/api/reports.ts`：追加 `detailedLedger()` 调用
- `frontend/src/store/useReportStore.ts`：追加明细账状态（`dlRows / dlLoading / dlError`）
- `frontend/src/features/reports/TrialBalancePage.tsx`：科目名称添加下钻跳转
- `frontend/src/App.tsx`：新增 `/ledger` 路由
- `frontend/src/components/layout/Sidebar.tsx`：新增"明细账"导航项

#### Running Balance 算法（与 Sprint 4.1 完全相同的有符号公式）

```python
# ① 年初余额
yr_signed = year_start_balance（正负取决于 balance_direction）

# ② 期前发生额（年初 → date_from - 1）
opening_sig = yr_signed + pre_DEBIT - pre_CREDIT

# ③ 逐笔滚算（date_from → date_to，按日期/字号升序）
running = opening_sig
for line in current_rows:
    debit  = line.amount if DEBIT  else 0
    credit = line.amount if CREDIT else 0
    running += debit - credit      # DEBIT 恒 +，CREDIT 恒 −
    direction = "借" if running > 0 else "贷" if running < 0 else "平"
    balance   = abs(running)

# ④ 本年累计（年初 → date_to，单次聚合）
ytd = _aggregate_single(year_start, date_to)
```

**特殊行注入（后端组装，前端按 `row_type` 做样式）**

| row_type | 含义 | 背景 |
|----------|------|------|
| `opening` | 期初余额 | 蓝色 `bg-blue-50` |
| `transaction` | 实际凭证明细行 | 普通，hover 效果 |
| `period_total` | 本期合计 | 灰色 `bg-gray-100` |
| `ytd_total` | 本年累计 | 灰色 `bg-gray-100` |

#### 前端功能
- 日期选择 + 摘要关键字模糊搜索
- 右侧快速切换面板（搜索框 + 科目列表，`subjectsApi.tree()` 扁平化）
- 凭证字号可点击 → `VoucherViewerModal` 弹窗展示凭证全部明细行
- 科目余额表 → 点击科目名称 → 跳转明细账（URL 参数携带 `subject_code + date_from + date_to`）
- 打印按钮

#### API 端点

```
GET /api/reports/detailed-ledger
  ?subject_code=1002          ← 必填
  &date_from=YYYY-MM-DD
  &date_to=YYYY-MM-DD
  &keyword=差旅               ← 可选，摘要模糊搜索
```

---

### Sprint 4.3 — 资产负债表与利润表前端 ✅ (commit: `d13f7cc`)

**架构：后端已完备，本 Sprint 纯前端视图层**

> **关键决策**：后端 `services/report_service.py`（435行）和所有财务报表端点在早期 Epic 中已建立，直接复用。Gemini 方案中的"AI 公式生成"功能经评估后**不实施**——中国会计准则科目编码高度标准化，公式为确定性知识，AI 介入只增加误差风险，不增加价值。

#### 新建文件

| 文件 | 作用 |
|------|------|
| `frontend/src/features/reports/BalanceSheetPage.tsx` | 资产负债表（会企01表）前端页面 |
| `frontend/src/features/reports/IncomeStatementPage.tsx` | 利润表（会企02表）前端页面 |

#### 修改文件
- `frontend/src/types/index.ts`：追加 `BSLineItem / BalanceSheet / ISLineItem / IncomeStatement` 类型
- `frontend/src/api/reports.ts`：`balanceSheet() / incomeStatement()` 添加强类型泛型
- `frontend/src/App.tsx`：新增 `/balance-sheet`、`/income-statement` 路由
- `frontend/src/components/layout/Sidebar.tsx`：新增"资产负债表"、"利润表"导航项

#### 资产负债表（BalanceSheetPage）

**布局**：左右双拼（资产 | 负债及所有者权益），期末余额 + 年初余额两列

| 特性 | 实现 |
|------|------|
| 期间选择 | 年份输入 + 月份下拉，自动计算月末 `as_of` 日期 |
| 不平衡预警 | 红色 Banner，显示差额金额 |
| 合计行 | `is_total=true` → 加粗 + 灰色背景 |
| 零值显示 | 非合计行为 `—`，合计行强制显示数值 |

**后端接口**：`GET /api/reports/balance-sheet?as_of=YYYY-MM-DD`
- 返回：`assets[]`（资产方）、`liabilities[]`（负债方）、`equity[]`（权益方）、`balanced`、`diff`

#### 利润表（IncomeStatementPage）

**布局**：单列垂直阶梯式，本期金额 + 上期金额两列

| 特性 | 实现 |
|------|------|
| 期间选择 | 年份 + 月份，自动计算月初/月末 |
| 行缩进 | `减：` / `加：` 开头行左缩进（`pl-6`） |
| 负数显示 | 红色字体 |
| 关键行高亮 | 四、净利润 → 绿色背景加粗 |

**后端接口**：`GET /api/reports/income-statement?date_from=YYYY-MM-DD&date_to=YYYY-MM-DD`
- 返回：`items[]`（行项目），`prev_from/prev_to`（上期同区间）

#### 已有后端基础（零改动）

| 服务 | 内容 |
|------|------|
| `services/report_service.py` | 硬编码中国企业会计准则标准科目映射（1001-6899），资产负债表 + 利润表完整实现 |
| `GET /api/reports/balance-sheet` | 期末余额 + 年初余额，含 `balanced` 标志 |
| `GET /api/reports/income-statement` | 本期金额 + 上年同期金额 |
| `GET /api/reports/cash-flow` | 现金流量表（会企03表，间接法） |
| `GET /api/reports/equity-changes` | 所有者权益变动表（会企04表） |

### Sprint 4.4 — 报表验证工具（Excel → 计算报表 → diff 对比）✅

**目标：开发者用科目余额表 Excel 直接验证报表公式映射，无需数据库**

#### 新建文件

| 文件 | 作用 |
|---|---|
| `services/validation_service.py` | Excel 解析引擎（pandas）+ 报表计算 + diff 对比 |
| `api/validate_routes.py` | `POST /api/validate/trial-balance`（无 JWT 鉴权，开发测试用）|
| `database/seed_local.sql` | V4.0 兼容最小种子数据（tenant + account_set + 三个默认用户）|
| `database/seed_demo_v4.sql` | V4.0 兼容演示数据（星辰科技 2026 年 1-3 月，含 13 条凭证）|
| `DEV_SETUP.md` | 本地开发启动完整指南（MySQL 导入命令、启动顺序、默认账号）|

#### 修改文件

| 文件 | 变更内容 |
|---|---|
| `services/report_service.py` | 提取 `_map_balance_sheet()` / `_map_income_statement()` 为纯函数，不依赖 DB Session |
| `main.py` | 注册 `validate_router`（无鉴权）；注释掉未实现的 `account_set_routes`；补充 SPA catch-all 路由 |
| `schemas/batch_schemas.py` | 修复 Pydantic v2 字段名冲突：`date: date` → `from datetime import date as _date` |
| `.gitignore` | 补充 `node_modules/`、`frontend/dist/`、`chroma_db/` |

#### 核心设计

**Excel 解析流程（三层自适应，兼容各会计软件导出格式）**
```
1. _find_header_row()     — 扫描前 30 行，找到含 ≥2 个关键词的列头行（不依赖固定行号）
2. _try_load_excel()      — 单行列头，skiprows = 0~14 逐一尝试
3. _try_load_excel_multiheader() — 双行合并列头（如荆鹏/HBJP），skiprows + header=[0,1]，
                                    合并 tuple 列名为 "期初余额借方"/"本期发生额贷方" 等
列名识别用正则，不做精确匹配（"科目编码"/"科目代码"/"code" 均可识别）
```

**API 请求（multipart form）**
```
POST /api/validate/trial-balance
  trial_balance_file: Excel（必填）
  reference_bs_file:  资产负债表 Excel（可选，用于 diff）
  reference_is_file:  利润表 Excel（可选，用于 diff）

响应：
  { "row_count", "column_mapping", "balance_sheet", "income_statement",
    "bs_diff", "is_diff", "raw_rows" }
```

**diff 对比逻辑**：对参考 Excel 的行项目名称做规范化（去序号前缀、去"减："等），
与计算结果模糊匹配，差额 < 1 元标记 `match=true`，未匹配行不报告（避免误报）。

#### 兼容性修复（公司电脑调试阶段）

| 问题 | 原因 | 修复 |
|---|---|---|
| `.xls` 文件读取失败 | xlrd 未安装 | `pip install xlrd` |
| 列名显示 `科目余额表.1 .2 ...` | 荆鹏导出为双行合并列头 | 新增 `_try_load_excel_multiheader()` |
| `/validate` 前端 404 | React Router 路由未被后端处理 | `main.py` 补 SPA catch-all |
| Pydantic v2 字段名冲突 | `date: date` 自引用 | `from datetime import date as _date` |

---

## Epic 4.0 架构铁律（贯穿 4.1~4.4）

1. **报表 = 凭证数据的不同视图**：所有报表均从 `VoucherLine + VoucherHeader（POSTED）` 聚合，严禁独立存储报表数值
2. **单一算盘原则**：Sprint 4.2 明细账的期初余额算法与 Sprint 4.1 `LedgerService` 使用**完全相同**的有符号中间值公式，不允许两套
3. **确定性优于生成性**：财务报表公式是中国会计准则的确定性知识，不使用 AI 生成（AI 仅用于有业务数据支撑的场景，如凭证生成、财务分析）
4. **试算平衡断言**：科目余额表在后端执行三列平衡断言；资产负债表返回 `balanced` 标志，前端展示不平衡警告

---

## 待做

### Sprint 3.6（暂定） — 批量复核工作台
- 黄灯一键复核：前端展示 `needs_review=True` 的凭证网格，财务人员逐条确认或驳回
- 定时重试：红灯记录支持"重新处理"按钮（重新调用 `generate_voucher` + 入库）
- 批量报告导出：Excel 下载（绿/黄/红三色分类汇总）

---

## 架构备忘

### 悬账断路器科目
- `1221` 其他应收款-待查明（借方差额）
- `2241` 其他应付款-待查明（贷方差额）
- 触发时状态锁定为 `DRAFT_PENDING_REVIEW`，必须人工复核

### DAG rule_json 完整格式（Sprint 3.4 扩展版）
```json
{
  "nodes": [
    {"id": "N1", "label": "首付挂长期待摊", "subject_hint": "1801", "action": "首次付款时执行"},
    {"id": "N2", "label": "次月起每月摊销", "subject_hint": "6602", "action": "次月1日起每月执行"}
  ],
  "edges": [
    {
      "from": "N1", "to": "N2",
      "condition": "次月1日起按月摊销，至金额归零",
      "weight": 5,
      "last_used_at": "2025-03-15T08:00:00+00:00",
      "context_features": {
        "subject_combo":  ["1801-DEBIT", "1001-CREDIT"],
        "line_templates": [
          {"subject_code": "1801", "direction": "DEBIT",  "ratio": 1.0, "memo_hint": "挂账"},
          {"subject_code": "1001", "direction": "CREDIT", "ratio": 1.0, "memo_hint": null}
        ],
        "min_amount": 3000.0,
        "max_amount": 5000.0
      }
    }
  ]
}
```

### Session 安全规范（后台任务通用原则）
所有由 `BackgroundTasks` 触发的异步方法（`learn_from_voucher_async`、`run_batch_pipeline`）均须：
1. 内部实例化独立 `SessionLocal()`，绝不复用路由层 Session
2. 所有业务参数（`tenant_id`、`account_set_id`、`creator_id`）显式传入，不依赖 ContextVar
3. `finally: db.close()` 确保连接归还
4. 顶层 `except Exception` 全吞，绝不上浮给 FastAPI 框架
