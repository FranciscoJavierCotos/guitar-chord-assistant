"""Unit tests for `rag/retrieval.py` — query-time vector search (Epic C, story C1 — #31).

`embed_texts` and `db.get_service_client` are stubbed (no network/`GEMINI_API_KEY` or
real Supabase needed in CI), following the same fake-client pattern as
`test_rag_ingest.py`. The fake client's `.rpc(...)` mimics PostgREST's RPC call chain
(`.rpc(name, params).execute()`) closely enough to exercise the real retrieval code.
"""

from __future__ import annotations

import types

import pytest

import db
import rag.retrieval as retrieval


class _FakeRpc:
    def __init__(self, client, fn_name, params):
        self._client = client
        self._fn_name = fn_name
        self._params = params

    def execute(self):
        self._client.rpc_calls.append((self._fn_name, self._params))
        return types.SimpleNamespace(data=self._client.rows)


class FakeSupabaseClient:
    def __init__(self, rows=None):
        self.rows = rows if rows is not None else []
        self.rpc_calls: list[tuple[str, dict]] = []

    def rpc(self, fn_name, params):
        return _FakeRpc(self, fn_name, params)


@pytest.fixture
def fake_client(monkeypatch):
    client = FakeSupabaseClient()
    monkeypatch.setattr(db, "get_service_client", lambda: client)
    return client


@pytest.fixture(autouse=True)
def _stub_embeddings(monkeypatch):
    def _embed(texts: list[str]) -> list[list[float]]:
        return [[0.1] * 768 for _ in texts]

    monkeypatch.setattr(retrieval, "embed_texts", _embed)


def test_search_corpus_embeds_the_query_and_calls_the_rpc(fake_client):
    retrieval.search_corpus("what is a diminished chord?", match_count=3)

    assert len(fake_client.rpc_calls) == 1
    fn_name, params = fake_client.rpc_calls[0]
    assert fn_name == "match_kb_chunks"
    assert params["match_count"] == 3
    assert params["query_embedding"] == [0.1] * 768


def test_search_corpus_uses_default_match_count(fake_client):
    retrieval.search_corpus("circle of fifths")

    _, params = fake_client.rpc_calls[0]
    assert params["match_count"] == retrieval.DEFAULT_MATCH_COUNT


def test_search_corpus_returns_rows_from_the_rpc(fake_client):
    fake_client.rows = [
        {
            "source": "circle-of-fifths",
            "title": "The Circle of Fifths",
            "url": None,
            "content": "The circle of fifths arranges the 12 pitch classes...",
            "similarity": 0.91,
        }
    ]

    results = retrieval.search_corpus("circle of fifths")

    assert results == fake_client.rows


def test_search_corpus_returns_empty_list_when_no_rows(fake_client):
    assert retrieval.search_corpus("an obscure query") == []


def test_search_corpus_handles_null_data_from_rpc(fake_client, monkeypatch):
    class _NullDataClient(FakeSupabaseClient):
        def rpc(self, fn_name, params):
            class _Rpc:
                def execute(self_inner):
                    return types.SimpleNamespace(data=None)

            return _Rpc()

    monkeypatch.setattr(db, "get_service_client", lambda: _NullDataClient())
    assert retrieval.search_corpus("anything") == []


def test_search_corpus_propagates_embedding_errors(monkeypatch, fake_client):
    def _raise(texts):
        raise RuntimeError("Gemini is not configured: set GEMINI_API_KEY.")

    monkeypatch.setattr(retrieval, "embed_texts", _raise)
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        retrieval.search_corpus("anything")
