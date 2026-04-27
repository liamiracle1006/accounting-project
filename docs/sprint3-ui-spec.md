# Sprint 3 UI 详细需求规格

> 本文档描述 Sprint 3 各子模块的前端实现细节。后端全部就绪，前端缺口如下：
> - **3.1 + 3.4**：AI 凭证生成页 — 完全缺失
> - **3.2**：凭证 CRUD — 仅有审核工作台，缺手工录入/编辑/回收站/断号整理
> - **3.3**：月末结账 — 页面存在但 API 路径全错，缺结转损益和反结账按钮
> - **3.5**：批量导入 — 完全缺失

---

## 1. Sprint 3.1 + 3.4 — AI 凭证生成（page-ai-voucher）

### 1.1 定位与导航

在 `<nav>` 中财务工作台前新增：
```html
<a href="#" data-page="ai-voucher" onclick="navTo('ai-voucher',this);return false;" class="finance-only">AI 记账</a>
```

`navTo('ai-voucher')` 时调用 `loadAiVoucherPage()`（仅重置表单状态，不发请求）。

---

### 1.2 页面整体布局

```
┌─ page-ai-voucher ───────────────────────────────────────────────────────┐
│  [Tab: AI 生成凭证]  [Tab: 业务习惯规则]                                 │
├─ Tab A: AI 生成 ────────────────────────────────────────────────────────┤
│  ┌─ 输入卡片 ─────────────────────────────────────────────────────────┐ │
│  │  业务描述 [____________________________________________]           │ │
│  │  凭证日期 [2026-04-08]    凭证字 [记▼]                             │ │
│  │  [✨ AI 生成凭证]                                                  │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│  ┌─ 推荐结果区（生成后显示）────────────────────────────────────────────┐ │
│  │  [Track A 卡片: 历史习惯]  [Track B 卡片: AI 推断]                  │ │
│  │  （选中某卡片后高亮，下方显示该轨道的凭证草稿预览）                   │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│  ┌─ 凭证草稿预览（选轨后显示）──────────────────────────────────────────┐ │
│  │  摘要: [________________]  日期: [________]                         │ │
│  │  ┌ 分录行表格（可编辑）────────────────────────────────────────────┐│ │
│  │  │ 科目编码 | 科目名称 | 方向 | 金额 | 备注 | [删]                ││ │
│  │  │ 1002   银行存款    贷  3600.00  服务器费  [×]                   ││ │
│  │  │ 6601   管理费用    借  3600.00  阿里云    [×]                   ││ │
│  │  │ [+ 添加行]                                                      ││ │
│  │  └────────────────────────────────────────────────────────────────┘│ │
│  │  借方合计: 3600.00  贷方合计: 3600.00  ✅                           │ │
│  │  ⚠️  断路器提示区（circuit_breaker_triggered=true 时显示）          │ │
│  │  [确认入账]                                                         │ │
│  └────────────────────────────────────────────────────────────────────┘ │
├─ Tab B: 业务习惯规则 ────────────────────────────────────────────────────┤
│  [+ 新增规则]                                                            │
│  ┌─ 规则列表 ─────────────────────────────────────────────────────────┐ │
│  │  规则名称 | 关键词 | 状态 | 上次使用 | 命中次数 | 操作             │ │
│  │  阿里云摊销  阿里云,服务器  启用  2026-04-01  12  [停用][删除]      │ │
│  └────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────┘
```

---

### 1.3 Tab A — AI 生成流程详解

#### 输入区

| 字段 | 控件 | 说明 |
|------|------|------|
| 业务描述 | `<textarea>` 2行，max 500字 | 必填，placeholder: "如：阿里云服务器费用 3600元" |
| 凭证日期 | `<input type="date">` | 默认今天 |
| 凭证字 | `<select>` 记/收/付/转 | 默认"记" |
| AI 生成凭证 | `<button class="btn btn-primary">` | 点击后 loading 状态，禁用 |

#### 调用 generate

```
POST /api/voucher-ai/generate
Body: { description: string, voucher_date: "YYYY-MM-DD" }
```

