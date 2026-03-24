# AgentLedger V1.0 — 基于 LLM 的小微企业智能业财融合系统

## 架构概览

```
自然语言输入
     │
     ▼
┌─────────────────────────────────────────┐
│  POST /api/records                      │  ← FastAPI 入口
└─────────────────────────────────────────┘
     │
     ▼
┌─────────────────────────────────────────┐
│  RecordService                          │
│  1. 存入 operational_record (PENDING)   │
│  2. 调用 LLM API → 获取 JSON           │
│  3. 更新 extracted_json                 │
└─────────────────────────────────────────┘
     │
     ▼
┌─────────────────────────────────────────┐
│  ai/json_parser.py                      │
│  严格校验 JSON：金额>0、枚举合法等       │
└─────────────────────────────────────────┘
     │
     ▼
┌─────────────────────────────────────────┐
│  AccountingEngineService（核心护城河）  │
│  • 关键词映射 expense_type → 科目代码   │
│  • payment_method → 贷方科目            │
│  • 组装借贷分录                         │
│  • 强制校验 Σ借 == Σ贷                 │
│  • 写入 voucher_header + voucher_line   │
└─────────────────────────────────────────┘
     │
     ▼
  operational_record.status = PROCESSED
  （任何异常 → MANUAL_REVIEW + 事务回滚）
```

## 快速启动

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env，填入数据库和 LLM API 信息

# 3. 初始化数据库
mysql -u root -p agentledger < database/ddl.sql
mysql -u root -p agentledger < database/dml.sql

# 4. 启动服务
python main.py
# 或
uvicorn main:app --reload
```

访问 http://localhost:8000/docs 查看交互式 API 文档。

## API 说明

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/records` | 提交自然语言流水（核心接口） |
| GET  | `/api/records` | 分页查询流水列表，支持按 status 过滤 |
| GET  | `/api/records/{id}` | 查询单条流水 |
| GET  | `/api/vouchers/{id}` | 查询凭证详情（含借贷明细） |
| GET  | `/health` | 健康检查 |

### 请求示例

```bash
curl -X POST http://localhost:8000/api/records \
  -H "Content-Type: application/json" \
  -d '{"raw_text": "今天请客户吃饭花了800元，员工张三垫付"}'
```

### 响应示例

```json
{
  "record_id": 1,
  "status": "PROCESSED",
  "raw_text": "今天请客户吃饭花了800元，员工张三垫付",
  "extracted_json": "{\"amount\":800,\"expense_type\":\"招待费\",...}",
  "error_message": null
}
```

## 运行测试

```bash
pytest tests/ -v
```

## 项目结构

```
accounting-project/
├── main.py                      # FastAPI 应用入口
├── requirements.txt
├── .env.example
├── config/
│   └── settings.py              # 环境变量配置
├── database/
│   ├── ddl.sql                  # 建表语句
│   ├── dml.sql                  # 初始化种子数据
│   └── connection.py            # SQLAlchemy 引擎
├── models/                      # ORM 实体类
│   ├── account_subject.py
│   ├── auxiliary_entity.py
│   ├── operational_record.py
│   ├── voucher_header.py
│   └── voucher_line.py
├── ai/                          # AI 集成层
│   ├── llm_client.py            # HTTP 客户端
│   ├── prompts.py               # Few-shot 提示词
│   └── json_parser.py           # JSON 解析与校验
├── services/                    # 业务逻辑层
│   ├── record_service.py        # 流水全流程编排
│   └── accounting_engine.py     # 复式记账引擎
├── api/
│   └── routes.py                # REST 路由
└── tests/
    ├── test_json_parser.py       # JSON 解析单元测试
    ├── test_accounting_engine.py # 记账引擎单元测试（内存 DB）
    └── test_api.py               # API 集成测试（Mock LLM）
```

## 核心设计原则

1. **LLM 只做文本解析**：不参与任何数值计算，不输出科目代码
2. **后端硬编码映射**：科目映射规则在 `accounting_engine.py` 中明确定义
3. **复式记账平衡强制校验**：`Σ借方 != Σ贷方` 时直接抛出异常，拒绝入账
4. **事务原子性**：任何环节失败全部回滚，流水状态标记为 `MANUAL_REVIEW`
5. **穿透审计**：凭证通过 `record_id` 外键可反查原始自然语言输入
