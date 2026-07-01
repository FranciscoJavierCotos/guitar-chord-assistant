"""Supabase user-JWT verification for ChordCoach (Epic B, story B1 — #26).

The backend is public-facing and already gates every `/api/*` route on the shared
proxy secret (`X-Internal-Token`, see `main.py`). B1 adds a *second, independent*
identity layer: routes that act on behalf of a signed-in user verify that user's
Supabase access token here **before** building the RLS-scoped client in `db.py`.

Security model (defense in depth — three independent layers):
  1. proxy shared secret  (X-Internal-Token)  — only our Next.js server can call
  2. verified user JWT     (this module)        — backend never trusts an identity
                                                  it hasn't cryptographically checked
  3. Postgres RLS          (db.get_user_client) — row ownership enforced in the DB

Verification specifics:
  * **Asymmetric only.** We verify against Supabase's public JWKS
    (`<SUPABASE_URL>/auth/v1/.well-known/jwks.json`) and restrict the accepted
    algorithms to asymmetric ones (ES256/RS256/EdDSA). HS256 is deliberately NOT
    allowed: permitting it alongside a public key enables the classic alg-confusion
    attack (an attacker signs an HS256 token using the *public* key as the HMAC
    secret). No JWT signing secret is ever stored in the backend.
  * We additionally assert `aud == "authenticated"`, the issuer matches this
    project's `/auth/v1`, and `exp` (PyJWT enforces expiry by default).
  * Any failure → HTTP 401 with a generic message; we never echo token contents.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

import anyio
from fastapi import Header, HTTPException

# Asymmetric algorithms Supabase may use to sign access tokens. HS256 is
# intentionally excluded (see module docstring — alg-confusion hardening).
_ALLOWED_ALGORITHMS = ["ES256", "RS256", "EdDSA"]
_EXPECTED_AUDIENCE = "authenticated"


@dataclass(frozen=True)
class AuthedUser:
    """A verified Supabase user. `access_token` is carried so the caller can build
    an RLS-scoped client (`db.get_user_client`) with the very token we validated."""

    id: str
    email: Optional[str]
    access_token: str


def _supabase_url() -> Optional[str]:
    value = os.getenv("SUPABASE_URL")
    return value.strip().rstrip("/") if value else None


def supabase_auth_configured() -> bool:
    """True when the backend has the URL needed to fetch Supabase's public JWKS."""
    return bool(_supabase_url())


@lru_cache(maxsize=1)
def _jwks_client():
    """Cached PyJWKClient for this project's public signing keys.

    PyJWKClient caches fetched keys in-process, so steady-state verification does
    no network I/O; it transparently refetches when an unknown `kid` appears
    (handles Supabase key rotation without a redeploy). Built lazily so importing
    this module never requires PyJWT/network at import time (tests/CI/local-no-DB).
    """
    url = _supabase_url()
    if not url:
        raise RuntimeError("SUPABASE_URL is not configured.")
    from jwt import PyJWKClient

    jwks_url = f"{url}/auth/v1/.well-known/jwks.json"
    return PyJWKClient(jwks_url, cache_keys=True)


def _verify_token(token: str) -> AuthedUser:
    """Verify a Supabase access token (signature + iss/aud/exp). Sync; run off-loop.

    Raises HTTPException(401) on any verification failure — never leaks why beyond a
    generic message, and never returns claims from an unverified token.
    """
    import jwt  # lazy: keeps PyJWT optional at import time

    url = _supabase_url()
    if not url:
        # Mirrors require_internal_token's fail-closed posture: no config → no auth.
        raise HTTPException(status_code=503, detail="Server auth not configured.")

    try:
        signing_key = _jwks_client().get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=_ALLOWED_ALGORITHMS,
            audience=_EXPECTED_AUDIENCE,
            issuer=f"{url}/auth/v1",
            options={"require": ["exp", "sub"]},
        )
    except Exception:  # noqa: BLE001 — collapse every JWT/JWKS failure to a 401
        raise HTTPException(status_code=401, detail="Invalid or expired token.")

    user_id = claims.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid or expired token.")

    return AuthedUser(id=user_id, email=claims.get("email"), access_token=token)


def _bearer_token(authorization: Optional[str]) -> str:
    """Extract the token from an `Authorization: Bearer <token>` header, or 401."""
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing bearer token.")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail="Missing bearer token.")
    return token.strip()


async def get_current_user(
    authorization: Optional[str] = Header(default=None),
) -> AuthedUser:
    """FastAPI dependency: the verified Supabase user behind this request.

    Stacks on top of `require_internal_token` (the proxy secret is still required).
    Runs the synchronous JWKS/JWT verification in a threadpool so it never blocks
    the event loop. Use on any route that must act on behalf of a real user.
    """
    token = _bearer_token(authorization)
    return await anyio.to_thread.run_sync(_verify_token, token)


async def get_current_user_optional(
    authorization: Optional[str] = Header(default=None),
) -> Optional[AuthedUser]:
    """Like `get_current_user`, but returns None instead of 401 when there's no
    bearer token at all (used by routes that stay usable anonymously — e.g. chat,
    B2 #27 — but attribute the turn to a real user when one is signed in).

    A *present but invalid* token still 401s: an expired/tampered token is
    anomalous (the frontend only ever attaches a live Supabase session), so
    silently downgrading it to "anonymous" would mask that instead of surfacing it.
    """
    if not authorization:
        return None
    token = _bearer_token(authorization)
    return await anyio.to_thread.run_sync(_verify_token, token)
