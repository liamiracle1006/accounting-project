# AgentLedger — 小微企业智能业财融合系统

基于 AI 的复式记账系统，支持自然语言生成凭证、多级审核、财务报表生成及报表验证。

## 技术栈

| 层 | 技术 |
|---|---|
| 前端 | React 18 + TypeScript + Vite + Tailwind CSS |
| 后端 | Python 3.12 + FastAPI + SQLAlchemy |
| 数据库 | MySQL 8.4 |
| AI | Claude API（凭证生成双轨模型） |

## 快速启动

```
终端 1（后端）                    终端 2（前端）
─────────────────────────────     ─────────────
py -3.12 -m uvicorn main:app      cd frontend
  --reload                        npm run dev
```

| 地址 | 用途 |
|---|---|
| http://localhost:5173 | 前端界面 |
| http://localhost:8000/docs | 后端 API 文档 |

默认账号：`accountant` / `boss` / `manager`，密码均为 `123456`

## 功能模块

### 凭证管理
- 自然语言描述 → AI 自动生成借贷分录（双轨模型：习惯规则 + AI 规则）
- 凭证审核工作流：草稿 → 待审 → 已过账 / 驳回
- 批量导入（Excel / 图片 / 混合解析）

### 账簿查询
- **科目余额表**：多级科目展示，借贷平衡校验
- **明细账**：Running Balance 引擎，支持穿透查账

### 财务报表
- **资产负债表**：企业准则 / 小企业准则双版本
- **利润表**：企业准则 / 小企业准则双版本，按月查询

### 报表验证工具
- 上传荆鹏等软件导出的科目余额表 Excel
- 自动解析并计算资产负债表和利润表
- 与用户上传的参考报表进行逐行 diff 对比（绿色=吻合 / 红色=差异）
- 支持多版本会计制度科目编码自动规范化（小企业 5xxx / 3xxx → 标准 6xxx / 4xxx）

### 其他
- 期间结账（月结、结转损益）
- 固定资产台账
- 费用申请审批
- 习惯规则管理

## 项目结构

```
accounting-project/
├── main.py                        # FastAPI 入口
├── api/                           # 路由层
│   ├── auth_routes.py
│   ├── voucher_routes.py
│   ├── report_routes.py
│   ├── validate_routes.py         # 报表验证接口
│   └── ...
├── services/                      # 业务逻辑
│   ├── report_service.py          # 报表生成引擎
│   ├── validation_service.py      # Excel 解析 + 报表验证
│   ├── voucher_service.py
│   └── ...
├── models/                        # ORM 实体
├── database/
│   ├── ddl.sql
│   └── seed_local.sql
└── frontend/
    └── src/
        ├── features/
        │   ├── vouchers/          # 凭证管理
        │   ├── reports/           # 财务报表
        │   │   ├── BalanceSheetPage.tsx
        │   │   └── IncomeStatementPage.tsx
        │   ├── validate/          # 报表验证工具
        │   │   └── ValidatePage.tsx
        │   ├── ledger/            # 明细账
        │   └── trial-balance/     # 科目余额表
        └── api/
```

## 设计原则

- **LLM 只做文本理解**，不参与数值计算和科目选择
- **复式记账强制平衡**：`Σ借 ≠ Σ贷` 时拒绝入账并回滚
- **双准则兼容**：所有报表支持企业会计准则与小企业会计准则切换
- **科目编码多制度自动对齐**：上传任意会计软件导出文件，系统自动规范化编码
