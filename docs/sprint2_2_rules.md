# AgentLedger V4.0 — Sprint 2.2 实施规则手册

> 本文件包含 Sprint 2.2（期初基线与海绵建账）所有实施规则、架构约束和待办任务。
> 新 session 读取此文件即可继续开发。

---

## 一、项目全局铁律（永久生效）

### 铁律 1：Habit RAG（习惯检索增强生成）
- 任何 AI 生成业务结论前，必须先从该租户历史数据中检索模式（few-shot context）
- 当前落点：`account_set_service.py` 中 `parse_license()` 调用 `_retrieve_tenant_account_habits()`

### 铁律 2：Financial Continuity（财务连续性）
- `start_period`（启用年月）和 `accounting_standard`（会计准则）一旦产生有效凭证（voucher）后 **永久锁定，禁止修改**
- 海绵建账（1901 待处理财产损溢）自动配平不平衡的期初导入
- 落点：
  - `account_set_service.py` → `update_account_set()` 中 `_has_vouchers()` 检查
  - `subject_service.py` → `update_subject()` 中 `_has_voucher_lines()` 检查
  - Sprint 2.2 新增：`initial_balance_service.py` → `_check_locked()` 检查

---

## 二、技术栈与架构约束

### 技术栈
| 组件 | 版本 |
|------|------|
| FastAPI | 0.115.5 |
| SQLAlchemy | 2.0.36（ORM mapped_column 风格）|
| MySQL | PyMySQL 1.1.1 |
| Pydantic | 2.10.3（V2，用 model_validator）|
| openpyxl | 3.1.5（Sprint 2.2 新增，需加入 requirements.txt）|

### 多租户隔离
- 所有业务表继承 `TenantMixin`（提供 `tenant_id` + `account_set_id`）
- `database/connection.py` 中的 SQLAlchemy `do_orm_execute` 事件拦截器自动注入 WHERE 过滤
- `TenantContext` 存储在 `contextvars.ContextVar`，每请求隔离，无跨请求泄漏
- 文件：`database/tenant_context.py`，`models/mixins.py`

### 软删除规则
- **永远不执行 SQL DELETE**，只设 `is_deleted=True` + `deleted_at=now()`
- 所有查询默认过滤 `is_deleted=False`

### API 上下文注入模式
```python
def _get_ctx(db: Session = Depends(get_db)) -> tuple[int, int]:
    from database.tenant_context import get_current_tenant
    ctx = get_current_tenant()
    if ctx is None:
        raise HTTPException(status_code=401, detail="未设置租户上下文，请先登录")
    if ctx.account_set_id is None:
        raise HTTPException(status_code=400, detail="请先选择账套（account_set_id 未设置）")
    return ctx.tenant_id, ctx.account_set_id
```

### 路由注册模式（main.py）
```python
from services.auth_service import get_current_user
_auth = [Depends(get_current_user)]
app.include_router(some_router, dependencies=_auth)
```

---

## 三、已完成的文件（Sprint 2.2 前置）

### 1. `models/accounting.py` ✅
包含三个 ORM 模型：
- **SystemSubject**：系统标准科目模板，全局只读，无 TenantMixin
- **TenantSubject**：租户科目实例，UNIQUE(tenant_id, account_set_id, subject_code)
  - `node_features` JSON TEXT 存储数量核算/外币/辅助维度配置
  - `graph_node_id` 属性：`f"{tenant_id}::{account_set_id}::{subject_code}"`
- **InitialBalance**（Sprint 2.2 已追加）：期初余额台账
  - UNIQUE(tenant_id, account_set_id, subject_code, auxiliary_hash)
  - 字段：initial_balance, ytd_debit, ytd_credit, year_start_balance
  - 外币：currency_code, foreign_currency_amount, exchange_rate
  - 数量：quantity, unit_price
  - 辅助：auxiliary_hash（String(64), default=""）, auxiliary_details（Text JSON）
  - 海绵：is_ai_sponge（Boolean, default=False）

### 2. `schemas/initial_balance_schemas.py` ✅
- `AuxiliaryEntry`：type, id, name
- `InitialBalanceInput`：所有输入字段（无 year_start_balance），含 non_negative_amounts 校验器
- `BatchSaveInput`：rows: list[InitialBalanceInput]
- `InitialBalanceResponse`：含 direction_warning（Optional[str]）
- `SubjectWithBalance`：科目树节点 + 余额字段 + children[]
- `TrialBalanceLine`：dimension, total_debit, total_credit, difference, is_balanced
- `TrialBalanceResult`：lines[], is_balanced, sponge_amount
- `ForeignTrialBalanceLine`：currency_code, total_debit, total_credit, difference, is_balanced
- `CompleteAccountSetupResult`：success, account_set_id, final_status, was_balanced, sponge_amount, sponge_subject, message

