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


def supabase_user_configured() -> bool:
    """True when the backend has enough config to build RLS-scoped user clients
    (`get_user_client`) — the anon key rather than the service-role key. Checked
    separately from `supabase_configured` because persisting a user's own
    conversations (B2 — #27) never needs the service-role key."""
    return bool(_env("SUPABASE_URL") and _env("SUPABASE_ANON_KEY"))


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


def get_own_profile(access_token: str) -> Optional[dict]:
    """Return the signed-in user's own `profiles` row, or None if it doesn't exist yet.

    Goes through the RLS-enforced user client (B1 — #26): PostgREST runs the query with
    the caller's JWT, so RLS guarantees only the user's own row can ever come back —
    the backend never has to filter by id itself. The profile row is normally created
    by the `on_auth_user_created` trigger (B0); None is a tolerated transient race.
    """
    client = get_user_client(access_token)
    result = (
        client.table("profiles")
        .select("id, username, display_name, created_at, updated_at")
        .limit(1)
        .execute()
    )
    rows = result.data or []
    return rows[0] if rows else None


def list_conversations(access_token: str) -> list[dict]:
    """List the signed-in user's conversations, newest-active first (B2 — #27).

    RLS-scoped: PostgREST runs with the caller's JWT, so `conversations_select_own`
    guarantees only that user's rows can ever come back.
    """
    client = get_user_client(access_token)
    result = (
        client.table("conversations")
        .select("id, title, created_at, updated_at")
        .order("updated_at", desc=True)
        .execute()
    )
    return result.data or []


def get_conversation(access_token: str, conversation_id: str) -> Optional[dict]:
    """Fetch one conversation with its messages, or None if it doesn't exist / isn't
    owned by the caller (B2 — #27). RLS makes "doesn't exist" and "not yours"
    indistinguishable from the caller's point of view, which is the correct
    behaviour for an ownership boundary.
    """
    client = get_user_client(access_token)
    conv_result = (
        client.table("conversations")
        .select("id, title, created_at, updated_at")
        .eq("id", conversation_id)
        .limit(1)
        .execute()
    )
    rows = conv_result.data or []
    if not rows:
        return None
    conversation = rows[0]
    msg_result = (
        client.table("messages")
        .select("role, content, agent_action, created_at")
        .eq("conversation_id", conversation_id)
        .order("created_at")
        .execute()
    )
    conversation["messages"] = msg_result.data or []
    return conversation


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
