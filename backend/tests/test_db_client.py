"""Unit tests for the Supabase client wiring (backend/db.py, B0 — #25).

No real Supabase package, DB, or network: the `supabase` module is stubbed via
sys.modules and env vars are monkeypatched, so these run anywhere CI runs. They pin
the contract the rest of the backend relies on: graceful "unconfigured" behaviour
when no DB env is set, a loud failure when a client is demanded without config, and a
correct connectivity round-trip when config + package are present.
"""

from __future__ import annotations

import sys
import types

import pytest

import db


@pytest.fixture(autouse=True)
def _clear_state(monkeypatch):
    # The service client is an lru_cache singleton — clear it between tests so env
    # changes take effect, and drop any Supabase env the host machine might have set.
    db.get_service_client.cache_clear()
    for var in ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_ANON_KEY"):
        monkeypatch.delenv(var, raising=False)
    yield
    db.get_service_client.cache_clear()


def _install_fake_supabase(monkeypatch, *, raise_on_execute=False):
    """Inject a minimal fake `supabase` module and return a recorder dict."""
    recorder: dict = {"created_with": None, "executed": False, "auth_token": None}

    class _Query:
        def select(self, *a, **k):
            return self

        def limit(self, *a, **k):
            return self

        def execute(self):
            recorder["executed"] = True
            if raise_on_execute:
                raise RuntimeError("boom")
            return types.SimpleNamespace(data=[], count=0)

    class _PostgREST:
        def auth(self, token):
            recorder["auth_token"] = token

    class _Client:
        def __init__(self):
            self.postgrest = _PostgREST()

        def table(self, name):
            recorder["table"] = name
            return _Query()

    def create_client(url, key):
        recorder["created_with"] = (url, key)
        return _Client()

    fake = types.ModuleType("supabase")
    fake.create_client = create_client
    fake.Client = _Client
    monkeypatch.setitem(sys.modules, "supabase", fake)
    return recorder


# ─── configuration detection ────────────────────────────────────────────────────
def test_supabase_configured_false_when_unset():
    assert db.supabase_configured() is False


def test_supabase_configured_true_with_url_and_service_key(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "svc")
    assert db.supabase_configured() is True


def test_supabase_user_configured_false_when_unset():
    assert db.supabase_user_configured() is False


def test_supabase_user_configured_true_with_url_and_anon_key(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon-pub")
    assert db.supabase_user_configured() is True


# ─── get_service_client ─────────────────────────────────────────────────────────
def test_service_client_raises_when_unconfigured():
    with pytest.raises(RuntimeError):
        db.get_service_client()


def test_service_client_builds_with_service_role_key(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "svc-secret")
    rec = _install_fake_supabase(monkeypatch)
    client = db.get_service_client()
    assert client is not None
    assert rec["created_with"] == ("https://x.supabase.co", "svc-secret")


# ─── get_user_client ──────────────────────────────────────────────────────────--
def test_user_client_uses_anon_key_and_attaches_jwt(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon-pub")
    rec = _install_fake_supabase(monkeypatch)
    db.get_user_client("user-jwt-123")
    assert rec["created_with"] == ("https://x.supabase.co", "anon-pub")
    assert rec["auth_token"] == "user-jwt-123"  # RLS-enforcing path


def test_user_client_raises_without_anon_key(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    with pytest.raises(RuntimeError):
        db.get_user_client("jwt")


# ─── check_connectivity ──────────────────────────────────────────────────────────
def test_connectivity_unconfigured_when_no_env():
    assert db.check_connectivity() == {"db": "unconfigured"}


def test_connectivity_ok_round_trip(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "svc")
    rec = _install_fake_supabase(monkeypatch)
    assert db.check_connectivity() == {"db": "ok"}
    assert rec["executed"] is True
    assert rec["table"] == "profiles"


def test_connectivity_error_is_caught_and_typed(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "svc")
    _install_fake_supabase(monkeypatch, raise_on_execute=True)
    result = db.check_connectivity()
    assert result["db"] == "error"
    assert result["detail"] == "RuntimeError"  # type name only — never the message/secret


# ─── list_conversations / get_conversation (B2 — #27) ──────────────────────────
def _install_conversations_fake(monkeypatch, *, conversations=None, messages=None):
    """A richer fake `supabase` module supporting .eq()/.order() chains, filtering
    an in-memory dataset by the last .eq() call — enough to drive db.py's
    conversation queries without a real Postgres/PostgREST round-trip."""
    conversations = conversations if conversations is not None else []
    messages = messages if messages is not None else []

    class _Query:
        def __init__(self, table_name):
            self._table = table_name
            self._eq = None

        def select(self, *a, **k):
            return self

        def eq(self, col, val):
            self._eq = (col, val)
            return self

        def order(self, *a, **k):
            return self

        def limit(self, *a, **k):
            return self

        def execute(self):
            rows = conversations if self._table == "conversations" else messages
            if self._eq:
                col, val = self._eq
                rows = [r for r in rows if r.get(col) == val]
            return types.SimpleNamespace(data=rows)

    class _PostgREST:
        def auth(self, token):
            pass

    class _Client:
        def __init__(self):
            self.postgrest = _PostgREST()

        def table(self, name):
            return _Query(name)

    fake = types.ModuleType("supabase")
    fake.create_client = lambda url, key: _Client()
    fake.Client = _Client
    monkeypatch.setitem(sys.modules, "supabase", fake)


def _configure_user_env(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon-pub")


def test_list_conversations_returns_only_rows_from_the_table(monkeypatch):
    _configure_user_env(monkeypatch)
    convs = [{"id": "c1", "title": "Blues progressions", "updated_at": "2026-07-01"}]
    _install_conversations_fake(monkeypatch, conversations=convs)
    assert db.list_conversations("jwt") == convs


def test_list_conversations_empty_when_none_exist(monkeypatch):
    _configure_user_env(monkeypatch)
    _install_conversations_fake(monkeypatch, conversations=[])
    assert db.list_conversations("jwt") == []


def test_get_conversation_returns_none_when_not_found_or_not_owned(monkeypatch):
    # RLS makes "doesn't exist" and "exists but belongs to someone else" the same
    # empty result from the caller's point of view — both must resolve to None.
    _configure_user_env(monkeypatch)
    _install_conversations_fake(monkeypatch, conversations=[], messages=[])
    assert db.get_conversation("jwt", "missing-id") is None


def test_get_conversation_returns_conversation_with_its_messages(monkeypatch):
    _configure_user_env(monkeypatch)
    convs = [{"id": "c1", "title": "Blues progressions"}]
    msgs = [
        {"conversation_id": "c1", "role": "user", "content": "give me a blues progression"},
        {"conversation_id": "c1", "role": "assistant", "content": "Try E7-A7-B7…"},
    ]
    _install_conversations_fake(monkeypatch, conversations=convs, messages=msgs)
    result = db.get_conversation("jwt", "c1")
    assert result["id"] == "c1"
    assert result["messages"] == msgs