### 3. `models/account_set.py` ✅
- `AccountSetStatus`：ONBOARDING / ACTIVE / RECYCLED / SUSPENDED
- `AccountingStandard`：小企业会计准则 / 企业会计准则
- `AccountSet` 字段：account_set_id(PK), tenant_id, start_period(YYYY-MM), accounting_standard, status, activated_at, subject_code_rule("4-2-2-2-2"), is_deleted 等

### 4. `services/subject_service.py` ✅
- `SubjectService` 类，含异常：SubjectNotFoundError, SubjectCodeConflictError, SubjectLockedError, SubjectHasBalanceError, SubjectCodeRuleError
- 68 条标准科目种子数据（`_SEED_SUBJECTS`），含 1901 待处理财产损溢
- 方法：seed_system_subjects, init_tenant_subjects, create_subject, update_subject, delete_subject, get_subject_tree, detect_refactor_opportunity

### 5. `api/subject_routes.py` ✅
- 前缀 `/api/subjects`，9 个端点 + /seed-system + /init/{id}
- 使用 `_get_ctx()` 模式注入 tenant_id, account_set_id

---

## 四、待实现任务清单（Sprint 2.2）

### 文件 A：`services/initial_balance_service.py`（新建）

#### 工具函数

**`_compute_auxiliary_hash(auxiliary_details: list[AuxiliaryEntry]) -> str`**（M1）
- 无辅助（空列表）→ 返回 `""`
- 有辅助 → `hashlib.md5(json.dumps(sorted(entries, key=lambda x: (x.type, x.id)), ensure_ascii=False).encode()).hexdigest()`

**`_compute_year_start(initial, ytd_debit, ytd_credit, direction) -> float`**（G2.2）
- 借方科目（direction=="借"）：`year_start = initial + ytd_credit - ytd_debit`
- 贷方科目（direction=="贷"）：`year_start = initial + ytd_debit - ytd_credit`
- **禁止前端传入 year_start_balance，API Schema 中无此字段**

**`_is_january_start(account_set) -> bool`**
- 读取 `account_set.start_period`（格式 "YYYY-MM"），月份部分 == "01" 则 True

**`_check_locked(db, tenant_id, account_set_id) -> None`**（M5）
- 查 AccountSet，若 status == ACTIVE 且存在 voucher_header 记录 → 抛 `InitialBalanceLockedError`
- 注意：voucher_header 表可能尚不存在，用 try/except 处理 ProgrammingError

#### class InitialBalanceService

**方法 1：`save_balance(db, tenant_id, account_set_id, input: InitialBalanceInput)`**
实现 G2.1 + G2.2 + M1 + M4：
1. 查 TenantSubject 获取科目信息（不存在 → 404 SubjectNotFoundError）
2. 调 `_check_locked()` 检查是否锁定
3. 查 AccountSet 获取 start_period，若 `_is_january_start()` → 强制 `ytd_debit=0, ytd_credit=0`（G2.1）
4. 调 `_compute_year_start()` 计算 year_start_balance（G2.2）
5. 余额方向异常检查（M4）：借方科目 initial_balance 实际为贷方余额 → 设 direction_warning，**不阻塞保存**
6. 数量×单价一致性检查：`quantity * unit_price != initial_balance` → warning
7. 调 `_compute_auxiliary_hash()` 计算 auxiliary_hash（M1）
8. UPSERT（按 tenant_id + account_set_id + subject_code + auxiliary_hash 查找，存在则更新，不存在则新建）
9. 若为辅助核算记录（auxiliary_hash != ""），重新聚合该科目的汇总记录（auxiliary_hash=""的那条）
10. **递归向上聚合父科目**（G2.3）：根据 parent_code 层层向上，每层重新 SUM 所有子科目的 initial_balance/ytd_debit/ytd_credit，重新计算 year_start_balance
11. 返回 InitialBalanceResponse（含 direction_warning）

**方法 2：`batch_save(db, tenant_id, account_set_id, input: BatchSaveInput)`**（M2）
- 循环调用 `save_balance()`，收集所有 warnings
- 事务整体提交（一行失败全部回滚）
- 返回 `{saved: int, warnings: list[str]}`

**方法 3：`get_balances_with_subjects(db, tenant_id, account_set_id)`**（M3）
- 一次 SELECT TenantSubject LEFT JOIN InitialBalance（只取 auxiliary_hash=""的汇总记录）
- Python 内存中构建 SubjectWithBalance 树（同 subject_tree 的构建逻辑）
- 返回 `list[SubjectWithBalance]`

