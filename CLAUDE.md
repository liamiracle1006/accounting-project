# AgentLedger — 项目上下文

> Claude Code 维护规则：每次对话结束前更新「当前进展」「踩过的坑」「下一步」三个 section，**替换不追加**，总长 < 150 行。深入资料见 `README.md` / `DEV_SETUP.md` / `SPRINT_NOTES.md` / `TESTING_AND_PLAN.md` / `docs/`。活跃任务计划在 `C:\Users\wangzy\.claude\plans\resilient-moseying-scone.md`。

## 项目目标
- 面向小微企业的 **AI 辅助复式记账系统**：自然语言/原始单据 → AI 生成借贷凭证 → 财务审核入账 → 标准会计报表
- 双标准支持：企业会计准则（6xxx）+ 小企业会计准则（5xxx/3xxx）
- 调用方式：用户从 Telegram 经 OpenClaw（`c:/Users/wangzy/Desktop/hobby/open_claw`）以 `claude --print` 在本项目内执行任务
- **多租户架构超前设计未真正接入**——见"踩过的坑"，目前实际单租户运行（tenant_id=1，account_set_id=1）

## 技术栈
| 层 | 技术 | 说明 |
|---|---|---|
| 前端 | React 18 + TypeScript + Vite + Tailwind + Zustand | Feature-Sliced 架构，22 个 features 模块 |
| 后端 | Python 3.12 + FastAPI + SQLAlchemy 2.x | 24 个 route 文件 |
| 数据库 | MySQL 8.4 | 必须 `charset=utf8mb4`；DDL 在 `database/ddl.sql`（**与多个 ORM 模型字段不一致**）|
| AI | OpenAI 兼容 LLM（gpt-4o-mini）+ JSON mode + tool calling | LLM_API_KEY 配在 `.env` |
| 认证 | JWT（python-jose）+ bcrypt | `services/auth_service.py` |
| 向量库 | ChromaDB（可选） | `chroma_db/`；未装时 `/api/rag/*` 返回 503 |

## 文件结构（要点）
```
accounting-project/
├── main.py                          # FastAPI 入口；不要再加 tenant context middleware
├── database/
│   ├── connection.py                # SQLAlchemy engine + tenant interceptor（永久 no-op，因 ctx=None）
│   ├── tenant_context.py            # ContextVar — 设计存在但生产路径不用
│   ├── ddl.sql                      # 建表 SQL（与多个 ORM 模型字段不同步！）
│   └── seed_local.sql               # 种子：科目、租户、账套、3 个用户
├── api/                             # 24 个路由：8 个用 _get_ctx() 走 services/tenant_resolver.py
├── services/
│   ├── tenant_resolver.py           # ⭐ 统一 tenant ctx 解析：resolve_tenant_ctx(db, user)
│   ├── daybook_import_service.py    # 序时账 Excel 导入（A1）
│   ├── validation_service.py        # 报表验证 + compute_from_baseline_and_vouchers (A4)
│   └── ledger_service.py            # 凭证→TB 聚合（依赖 InitialBalance + 跨期凭证累计）
├── frontend/src/features/
│   ├── daybook/DaybookImportPage    # 序时账导入 UI（A3）
│   ├── validate/ValidatePage        # 双模式：A 单文件 / B 基准+凭证（A6）
│   └── ...                          # 21 个其他 features
└── docs/                            # 架构快照、sprint 规范
```

## 当前进展
**已完成**：
- **前端 React 全量迁移**：21+ feature 页（dashboard / vouchers / reports / records / assets / advisor / knowledge / audit / invoice / daybook…）
- **凭证流程**：流水→AI 生成→审核→过账→月末结账
- **报表**：试算平衡 / 明细账 / BS / IS（双标准）+ 验证工具
- **Phase A 序时账验证链路**（commit `7372e5a`）：
  - A1-A3：序时账 Excel → DRAFT 凭证（合并单元格 ffill、红字记账翻方向、10 位子码归一到 4 位母科目）
  - A4-A6：上传"上期期末科目表 + 日期范围" → 用本期 POSTED 凭证反推 BS/IS + 跟参考报表 diff