返回 `DualTrackResponse`:
```json
{
  "recommendations": [
    {
      "track": "A",
      "source": "HABIT",
      "confidence": "HIGH",
      "habit_rule_id": 5,
      "draft": { "memo": "...", "voucher_date": "...", "lines": [...], "is_balanced": true, ... }
    },
    {
      "track": "B",
      "source": "AI_RULE",
      "confidence": "LOW",
      "habit_rule_id": null,
      "draft": { ... }
    }
  ]
}
```

#### 双轨卡片展示规则

- **Track A 卡片**（仅 recommendations 包含 track="A" 时显示）：
  - 标题：`历史习惯推荐`，右上角置信度徽章
    - HIGH → 绿色 `● 高置信`
    - MEDIUM → 橙色 `● 中置信`
    - LOW → 灰色 `● 低置信`
  - 卡片正文：显示匹配到的习惯规则名称（从 habit_rule_id 反查，可省略，直接写"基于 X 条历史记录"）
  - 底部：`选择此方案` 按钮

- **Track B 卡片**（永远显示）：
  - 标题：`AI 智能推断`，置信度徽章
  - 底部：`选择此方案` 按钮

- **选中某卡片**后：
  - 卡片边框变蓝高亮
  - 下方草稿预览区出现，填充该轨道的 draft 数据
  - 记录 `_selectedHabitRuleId = item.habit_rule_id`（Track A 有值，Track B 为 null）

#### 凭证草稿预览区（可编辑）

显示 draft 字段，用户可在提交前修改：
- **摘要** `<input>` 对应 `draft.memo`
- **分录行表格**：每行对应 `draft.lines[]` 中一条
  - 科目编码 `<input>` 对应 `subject_code`，只读（灰色），科目名称列只读展示 `subject_name`
  - 方向 `<select>` DEBIT（借）/ CREDIT（贷）
  - 金额 `<input type="number">`
  - 备注 `<input>`
  - [×] 删除行（最少保留2行）
- **[+ 添加行]**：新增一空白行
- **借贷合计实时计算**：前端实时累加 DEBIT / CREDIT 金额，相差 > 0.005 显示红色 `❌ 借贷不平`
- **断路器提示**：若 `draft.circuit_breaker_triggered === true`，在借贷合计下方显示橙色警告框，内容来自 `draft.pending_review_reason`

#### 确认入账

点击 `[确认入账]` 按钮：
1. 前端校验借贷平衡，不平则 toast 提示不允许提交
2. 组装请求：
```json
POST /api/voucher-ai/confirm
{
  "description": "<原始输入的业务描述>",
  "voucher_date": "YYYY-MM-DD",
  "voucher_word": "记",
  "memo": "<当前摘要框内容>",
  "lines": [
    { "subject_code": "6601", "direction": "DEBIT", "amount": 3600.00, "memo": null, "auxiliary_data": null },
    ...
  ],
  "habit_rule_id": 5  // Track A 时有值，Track B 时为 null
}
```
3. 成功（201）：`showToast('凭证已入账', 'success')`，清空输入区，隐藏结果区
4. 失败：`showToast(data.detail, 'error')`

---

### 1.4 Tab B — 业务习惯规则

#### 规则列表

调用 `GET /api/voucher-ai/habit-rules`，返回 `HabitRuleOut[]`：
```json
[
  {
    "id": 5,
    "rule_name": "阿里云服务器年费摊销",
    "description": null,
    "keywords": ["阿里云", "服务器"],
    "rule_json": { "nodes": [...], "edges": [...] },
    "is_active": true,
    "created_at": "...",
    "updated_at": "..."
  }
]
```

表格列：规则名称 | 关键词（tags 形式显示） | 状态（启用/停用） | 创建时间 | 操作

操作按钮：
- `[停用]` / `[启用]`：调 `PUT /api/voucher-ai/habit-rules/{id}` `{ "is_active": false/true }`
- `[删除]`：confirm 弹窗后调 `DELETE /api/voucher-ai/habit-rules/{id}`

