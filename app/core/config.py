import os
import secrets
import warnings
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# ── Dataset & LLM ──
BOOKS_CSV_PATH = os.environ.get("BOOKS_CSV_PATH", str(PROJECT_ROOT / "data" / "books.csv"))
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
LLM_MODE = os.environ.get("LLM_MODE", "groq")

# ── Row & Query Limits ──
MAX_SCAN_ROWS = int(os.environ.get("MAX_SCAN_ROWS", "100000"))
MAX_RETURN_ROWS = int(os.environ.get("MAX_RETURN_ROWS", "50"))
DEFAULT_LIMIT = 20
MAX_QUESTION_LENGTH = 500

# ── Rate Limiting & Cache ──
RATE_LIMIT_TOKENS = int(os.environ.get("RATE_LIMIT_TOKENS", "20"))
RATE_LIMIT_REFILL_PER_SEC = float(os.environ.get("RATE_LIMIT_REFILL_PER_SEC", "2.0"))
CACHE_MAX_SIZE = int(os.environ.get("CACHE_MAX_SIZE", "256"))
AUDIT_LOG_PATH = PROJECT_ROOT / "logs" / "audit.jsonl"
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")

# ── Enterprise Security ──
CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "*").split(",")
ENABLE_CORS = os.environ.get("ENABLE_CORS", "true").lower() == "true"
MAX_UPLOAD_SIZE_MB = int(os.environ.get("MAX_UPLOAD_SIZE_MB", "50"))
ALLOWED_UPLOAD_EXTENSIONS = {"csv", "json", "xls", "xlsx", "tsv", "parquet"}

# Generate a secure session secret if not provided
_session_secret = os.environ.get("SESSION_SECRET", "")
if not _session_secret or _session_secret == "change-me-in-production":
    _session_secret = secrets.token_hex(32)
    warnings.warn(
        "SESSION_SECRET not set or using default. A random secret has been generated. "
        "Set SESSION_SECRET in your .env file for production use.",
        stacklevel=1,
    )
SESSION_SECRET = _session_secret

# ── Multi-turn Conversation ──
MAX_CONVERSATION_TURNS = int(os.environ.get("MAX_CONVERSATION_TURNS", "10"))

# ── Data Quality Thresholds ──
DATA_QUALITY_THRESHOLDS = {
    "missing_pct_warning": 20.0,
    "missing_pct_critical": 50.0,
    "low_cardinality_threshold": 5,
    "high_cardinality_pct": 95.0,
}

# ── Metrics & Observability ──
METRICS_ENABLED = os.environ.get("METRICS_ENABLED", "true").lower() == "true"

# ── API Key Validation ──
if LLM_MODE == "groq" and not GROQ_API_KEY:
    warnings.warn(
        "GROQ_API_KEY is not set but LLM_MODE=groq. Set GROQ_API_KEY in .env "
        "or use LLM_MODE=stub for testing.",
        stacklevel=1,
    )
