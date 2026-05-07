# AgentLedger — 项目上下文

> Claude Code 维护规则：每次对话结束前更新「当前进展」「踩过的坑」「下一步」三个 section，**替换不追加**，总长 < 150 行。深入资料见 `README.md` / `DEV_SETUP.md` / `SPRINT_NOTES.md` / `TESTING_AND_PLAN.md` / `docs/`。

## 项目目标
- 面向小微企业的 **AI 辅助复式记账系统**：自然语言 → AI 生成借贷凭证 → 财务审核入账 → 标准会计报表
- 多租户多账套架构（TenantMixin + 双层隔离）
- 双标准支持：企业会计准则（6xxx）+ 小企业会计准则（5xxx/3xxx）
- 调用方式：用户从 Telegram 经 OpenClaw（`c:/Users/wangzy/Desktop/hobby/open_claw`）以 `claude --print` 在本项目内执行任务

## 技术栈
| 层 | 技术 | 说明 |
|---|---|---|
| 前端 | React 18 + TypeScript + Vite + Tailwind + Zustand | Feature-Sliced 架构，21 个 features 模块 |
| 后端 | Python 3.12 + FastAPI + SQLAlchemy 2.x | 23 个 route 文件 |
| 数据库 | MySQL 8.4 | 必须 `charset=utf8mb4`，DDL 在 `database/ddl.sql` |
| AI | OpenAI 兼容 LLM（gpt-4o-mini）+ JSON mode + tool calling | LLM_API_KEY 配在 `.env` |
| 认证 | JWT（python-jose）+ bcrypt | `services/auth_service.py` |
| 向量库 | ChromaDB（可选，RAG 用） | `chroma_db/`，未装则 RAG 接口返回 503 |

## 当前文件结构
```
accounting-project/
├── main.py                      # FastAPI 入口，注册所有 router + JWT 全局依赖
├── config/settings.py           # 环境变量、DATABASE_URL、LLM 配置
├── database/
│   ├── connection.py            # SQLAlchemy engine + 租户隔离拦截器
│   ├── tenant_context.py        # ContextVar — 每请求独立的租户上下文
│   ├── ddl.sql                  # 建表 SQL（注意：与部分 ORM 模型字段不同步）
│   └── seed_local.sql           # 种子：科目、租户、账套、3 个用户
├── api/                         # 23 个路由文件，业务路由全部依赖 get_current_user
├── services/                    # 业务服务层（auth/voucher/report/import/ai 等）
│   └── graph_engine/            # AI 凭证生成的科目下钻 + 习惯规则引擎
├── ai/                          # LLM 客户端 + agent_runner（多轮 tool calling）
├── models/                      # 24 个 ORM 模型，多数继承 TenantMixin
├── rag/                         # RAG 知识库（chromadb + 税务策略检索）
├── schemas/                     # Pydantic 输入/输出 schema
├── frontend/src/
│   ├── App.tsx                  # 路由表
│   ├── api/                     # axios 封装 + 各模块 API client
│   ├── store/                   # Zustand（auth、toast）
│   ├── components/              # 通用组件 + Layout/Sidebar
│   └── features/                # 21 个 feature 页面（dashboard/vouchers/reports/...）
├── static/                      # 旧版 HTML 单文件前端（已废弃，不再维护）
└── docs/                        # 架构快照、sprint 规范
```

## 当前进展
**已完成**：
- 前端从旧 HTML 5500 行迁移到 React + TS（21 个 features）
- 完整凭证流程：流水录入 → AI 生成 → 审核 → 过账 → 月末结账
- 报表：试算平衡、明细账、资产负债表、利润表（双标准）+ 验证工具（Excel diff）
- 多租户隔离：TenantMixin + ContextVar + SQLAlchemy 拦截器自动注入 filter
- JWT 鉴权 + 租户上下文已在 `get_current_user` 中自动设置（commit `2506414`）
- 4 个新页面已上线：审计日志、发票管理、AI 财税顾问、RAG 知识库

**待实现 / TODO**：
- 现金流量表 / 权益变动表前端页面（后端 API 已存在）
- 账套向导（涉及租户上下文架构调整）
- 税务规划页（需要后端新增 `/api/analytics/tax-plan` 端点）
- DDL 与 `models/account_set.py` 等 ORM 模型字段不一致，需统一

## 踩过的坑
- **数据库字符集**：DDL 没指定 charset，旧数据用非 UTF-8 连接导入会变 `????`（字节已损坏不可恢复）。新建表/列必须显式 `CHARACTER SET utf8mb4`
- **useToast 不稳定引用**：toast 函数若每次渲染都新建，会让 `useCallback([..., error])` 无限循环。`useToast.ts` 已用 `useCallback` 包装
- **401 vs 400**：前端 `api/client.ts` 在收到 401 时自动登出。后端业务错误（如"未设置租户上下文"）必须用 400，不能用 401
- **租户上下文**：`set_current_tenant()` 必须在 **async middleware** 里设置（main.py 已加），不能只放在 sync `get_current_user` 里——sync 函数跑在 worker thread，那里 set 的 ContextVar 回不到主 event loop，endpoint 处理时拿不到
- **ORM 与 DDL 不同步**：`AccountSet` 模型有 `is_deleted/company_name` 等字段，实际表里没有 → ORM 查询会 500。涉及该表时用原生 SQL
- **Windows 终端 cp1252**：`py -3.12 -c "..."` 里直接含中文 print 会 `UnicodeEncodeError`。中文脚本写到 `.py` 文件再运行；或用 HEX/repr 输出
- **种子文件没流水数据**：`operational_record` 的内容是用户输入的，重置后需要从前端重录

## 下一步
- 用户已清空 `voucher_line/voucher_header/operational_record`，正在前端重新录入业务数据
- 等用户录入若干流水后，验证 AI 凭证生成 + 报表计算是否正常