#### 新增规则 Modal

字段：
- 规则名称（必填 text）
- 描述（选填 text）
- 关键词（逗号分隔输入，split 后传 array）
- DAG JSON（`<textarea>` raw JSON 编辑，validate JSON.parse）
- 是否启用（checkbox，默认 true）

提交：`POST /api/voucher-ai/habit-rules`，成功后关闭 Modal，刷新列表。

---

### 1.5 JS 函数清单

```javascript
// Tab 切换
function switchAiTab(tab, el)

// Tab A
async function generateVoucher()           // 调 /generate，渲染双轨卡片
function renderDualTrack(recommendations)  // 渲染 Track A / B 卡片
function selectTrack(index)                // 选轨，渲染草稿预览区
function renderDraftPreview(draft)         // 填充摘要 + 行表格
function addDraftLine()                    // 新增空白行
function removeDraftLine(btn)              // 删除行
function recalcDraftBalance()              // 实时借贷合计
async function confirmVoucher()            // 组装并调 /confirm

// Tab B
async function loadHabitRules()            // 调 GET /habit-rules，渲染表格
function openHabitModal(id?)               // 打开新增/编辑 Modal
async function saveHabitRule()             // 提交 POST / PUT
async function toggleHabitRule(id, active) // 停用/启用
async function deleteHabitRule(id)         // 删除

// 状态变量
let _aiRecommendations = [];
let _selectedTrackIndex = null;
let _selectedHabitRuleId = null;
```

---

## 2. Sprint 3.2 — 凭证 CRUD 补全（page-workbench）

### 2.1 现状说明

现有 `page-workbench` 使用 `/api/workbench/vouchers`（审核专用路由），功能：
- 按状态过滤凭证列表（PENDING_REVIEW / POSTED / REJECTED / DRAFT）
- 点击凭证查看详情 + 审核/驳回操作

**保留现有审核流不变**，在此基础上扩展：

---

### 2.2 扩展：工具栏新增按钮

在 `page-workbench` 顶部卡片的 card-header 右侧，与刷新按钮同排新增：

```
[+ 手工录入凭证]  [🗑 回收站]  [🔢 断号整理]  |  [状态过滤 ▼]  [刷新]
```

---

### 2.3 手工录入凭证 Modal（voucherCreateModal）

触发：点击 `[+ 手工录入凭证]`

**Modal 结构：**

```
┌─ 新建凭证 ────────────────────────────────────────────────┐
│  凭证日期 [2026-04-08]   凭证字 [记▼]   摘要 [___________]│
├── 分录行 ──────────────────────────────────────────────────┤
│  科目编码    方向         金额       备注         操作     │
│  [________] [借▼]  [____________] [__________]  [×]      │
│  [________] [贷▼]  [____________] [__________]  [×]      │
│  [+ 添加行]                                                │
├── 借贷校验 ─────────────────────────────────────────────────┤
│  借方合计: 0.00   贷方合计: 0.00   ❌ 借贷不平             │
│  [取消]                                      [提交凭证]   │
└────────────────────────────────────────────────────────────┘
```

字段对应 `VoucherCreateInput`:
```json
{
  "voucher_date": "2026-04-08",
  "voucher_word": "记",
  "memo": "摘要文字",
  "lines": [
    { "subject_code": "6601", "direction": "DEBIT", "amount": 3600.00, "memo": null, "auxiliary_entity_id": null },
    { "subject_code": "1002", "direction": "CREDIT", "amount": 3600.00, "memo": null, "auxiliary_entity_id": null }
  ]
}
```

行为：
- **借贷实时校验**：每次 input 事件重算 DEBIT / CREDIT 合计，差额 > 0.005 → `[提交凭证]` 禁用，显示 `❌ 借贷不平`
- **最少行数**：始终保持 ≥ 2 行，删除时若剩余 ≤ 2 禁用删除按钮
- **提交**：`POST /api/vouchers`，201 成功后 toast + 关闭 Modal + `loadWorkbench()`
- **错误处理**：422 时 `showToast(data.detail, 'error')`（后端已做借贷平衡 model_validator）

