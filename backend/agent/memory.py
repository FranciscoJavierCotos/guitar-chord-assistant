"""
Session-based conversation memory manager.
Sessions are stored in-process (no DB required for MVP) and auto-expire after 2 hours.

History uses langchain_core's InMemoryChatMessageHistory instead of the deprecated
ConversationBufferWindowMemory. The k-turn window is applied at read time in
coach_agent.run_agent (see HISTORY_WINDOW_TURNS), keeping the prompt small while we
retain the full transcript in the session.
"""

import time
from langchain_core.chat_history import InMemoryChatMessageHistory

SESSION_TTL_SECONDS = 7200  # 2 hours
_PRACTICE_LOG_MAX = 50

# Number of conversation turns (a turn = one human + one AI message) to feed back
# into the prompt. Mirrors the old ConversationBufferWindowMemory(k=10).
HISTORY_WINDOW_TURNS = 10

_sessions: dict[str, dict] = {}


def _evict_expired() -> None:
    """Remove sessions older than SESSION_TTL_SECONDS."""
    cutoff = time.time() - SESSION_TTL_SECONDS
    expired = [sid for sid, data in _sessions.items() if data["last_used"] < cutoff]
    for sid in expired:
        del _sessions[sid]


def _new_session() -> dict:
    return {
        "history": InMemoryChatMessageHistory(),
        "last_used": time.time(),
        "practice_log": [],
        "skill_level": "beginner",
    }


def get_history(session_id: str) -> InMemoryChatMessageHistory:
    """Return (or create) the chat-message history for a session."""
    _evict_expired()
    if session_id not in _sessions:
        _sessions[session_id] = _new_session()
    else:
        _sessions[session_id]["last_used"] = time.time()

    return _sessions[session_id]["history"]


def get_session_data(session_id: str) -> dict:
    """Return session metadata (practice_log and skill_level)."""
    _evict_expired()
    if session_id not in _sessions:
        return {"practice_log": [], "skill_level": "beginner"}
    return {
        "practice_log": _sessions[session_id].get("practice_log", []),
        "skill_level": _sessions[session_id].get("skill_level", "beginner"),
    }


def log_practice_item(session_id: str, item: dict) -> None:
    """Append a practice item to the session log (capped at _PRACTICE_LOG_MAX)."""
    if session_id not in _sessions:
        return
    log = _sessions[session_id].setdefault("practice_log", [])
    log.append({**item, "timestamp": time.time()})
    _sessions[session_id]["practice_log"] = log[-_PRACTICE_LOG_MAX:]


def set_skill_level(session_id: str, level: str) -> None:
    """Set the player skill level for this session."""
    if level.lower() not in {"beginner", "intermediate", "advanced"}:
        return
    if session_id in _sessions:
        _sessions[session_id]["skill_level"] = level.lower()


def clear_memory(session_id: str) -> bool:
    """Clear and remove a session. Returns True if the session existed."""
    if session_id in _sessions:
        del _sessions[session_id]
        return True
    return False


def session_count() -> int:
    _evict_expired()
    return len(_sessions)
