"""Unit tests for the `search_music_theory` LangChain tool (Epic C, story C1 — #31).

`rag.retrieval.search_corpus` is stubbed so these run without network/API keys, in
the same spirit as the other tool tests exercise pure formatting logic.
"""

from __future__ import annotations

import pytest

import rag.retrieval as retrieval
from agent.tools import TOOLS, search_music_theory


def test_search_music_theory_is_registered_in_tools():
    assert search_music_theory in TOOLS


def test_search_music_theory_formats_passages_with_citations(monkeypatch):
    monkeypatch.setattr(
        retrieval,
        "search_corpus",
        lambda query, **kw: [
            {
                "source": "circle-of-fifths",
                "title": "The Circle of Fifths",
                "url": "https://example.com/circle-of-fifths",
                "content": "The circle of fifths arranges the 12 pitch classes...",
                "similarity": 0.91,
            }
        ],
    )

    result = search_music_theory.invoke({"query": "circle of fifths"})

    assert "The Circle of Fifths" in result
    assert "https://example.com/circle-of-fifths" in result
    assert "The circle of fifths arranges the 12 pitch classes" in result


def test_search_music_theory_omits_citation_when_no_url(monkeypatch):
    monkeypatch.setattr(
        retrieval,
        "search_corpus",
        lambda query, **kw: [
            {
                "source": "modes-overview",
                "title": "Modes Overview",
                "url": None,
                "content": "Modes are rotations of the major scale...",
                "similarity": 0.8,
            }
        ],
    )

    result = search_music_theory.invoke({"query": "what are modes"})

    assert "Modes Overview" in result
    assert "(None)" not in result


def test_search_music_theory_handles_no_results(monkeypatch):
    monkeypatch.setattr(retrieval, "search_corpus", lambda query, **kw: [])

    result = search_music_theory.invoke({"query": "something obscure"})

    assert "No relevant passages found" in result


def test_search_music_theory_handles_unconfigured_backend(monkeypatch):
    def _raise(query, **kw):
        raise RuntimeError("Gemini is not configured: set GEMINI_API_KEY.")

    monkeypatch.setattr(retrieval, "search_corpus", _raise)

    result = search_music_theory.invoke({"query": "circle of fifths"})

    assert "unavailable" in result.lower()
    assert "GEMINI_API_KEY" in result
