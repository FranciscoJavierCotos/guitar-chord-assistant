"""
API contract + security tests for main.py, driven through FastAPI's TestClient.

The backend sits on a public URL, so the hardening (shared-secret auth, body-size
ceiling, request validation, fail-closed behaviour) is load-bearing, not cosmetic.
These tests pin that contract down without needing a DeepSeek key or network: the
agent is never actually invoked because every chat request is short-circuited by
auth, validation, or the missing-key 503 before reaching the LLM.
"""

import pytest
from fastapi.testclient import TestClient

import main

TOKEN = "test-internal-token"


@pytest.fixture
def client(monkeypatch):
    """A TestClient with a known internal token configured on the server."""
    monkeypatch.setenv("INTERNAL_API_TOKEN", TOKEN)
    return TestClient(main.app)


def auth(headers: dict | None = None) -> dict:
    h = {"X-Internal-Token": TOKEN}
    if headers:
        h.update(headers)
    return h


# ─── /api/health (must stay open for Render) ────────────────────────────────────
class TestHealth:
    def test_health_is_unauthenticated_and_reports_version(self, client):
        res = client.get("/api/health")
        assert res.status_code == 200
        assert res.json() == {"status": "ok", "version": "1.0.0"}


# ─── Shared-secret auth ─────────────────────────────────────────────────────────
class TestAuth:
    def test_missing_token_is_rejected_401(self, client):
        res = client.get("/api/chords")
        assert res.status_code == 401

    def test_wrong_token_is_rejected_401(self, client):
        res = client.get("/api/chords", headers={"X-Internal-Token": "nope"})
        assert res.status_code == 401

    def test_correct_token_is_accepted(self, client):
        res = client.get("/api/chords", headers=auth())
        assert res.status_code == 200

    def test_fails_closed_when_server_has_no_token_configured(self, monkeypatch):
        # If INTERNAL_API_TOKEN is unset, NO caller can be authorized → 503.
        monkeypatch.delenv("INTERNAL_API_TOKEN", raising=False)
        c = TestClient(main.app)
        res = c.get("/api/chords", headers={"X-Internal-Token": "anything"})
        assert res.status_code == 503


# ─── Request-size ceiling ───────────────────────────────────────────────────────
class TestBodySizeLimit:
    def test_oversized_body_is_rejected_413(self, client):
        big = "x" * (main.MAX_BODY_BYTES + 1)
        res = client.post(
            "/api/chat",
            headers=auth({"Content-Type": "application/json"}),
            content=big,
        )
        assert res.status_code == 413

    def test_non_integer_content_length_is_rejected_400(self, client):
        res = client.post(
            "/api/chat",
            headers=auth({"Content-Type": "application/json", "Content-Length": "abc"}),
            content="{}",
        )
        assert res.status_code == 400


# ─── ChatRequest validation ─────────────────────────────────────────────────────
class TestChatValidation:
    def test_empty_message_is_422(self, client, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "x")  # ensure 422 isn't masked by 503
        res = client.post("/api/chat", headers=auth(), json={"message": ""})
        assert res.status_code == 422

    def test_overlong_message_is_422(self, client, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "x")
        res = client.post("/api/chat", headers=auth(), json={"message": "y" * 2001})
        assert res.status_code == 422

    def test_missing_deepseek_key_returns_503(self, client, monkeypatch):
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        res = client.post("/api/chat", headers=auth(), json={"message": "hi"})
        assert res.status_code == 503


# ─── Data endpoints ─────────────────────────────────────────────────────────────
class TestDataEndpoints:
    def test_list_chords_returns_summary_shape(self, client):
        res = client.get("/api/chords", headers=auth())
        assert res.status_code == 200
        data = res.json()
        assert "C" in data
        # Summary projection only — full fingering positions are NOT exposed here.
        assert set(data["C"].keys()) == {"name", "full_name", "type", "difficulty"}

    def test_get_known_chord_returns_full_record(self, client):
        res = client.get("/api/chord/Am", headers=auth())
        assert res.status_code == 200
        body = res.json()
        assert body["name"] == "Am"
        assert len(body["positions"]) == 6

    def test_unknown_chord_is_404(self, client):
        res = client.get("/api/chord/NotAChord", headers=auth())
        assert res.status_code == 404

    def test_list_progressions_unfiltered(self, client):
        res = client.get("/api/progressions", headers=auth())
        assert res.status_code == 200
        assert isinstance(res.json(), list)
        assert len(res.json()) > 0

    def test_progressions_filtered_by_genre(self, client):
        res = client.get("/api/progressions", headers=auth(), params={"genre": "blues"})
        assert res.status_code == 200
        results = res.json()
        assert len(results) > 0
        assert all("blues" in p["genre"] for p in results)
