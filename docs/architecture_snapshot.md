# AgentLedger V4.0 — Architecture Snapshot (Sprint 0)

> 生成时间：2026-04-01  
> 当前分支：`feature/v4-saas-core`  
> 用途：为后续 Sprint 和新 AI 上下文提供架构速查手册

---

## 1. 新增核心表结构

### 1.1 `tenant` — 顶层租户

| 字段 | 类型 | 说明 |
|------|------|------|
| `tenant_id` | BIGINT PK AUTO | 租户唯一标识 |
| `tenant_name` | VARCHAR(200) | 企业/租户名称 |
| `contact_email` | VARCHAR(200) NULL | 主联系人邮箱 |
| `status` | VARCHAR(20) | `TRIAL` / `ACTIVE` / `SUSPENDED` |
| `created_at` / `updated_at` | DATETIME | 时间戳 |

> 一个 tenant 对应一家购买 SaaS 服务的企业。

---

### 1.2 `account_set` — 账套（铁律二的生命周期容器）

| 字段 | 类型 | 说明 |
|------|------|------|
| `account_set_id` | BIGINT PK AUTO | 账套唯一标识 |
| `tenant_id` | BIGINT FK→tenant | 所属租户 |
| `account_set_name` | VARCHAR(200) | 如"2026年度账"、"子公司账套" |
| `fiscal_year_start_month` | INT DEFAULT 1 | 会计年度起始月（中国默认1月） |
| `accounting_standard` | VARCHAR(20) | `SMALL_BIZ` / `GENERAL` |
| `status` | VARCHAR(30) | 见下方生命周期 |
| `activated_at` | DATETIME NULL | 状态切为 READY 时记录 |

**账套生命周期（铁律二的核心）：**
```
ONBOARDING  ──►  READY_FOR_VOUCHERS  ──►  SUSPENDED
    ↑
期初余额导入阶段
借贷不平 → 差额走 1901
正式启用后日常分录必须严格借贷相等
```

---

## 2. 全量业务表多租户字段分布

| 表 | tenant_id | account_set_id | 说明 |
|----|-----------|---------------|------|
| `operational_record` | ✓ | ✓ | 拦截器自动过滤 |
| `voucher_header` | ✓ | ✓ | 拦截器自动过滤 |
| `voucher_line` | ✓ | ✓ | 拦截器自动过滤 |
| `enterprise_profile` | ✓ | ✓ | 拦截器自动过滤 |
| `asset_register` | ✓ | ✓ | 拦截器自动过滤 |
| `auxiliary_entity` | ✓ | ✓ | 拦截器自动过滤 |
| `accounting_period` | ✓ | ✓ | 拦截器自动过滤 |
| `boss_decision_log` | ✓ | ✓ | 拦截器自动过滤 |
| `tax_annual_plan` | ✓ | ✓ | 拦截器自动过滤 |
| `expense_request` | ✓ | ✓ | 拦截器自动过滤 |
| `invoice` | ✓ | ✓ | 拦截器自动过滤 |
| `department` | ✓ | ✓ | 拦截器自动过滤 |
| `user_account` | ✓ | — | 手动过滤，用户跨账套访问 |
| `audit_log` | ✓ | — | 手动过滤，审计跨账套查询 |
| `account_subject` | — | — | 共享系统表，中国统一会计科目 |

---

## 3. TenantSession 拦截器实现（全局防穿透）

### 3.1 原理图

```
FastAPI Request
    │
    ▼
[Middleware / Dependency]
    │  set_current_tenant(TenantContext(tenant_id=X, account_set_id=Y))
    ▼
contextvars.ContextVar  ←──── 每个 async Task 独立，不跨请求泄漏
    │
    ▼
SQLAlchemy Session.execute()
    │
    ▼
[@event.listens_for(SessionLocal, "do_orm_execute")]
    │  读取 ContextVar → 构建 with_loader_criteria
    ▼
ORM Query + WHERE tenant_id=X AND account_set_id=Y  （自动注入）
    │
    ▼
MySQL
```

### 3.2 核心代码位置

