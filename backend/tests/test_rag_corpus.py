"""Golden-corpus integrity checks for the RAG knowledge base (Epic C, story C0 — #30).

Mirrors `test_eval.py`'s validation of its golden set: every committed corpus file
must parse, every `source` slug must be unique and match its filename (the natural
key for idempotent upsert/pruning — see `rag/ingest.py`), and every doc must produce
at least one chunk. No network/API key needed — this only exercises `rag/chunking.py`.
"""

from __future__ import annotations

import pytest

from rag.chunking import parse_corpus_file
from rag.ingest import CORPUS_DIR

CORPUS_FILES = sorted(CORPUS_DIR.glob("*.md"))


def test_corpus_dir_has_files():
    assert CORPUS_FILES, f"no corpus files found in {CORPUS_DIR}"


@pytest.mark.parametrize("path", CORPUS_FILES, ids=[p.stem for p in CORPUS_FILES])
def test_file_parses_without_error(path):
    doc = parse_corpus_file(path)
    assert doc.source and doc.title
    assert doc.chunks, f"{path.name} produced zero chunks"
    assert all(chunk.strip() for chunk in doc.chunks)


@pytest.mark.parametrize("path", CORPUS_FILES, ids=[p.stem for p in CORPUS_FILES])
def test_source_matches_filename_stem(path):
    doc = parse_corpus_file(path)
    assert doc.source == path.stem, (
        f"{path.name}: frontmatter source {doc.source!r} != filename stem {path.stem!r}"
    )


def test_no_duplicate_source_slugs():
    sources = [parse_corpus_file(p).source for p in CORPUS_FILES]
    assert len(sources) == len(set(sources)), "duplicate `source` slugs across corpus files"
