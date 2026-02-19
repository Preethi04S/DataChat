import hashlib
import json
from collections import OrderedDict
from threading import Lock
from app.core.config import CACHE_MAX_SIZE


class DeterministicCache:
    def __init__(self, max_size: int = CACHE_MAX_SIZE):
        self.max_size = max_size
        self._cache: OrderedDict[str, dict] = OrderedDict()
        self._lock = Lock()

    @staticmethod
    def make_key(dataset_hash: str, normalized_plan: dict) -> str:
        plan_json = json.dumps(normalized_plan, sort_keys=True, default=str)
        raw = f"{dataset_hash}:{plan_json}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def get(self, key: str) -> dict | None:
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
            return None

    def put(self, key: str, value: dict):
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
            self._cache[key] = value
            if len(self._cache) > self.max_size:
                self._cache.popitem(last=False)

    def clear(self):
        with self._lock:
            self._cache.clear()


plan_cache = DeterministicCache()
