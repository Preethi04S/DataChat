"""Multi-turn Conversation Context Manager — Maintains session state
for contextual follow-up queries (Conversational AI).

Aligned with Akaike Technologies' Conversational AI product line.
"""
from __future__ import annotations
import time
import threading
from collections import OrderedDict
from app.core.config import MAX_CONVERSATION_TURNS
from app.core.logging import get_logger

logger = get_logger(__name__)

_lock = threading.Lock()


class ConversationTurn:
    """Single turn in a multi-turn conversation."""

    def __init__(self, question: str, plan_intent: str, columns_used: list[str],
                 filters_used: list[str], result_count: int):
        self.question = question
        self.plan_intent = plan_intent
        self.columns_used = columns_used
        self.filters_used = filters_used
        self.result_count = result_count
        self.timestamp = time.time()


class ConversationSession:
    """Manages a multi-turn conversation session with context memory."""

    def __init__(self, session_id: str, max_turns: int = MAX_CONVERSATION_TURNS):
        self.session_id = session_id
        self.turns: list[ConversationTurn] = []
        self.max_turns = max_turns
        self.created_at = time.time()
        self.last_active = time.time()

    def add_turn(self, turn: ConversationTurn):
        self.turns.append(turn)
        self.last_active = time.time()
        if len(self.turns) > self.max_turns:
            self.turns = self.turns[-self.max_turns:]

    def get_context_summary(self) -> str:
        """Build context string from previous turns for the LLM planner."""
        if not self.turns:
            return ""
        lines = ["Previous conversation context:"]
        for i, turn in enumerate(self.turns[-3:], 1):
            lines.append(
                f"  Turn {i}: Q=\"{turn.question}\" -> intent={turn.plan_intent}, "
                f"cols={turn.columns_used}, results={turn.result_count}"
            )
        return "\n".join(lines)

    def get_referenced_columns(self) -> list[str]:
        """Get all columns referenced across conversation turns."""
        cols = set()
        for turn in self.turns:
            cols.update(turn.columns_used)
        return list(cols)

    def is_followup(self, question: str) -> bool:
        """Detect if a question is a follow-up based on pronouns and references."""
        followup_indicators = [
            "what about", "and also", "how about", "same but",
            "those", "these", "them", "they", "their", "its",
            "more", "less", "instead", "also", "too",
            "the same", "similar", "like that",
        ]
        q_lower = question.lower()
        return any(indicator in q_lower for indicator in followup_indicators)


class ConversationManager:
    """Manages multiple conversation sessions with TTL-based expiry."""

    def __init__(self, max_sessions: int = 100, ttl_seconds: int = 1800):
        self._sessions: OrderedDict[str, ConversationSession] = OrderedDict()
        self._max_sessions = max_sessions
        self._ttl = ttl_seconds

    def get_or_create(self, session_id: str) -> ConversationSession:
        with _lock:
            self._cleanup_expired()
            if session_id in self._sessions:
                self._sessions.move_to_end(session_id)
                return self._sessions[session_id]
            session = ConversationSession(session_id)
            self._sessions[session_id] = session
            if len(self._sessions) > self._max_sessions:
                self._sessions.popitem(last=False)
            return session

    def _cleanup_expired(self):
        now = time.time()
        expired = [
            sid for sid, session in self._sessions.items()
            if now - session.last_active > self._ttl
        ]
        for sid in expired:
            del self._sessions[sid]

    def get_active_session_count(self) -> int:
        with _lock:
            self._cleanup_expired()
            return len(self._sessions)


# Singleton conversation manager
conversation_manager = ConversationManager()
