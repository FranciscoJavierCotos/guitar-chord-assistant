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
