"""Query-time retrieval over the RAG corpus (Epic C, story C1 — #31).

Embeds the query via `rag/embeddings.py` (same model/dimension/normalization as
ingestion, C0, so query and corpus vectors never drift) and calls the
`match_kb_chunks` Postgres RPC (migration `20260701185136_c1_match_kb_chunks.sql`),
which does the pgvector `<=>` cosine-distance ordering that PostgREST's table query
builder can't express directly.

Uses the service-role client, same as `rag/ingest.py`: `kb_chunks` is public-read
reference data (not per-user data), retrieval runs for anonymous chat sessions too,
and the call never leaves the backend.
"""

from __future__ import annotations

from rag.embeddings import embed_texts

DEFAULT_MATCH_COUNT = 5


def search_corpus(query: str, match_count: int = DEFAULT_MATCH_COUNT) -> list[dict]:
    """Return up to `match_count` corpus chunks most similar to `query`.

    Each result dict has keys: source, title, url, content, similarity. Raises
    RuntimeError if GEMINI_API_KEY or Supabase env is unset (propagated from
    `embed_texts` / `db.get_service_client`).
    """
    [query_vector] = embed_texts([query])

    from db import get_service_client  # local import: mirrors rag/ingest.py

    client = get_service_client()
    result = client.rpc(
        "match_kb_chunks",
        {"query_embedding": query_vector, "match_count": match_count},
    ).execute()
    return result.data or []
