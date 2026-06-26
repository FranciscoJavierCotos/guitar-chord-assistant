"""Tests for the Supabase user-JWT verification layer (B1 — #26).

These are the security-critical assertions for `auth.py`: a token is accepted only
when its signature, issuer, audience, and expiry all check out — and, crucially,
that an HS256 token is rejected even if it's "validly" signed (alg-confusion guard).
No network: we generate an RSA keypair in-process and stub the JWKS client to return
the matching public key, so the real `jwt.decode` path runs against known inputs.
"""

import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

import auth

SUPABASE_URL = "https://proj.supabase.co"
ISSUER = f"{SUPABASE_URL}/auth/v1"


@pytest.fixture
def keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


@pytest.fixture
def use_jwks(monkeypatch, keypair):
    """Point auth.SUPABASE_URL at a known project and stub the JWKS lookup to the
    test public key, so jwt.decode verifies against our keypair."""
    _, public_key = keypair
    monkeypatch.setenv("SUPABASE_URL", SUPABASE_URL)

    class _FakeSigningKey:
        key = public_key

    class _FakeJwks:
        def get_signing_key_from_jwt(self, _token):
            return _FakeSigningKey()

    monkeypatch.setattr(auth, "_jwks_client", lambda: _FakeJwks())


def make_token(private_key, *, alg="RS256", **overrides):
    now = int(time.time())
    claims = {
        "sub": "user-123",
        "email": "player@example.com",
        "aud": "authenticated",
        "iss": ISSUER,
        "iat": now,
        "exp": now + 3600,
    }
    claims.update(overrides)
    return jwt.encode(claims, private_key, algorithm=alg)


# ─── _verify_token ──────────────────────────────────────────────────────────────
class TestVerifyToken:
    def test_valid_token_returns_user(self, use_jwks, keypair):
        private_key, _ = keypair
        user = auth._verify_token(make_token(private_key))
        assert user.id == "user-123"
        assert user.email == "player@example.com"
        assert user.access_token  # the raw token is carried through

    def test_expired_token_rejected(self, use_jwks, keypair):
        private_key, _ = keypair
        token = make_token(private_key, exp=int(time.time()) - 10)
        with pytest.raises(auth.HTTPException) as exc:
            auth._verify_token(token)
        assert exc.value.status_code == 401

    def test_wrong_audience_rejected(self, use_jwks, keypair):
        private_key, _ = keypair
        token = make_token(private_key, aud="anon")
        with pytest.raises(auth.HTTPException) as exc:
            auth._verify_token(token)
        assert exc.value.status_code == 401

    def test_wrong_issuer_rejected(self, use_jwks, keypair):
        private_key, _ = keypair
        token = make_token(private_key, iss="https://evil.example.com/auth/v1")
        with pytest.raises(auth.HTTPException) as exc:
            auth._verify_token(token)
        assert exc.value.status_code == 401

    def test_signature_from_other_key_rejected(self, use_jwks):
        attacker_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        token = make_token(attacker_key)  # signed by a key the JWKS doesn't know
        with pytest.raises(auth.HTTPException) as exc:
            auth._verify_token(token)
        assert exc.value.status_code == 401

    def test_hs256_token_rejected_alg_confusion(self, use_jwks):
        """An HS256-signed token must be rejected outright: our decode restricts the
        accepted algorithms to asymmetric ones, so the classic alg-confusion attack
        (signing HS256 with the public key as the HMAC secret) can never validate —
        the algorithm is refused before the key is even considered."""
        forged = jwt.encode(
            {"sub": "user-123", "aud": "authenticated", "iss": ISSUER, "exp": int(time.time()) + 60},
            "any-shared-secret-at-least-32-bytes-long!!",
            algorithm="HS256",
        )
        with pytest.raises(auth.HTTPException) as exc:
            auth._verify_token(forged)
        assert exc.value.status_code == 401

    def test_missing_sub_rejected(self, use_jwks, keypair):
        private_key, _ = keypair
        # Drop sub entirely; PyJWT's require=["sub"] should reject it.
        token = make_token(private_key, sub=None)
        # jwt.encode keeps sub=None; decode treats missing required claim as invalid.
        with pytest.raises(auth.HTTPException) as exc:
            auth._verify_token(token)
        assert exc.value.status_code == 401

    def test_unconfigured_returns_503(self, monkeypatch, keypair):
        monkeypatch.delenv("SUPABASE_URL", raising=False)
        private_key, _ = keypair
        with pytest.raises(auth.HTTPException) as exc:
            auth._verify_token(make_token(private_key))
        assert exc.value.status_code == 503


# ─── _bearer_token ──────────────────────────────────────────────────────────────
class TestBearerExtraction:
    def test_missing_header_rejected(self):
        with pytest.raises(auth.HTTPException) as exc:
            auth._bearer_token(None)
        assert exc.value.status_code == 401

    def test_wrong_scheme_rejected(self):
        with pytest.raises(auth.HTTPException) as exc:
            auth._bearer_token("Basic abc")
        assert exc.value.status_code == 401

    def test_empty_token_rejected(self):
        with pytest.raises(auth.HTTPException):
            auth._bearer_token("Bearer    ")

    def test_valid_bearer_extracted(self):
        assert auth._bearer_token("Bearer abc.def.ghi") == "abc.def.ghi"

    def test_scheme_is_case_insensitive(self):
        assert auth._bearer_token("bearer xyz") == "xyz"