- **租户上下文统一**：8 个路由的 `_get_ctx` 走 `resolve_tenant_ctx(db, user)`，绕开 ContextVar
- **DB schema 修补**：`voucher_header` 表加了 voucher_number / voucher_word / creator_id / is_deleted 4 列与 ORM 对齐

**待实现 / TODO**：
- **A4-A6 端到端验证**（用户手动操作）：把 12 月 DRAFT 凭证全部 POSTED → 在 ValidatePage 模式 B 上传 11 月期末科目表 → 比对 12 月参考 BS/IS
- **Phase B 银行回单 / 发票 OCR**：用户已确认能提供 jpg/png 银行回单 + PDF/图片增值税发票；需 Vision API key + 样例
- 现金流量表 / 权益变动表前端页面（后端 API 已存在）
- 账套向导（涉及多租户激活，暂缓）

## 踩过的坑
- **租户上下文 ContextVar/middleware**：设计存在但从未接入 JWT。**不要再尝试加 middleware 设 ContextVar**——会触发 `database/connection.py` 的 SQLAlchemy interceptor 给所有 ORM SELECT 注入 `with_loader_criteria`，跟历史 SQL 不兼容直接 500。每个需要 ctx 的路由用 `services/tenant_resolver.py:resolve_tenant_ctx(db, user)` 从 `current_user.tenant_id` 直接查
- **ORM 与 DDL 不同步**：`VoucherHeader`、`AccountSet` 等模型字段比实际表多。`voucher_header` 已经 ALTER 加列对齐；`account_set` 涉及该表查询请用原生 SQL（`SELECT account_set_id FROM account_set WHERE tenant_id=?`）
- **数据库字符集**：DDL 没指定 charset，旧数据用非 UTF-8 连接导入会变 `????`（字节已损坏不可恢复）。新建列显式 `CHARACTER SET utf8mb4`
- **useToast 不稳定引用**：toast 函数若每次渲染都新建，会让 `useCallback([..., error])` 无限循环。`useToast.ts` 已用 `useCallback` 包装稳定下来
- **401 vs 400**：前端 `api/client.ts` 收 401 自动登出。后端业务错误（"未设置租户上下文"等）必须用 **400**
- **序时账红字记账**：Excel 中负数金额表示反方向记账（"贷方 -5.20" = "借方 +5.20"）。`daybook_import_service.py` 已处理：负数翻到对方
- **序时账子科目码归一**：荆鹏导出 5-10 位子码（如 5401004），voucher_line FK 只接受 4 位母科目码。导入时取前 4 位 → `_resolve_code` → GAAP 6xxx/4xxx；原始码+名保留到 `voucher_line.memo`
- **Windows 终端 cp1252**：`py -3.12 -c "..."` 含中文 print 会 `UnicodeEncodeError`。中文脚本写到 `.py` 文件再运行；或用 HEX/repr 输出
- **种子文件没流水数据**：`operational_record` 是用户输入，重置后需要重新录或导序时账
- **凭证 INSERT 用原生 SQL**：daybook_import 用 `db.execute(text("INSERT..."))` 是为了绕 ORM/DDL 不同步——现在 voucher_header 已对齐，可以改回 ORM 但不紧急

## 下一步
1. 用户在凭证管理页将 12 月所有 DRAFT 凭证 POSTED
2. 用户在 ValidatePage 模式 B 跑端到端：基准（11 月期末科目表）+ 12 月日期范围 + 12 月参考 BS/IS → 看 diff
3. 若 diff 有大差异：定位是凭证录入问题、4 位母科目归一不一致、还是基准表解析问题
4. A4-A6 验证通过后启动 Phase B（银行回单/发票 OCR 制单），需用户提供 Vision API key + 样例
