"""Tests for the Postgres-backed chat history (agent/conversation_store.py, B2 — #27).

No real Supabase: `db.get_user_client` is monkeypatched to a small in-memory fake
that mimics the two tables (`conversations`, `messages`) closely enough to drive
`SupabaseChatMessageHistory`'s load/append logic and its per-user isolation
guarantees, which is what this story's acceptance criteria actually care about.
"""

from __future__ import annotations

import types

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from agent.conversation_store import SupabaseChatMessageHistory


class _FakeTables:
    """In-memory stand-in for two Postgres tables, filtered by the querying user
    like RLS would: `conversations`/`messages` rows are scoped by `user_id`, and a
    query from a different user simply sees no rows for someone else's data."""

    def __init__(self):
        self.conversations: list[dict] = []
        self.messages: list[dict] = []


class _FakeQuery:
    def __init__(self, table_name, tables: _FakeTables, owner_user_id):
        self._table_name = table_name
        self._tables = tables
        self._owner_user_id = owner_user_id
        self._eq: dict[str, object] = {}
        self._pending_insert: list[dict] | None = None

    def _rows_getter(self):
        return self._tables.conversations if self._table_name == "conversations" else self._tables.messages

    def select(self, *a, **k):
        return self

    def eq(self, col, val):
        self._eq[col] = val
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def insert(self, payload):
        self._pending_insert = payload if isinstance(payload, list) else [payload]
        return self

    def execute(self):
        if self._pending_insert is not None:
            rows = self._rows_getter()
            for row in self._pending_insert:
                # Mimic the `conversations.id` primary key: a second insert with an
                # id that already exists under a different owner conflicts (see the
                # module docstring's shared-browser edge case).
                if self._table_name == "conversations":
                    clash = next((r for r in rows if r.get("id") == row.get("id")), None)
                    if clash is not None and clash["user_id"] != row["user_id"]:
                        raise RuntimeError("duplicate key value violates unique constraint")
                rows.append(row)
            return types.SimpleNamespace(data=self._pending_insert)

        rows = self._rows_getter()
        # RLS stand-in. `conversations` rows are owned directly (user_id column).
        # `messages` has no owner column of its own in the real schema — ownership
        # is derived by joining to the parent conversation — so mirror that here
        # too, rather than only scoping the table that happens to carry user_id.
        if self._table_name == "conversations":
            rows = [r for r in rows if r.get("user_id") == self._owner_user_id]
        else:
            owned_conversation_ids = {
                c["id"] for c in self._tables.conversations if c.get("user_id") == self._owner_user_id
            }
            rows = [r for r in rows if r.get("conversation_id") in owned_conversation_ids]
        for col, val in self._eq.items():
            rows = [r for r in rows if r.get(col) == val]
        return types.SimpleNamespace(data=rows)


class _FakeClient:
    def __init__(self, tables: _FakeTables, user_id: str):
        self._tables = tables
        self._user_id = user_id

    def table(self, name):
        return _FakeQuery(name, self._tables, self._user_id)


@pytest.fixture
def shared_tables():
    return _FakeTables()


def _history(monkeypatch, tables, conversation_id, user_id, access_token="tok"):
    monkeypatch.setattr(
        "db.get_user_client", lambda token: _FakeClient(tables, user_id)
    )
    return SupabaseChatMessageHistory(conversation_id, user_id, access_token)


class TestLoad:
    def test_new_conversation_starts_empty(self, monkeypatch, shared_tables):
        history = _history(monkeypatch, shared_tables, "c1", "user-a")
        assert history.messages == []

    def test_loads_existing_turns_as_langchain_messages(self, monkeypatch, shared_tables):
        shared_tables.conversations.append({"id": "c1", "user_id": "user-a", "title": "hi"})
        shared_tables.messages.extend([
            {"conversation_id": "c1", "role": "user", "content": "give me a blues progression"},
            {"conversation_id": "c1", "role": "assistant", "content": "Try E7-A7-B7…"},
        ])
        history = _history(monkeypatch, shared_tables, "c1", "user-a")
        assert len(history.messages) == 2
        assert isinstance(history.messages[0], HumanMessage)
        assert history.messages[0].content == "give me a blues progression"
        assert isinstance(history.messages[1], AIMessage)
        assert history.messages[1].content == "Try E7-A7-B7…"


class TestAddMessages:
    def test_first_turn_creates_the_conversation_row(self, monkeypatch, shared_tables):
        history = _history(monkeypatch, shared_tables, "c1", "user-a")
        history.add_messages([HumanMessage(content="hi there"), AIMessage(content="hello!")])

        assert len(shared_tables.conversations) == 1
        conv = shared_tables.conversations[0]
        assert conv["id"] == "c1"
        assert conv["user_id"] == "user-a"
        assert conv["title"] == "hi there"  # seeded from the first human message

    def test_second_turn_does_not_duplicate_the_conversation_row(self, monkeypatch, shared_tables):
        history = _history(monkeypatch, shared_tables, "c1", "user-a")
        history.add_messages([HumanMessage(content="turn 1"), AIMessage(content="reply 1")])
        history.add_messages([HumanMessage(content="turn 2"), AIMessage(content="reply 2")])
        assert len(shared_tables.conversations) == 1

    def test_messages_are_persisted_and_reflected_in_memory(self, monkeypatch, shared_tables):
        history = _history(monkeypatch, shared_tables, "c1", "user-a")
        history.add_messages([HumanMessage(content="turn 1"), AIMessage(content="reply 1")])

        assert len(shared_tables.messages) == 2
        assert history.messages[-2].content == "turn 1"
        assert history.messages[-1].content == "reply 1"

    def test_next_load_for_same_conversation_sees_persisted_turns(self, monkeypatch, shared_tables):
        h1 = _history(monkeypatch, shared_tables, "c1", "user-a")
        h1.add_messages([HumanMessage(content="turn 1"), AIMessage(content="reply 1")])

        h2 = _history(monkeypatch, shared_tables, "c1", "user-a")
        assert [m.content for m in h2.messages] == ["turn 1", "reply 1"]


class TestPerUserIsolation:
    """Acceptance criterion: conversations persist scoped to the user (RLS)."""

    def test_a_second_user_does_not_see_the_first_users_conversation(self, monkeypatch, shared_tables):
        owner = _history(monkeypatch, shared_tables, "c1", "user-a")
        owner.add_messages([HumanMessage(content="secret question"), AIMessage(content="secret answer")])

        other = _history(monkeypatch, shared_tables, "c1", "user-b")
        assert other.messages == []

    def test_a_second_user_reusing_the_same_conversation_id_gets_their_own_row(
        self, monkeypatch, shared_tables
    ):
        owner = _history(monkeypatch, shared_tables, "c1", "user-a")
        owner.add_messages([HumanMessage(content="from A"), AIMessage(content="reply to A")])

        other = _history(monkeypatch, shared_tables, "c1", "user-b")
        # The id collision (see the module docstring) surfaces as an exception
        # rather than silently attaching user-b's turn to user-a's conversation.
        with pytest.raises(Exception):
            other.add_messages([HumanMessage(content="from B"), AIMessage(content="reply to B")])

        # Crucially, user A's data was never mutated by user B's attempt.
        assert [m.content for m in owner.messages] == ["from A", "reply to A"]
