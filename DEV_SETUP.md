# AgentLedger 本地开发启动指南

## 前置要求
- Python 3.12
- Node.js 20+
- MySQL 8.4
- 项目根目录有 `.env` 文件（从 `.env.example` 复制并填写）

---

## 首次初始化数据库（只需做一次）

### 1. 创建数据库
用开始菜单打开 **MySQL 8.4 Command Line Client**，输入 root 密码后执行：
```sql
CREATE DATABASE agentledger CHARACTER SET utf8mb4;
exit
```

### 2. 建表
在 VSCode 终端运行：
```powershell
Get-Content database\ddl.sql | & "C:\Program Files\MySQL\MySQL Server 8.4\bin\mysql.exe" -u root -p agentledger
```

### 3. 导入种子数据（用户账号 + 科目表）
```powershell
Get-Content database\seed_local.sql | & "C:\Program Files\MySQL\MySQL Server 8.4\bin\mysql.exe" -u root -p agentledger
```

---

## 每次启动

### 终端 1 — 后端
```bash
py -3.12 -m uvicorn main:app --reload
```

### 终端 2 — 前端
```bash
cd frontend
npm run dev
```

### 访问地址
- 前端：http://localhost:5173
- 后端 API 文档：http://localhost:8000/docs

---

## 默认账号（密码均为 123456）

| 用户名 | 角色 |
|---|---|
| boss | 老板 |
| accountant | 财务（主要测试账号）|
| manager | 部门主管 |

---

## 常见问题

**npm 不可用**
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

**pip 乱码报错**
```bash
py -3.12 -X utf8 -m pip install -r requirements.txt
```

**后端报 ModuleNotFoundError**
检查 `main.py`，把还没实现的路由注释掉。
