"""Supabase/Postgres client wiring for ChordCoach (Epic B, story B0 — #25).

This is the typed data-layer entry point every later Accounts/RAG story builds on.
The MVP kept sessions in an in-process dict (see `agent/memory.py`); from B0 onward
durable user data lives in Supabase Postgres, protected by Row-Level Security.

Two client flavors, deliberately separated:

* **service-role client** (`get_service_client`) — authenticates with the secret
  service-role key and **bypasses RLS**. Backend-only admin work (migrations-adjacent
  maintenance, trusted server tasks). The service-role key must never reach the browser.
* **user-scoped client** (`get_user_client`) — the publishable/anon key plus the
  signed-in user's access token, so PostgREST runs every query **with RLS enforced**.
  This is the path later stories use to read/write a user's own rows.

`supabase` is imported lazily inside the factories so importing this module never
fails when the package or env vars are absent (tests, CI, local dev without DB).
Configuration comes only from server-side env — nothing here is browser-facing.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:  # imported only for type checkers; never at runtime
    from supabase import Client


def _env(name: str) -> Optional[str]:
    value = os.getenv(name)
    return value.strip() if value else None


def supabase_configured() -> bool:
    """True when the backend has enough config to reach Supabase as the service role."""
    return bool(_env("SUPABASE_URL") and _env("SUPABASE_SERVICE_ROLE_KEY"))


@lru_cache(maxsize=1)
def get_service_client() -> "Client":
    """Service-role Supabase client (RLS-bypassing). Cached as a singleton.

    Raises RuntimeError if SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY are unset, so
    callers fail loudly rather than silently operating without a database.
    """
    url = _env("SUPABASE_URL")
    key = _env("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise RuntimeError(
            "Supabase is not configured: set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY."
        )
    from supabase import create_client  # lazy: keeps the package optional at import time

    return create_client(url, key)


def get_user_client(access_token: str) -> "Client":
    """RLS-enforced client scoped to a signed-in user.

    Uses the publishable/anon key for the connection and attaches the user's access
    token as the PostgREST `Authorization` bearer, so `auth.uid()` resolves to that
    user and every query is filtered by the RLS policies. Used from B1 onward.
    """
    url = _env("SUPABASE_URL")
    anon_key = _env("SUPABASE_ANON_KEY")
    if not url or not anon_key:
        raise RuntimeError(
            "Supabase is not configured: set SUPABASE_URL and SUPABASE_ANON_KEY."
        )
    from supabase import create_client

    client = create_client(url, anon_key)
    # Route every request through the user's JWT so RLS sees the real auth.uid().
    client.postgrest.auth(access_token)
    return client


def check_connectivity() -> dict[str, str]:
    """Confirm the backend can reach Supabase. Used by the DB health route.

    Returns one of:
      {"db": "unconfigured"} — no Supabase env set (expected in MVP/local-without-DB)
      {"db": "ok"}           — a trivial round-trip to PostgREST succeeded
      {"db": "error", ...}   — configured but the round-trip failed

    Never raises and never leaks the URL/key — only a coarse status string, safe to
    return on an authenticated route.
    """
    if not supabase_configured():
        return {"db": "unconfigured"}
    try:
        client = get_service_client()
        # Cheapest possible round-trip that exercises auth + PostgREST: a head/count
        # against a known table, fetching zero rows. Service role bypasses RLS so an
        # empty table still returns a count rather than an error.
        client.table("profiles").select("id", count="exact").limit(0).execute()
        return {"db": "ok"}
    except Exception as exc:  # noqa: BLE001 — surface a status, not the stack/secret
        return {"db": "error", "detail": type(exc).__name__}
