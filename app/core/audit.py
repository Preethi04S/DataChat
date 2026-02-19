import hashlib
import json
import time
import threading
from pathlib import Path
from app.core.config import AUDIT_LOG_PATH
from app.core.logging import get_logger

logger = get_logger(__name__)

_lock = threading.Lock()
_prev_hash = "0" * 64


def _canonical_json(obj: dict) -> str:
    return json.dumps(obj, sort_keys=True, default=str)


def append_audit_entry(
    request_id: str,
    dataset_hash: str,
    normalized_plan: dict | None,
    rows_scanned: int,
    rows_returned: int,
    cache_hit: bool,
    verify_status: str,
    elapsed_ms: float,
):
    global _prev_hash

    entry = {
        "timestamp": time.time(),
        "request_id": request_id,
        "dataset_hash": dataset_hash,
        "normalized_plan": normalized_plan,
        "rows_scanned": rows_scanned,
        "rows_returned": rows_returned,
        "cache_hit": cache_hit,
        "verify_status": verify_status,
        "elapsed_ms": round(elapsed_ms, 2),
        "prev_hash": _prev_hash,
    }
    payload = _prev_hash + _canonical_json(entry)
    entry_hash = hashlib.sha256(payload.encode()).hexdigest()
    entry["entry_hash"] = entry_hash

    with _lock:
        _prev_hash = entry_hash
        try:
            Path(AUDIT_LOG_PATH).parent.mkdir(parents=True, exist_ok=True)
            with open(AUDIT_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, default=str) + "\n")
        except Exception as e:
            logger.error(f"Audit log write failed: {e}")