**方法 4：`calculate_trial_balance(db, tenant_id, account_set_id)`**（G3.1）
- 只取一级科目（level=1）的 InitialBalance（auxiliary_hash=""）
- 按 balance_direction 分组，计算 4 个维度：
  - 期初余额：借方科目 initial_balance 之和 vs 贷方科目 initial_balance 之和
  - 本年累计借方：所有 ytd_debit 之和 vs 所有 ytd_credit 之和（按方向分）
  - 本年累计贷方：同上反向
  - 年初余额：借方科目 year_start_balance 之和 vs 贷方科目 year_start_balance 之和
- 每个维度算 difference = total_debit - total_credit
- is_balanced = 所有维度的 difference 均为 0
- sponge_amount = 最大的 |difference|
- 返回 TrialBalanceResult

**方法 5：`calculate_foreign_trial_balance(db, tenant_id, account_set_id, currency_code)`**（G3.2）
- 筛选 currency_code 匹配的 InitialBalance 记录
- 对 foreign_currency_amount 按 balance_direction 求借贷合计
- 返回 ForeignTrialBalanceLine

**方法 6：`complete_account_setup(db, tenant_id, account_set_id)`**（G5.1 海绵熔断）
1. 调 `calculate_trial_balance()` 获取试算结果
2. 若已平衡 → 直接切 ACTIVE
3. 若不平衡：
   a. 确保 1901（待处理财产损溢）科目存在于 TenantSubject（没有则从 SystemSubject 克隆创建）
   b. 计算差额：`sponge = total_debit - total_credit`（期初余额维度）
   c. 写入/更新 1901 的 InitialBalance 记录：
      - 若 sponge > 0（借方多）→ initial_balance = sponge（放贷方填平）  
      - 若 sponge < 0（贷方多）→ initial_balance = |sponge|（放借方填平）
      - `is_ai_sponge=True`
   d. 重新试算确认平衡
4. 账套 status → ACTIVE，activated_at = now()
5. 返回 CompleteAccountSetupResult

**方法 7：`reopen_account_setup(db, tenant_id, account_set_id)`**（M5）
1. 查 AccountSet，必须是 ACTIVE 状态
2. 检查是否有 voucher_header 记录 → 有则拒绝（HTTP 409）
3. 账套 status → ONBOARDING，activated_at = None
4. 返回 success message

**方法 8：`export_template(db, tenant_id, account_set_id) -> bytes`**（G4.1）
- 读取 TenantSubject 列表（is_deleted=False）
- 用 openpyxl 创建 Excel 工作表
- 列：科目编码 | 科目名称 | 余额方向 | 期初余额 | 本年累计借方 | 本年累计贷方
- 非叶子科目（有子科目的）行灰色背景，提示"汇总行，请勿手工填写"
- 叶子科目行空白待填
- 返回 BytesIO 的 bytes

**方法 9：`import_from_excel(db, tenant_id, account_set_id, file_bytes) -> dict`**（G4.2）
- openpyxl 解析上传文件
- 按"科目编码"列匹配 TenantSubject
- 找不到编码 → 收集错误（行号+原因），**不中断其他行**
- 匹配到的行调用 `save_balance()`
- 返回 `{imported: int, errors: [{row, reason}], warnings: [str]}`

#### 异常类
- `InitialBalanceLockedError(Exception)` — ACTIVE 且有凭证时拒绝修改
- 复用 `SubjectNotFoundError` from subject_service

### 文件 B：`api/initial_balance_routes.py`（新建）

前缀：`/api/initial-balances`，tags=["initial-balances"]

| 方法 | 路径 | 功能 | Service 方法 |
|------|------|------|-------------|
| POST | `/` | 保存单条期初余额 | save_balance() |
| POST | `/batch-save` | 批量保存 | batch_save() |
| GET | `/with-subjects` | 科目树+余额联合查询 | get_balances_with_subjects() |
| GET | `/trial-balance` | 本位币试算平衡 | calculate_trial_balance() |
| GET | `/foreign-trial-balance` | 外币试算平衡（query: currency_code） | calculate_foreign_trial_balance() |
| POST | `/complete` | 完成建账（海绵熔断） | complete_account_setup() |
| POST | `/reopen` | 重新开账 | reopen_account_setup() |
| GET | `/export-template` | 下载 Excel 模板 | export_template() → StreamingResponse |
| POST | `/import` | 导入 Excel | import_from_excel() ← UploadFile |

Context 注入：同 subject_routes 的 `_get_ctx()` 模式。
异常映射：InitialBalanceLockedError → 409，SubjectNotFoundError → 404，ValueError → 422。

