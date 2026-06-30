"""Unit tests for `rag/ingest.py` — corpus loading, delete-then-insert, idempotency,
and orphan pruning.

`embed_texts` and `db.get_service_client` are stubbed (no network/`GEMINI_API_KEY` or
real Supabase needed in CI), following the same fake-client pattern as
`test_db_client.py`. The fake `kb_chunks` table is an in-memory list that mimics the
PostgREST query chain (`.delete().eq(...).execute()`, `.insert(...).execute()`,
`.select(...).execute()`) closely enough to exercise the real ingest pipeline code.
"""

from __future__ import annotations

import types

import pytest

import db
import rag.ingest as ingest
from rag.chunking import CorpusDoc


# ─── fake Supabase client ───────────────────────────────────────────────────────


class _FakeDelete:
    def __init__(self, table):
        self._table = table
        self._source = None

    def eq(self, col, value):
        assert col == "source"
        self._source = value
        return self

    def execute(self):
        self._table.deleted_sources.append(self._source)
        self._table.rows = [r for r in self._table.rows if r["source"] != self._source]
        return types.SimpleNamespace(data=[])


class _FakeInsert:
    def __init__(self, table, rows):
        self._table = table
        self._rows = rows

    def execute(self):
        self._table.inserted_batches.append(self._rows)
        self._table.rows.extend(self._rows)
        return types.SimpleNamespace(data=self._rows)


class _FakeSelect:
    def __init__(self, table):
        self._table = table

    def execute(self):
        data = [{"source": r["source"]} for r in self._table.rows]
        return types.SimpleNamespace(data=data)


class FakeKbTable:
    def __init__(self):
        self.rows: list[dict] = []
        self.deleted_sources: list[str] = []
        self.inserted_batches: list[list[dict]] = []

    def delete(self):
        return _FakeDelete(self)

    def insert(self, rows):
        return _FakeInsert(self, rows)

    def select(self, *_a, **_k):
        return _FakeSelect(self)


class FakeSupabaseClient:
    def __init__(self):
        self.kb_chunks = FakeKbTable()

    def table(self, name):
        assert name == "kb_chunks", f"unexpected table {name!r}"
        return self.kb_chunks


def _fake_embed(dim: int = 768):
    """A deterministic, fixed-vector stand-in for rag.embeddings.embed_texts."""

    def _embed(texts: list[str]) -> list[list[float]]:
        return [[0.0] * dim for _ in texts]

    return _embed


@pytest.fixture
def fake_client(monkeypatch):
    client = FakeSupabaseClient()
    monkeypatch.setattr(db, "get_service_client", lambda: client)
    return client


@pytest.fixture(autouse=True)
def _stub_embeddings(monkeypatch):
    monkeypatch.setattr(ingest, "embed_texts", _fake_embed())


def _doc(source: str, chunks: list[str], *, title: str | None = None) -> CorpusDoc:
    return CorpusDoc(source=source, title=title or source, url=None, chunks=chunks)


# ─── load_corpus validation ─────────────────────────────────────────────────────


def test_load_corpus_rejects_duplicate_sources(tmp_path):
    fm = "---\ntitle: T\nsource: dup\nurl:\n---\n\n## H\nbody one."
    (tmp_path / "a.md").write_text(fm, encoding="utf-8")
    (tmp_path / "b.md").write_text(fm.replace("body one.", "body two."), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        ingest.load_corpus(tmp_path)


def test_load_corpus_rejects_zero_chunk_doc(tmp_path):
    (tmp_path / "empty.md").write_text(
        "---\ntitle: Empty\nsource: empty\nurl:\n---\n\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="zero chunks"):
        ingest.load_corpus(tmp_path)


def test_load_corpus_parses_real_files(tmp_path):
    (tmp_path / "one.md").write_text(
        "---\ntitle: One\nsource: one\nurl:\n---\n\n## H\nSome content here.",
        encoding="utf-8",
    )
    docs = ingest.load_corpus(tmp_path)
    assert len(docs) == 1
    assert docs[0].source == "one"


# ─── delete-then-insert per source ───────────────────────────────────────────────


def test_run_deletes_then_inserts_per_source(fake_client):
    docs = [_doc("alpha", ["chunk a1", "chunk a2"]), _doc("beta", ["chunk b1"])]
    summary = ingest.run(docs, dry_run=False)

    assert set(fake_client.kb_chunks.deleted_sources) == {"alpha", "beta"}
    assert summary["rows_written"] == 3
    sources_in_db = {r["source"] for r in fake_client.kb_chunks.rows}
    assert sources_in_db == {"alpha", "beta"}
    alpha_rows = sorted(
        (r for r in fake_client.kb_chunks.rows if r["source"] == "alpha"),
        key=lambda r: r["chunk_index"],
    )
    assert [r["content"] for r in alpha_rows] == ["chunk a1", "chunk a2"]
    assert [r["chunk_index"] for r in alpha_rows] == [0, 1]
    assert all(len(r["embedding"]) == 768 for r in fake_client.kb_chunks.rows)


def test_dry_run_never_touches_the_db(fake_client):
    docs = [_doc("alpha", ["chunk a1"])]
    summary = ingest.run(docs, dry_run=True)

    assert fake_client.kb_chunks.rows == []
    assert fake_client.kb_chunks.deleted_sources == []
    assert "rows_written" not in summary
    assert summary["chunks"] == 1


# ─── idempotency ─────────────────────────────────────────────────────────────────


def test_rerunning_ingestion_is_idempotent(fake_client):
    docs = [_doc("alpha", ["chunk a1", "chunk a2"])]
    ingest.run(docs, dry_run=False)
    ingest.run(docs, dry_run=False)

    rows = fake_client.kb_chunks.rows
    assert len(rows) == 2
    keys = [(r["source"], r["chunk_index"]) for r in rows]
    assert len(keys) == len(set(keys)), "duplicate (source, chunk_index) rows after rerun"


def test_rerunning_with_fewer_chunks_drops_stale_rows(fake_client):
    ingest.run([_doc("alpha", ["a1", "a2", "a3"])], dry_run=False)
    ingest.run([_doc("alpha", ["a1-edited"])], dry_run=False)

    rows = fake_client.kb_chunks.rows
    assert len(rows) == 1
    assert rows[0]["content"] == "a1-edited"


# ─── orphan pruning ──────────────────────────────────────────────────────────────


def test_removed_source_is_pruned_on_next_run(fake_client):
    ingest.run([_doc("alpha", ["a1"]), _doc("beta", ["b1"])], dry_run=False)
    summary = ingest.run([_doc("alpha", ["a1"])], dry_run=False)

    sources_in_db = {r["source"] for r in fake_client.kb_chunks.rows}
    assert sources_in_db == {"alpha"}
    assert summary["orphans_pruned"] == 1
