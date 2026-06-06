"""
Session-based conversation memory manager.
Sessions are stored in-process (no DB required for MVP) and auto-expire after 2 hours.
"""

import time
from langchain.memory import ConversationBufferWindowMemory

SESSION_TTL_SECONDS = 7200  # 2 hours

_sessions: dict[str, dict] = {}


def _evict_expired() -> None:
    """Remove sessions older than SESSION_TTL_SECONDS."""
    cutoff = time.time() - SESSION_TTL_SECONDS
    expired = [sid for sid, data in _sessions.items() if data["last_used"] < cutoff]
    for sid in expired:
        del _sessions[sid]


def get_memory(session_id: str) -> ConversationBufferWindowMemory:
    """Return (or create) the ConversationBufferWindowMemory for a session."""
    _evict_expired()
    if session_id not in _sessions:
        _sessions[session_id] = {
            "memory": ConversationBufferWindowMemory(
                k=10,
                memory_key="chat_history",
                return_messages=True,
            ),
            "last_used": time.time(),
        }
    else:
        _sessions[session_id]["last_used"] = time.time()

    return _sessions[session_id]["memory"]


def clear_memory(session_id: str) -> bool:
    """Clear and remove a session. Returns True if the session existed."""
    if session_id in _sessions:
        del _sessions[session_id]
        return True
    return False


def session_count() -> int:
    _evict_expired()
    return len(_sessions)
