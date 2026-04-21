# AgentLedger 项目参考文档 + 一周行动计划

> 最后更新：2026-04-21

---

## 一、项目全景

### 是什么
AgentLedger 是一个基于 LLM 的智能财务系统，核心价值是"AI 辅助记账 + 标准财务报表"。

### 技术栈

| 层 | 技术 |
|---|---|
| 后端 | FastAPI + SQLAlchemy + MySQL |
| 前端 | React 18 + TypeScript + Vite + Tailwind + Zustand |
| AI | OpenAI / gpt-4o-mini（JSON mode + tool calling）|
| 认证 | JWT（python-jose）|

### 数据管道（最核心的链路）

```
业务事件（用户描述）
    ↓ AI 解析
凭证 VoucherHeader + VoucherLine（DEBIT/CREDIT + amount）
    ↓ _build_balances()  ← 累加 Σ DEBIT - Σ CREDIT
科目余额字典 {code: Decimal}
    ↓ _map_balance_sheet() / _map_income_statement()
资产负债表 / 利润表（官方会企01/02表格式）
```

---

## 二、各 Sprint 完成状态

### Sprint 2 — 凭证管理
- 凭证 CRUD + 借贷平衡校验
- 审核流程：DRAFT → PENDING_REVIEW → POSTED → REJECTED
- POSTED 凭证防篡改（audit guard）

### Sprint 3.1 / 3.4 / 3.6 — AI 记账核心
- AI 解析业务描述 → 生成借贷凭证（dual-track panel）
- 习惯规则（HabitRule）沉淀：AI 记账行为自动学习成规则
- 规则控制台（HabitRuleDashboard）

### Sprint 3.2 — 凭证工作台
- 凭证列表、搜索、审核操作

### Sprint 3.3 — 月末结账
- 会计期间管理（OPEN/CLOSED）
- 月末损益结转（6xxx → 4103 本年利润）

### Sprint 3.5 — 批量导入
- Excel 上传 → Pandas 清洗 → LLM 列头映射 → 凭证批量生成

### Sprint 3.x — React 迁移（全量重构）
- 从 5500 行单文件 HTML 迁移到 React + TypeScript + Feature-Sliced 架构
- 约 54 个文件，商用级工程结构

### Sprint 4.1 — 万能算盘引擎（科目余额表）
- `LedgerService.calculate_period_balances()` — 六栏式余额计算
- 前端 `/trial-balance` — 科目余额表页面
- 试算平衡断言（Σ借 = Σ贷）

### Sprint 4.2 — 穿透查账（明细账）
- `LedgerDetailService` — Running Balance 算法
- 四种特殊行：期初余额 / 本期合计 / 本年累计 / 明细
- 前端 `/ledger` — 明细账 + 快速切换面板 + 凭证弹窗

### Sprint 4.3 — 财务报表前端
- 前端 `/balance-sheet` — 资产负债表（左右双拼）
- 前端 `/income-statement` — 利润表（垂直阶梯式）
- 后端早已完成（`services/report_service.py`，含完整科目号映射）

### Sprint 4.4 — 报表验证工具（Dev Testing）
- 新建 `services/validation_service.py`：解析科目余额表 Excel（pandas + 关键词列识别）
- 重构 `services/report_service.py`：提取 `_map_balance_sheet()` 和 `_map_income_statement()` 为纯函数（不依赖 DB）
- 新建 `api/validate_routes.py`：`POST /api/validate/trial-balance`（无鉴权）
- 前端 `/validate`：上传 Excel → 计算报表 → 展示结果 + 列映射 debug

---

## 三、关键架构决策（铁律）

1. **报表是凭证数据的视图，严禁重复聚合 SQL** — 所有余额计算必须复用 LedgerService
2. **AI 有价值当且仅当它需要你的业务数据** — 通用答案（如报表公式）不需要 AI
3. **中国会计准则科目号是确定性的** — 1001=现金，6001=营业收入，映射逻辑应硬编码不应 AI 生成
4. **POSTED 凭证不可修改** — audit guard 在进程启动时注册事件监听器

---

## 四、报表验证方案（Excel 三表）

### 你手里有什么
- 科目余额表（包含：期初余额、本期发生额、期末余额，按借/贷方分列）
- 资产负债表（参考答案）
- 利润表（参考答案）

### 能验证什么

| 验证目标 | 能否用这三张表验证 | 方法 |
|---|---|---|
| 报表公式映射（哪个科目号→哪个报表行）| ✅ 可以 | Sprint 4.4：上传科目余额表，对比系统输出 |
| 余额累加逻辑（_build_balances 是否正确）| ❌ 不能 | 需要实际凭证数据 |

### 验证逻辑
```
科目余额表 → 期末余额(借) - 期末余额(贷) = net_balance
                ↓
           系统公式映射
                ↓
        资产负债表 / 利润表
                ↓
        与参考 Excel 逐行对比
```

### 行名差异不用担心
系统使用官方会企01/02表标准行名。参考 Excel 可能有细微差异（如"一、营业收入"vs"营业收入"），只需对比**数字**，不需完全匹配行名。

---

## 五、本地开发环境搭建

### 需要下载的软件

| 软件 | 用途 | 备注 |
|---|---|---|
| Python 3.11+ | 后端运行 | 安装时勾选 Add to PATH |
| Node.js 20 LTS | 前端运行 | 选 LTS 版本 |
| MySQL Installer 8.0 | 数据库（含 Workbench GUI）| 记住 root 密码 |

