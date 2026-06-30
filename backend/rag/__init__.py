"""RAG corpus + ingestion pipeline for ChordCoach (Epic C, story C0 — #30).

Curates a small music-theory corpus (`rag/corpus/*.md`), chunks it (`rag/chunking.py`),
embeds it via Google Gemini (`rag/embeddings.py`), and upserts it into the
`public.kb_chunks` pgvector table (`rag/ingest.py`) for the retrieval tool C1 builds
next sprint.

Entry point: ``python -m rag`` (see `rag/__main__.py` / `rag/ingest.py`).
"""
