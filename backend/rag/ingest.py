"""Ingestion pipeline for the RAG corpus (Epic C, story C0 — #30).

``python -m rag`` chunks the curated corpus (`backend/rag/corpus/*.md`), embeds each
chunk via Gemini (`rag/embeddings.py`), and upserts it into `public.kb_chunks`
(`supabase/migrations/<...>_c0_kb_embeddings.sql`) through the service-role client.

Idempotency: delete-and-reinsert per source, plus orphan pruning. Re-running this
script deletes all `kb_chunks` rows for a given source, embeds and inserts the
current chunk set for it, then deletes any source no longer present in the corpus
directory. This converges to the same end state on every run regardless of where a
previous run stopped, since each source's rows are replaced as a unit rather than
diffed chunk-by-chunk — simpler and more obviously correct for a small admin script,
and resilient to chunk boundaries shifting after a corpus edit.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

from rag.chunking import CorpusDoc, parse_corpus_file
from rag.embeddings import EMBEDDING_DIM, EMBEDDING_MODEL, embed_texts

CORPUS_DIR = Path(__file__).resolve().parent / "corpus"

# Rough token approximation for the printed summary only — not used for billing or
# for chunking decisions (those use word counts; see rag/chunking.py).
_WORDS_TO_TOKENS = 1.3
_GEMINI_COST_PER_MTOK = 0.15


def load_corpus(corpus_dir: Path = CORPUS_DIR) -> list[CorpusDoc]:
    """Parse every corpus file, validating no duplicate sources and >=1 chunk each."""
    docs = [parse_corpus_file(p) for p in sorted(corpus_dir.glob("*.md"))]

    seen: set[str] = set()
    for doc in docs:
        if doc.source in seen:
            raise ValueError(f"duplicate corpus source slug: {doc.source!r}")
        seen.add(doc.source)
        if not doc.chunks:
            raise ValueError(f"corpus source {doc.source!r} produced zero chunks")
    return docs


def _upsert_doc(client, doc: CorpusDoc) -> int:
    """Delete-then-insert all kb_chunks rows for one source. Returns rows written."""
    client.table("kb_chunks").delete().eq("source", doc.source).execute()

    vectors = embed_texts(doc.chunks)
    rows = [
        {
            "source": doc.source,
            "title": doc.title,
            "url": doc.url,
            "chunk_index": i,
            "content": chunk,
            "embedding": vector,
        }
        for i, (chunk, vector) in enumerate(zip(doc.chunks, vectors))
    ]
    client.table("kb_chunks").insert(rows).execute()
    return len(rows)


def _prune_orphans(client, current_sources: set[str]) -> int:
    """Delete kb_chunks rows for any source no longer present in the corpus dir.

    Returns the number of orphaned sources pruned.
    """
    existing = client.table("kb_chunks").select("source").execute()
    existing_sources = {row["source"] for row in (existing.data or [])}
    orphans = existing_sources - current_sources
    for source in orphans:
        client.table("kb_chunks").delete().eq("source", source).execute()
    return len(orphans)


def run(docs: list[CorpusDoc], dry_run: bool) -> dict:
    """Run the pipeline against the given docs. Returns a summary dict for printing."""
    total_words = sum(len(chunk.split()) for doc in docs for chunk in doc.chunks)
    total_chunks = sum(len(doc.chunks) for doc in docs)
    summary = {
        "sources": len(docs),
        "chunks": total_chunks,
        "embedding_model": EMBEDDING_MODEL,
        "embedding_dim": EMBEDDING_DIM,
        "estimated_tokens": round(total_words * _WORDS_TO_TOKENS),
        "estimated_cost_usd": round(
            total_words * _WORDS_TO_TOKENS / 1_000_000 * _GEMINI_COST_PER_MTOK, 6
        ),
    }
    if dry_run:
        return summary

    from db import get_service_client  # local import: keeps --dry-run free of the DB dep

    client = get_service_client()
    rows_written = sum(_upsert_doc(client, doc) for doc in docs)
    orphans_pruned = _prune_orphans(client, {doc.source for doc in docs})
    summary["rows_written"] = rows_written
    summary["orphans_pruned"] = orphans_pruned
    return summary


def _print_summary(summary: dict, dry_run: bool) -> None:
    prefix = "[dry-run] " if dry_run else ""
    print(f"{prefix}sources processed: {summary['sources']}")
    print(f"{prefix}chunks: {summary['chunks']}")
    if "rows_written" in summary:
        print(f"rows written: {summary['rows_written']}")
        print(f"orphan sources pruned: {summary['orphans_pruned']}")
    print(f"embedding model: {summary['embedding_model']} ({summary['embedding_dim']}-dim)")
    print(
        f"estimated tokens: {summary['estimated_tokens']} "
        f"(~${summary['estimated_cost_usd']:.6f})"
    )


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest the RAG corpus into kb_chunks.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Chunk and report without calling the embeddings API or touching the DB.",
    )
    args = parser.parse_args(argv)

    try:
        docs = load_corpus()
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    summary = run(docs, dry_run=args.dry_run)
    _print_summary(summary, dry_run=args.dry_run)
    return 0
