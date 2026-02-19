import time
import threading
from app.core.config import RATE_LIMIT_TOKENS, RATE_LIMIT_REFILL_PER_SEC


class TokenBucket:
    def __init__(self, capacity: int = RATE_LIMIT_TOKENS, refill_rate: float = RATE_LIMIT_REFILL_PER_SEC):
        self.capacity = capacity
        self.tokens = float(capacity)
        self.refill_rate = refill_rate
        self.last_refill = time.monotonic()
        self._lock = threading.Lock()

    def consume(self, tokens: int = 1) -> bool:
        with self._lock:
            now = time.monotonic()
            elapsed = now - self.last_refill
            self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
            self.last_refill = now
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False


rate_limiter = TokenBucket()