---

### 2.4 编辑凭证

现有审核弹窗（`wbModal`）中，当凭证状态为 `DRAFT` 时，在操作区新增 `[编辑]` 按钮。

点击 `[编辑]`：
- 关闭 wbModal
- 打开一个与"手工录入"相同结构的 Modal（复用 `voucherCreateModal`），预填充当前凭证数据
- 提交改为 `PUT /api/vouchers/{voucher_id}`，请求体 `VoucherUpdateInput`（结构同 CreateInput）
- 成功后 toast + 刷新列表

---

### 2.5 回收站（voucherTrashModal）

触发：点击 `[🗑 回收站]`

**Modal 结构：**

```
┌─ 凭证回收站 ────────────────────────────────────────────────┐
│  加载中… / 空回收站提示 / 列表                                │
│  凭证号 | 日期 | 摘要 | 金额 | 删除时间 | 操作             │
│  #42    2026-04-01  服务器费  3600.00  04-05 10:30  [还原] │
│  [关闭]                                                      │
└─────────────────────────────────────────────────────────────┘
```

调用：`GET /api/vouchers/trash` → 返回 `VoucherOut[]`（已软删除的）

`[还原]` 按钮：`POST /api/vouchers/{voucher_id}/restore`，成功后该行变绿消失（`setTimeout(() => row.remove(), 800)`），toast 提示。

---

### 2.6 断号整理（简单确认弹窗，无需独立 Modal）

触发：点击 `[🔢 断号整理]`

弹出 `<dialog>` 或用现有 confirm 风格：
```
选择期间：年份 [2026] 月份 [4▼]
[确认整理]  [取消]
```

调用：`POST /api/vouchers/reorganize`
```json
{ "period_year": 2026, "period_month": 4 }
```

返回 `ReorganizeResult`:
```json
{ "period": "2026-04", "updated_count": 15, "message": "已将 2026-04 的 15 张凭证重新编号" }
```

成功后 toast 显示 `message`，关闭弹窗，刷新列表。

---

### 2.7 凭证列表升级（从 workbench 改为使用 /api/vouchers）

**注意**：`page-workbench` 当前调用 `/api/workbench/vouchers`（第三方审核路由），**不改动**，保持原有审核流。

新增的手工录入、编辑、回收站、断号整理全部使用 `/api/vouchers` 系列 API，不改变 workbench 的查询逻辑。

---

### 2.8 JS 函数清单

```javascript
// 手工录入
function openVoucherCreateModal()         // 打开新建凭证 Modal（空白）
function openVoucherEditModal(voucherId)  // 打开编辑 Modal（预填充，先 GET /api/vouchers/{id}）
function addVoucherLine()                 // 新增凭证行
function removeVoucherLine(btn)          // 删除凭证行（不低于2行）
function recalcVoucherBalance()          // 实时借贷合计校验
async function submitVoucherCreate()     // POST /api/vouchers
async function submitVoucherEdit()       // PUT /api/vouchers/{id}

// 回收站
async function openTrashModal()          // GET /api/vouchers/trash → 渲染列表
async function restoreVoucher(id, row)   // POST /api/vouchers/{id}/restore

// 断号整理
function openReorganizeDialog()          // 打开年月选择弹窗
async function submitReorganize()        // POST /api/vouchers/reorganize → toast 结果
```

---

## 3. Sprint 3.3 — 修复月末结账（page-closing）

### 3.1 现有 Bug：API 路径全错

| 位置 | 当前（错误） | 修正后 |
|------|------------|--------|
| `loadPeriods()` | `GET /api/reports/periods` | `GET /api/period` |
| `closePeriod()` | `POST /api/reports/periods/${year}/${month}/close` | `POST /api/period/${year}/${month}/close` |

两处 URL 改字符串即可，无需改逻辑。

---

### 3.2 新增：结转损益按钮

在"执行结账"卡片中，`[执行月末结账]` 按钮旁边新增：

