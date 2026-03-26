"""
AgentLedger V2.0 — Application Entry Point
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
from services.auth_service import get_current_user

logging.basicConfig(
    level=logging.DEBUG if APP_DEBUG else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)

app = FastAPI(
    title="AgentLedger V2.0",
    description="基于 LLM 的智能业财融合系统（小微 + 一般企业双模式）",
    version="2.0.0",
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
app.include_router(router,            dependencies=_auth)
app.include_router(enterprise_router, dependencies=_auth)
app.include_router(decision_router,   dependencies=_auth)

_STATIC = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=_STATIC), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(_STATIC / "index.html")


@app.get("/health")
def health_check():
    return {"status": "ok", "version": "2.0.0"}


if __name__ == "__main__":
    import uvicorn
    from config.settings import APP_HOST, APP_PORT
    uvicorn.run("main:app", host=APP_HOST, port=APP_PORT, reload=APP_DEBUG)
