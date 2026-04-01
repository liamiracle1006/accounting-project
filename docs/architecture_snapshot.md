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

## 6. 待办：Sprint 1（Habit RAG）接口约定

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
