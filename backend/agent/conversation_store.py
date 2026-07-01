"""Postgres-backed chat history for signed-in users (Epic B, story B2 — #27).

Replaces `agent/memory.py`'s in-process dict *for authenticated requests only*.
Anonymous chat keeps using `agent/memory.py` unchanged (RLS has nothing to scope
to without a `user_id`, and the in-process store is fine for a throwaway session).

`SupabaseChatMessageHistory` is a duck-typed drop-in for the subset of
`InMemoryChatMessageHistory` that `agent/coach_agent.py` actually uses
(`.messages` and `.add_messages(...)`) — see `ChatHistoryLike`. It reads/writes
through the RLS-scoped user client (`db.get_user_client`), so `conversations`/
`messages` row ownership is enforced by Postgres, not by this code.

The conversation id is the frontend's per-browser `session_id` (a client-generated
uuidv4, already a valid `uuid` literal) — reused as the `conversations.id` primary
key rather than inventing a second identifier. One quirk this creates: if the same
browser (and thus the same `session_id`) is later used by a *different* signed-in
user, that user's RLS-scoped `select` on the id returns nothing (not theirs), so
`_ensure_conversation` tries to `insert` a new row with an id that already exists
under another owner — the insert fails with a unique-violation and the turn simply
isn't persisted (caught by the caller in `coach_agent.py`). No data leaks either
way; it's just a rare shared-browser edge case, not handled beyond that.
"""

from __future__ import annotations

import logging
from typing import Optional, Protocol

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from agent.memory import HISTORY_WINDOW_TURNS

logger = logging.getLogger("chordcoach.conversation_store")

# Load a bit more than the read-time window (HISTORY_WINDOW_TURNS turns = 2×N
# messages) so future increases to the window don't silently starve context
# without a corresponding query-limit change here.
_LOAD_LIMIT = HISTORY_WINDOW_TURNS * 2 * 4


class ChatHistoryLike(Protocol):
    """The subset of `BaseChatMessageHistory` that `coach_agent.py` relies on."""

    @property
    def messages(self) -> list[BaseMessage]: ...

    def add_messages(self, messages: list[BaseMessage]) -> None: ...


class SupabaseChatMessageHistory:
    """Chat history for one conversation, persisted to Supabase Postgres.

    Blocking (network I/O via the `supabase` client) — construction loads the
    existing turns synchronously and `add_messages` writes synchronously. Callers
    run both off the event loop (`anyio.to_thread.run_sync`), matching every other
    Supabase call site in this codebase (`db.get_own_profile`, etc).
    """

    def __init__(self, conversation_id: str, user_id: str, access_token: str):
        self.conversation_id = conversation_id
        self.user_id = user_id
        self.access_token = access_token
        self._messages: list[BaseMessage] = self._load()

    def _client(self):
        from db import get_user_client

        return get_user_client(self.access_token)

    def _load(self) -> list[BaseMessage]:
        client = self._client()
        result = (
            client.table("messages")
            .select("role, content")
            .eq("conversation_id", self.conversation_id)
            .order("created_at")
            .limit(_LOAD_LIMIT)
            .execute()
        )
        messages: list[BaseMessage] = []
        for row in result.data or []:
            if row["role"] == "user":
                messages.append(HumanMessage(content=row["content"]))
            elif row["role"] == "assistant":
                messages.append(AIMessage(content=row["content"]))
        return messages

    @property
    def messages(self) -> list[BaseMessage]:
        return self._messages

    def _ensure_conversation(self, client, new_messages: list[BaseMessage]) -> None:
        existing = (
            client.table("conversations")
            .select("id")
            .eq("id", self.conversation_id)
            .limit(1)
            .execute()
        )
        if existing.data:
            return
        title: Optional[str] = None
        for m in new_messages:
            if isinstance(m, HumanMessage) and isinstance(m.content, str):
                title = m.content[:60]
                break
        client.table("conversations").insert(
            {"id": self.conversation_id, "user_id": self.user_id, "title": title}
        ).execute()

    def add_messages(self, messages: list[BaseMessage]) -> None:
        client = self._client()
        self._ensure_conversation(client, messages)
        rows = [
            {
                "conversation_id": self.conversation_id,
                "role": "user" if isinstance(m, HumanMessage) else "assistant",
                "content": m.content,
            }
            for m in messages
        ]
        client.table("messages").insert(rows).execute()
        self._messages.extend(messages)
