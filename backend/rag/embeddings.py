"""Embeddings client for the RAG corpus (Epic C, story C0 — #30).

Single source of truth for embedding text, used by this story's ingestion script
(`rag/ingest.py`) and reused as-is by C1's retrieval tool next sprint — so query-time
and ingest-time embeddings can never drift apart on model/dimension/normalization.

DeepSeek has no embeddings endpoint, so this is a second, narrowly-scoped LLM
provider: Google Gemini's `gemini-embedding-001` ($0.15/1M tokens, free tier
available), truncated to 768 dimensions (Matryoshka representation learning) from
its native 3072 — one of Google's three recommended output sizes, chosen to keep the
HNSW index compact for a small corpus at negligible retrieval-quality cost.

`google.genai` is imported lazily inside `embed_texts`, matching `backend/db.py`'s
lazy-`supabase`-import pattern, so importing this module never fails when the
package or `GEMINI_API_KEY` is absent (tests, CI, local dev without RAG configured).
"""

from __future__ import annotations

import os

EMBEDDING_MODEL = "gemini-embedding-001"
EMBEDDING_DIM = 768


def _env(name: str) -> str | None:
    value = os.getenv(name)
    return value.strip() if value else None


def _l2_normalize(vector: list[float]) -> list[float]:
    """Manually L2-normalize an embedding.

    `gemini-embedding-001` only auto-normalizes its native 3072-dim output; when
    truncated via `output_dimensionality` (as here, to 768) the result is NOT
    re-normalized by the API, so skipping this would silently degrade cosine-distance
    ranking at query time (C1) without ever raising an error.
    """
    norm = sum(x * x for x in vector) ** 0.5
    if norm == 0:
        return vector
    return [x / norm for x in vector]


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts, returning one 768-dim, L2-normalized vector per text.

    Raises RuntimeError if GEMINI_API_KEY is unset — only when actually called, never
    at import time.
    """
    api_key = _env("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("Gemini is not configured: set GEMINI_API_KEY.")

    from google import genai  # lazy: keeps the package optional at import time
    from google.genai import types

    client = genai.Client(api_key=api_key)
    response = client.models.embed_content(
        model=EMBEDDING_MODEL,
        contents=texts,
        config=types.EmbedContentConfig(output_dimensionality=EMBEDDING_DIM),
    )
    embeddings = response.embeddings or []
    return [_l2_normalize(list(e.values or [])) for e in embeddings]