**`database/tenant_context.py`** — 存取 TenantContext：
```python
@dataclass(frozen=True)
class TenantContext:
    tenant_id: int
    account_set_id: int | None = None   # None = 管理员视角（跨账套）

_current_tenant: ContextVar[TenantContext | None] = ContextVar("_current_tenant", default=None)

def get_current_tenant() -> TenantContext | None: ...
def set_current_tenant(ctx: TenantContext) -> None: ...
```

**`database/connection.py`** — SQLAlchemy 事件拦截器：
```python
@event.listens_for(SessionLocal, "do_orm_execute")
def _apply_tenant_filter(execute_state):
    if execute_state.is_select and not execute_state.is_column_load \
            and not execute_state.is_relationship_load:
        ctx = get_current_tenant()
        if ctx is None:
            return                          # 后台任务/迁移：不注入，直接放行
        _ctx = ctx                          # 捕获局部变量，避免异步环境下闭包逃逸

        def _criteria(cls):
            crit = cls.tenant_id == _ctx.tenant_id
            if _ctx.account_set_id is not None:
                crit = crit & (cls.account_set_id == _ctx.account_set_id)
            return crit

        execute_state.statement = execute_state.statement.options(
            with_loader_criteria(TenantMixin, _criteria, include_aliases=True)
        )
```

**`models/mixins.py`** — 被拦截器识别的 Mixin 标记：
```python
class TenantMixin:
    tenant_id:      Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    account_set_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
```

### 3.3 防穿透保障

| 场景 | 行为 |
|------|------|
| 正常请求（已设置 TenantContext） | 自动注入 `WHERE tenant_id=X AND account_set_id=Y` |
| 后台任务（`BackgroundTasks`，未设置 Context） | `ctx=None`，拦截器放行，服务层需手动传参 |
| 管理员跨账套查询（`account_set_id=None`） | 只注入 `WHERE tenant_id=X`，跨账套可见 |
| 关系加载（`is_relationship_load=True`） | 短路跳过，避免递归 |
| 列加载（`is_column_load=True`） | 短路跳过，避免递归 |

---

## 4. DDL 当前状态

**文件：** `database/ddl.sql`  
**版本：** V4.0（完全重写，不兼容 V3.0）

**表顺序（按 FK 依赖）：**
```
account_subject (共享，无租户)
    ↓
tenant
    ↓
account_set  ←── FK→tenant
    ↓
user_account ←── FK→tenant
department   ←── FK→tenant, account_set
auxiliary_entity ←── FK→tenant, account_set
enterprise_profile ←── FK→tenant, account_set
    ↓
operational_record ←── FK→tenant, account_set
    ↓
voucher_header ←── FK→operational_record, tenant, account_set
voucher_line   ←── FK→voucher_header, account_subject, auxiliary_entity, tenant, account_set
boss_decision_log ←── FK→operational_record, tenant, account_set
    ↓
asset_register ←── FK→voucher_header, boss_decision_log, tenant, account_set
accounting_period ←── FK→tenant, account_set
audit_log ←── FK→tenant
invoice ←── FK→tenant, account_set
expense_request ←── FK→tenant, account_set
tax_annual_plan ←── FK→enterprise_profile, tenant, account_set
```

**关键索引设计：**
- 所有业务表均有 `INDEX idx_xxx_tenant_as (tenant_id, account_set_id)` 复合索引
- `accounting_period` UNIQUE 约束从 `(year, month)` 扩展为 `(tenant_id, account_set_id, year, month)`
- `invoice` UNIQUE 约束从 `(invoice_code, invoice_number)` 扩展为含 tenant+account_set

---

## 5. seed_demo.sql 当前状态

**文件：** `database/seed_demo.sql`  
**状态：** ⚠️ 尚未更新为 V4.0 格式

V3.0 的演示数据**不含** `tenant_id` / `account_set_id` 字段，无法直接在 V4.0 DDL 上执行。

