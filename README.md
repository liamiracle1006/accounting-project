# AgentLedger — AI-Powered Accounting System for Small Businesses

A full-stack double-entry bookkeeping system with AI-assisted voucher generation, multi-role review workflows, financial statement generation, and trial balance validation.

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React 18 + TypeScript + Vite + Tailwind CSS |
| Backend | Python 3.12 + FastAPI + SQLAlchemy |
| Database | MySQL 8.4 |
| AI | Claude API (dual-track voucher generation) |

## Quick Start

Open two terminals:

```
Terminal 1 (Backend)                  Terminal 2 (Frontend)
────────────────────────────────      ────────────────────
py -3.12 -m uvicorn main:app          cd frontend
  --reload                            npm run dev
```

| URL | Purpose |
|---|---|
| http://localhost:5173 | Web UI |
| http://localhost:8000/docs | API docs (Swagger) |

Default credentials: username `accountant` / `boss` / `manager`, password `123456`

## Features

### Voucher Management
- Natural language input → AI-generated double-entry journal (dual-track: habit rules + AI rules)
- Review workflow: Draft → Pending Review → Posted / Rejected
- Bulk import via Excel, scanned images, or mixed sources

### Ledger & Reports
- **Trial Balance**: Multi-level account tree with debit/credit balance validation
- **General Ledger**: Running balance engine with drill-through to source vouchers
- **Balance Sheet**: Enterprise GAAP and Small Business Standards (小企业准则) versions
- **Income Statement**: Both standards, monthly query

### Validation Tool
- Upload a trial balance Excel exported from any accounting software (e.g. Jingpeng/荆鹏)
- Automatically parses and computes Balance Sheet and Income Statement
- Line-by-line diff comparison against a user-uploaded reference report (green = match, red = difference)
- Automatic account code normalization across standards (Small Business 5xxx/3xxx → Standard 6xxx/4xxx)
- Fuzzy name matching to handle prefix variations (e.g. "应交城市维护建设税" → IS line "城市维护建设税")

### Other Modules
- Period closing (month-end close, P&L transfer)
- Fixed asset register
- Expense request & approval
- Habit rule management for recurring journal entries

## Project Structure

```
accounting-project/
├── main.py                        # FastAPI entry point
├── api/                           # Route handlers
│   ├── report_routes.py
│   ├── validate_routes.py         # Validation tool API
│   └── ...
├── services/                      # Business logic
│   ├── report_service.py          # Financial statement engine
│   ├── validation_service.py      # Excel parsing + validation
│   └── ...
├── models/                        # SQLAlchemy ORM models
├── database/
│   ├── ddl.sql                    # Schema
│   └── seed_local.sql             # Local seed data
└── frontend/
    └── src/
        ├── features/
        │   ├── reports/           # Balance sheet, income statement, ledger
        │   ├── validate/          # Validation tool UI
        │   └── vouchers/          # Voucher workbench
        └── api/
```

## Design Principles

- **LLM handles language, not numbers** — AI only parses intent; all accounting logic is deterministic backend code
- **Strict double-entry enforcement** — any voucher where Σdebit ≠ Σcredit is rejected with a full transaction rollback
- **Dual-standard support** — all reports support both Enterprise GAAP (企业会计准则) and Small Business Standards (小企业会计准则)
- **Cross-software compatibility** — trial balance files from different accounting software are automatically normalized before computation
