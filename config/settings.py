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

# ── LLM API (文本，OpenAI-compatible) ─────────────────────────────────────────
LLM_API_KEY     = os.getenv("LLM_API_KEY",     "")
LLM_BASE_URL    = os.getenv("LLM_BASE_URL",    "https://api.openai.com/v1")
LLM_MODEL       = os.getenv("LLM_MODEL",       "gpt-4o-mini")
LLM_TIMEOUT     = int(os.getenv("LLM_TIMEOUT", "30"))
LLM_MAX_TOKENS  = int(os.getenv("LLM_MAX_TOKENS", "1024"))

# ── Vision LLM API（发票 OCR，可与文本 LLM 相同或单独配置）──────────────────────
# 若不填写则 OCR 功能返回空结果，其余功能不受影响。
# 推荐：通义千问 Qwen-VL-Max（阿里云 DashScope）
#   VISION_API_BASE = https://dashscope.aliyuncs.com/compatible-mode/v1
#   VISION_MODEL    = qwen-vl-max
VISION_API_KEY  = os.getenv("VISION_API_KEY",  os.getenv("LLM_API_KEY", ""))
VISION_API_BASE = os.getenv("VISION_API_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1")
VISION_MODEL    = os.getenv("VISION_MODEL",    "qwen-vl-max")

# ── Field-level Encryption (tax_password 等敏感字段）────────────────────────────
# 生成命令（Python）：
#   from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())
# 将输出的 base64 字符串填写到 .env 的 FIELD_ENCRYPTION_KEY=
# 若不填写则退化为明文存储，生产环境必须配置。
FIELD_ENCRYPTION_KEY = os.getenv("FIELD_ENCRYPTION_KEY", "")

# ── Application ───────────────────────────────────────────────────────────────
APP_HOST  = os.getenv("APP_HOST", "0.0.0.0")
APP_PORT  = int(os.getenv("APP_PORT", "8000"))
APP_DEBUG = os.getenv("APP_DEBUG", "false").lower() == "true"

# ── Auth / JWT ────────────────────────────────────────────────────────────────
JWT_SECRET_KEY   = os.getenv("JWT_SECRET_KEY", "CHANGE_ME_IN_PRODUCTION_32chars!!")
JWT_ALGORITHM    = "HS256"
JWT_EXPIRE_HOURS = int(os.getenv("JWT_EXPIRE_HOURS", "12"))

# ── RAG / Vector Store ────────────────────────────────────────────────────────
# ChromaDB 持久化路径（相对于项目根目录）
CHROMA_PATH      = os.getenv("CHROMA_PATH", "./chroma_db")
CHROMA_COLLECTION= os.getenv("CHROMA_COLLECTION", "tax_strategies")

# Embedding API（OpenAI-compatible，可替换千问 text-embedding-v3 等）
EMBED_API_KEY    = os.getenv("EMBED_API_KEY",  os.getenv("LLM_API_KEY", ""))
EMBED_BASE_URL   = os.getenv("EMBED_BASE_URL", "https://api.openai.com/v1")
EMBED_MODEL      = os.getenv("EMBED_MODEL",    "text-embedding-3-small")
EMBED_BATCH_SIZE = int(os.getenv("EMBED_BATCH_SIZE", "32"))