**Sprint 2（Sponge 建账）开发时需同步更新：**
```sql
-- 需要先插入 tenant 和 account_set 种子数据
INSERT INTO tenant (tenant_id, tenant_name, status) VALUES (1, '星辰科技有限公司', 'ACTIVE');
INSERT INTO account_set (account_set_id, tenant_id, account_set_name, status)
    VALUES (1, 1, '2026年度账', 'READY_FOR_VOUCHERS');

-- 所有业务表 INSERT 需补充 tenant_id=1, account_set_id=1
```

---

## 6. Sprint 1 交付：智能账套管理系统

> 完成时间：2026-04-02  
> 涉及文件：`models/account_set.py` · `services/account_set_service.py` · `services/crypto_utils.py` · `api/account_set_routes.py`

---

### 6.1 `account_set` 表完整字段（V4.0 Sprint 1）

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `account_set_id` | BIGINT PK AUTO | — | 账套唯一标识 |
| `tenant_id` | BIGINT FK→tenant | — | 顶层租户隔离，有索引 |
| `account_set_name` | VARCHAR(200) | — | 账套显示名称 |
| `company_name` | VARCHAR(200) | — | 公司全称（来自营业执照） |
| `start_period` | VARCHAR(7) | — | 启用年月 `YYYY-MM`，**铁律二保护字段** |
| `fiscal_year_start_month` | INT | `1` | 会计年度起始月（中国默认1月） |
| `accounting_standard` | VARCHAR(30) | `小企业会计准则` | 枚举：`小企业会计准则` / `企业会计准则`，**铁律二保护字段** |
| `taxpayer_type` | VARCHAR(20) | `小规模纳税人` | 枚举：`小规模纳税人` / `一般纳税人` |
| `uscc` | VARCHAR(18) NULL | — | 统一社会信用代码，AI 查验发票合规的核心依据 |
| `tax_bureau_region` | VARCHAR(100) NULL | — | 报税地区 |
| `tax_password` | VARCHAR(500) NULL | — | 电子申报密码（**Fernet AES-128 加密存储**） |
| `module_settings` | TEXT NULL | — | JSON 功能开关，如 `{"asset_module":true,"decimals":2}` |
| `status` | VARCHAR(30) | `ONBOARDING` | `ONBOARDING` / `ACTIVE` / `RECYCLED` / `SUSPENDED` |
| `is_deleted` | BOOLEAN | `False` | **软删除标记**，True = 在回收站 |
| `deleted_at` | DATETIME NULL | — | 进入回收站的时间戳 |
| `activated_at` | DATETIME NULL | — | 正式启用时间（切为 ACTIVE 时写入） |
| `created_at` / `updated_at` | DATETIME | `NOW()` | 审计时间戳 |

**账套生命周期（扩展版）：**
```
ONBOARDING  ──► ACTIVE  ──► SUSPENDED
    │               │
    │    软删除      │    软删除
    └──────────────►┴──────► RECYCLED ──► (restore) ──► ACTIVE / ONBOARDING
```

---

### 6.2 软删除机制（Recycle Bin）

**核心原则：绝不执行 `SQL DELETE`。**

| 操作 | 行为 |
|------|------|
| `DELETE /api/account-sets/{id}` | `is_deleted=True`, `status=RECYCLED`, `deleted_at=now()` |
| `POST /api/account-sets/{id}/restore` | `is_deleted=False`, `deleted_at=NULL`, `status` 恢复为删除前值 |
| 所有业务查询（凭证、报表） | Service 层 `filter(is_deleted=False)` 自动防穿透 |

**查询防穿透实现位置：**
- `services/account_set_service.py` → `_get_active_account_set()` — 单账套查询强制验证 `is_deleted=False`
- `services/account_set_service.py` → `list_account_sets(include_recycled=False)` — 列表默认过滤
- TenantSession 拦截器（`database/connection.py`）— 在 `account_set_id` 层面自动隔离

---

### 6.3 铁律二守门逻辑（Financial Continuity）

`start_period` 和 `accounting_standard` 一旦账套产生有效凭证后不可修改。

**代码位置：** `services/account_set_service.py:update_account_set()`