### 文件 C：`requirements.txt`（修改）
添加一行：`openpyxl==3.1.5`

### 文件 D：`main.py`（修改）
在 import 区添加：
```python
from api.initial_balance_routes import router as initial_balance_router
```
在路由注册区添加：
```python
app.include_router(initial_balance_router, dependencies=_auth)
```

---

## 五、关键业务公式

### year_start_balance 防篡改公式
```
借方科目：year_start = initial_balance + ytd_credit - ytd_debit
贷方科目：year_start = initial_balance + ytd_debit  - ytd_credit
特例：1月开账 → ytd_debit = ytd_credit = 0 → year_start = initial_balance
```

### auxiliary_hash 计算
```python
import hashlib, json
def _compute_auxiliary_hash(details: list) -> str:
    if not details:
        return ""
    sorted_entries = sorted(
        [{"type": d.type, "id": d.id, "name": d.name} for d in details],
        key=lambda x: (x["type"], x["id"])
    )
    return hashlib.md5(
        json.dumps(sorted_entries, ensure_ascii=False).encode()
    ).hexdigest()
```

### 科目编码规则 "4-2-2-2-2"
- level 1 = 4 位（1001）
- level 2 = 父编码 + 2 位（100101）
- level 3 = 父编码 + 2 位（10010101）

### 海绵建账（1901 配平）
- 科目编码：1901，科目名称：待处理财产损溢，类别：资产，方向：借
- 试算不平衡时自动创建/更新 1901 的 InitialBalance 记录
- `is_ai_sponge=True` 标记，供前端高亮提示

---

## 六、关键约束总结

1. `year_start_balance` 禁止前端传入，Schema 中无此字段，后端自动推导
2. 永远不执行 SQL DELETE，只改 `is_deleted=True`
3. 所有查询经 TenantMixin 拦截器自动隔离
4. openpyxl 的 import 用 `try/except ImportError`，未安装返回 HTTP 503
5. 1月开账时强制 `ytd_debit = ytd_credit = 0`
6. 余额方向异常只警告（direction_warning），不阻塞保存
7. 父科目余额 = 所有子科目余额自动聚合，**不允许手工录入**
8. 海绵记录（1901）完成建账后自动生成，`is_ai_sponge=True`
9. ACTIVE 状态且有凭证 → 期初余额只读，修改被拒绝（409）
10. reopen 重新开账：仅允许 ACTIVE 且无凭证时操作

---

## 七、现有目录结构参考

```
accounting-project/
├── main.py                          # FastAPI 入口，路由注册
├── requirements.txt                 # 依赖（需加 openpyxl）
├── config/settings.py               # 配置
├── database/
│   ├── connection.py                # SQLAlchemy engine + get_db + 拦截器
│   └── tenant_context.py            # TenantContext ContextVar
├── models/
│   ├── mixins.py                    # TenantMixin (tenant_id + account_set_id)
│   ├── account_set.py               # AccountSet, AccountSetStatus
│   └── accounting.py                # SystemSubject, TenantSubject, InitialBalance
├── schemas/
│   ├── subject_schemas.py           # 科目相关 Pydantic schemas
│   └── initial_balance_schemas.py   # 期初余额 Pydantic schemas ✅
├── services/
│   ├── auth_service.py              # JWT 鉴权 + get_current_user
│   ├── account_set_service.py       # 账套 CRUD + OCR + Iron Law 2
│   ├── subject_service.py           # 科目 CRUD + 骨架初始化
│   ├── crypto_utils.py              # Fernet AES 加解密
│   └── initial_balance_service.py   # ❌ 待创建
├── api/
│   ├── account_set_routes.py        # /api/account-sets
│   ├── subject_routes.py            # /api/subjects
│   └── initial_balance_routes.py    # ❌ 待创建 → /api/initial-balances
└── docs/
    └── architecture_snapshot.md     # Sprint 0 架构快照
```

---

## 八、验证方式

1. **语法检查**：`python -c "import ast; ast.parse(open('file.py').read())"` 对每个新/改文件
2. **POST /api/initial-balances** 保存单条余额，验证 year_start_balance 自动计算
3. **POST /api/initial-balances/batch-save** 批量提交，验证父科目聚合
4. **GET /api/initial-balances/trial-balance** 验证借贷平衡四维度
5. **POST /api/initial-balances/complete** 触发海绵熔断，验证 1901 记录生成
6. **GET /api/initial-balances/export-template** 下载 Excel 验证列结构
7. **POST /api/initial-balances/import** 上传 Excel 验证逐行解析和错误收集

---

## 九、Git 分支

开发分支：`claude/pattern-learning-rag-bQor1`
所有提交推到此分支。
