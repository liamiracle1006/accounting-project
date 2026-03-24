"""
AgentLedger — Application settings
Reads from environment variables (or .env file via python-dotenv).
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ── Database ──────────────────────────────────────────────────────────────────
DB_HOST     = os.getenv("DB_HOST",     "127.0.0.1")
DB_PORT     = int(os.getenv("DB_PORT", "3306"))
DB_NAME     = os.getenv("DB_NAME",     "agentledger")
DB_USER     = os.getenv("DB_USER",     "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_ECHO     = os.getenv("DB_ECHO",     "false").lower() == "true"

DATABASE_URL = (
    f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    "?charset=utf8mb4"
)

# ── LLM API ───────────────────────────────────────────────────────────────────
LLM_API_KEY     = os.getenv("LLM_API_KEY",     "")
LLM_BASE_URL    = os.getenv("LLM_BASE_URL",    "https://api.openai.com/v1")
LLM_MODEL       = os.getenv("LLM_MODEL",       "gpt-4o-mini")
LLM_TIMEOUT     = int(os.getenv("LLM_TIMEOUT", "30"))
LLM_MAX_TOKENS  = int(os.getenv("LLM_MAX_TOKENS", "1024"))

# ── Application ───────────────────────────────────────────────────────────────
APP_HOST  = os.getenv("APP_HOST", "0.0.0.0")
APP_PORT  = int(os.getenv("APP_PORT", "8000"))
APP_DEBUG = os.getenv("APP_DEBUG", "false").lower() == "true"