```python
if (data.start_period or data.accounting_standard) and _has_vouchers(db, account_set_id):
    raise AccountSetLockedError(...)  # → HTTP 409 Conflict
```

`_has_vouchers()` 查询 `voucher_header` 表是否存在该 `account_set_id` 的记录。

---

### 6.4 铁律一落点（Habit RAG — 营业执照解析）

**代码位置：** `services/account_set_service.py:parse_license()`

```
POST /api/account-sets/parse-license (UploadFile)
    │
    ▼
① _retrieve_tenant_account_habits(db, tenant_id)
    └─ 查询该租户历史 AccountSet，统计 accounting_standard / taxpayer_type 多数派
    │
    ▼
② _build_license_prompt(habits)
    └─ 将历史多数派作为 few-shot 强约束嵌入 Vision LLM prompt
    │
    ▼
③ Vision LLM（Qwen-VL-Max / GPT-4V）
    └─ 提取 company_name / uscc / registered_capital / 推荐值
    │
    ▼
④ 返回 ParsedLicenseData → 前端表单预填，用户确认后调用 POST /api/account-sets
```

---

### 6.5 `tax_password` Fernet 加密（`services/crypto_utils.py`）

**算法：** Fernet = AES-128-CBC + HMAC-SHA256（`cryptography` 库）

#### 必须配置的 .env 环境变量

```dotenv
# ── 账套税务密码字段加密密钥 ────────────────────────────────────────
# 算法：Fernet（AES-128-CBC + HMAC-SHA256）
# 生成命令：
#   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# 将输出的 44 字符 base64url 字符串填入此处。
# ⚠️  生产环境必填。未配置时退化为明文存储（前缀 "plain:"），有安全风险。
FIELD_ENCRYPTION_KEY=your-fernet-key-here
```

**降级行为（开发环境）：**
- `FIELD_ENCRYPTION_KEY` 未设置 → `tax_password` 以 `plain:xxx` 前缀明文存储，并打印 WARNING 日志
- 加密/解密函数（`encrypt_field` / `decrypt_field`）自动识别前缀，向后兼容

**API 脱敏：** `GET /api/account-sets/{id}` 响应中 `tax_password` 字段替换为 `has_tax_password: bool`，原文永不出现在 HTTP 响应体中。

---

### 6.6 Sprint 1 API 路由总表

**Router 前缀：** `/api/account-sets`（注册于 `main.py`，受 JWT 鉴权保护）

| 方法 | 路径 | 功能 | 关键逻辑 |
|------|------|------|----------|
| `POST` | `/parse-license` | 营业执照 Vision LLM 解析 | Iron Law 1 Habit RAG |
| `GET` | `` | 账套列表 | `include_recycled` 参数 |
| `POST` | `` | 创建账套 | `start_period` 格式校验 |
| `GET` | `/recycle-bin` | 回收站列表 | `is_deleted=True` 专属查询 |
| `GET` | `/{id}` | 查询单账套 | 脱敏 `tax_password` |
| `PATCH` | `/{id}` | 更新账套 | Iron Law 2 守门 → 409 |
| `POST` | `/{id}/activate` | 激活账套 | ONBOARDING → ACTIVE |
| `DELETE` | `/{id}` | 软删除（进回收站） | 只写标记，不 DELETE |
| `POST` | `/{id}/restore` | 从回收站恢复 | 状态自动推断 |
| `POST` | `/{id}/clone` | 账套克隆 | `settings` / `accounting_subjects`（Sprint 2 落地） |

---

## 7. 待办：Sprint 1（Habit RAG）接口约定

下一步在 `services/habit_retrieval_service.py` 实现，调用方签名预留：

```python
class HabitRetrievalService:
    def get_habits(
        self,
        expense_type_keyword: str,
        top_k: int = 5,
    ) -> list[HabitPattern]:
        """
        从 voucher_line（单一数据源，Single Source of Truth）检索
        当前账套历史中最常见的分录模式。
        结果注入 LLM prompt 作为 few-shot 示例。
        未来 Graph RAG 升级时直接复用此数据源。
        """
        ...
```