```
[结转本期损益]  [执行月末结账]
```

点击 `[结转本期损益]`：
- 读取同一 year / month 输入值
- `POST /api/period/${year}/${month}/transfer-pnl`
- 返回 `TransferPnLResult`:
  ```json
  { "year": 2026, "month": 3, "net_profit": 15800.00, "voucher_id": 88, "message": "已生成结转凭证 #88" }
  ```
- 在 `#close-result` 区域显示：
  ```
  ✅ 结转完成：本期净利润 ¥15,800.00，已生成凭证 #88
  ```
- 失败时显示红色错误提示（如"损益类科目尚未有余额"）

---

### 3.3 新增：反结账按钮

在期间列表 `#period-list` 中，每个 `CLOSED` 状态的期间行，仅最后一条 CLOSED 期间显示 `[反结账]` 按钮。

判断逻辑：渲染时记录 CLOSED 期间列表，只给第一条（最新）CLOSED 期间加按钮。

点击 `[反结账]`：
- confirm 弹窗："确定要反结账 2026年3月吗？此操作将删除结转凭证并重新开放该期间。"
- 确认后：`POST /api/period/${year}/${month}/unclose`
- 返回 `UncloseResult`:
  ```json
  { "year": 2026, "month": 3, "message": "已反结账，期间 2026-03 重新开放" }
  ```
- `showToast(data.message, 'success')`，`loadPeriods()` 刷新列表

---

### 3.4 期间列表渲染升级

当前渲染仅显示基础信息，升级为：

```
2026年4月   ● 开放中                                    [结转损益] [结账]
2026年3月   ● 已结账   结账时间: 2026-04-01 10:30        [反结账]    ← 仅最新已结账期间显示
2026年2月   ● 已结账   结账时间: 2026-03-01 09:00
2026年1月   ● 已结账   结账时间: 2026-02-01 11:30
```

`GET /api/period` 返回 `PeriodOut[]`（最多24条，按年月倒序）：
```json
[
  { "period_id": 4, "year": 2026, "month": 4, "status": "OPEN", "closed_at": null, "closed_by": null, "closing_voucher_id": null },
  { "period_id": 3, "year": 2026, "month": 3, "status": "CLOSED", "closed_at": "2026-04-01T10:30:00", "closed_by": 1, "closing_voucher_id": 88 }
]
```

状态徽章：`OPEN` → 绿色圆点 `● 开放中`；`CLOSED` → 灰色 `● 已结账 结账时间: ...`

---

### 3.5 JS 函数改动清单

```javascript
// 修复
async function loadPeriods()         // URL: /api/reports/periods → /api/period
async function closePeriod()         // URL: /api/reports/periods/.../close → /api/period/.../close

// 新增
async function transferPnL()         // POST /api/period/${year}/${month}/transfer-pnl → 显示净利润
async function uncloseperiod(year, month)  // POST /api/period/${year}/${month}/unclose → toast + 刷新
```

---

## 4. Sprint 3.5 — 批量导入流水线（page-batch）

### 4.1 导航

在 `<nav>` 新增（finance-only）：
```html
<a href="#" data-page="batch" onclick="navTo('batch',this);return false;" class="finance-only">批量导入</a>
```

`navTo('batch')` 时调用 `loadBatchPage()`（重置为步骤 1）。

---

### 4.2 页面整体布局（3步线性流程）

```
① 上传文件  →  ② 核对数据  →  ③ 处理中 / 查看报告

步骤 1：上传区（始终可见）
步骤 2：解析结果表格（upload 成功后显示）
步骤 3：进度条 + 三色报告（submit 后显示）
```

---

### 4.3 步骤 1 — 文件上传区

```
┌─ 上传票据文件 ─────────────────────────────────────────────────────────┐
│  支持格式：Excel (.xlsx/.xls/.csv) · 图片 (.jpg/.png/.webp) · PDF      │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │                                                                  │   │
│  │          📎 点击选择文件 或 拖放到此处                           │   │
│  │          （可一次选多个文件，Excel 与图片可混合上传）              │   │
│  │                                                                  │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│  [解析预览]                                                              │
└────────────────────────────────────────────────────────────────────────┘
```

