import hashlib
from pathlib import Path

_dataset_hash: str | None = None


def compute_fingerprint(csv_path: str) -> str:
    global _dataset_hash
    h = hashlib.sha256()
    with open(csv_path, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    _dataset_hash = h.hexdigest()
    return _dataset_hash


def compute_fingerprint_bytes(data: bytes) -> str:
    global _dataset_hash
    _dataset_hash = hashlib.sha256(data).hexdigest()
    return _dataset_hash


def get_dataset_hash() -> str:
    if _dataset_hash is None:
        raise RuntimeError("Dataset fingerprint not computed yet")
    return _dataset_hash
