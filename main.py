"""
AgentLedger V3.0 — Application Entry Point
"""
import logging
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from config.settings import APP_DEBUG
from api.routes import router
from api.enterprise_routes import router as enterprise_router
from api.decision_routes import router as decision_router
from api.auth_routes import router as auth_router
from api.department_routes import router as department_router
from api.expense_routes import router as expense_router
from api.workbench_routes import router as workbench_router
from api.report_routes import router as report_router
from api.audit_routes import router as audit_router
from api.invoice_routes import router as invoice_router
from api.ocr_routes import router as ocr_router
from api.rag_routes import router as rag_router
from api.analytics_routes import router as analytics_router
# from api.account_set_routes import router as account_set_router  # service not yet implemented
from api.subject_routes import router as subject_router
from api.initial_balance_routes import router as initial_balance_router
from api.import_routes import router as import_router
from api.voucher_ai_routes import router as voucher_ai_router
from api.voucher_routes import router as voucher_router
from api.period_routes import router as period_router
from api.batch_routes import router as batch_router
from api.validate_routes import router as validate_router
from services.auth_service import get_current_user
from services.audit_guard import register_voucher_guard

logging.basicConfig(
    level=logging.DEBUG if APP_DEBUG else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)

# 注册 POSTED 凭证防篡改事件监听器（进程全局，只需一次）
register_voucher_guard()

app = FastAPI(
    title="AgentLedger V3.0",
    description="基于 LLM 的智能业财融合系统 — Dual-Core Architecture",
    version="3.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# auth_router 不需要鉴权（它就是登录入口）
app.include_router(auth_router)

# 其余所有业务 API 均需要有效 JWT
_auth = [Depends(get_current_user)]
app.include_router(router,             dependencies=_auth)
app.include_router(enterprise_router,  dependencies=_auth)
app.include_router(decision_router,    dependencies=_auth)
app.include_router(department_router,  dependencies=_auth)
app.include_router(expense_router,     dependencies=_auth)
app.include_router(workbench_router,   dependencies=_auth)
app.include_router(report_router,      dependencies=_auth)
app.include_router(audit_router,       dependencies=_auth)
app.include_router(invoice_router,     dependencies=_auth)
app.include_router(ocr_router,         dependencies=_auth)
app.include_router(rag_router,         dependencies=_auth)
app.include_router(analytics_router,   dependencies=_auth)
# app.include_router(account_set_router, dependencies=_auth)
app.include_router(subject_router,          dependencies=_auth)
app.include_router(initial_balance_router,  dependencies=_auth)
app.include_router(import_router,           dependencies=_auth)
app.include_router(voucher_ai_router,       dependencies=_auth)
app.include_router(voucher_router,          dependencies=_auth)
app.include_router(period_router,           dependencies=_auth)
app.include_router(batch_router,            dependencies=_auth)
app.include_router(validate_router)  # 开发测试，无鉴权

_STATIC = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=_STATIC), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(_STATIC / "index.html")


@app.get("/{full_path:path}", include_in_schema=False)
def spa_fallback(full_path: str):
    return FileResponse(_STATIC / "index.html")


@app.get("/health")
def health_check():
    return {"status": "ok", "version": "3.0.0"}


if __name__ == "__main__":
    import uvicorn
    from config.settings import APP_HOST, APP_PORT
    uvicorn.run("main:app", host=APP_HOST, port=APP_PORT, reload=APP_DEBUG)