### 启动顺序
```bash
# 1. 安装后端依赖
pip install -r requirements.txt

# 2. 安装前端依赖
cd frontend && npm install

# 3. 配置 .env
DB_HOST=localhost
DB_PORT=3306
DB_USER=root
DB_PASSWORD=你的密码
DB_NAME=agentledger

# 4. 创建数据库
mysql -u root -p -e "CREATE DATABASE agentledger CHARACTER SET utf8mb4;"

# 5. 启动（两个终端同时开）
uvicorn main:app --reload          # 终端1
cd frontend && npm run dev          # 终端2
```

---

## 六、全功能测试清单

> 按依赖顺序执行，前面不通后面没法测

### 阶段 0：环境启动（10分钟）
- [ ] 后端无报错启动
- [ ] 前端 `http://localhost:5173` 登录页正常
- [ ] 登录成功跳转仪表盘

### 阶段 1：冒烟测试——所有页面能打开（15分钟）

| 页面 | 路径 | 通过标准 |
|---|---|---|
| 仪表盘 | `/dashboard` | 正常渲染 |
| 凭证管理 | `/vouchers` | 表格显示 |
| AI 记账 | `/ai-voucher` | 页面渲染 |
| 批量导入 | `/batch` | 页面渲染 |
| 月末结账 | `/closing` | 期间列表显示 |
| 科目余额表 | `/trial-balance` | 表格（可空）|
| 明细账 | `/ledger` | 页面渲染 |
| 资产负债表 | `/balance-sheet` | 报表渲染 |
| 利润表 | `/income-statement` | 报表渲染 |
| 报表验证 | `/validate` | 上传区域显示 |
| 科目管理 | `/subjects` | 科目列表 |

遇到白屏：F12 → Console，记录报错信息。

### 阶段 2：黄金路径（45分钟，最关键）

```
在 /vouchers 新建凭证：
  借：银行存款 (1002)    10,000
  贷：实收资本 (4001)    10,000
→ 提交审核 → 审核通过（POSTED）
```

- [ ] 凭证状态变"已过账"
- [ ] `/trial-balance` 同期：1002 借方 = 10,000，4001 贷方 = 10,000，试算平衡 ✅
- [ ] `/ledger` 选 1002：有一条记录，余额 = 10,000
- [ ] `/balance-sheet`：货币资金 = 10,000，实收资本 = 10,000，资产 = 负债+权益 ✅

**这条链跑通 = 核心数据管道没有问题。**

### 阶段 3：报表验证（30分钟）
进 `/validate`，上传科目余额表 Excel：
- [ ] 列映射识别正确（检查 debug 信息区域）
- [ ] 系统算出的资产负债表 vs 参考 Excel — 记录差异
- [ ] 系统算出的利润表 vs 参考 Excel — 记录差异

### 阶段 4：AI 功能（20分钟，需要 API Key）
在 `/ai-voucher` 输入"支付员工工资 50000 元，从银行转出"：
- [ ] AI 生成借贷凭证，科目代码合理
- [ ] 接受后正常保存

---

## 七、一周行动计划（2026-04-21 ~ 04-27）

> 目标：结束懈怠期，完成测试 + 修复 + 一个新功能

### 周一（今天）— 准备 + 启动
- [ ] 下午从工作人员处拿到三张 Excel 文件
- [ ] 晚上确认家里环境正常（Python / Node / MySQL）
- [ ] 完成阶段 0 + 阶段 1（冒烟测试）
- [ ] 记录所有白屏/报错页面

**预计时间：1.5 小时**

### 周二 — 黄金路径 + 报表验证
- [ ] 完成阶段 2（黄金路径，最重要）
- [ ] 完成阶段 3（Excel 报表验证）
- [ ] 建立 Bug 清单

**预计时间：1.5 小时**

### 周三 — 修复 Bug + Sprint 4.4 补完
- [ ] 根据 Bug 清单逐一修复
- [ ] 补充自动 diff 高亮功能（上传参考 Excel，标红差异行）

**预计时间：2 小时**

### 周四 — Sprint 4.5 规划 + 开始
候选（选一个）：

| 候选 | 价值 | 难度 |
|---|---|---|
| 现金流量表前端 | 后端已有，纯前端 | 低 ⭐ 推荐 |
| 所有者权益变动表 | 后端已有，纯前端 | 低 |
| AI 财务解读 | 把报表数据发给 LLM | 中 |

**预计时间：1.5 小时**

### 周五 — 完成 Sprint 4.5
- [ ] 实现并测试
- [ ] push 到 GitHub
- [ ] 更新 SPRINT_NOTES.md

**预计时间：1.5 小时**

### 周末 — 缓冲 + 回顾
- 补完未完成任务
- 思考 Sprint 5.x 方向

---

## 八、下一阶段候选 Sprint

| 优先级 | Sprint | 描述 |
|---|---|---|
| 🔴 立刻 | 4.4 补完 | 加自动 diff 高亮对比功能 |
| 🟡 近期 | 4.5 | 现金流量表前端（后端已就绪）|
| 🟡 近期 | 4.6 | 所有者权益变动表前端 |
| 🟢 中期 | 5.1 | AI 财务解读（真正有价值的 AI 用法）|
| 🟢 中期 | 5.2 | 对账中心（上传柠檬云 Excel 自动对比）|
| 🔵 长期 | 5.3 | 汇总凭证注入工具（完整管道验证）|

---

## 九、Gemini 建议评估总结

| Gemini 建议 | 评估 |
|---|---|
| 不要用 OCR，直接读 Excel 单元格 | ✅ 已用 pandas 实现 |
| LLM 辅助列名识别 | 🟡 正则已够用，LLM 是备选 |
| 自动 diff 高亮 | ✅ 值得做，Sprint 4.4 延伸 |
| 汇总凭证注入工具 | 🟡 好想法，Sprint 5.3 |
| 对账仪表盘 5.0 | ✅ 长期方向，Sprint 5.2 |
| AI 公式生成 | ❌ 不需要，科目号是确定性知识 |
