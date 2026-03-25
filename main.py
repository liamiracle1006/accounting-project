"""
AgentLedger V1.0 — Application Entry Point
"""
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from config.settings import APP_DEBUG
from api.routes import router
from api.enterprise_routes import router as enterprise_router

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

app.include_router(router)
app.include_router(enterprise_router)

_STATIC = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=_STATIC), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(_STATIC / "index.html")


@app.get("/health")
def health_check():
    return {"status": "ok", "version": "1.0.0"}


if __name__ == "__main__":
    import uvicorn
    from config.settings import APP_HOST, APP_PORT
    uvicorn.run("main:app", host=APP_HOST, port=APP_PORT, reload=APP_DEBUG)