行为：
- `<input type="file" multiple accept=".xlsx,.xls,.csv,.jpg,.jpeg,.png,.webp,.pdf">`
- 选文件后显示文件名列表（可逐个删除）
- 点击 `[解析预览]` 按钮：
  - 将所有文件 append 到 `FormData`，字段名 `files`（与后端 `File(...)`  字段名一致）
  - `POST /api/batch/parse-preview` multipart
  - Loading 状态（禁用按钮，显示 spinner）
  - 成功后进入步骤 2

调用返回 `ParsePreviewResponse`:
```json
{
  "items": [
    { "date": "2026-03-15", "amount": 3600.00, "counterparty": "阿里云", "summary": "服务器费用", "file_url": null }
  ],
  "total": 12,
  "parse_engine": "EXCEL"
}
```

步骤 1 顶部显示解析摘要：`已识别 12 条票据（使用 EXCEL 引擎）`

---

### 4.4 步骤 2 — 核对网格

```
┌─ 核对票据数据（共 12 条）─────────────────────────────────────────────┐
│  凭证字: [记▼]                          [重新上传] [提交批量入账 →]   │
├────┬─────────────┬────────────┬────────────────┬──────────────┬──────┤
│ #  │ 日期        │ 金额       │ 对方单位       │ 摘要         │      │
├────┼─────────────┼────────────┼────────────────┼──────────────┼──────┤
│ 1  │ 2026-03-15  │ 3,600.00   │ 阿里云         │ 服务器费用   │ [×] │
│ 2  │ 2026-03-16  │   50.00    │                │ 星巴克报销   │ [×] │
└────┴─────────────┴────────────┴────────────────┴──────────────┴──────┘
```

行为：
- 每行所有字段**可直接 inline 编辑**（`contenteditable`，或每格 `<input>` + blur 保存）
  - `date`：type="date"
  - `amount`：type="number" step="0.01" min="0.01"
  - `counterparty`：text，可空
  - `summary`：text，必填（min 1）
- `[×]` 删除该行，剩余 0 行时禁用提交按钮
- `[重新上传]`：清空网格，回到步骤 1
- `凭证字` 下拉（记/收/付/转），此处设置的值将传入 `/execute` 的 `voucher_word`
- `[提交批量入账]`：点击后进入步骤 3

---

### 4.5 步骤 3 — 进度轮询

点击 `[提交批量入账]` 后：

**调用 execute:**
```json
POST /api/batch/execute
{
  "items": [ { "date": "...", "amount": ..., "counterparty": "...", "summary": "..." } ],
  "voucher_word": "记"
}
```

返回 `ExecuteBatchResponse`:
```json
{ "task_id": 7, "total_count": 12 }
```

**进度展示 UI:**
```
┌─ 批量入账进行中 ────────────────────────────────────────────┐
│  任务 #7 · 共 12 条                                          │
│  ████████░░░░░░░░░░░░  8 / 12                                │
│  ✅ 成功: 7    ⚠️ 待复核: 1    ❌ 失败: 0                   │
│  状态: PROCESSING                                            │
└─────────────────────────────────────────────────────────────┘
```

**轮询逻辑（`setInterval 2000ms`）:**
- `GET /api/batch/task/{task_id}/progress`
- 返回 `TaskProgressOut`:
  ```json
  { "task_id": 7, "status": "PROCESSING", "total_count": 12, "success_count": 8, "error_count": 0, "needs_review_count": 1, ... }
  ```
- 更新进度条宽度：`(success_count + error_count) / total_count * 100%`
- 状态变为 `COMPLETED` 或 `FAILED` 时停止轮询，调用 `loadBatchResults(task_id)` 显示报告

---

### 4.6 三色报告

