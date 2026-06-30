"""Enables ``python -m rag`` to run the ingestion pipeline."""

from rag.ingest import main

if __name__ == "__main__":
    raise SystemExit(main())
