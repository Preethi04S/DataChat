"""
Lightweight in-process session manager.
Stores last N turns per session_id so the LLM can reference prior context.
"""
import uuid
from collections import defaultdict, deque

MAX_HISTORY = 5
_store: dict[str, deque] = defaultdict(lambda: deque(maxlen=MAX_HISTORY))


def new_session() -> str:
    sid = str(uuid.uuid4())
    _store[sid]  # initialise
    return sid


def add_turn(session_id: str, query: str, response: str) -> None:
    _store[session_id].append({"query": query, "response": response})


def get_history(session_id: str) -> list[dict]:
    return list(_store.get(session_id, []))


def history_as_text(session_id: str) -> str:
    history = get_history(session_id)
    if not history:
        return ""
    lines = []
    for i, turn in enumerate(history, 1):
        lines.append(f"Turn {i}:\n  Q: {turn['query']}\n  A: {turn['response']}")
    return "\n".join(lines)