`GET /api/batch/task/{task_id}/results` 返回 `BatchResultsOut`:
```json
{
  "task_id": 7,
  "status": "COMPLETED",
  "success": [ { "id": 1, "raw_data": {...}, "confidence": "HIGH", "voucher_id": 101, "needs_review": false, ... } ],
  "needs_review": [ { "id": 2, "raw_data": {...}, "confidence": "MEDIUM", "voucher_id": 102, "needs_review": true, ... } ],
  "errors": [ { "id": 3, "raw_data": {...}, "confidence": null, "voucher_id": null, "error_msg": "科目匹配失败" } ]
}
```

报告展示：

```
┌─ 处理结果 ─────────────────────────────────────────────────────────────┐
│  ✅ 自动入账  7 条   ⚠️ 需人工复核  1 条   ❌ 处理失败  0 条           │
├─ 🟢 自动入账明细 ───────────────────────────────────────────────────────┤
│  日期      金额     摘要        置信度    凭证号                        │
│  03-15   3,600.00  服务器费用  HIGH     #101 → [查看凭证]              │
├─ 🟡 需人工复核明细 ─────────────────────────────────────────────────────┤
│  03-16     50.00  星巴克报销  MEDIUM   #102 → [查看凭证] ⚠️ 待复核    │
├─ 🔴 失败明细 ──────────────────────────────────────────────────────────┤
│  （无）                                                                 │
│  [重新发起导入]                                                          │
└────────────────────────────────────────────────────────────────────────┘
```

`[查看凭证]`：跳转 `navTo('workbench')` 并过滤对应 voucher_id（或直接打开 wbModal）。

---

### 4.7 JS 函数清单

```javascript
// 状态变量
let _batchFiles = [];
let _batchItems = [];
let _batchTaskId = null;
let _batchPollTimer = null;

// 步骤1
function loadBatchPage()              // 重置为步骤1
function onBatchFileSelect(input)     // 接收文件，显示文件名列表
function removeBatchFile(index)       // 移除某文件
async function parseBatchPreview()    // POST /api/batch/parse-preview → 进入步骤2

// 步骤2
function renderBatchGrid(items)       // 渲染可编辑表格
function deleteBatchRow(index)        // 删除一行
function collectGridItems()           // 从表格收集当前数据
async function submitBatch()          // POST /api/batch/execute → 进入步骤3

// 步骤3
function startBatchPolling(taskId)    // 开始 setInterval 轮询
function updateBatchProgress(data)   // 更新进度条和计数
function stopBatchPolling()          // clearInterval

// 报告
async function loadBatchResults(taskId) // GET /api/batch/task/{id}/results → 渲染三色报告
function renderBatchResults(data)      // 三色分区渲染
```

---

## 5. 实施优先级与依赖关系

| 优先级 | 任务 | 工作量估算 | 依赖 |
|--------|------|----------|------|
| P0 | 3.3 API 路径修复 | 5 分钟 | 无 |
| P1 | 3.3 新增结转损益 + 反结账 + 升级期间列表 | 1小时 | P0 |
| P1 | 3.1+3.4 AI 凭证生成页 | 3小时 | 无 |
| P2 | 3.5 批量导入流水线 | 3小时 | 无 |
| P3 | 3.2 手工录入 + 编辑 | 2小时 | 无 |
| P3 | 3.2 回收站 + 断号整理 | 1小时 | P3 |

---

## 6. 共用约定

- **API 前缀**：全部使用 `${API}`（现有全局变量 `const API = ''`）
- **Toast 通知**：使用现有 `showToast(msg, type)` 函数（'success' / 'error'）
- **金额格式化**：使用现有 `fmt(amount)` 函数（千位分隔 + 两位小数）
- **XSS 防护**：字符串插入 HTML 时使用现有 `escHtml(str)` 函数
- **Loading 状态**：按钮 `disabled = true` + `textContent = '处理中…'`，结束后恢复
- **空状态**：无数据时显示 `<div class="empty-state"><p>暂无数据</p></div>`
- **Modal 关闭**：点击遮罩层关闭（`onclick="if(event.target===this) closeXxx()"`）
