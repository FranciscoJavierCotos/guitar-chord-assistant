"""Unit tests for `rag/chunking.py` — frontmatter parsing + heading/paragraph chunking.

Pure-function tests against synthetic files (no real corpus content needed; that's
covered by `test_rag_corpus.py`). No network/API key needed.
"""

from __future__ import annotations

from rag.chunking import parse_corpus_file

FRONTMATTER = "---\ntitle: Test Doc\nsource: test-doc\nurl:\n---\n\n"


def _write(tmp_path, body: str, *, filename: str = "test-doc.md"):
    path = tmp_path / filename
    path.write_text(FRONTMATTER + body, encoding="utf-8")
    return path


def _paragraph(word: str, n: int) -> str:
    return " ".join([word] * n)


def test_frontmatter_fields_parsed(tmp_path):
    path = _write(tmp_path, "## Heading\nSome body text.")
    doc = parse_corpus_file(path)
    assert doc.title == "Test Doc"
    assert doc.source == "test-doc"
    assert doc.url is None


def test_blank_url_is_none_but_present_url_is_kept(tmp_path):
    path = tmp_path / "with-url.md"
    path.write_text(
        "---\ntitle: With URL\nsource: with-url\nurl: https://example.com/theory\n---\n\n"
        "## Heading\nBody.",
        encoding="utf-8",
    )
    doc = parse_corpus_file(path)
    assert doc.url == "https://example.com/theory"


def test_splits_on_headings(tmp_path):
    body = "## First Section\nFirst body.\n\n## Second Section\nSecond body."
    path = _write(tmp_path, body)
    doc = parse_corpus_file(path)
    assert len(doc.chunks) == 2
    assert doc.chunks[0].startswith("## First Section")
    assert "First body." in doc.chunks[0]
    assert doc.chunks[1].startswith("## Second Section")
    assert "Second body." in doc.chunks[1]


def test_oversized_section_is_paragraph_split(tmp_path):
    # Three ~100-word paragraphs under one heading: 300 words total, well past the
    # ~220-word section threshold, so this must split into multiple chunks.
    paragraphs = [_paragraph("word", 100) for _ in range(3)]
    body = "## Big Section\n" + "\n\n".join(paragraphs)
    path = _write(tmp_path, body)
    doc = parse_corpus_file(path)

    assert len(doc.chunks) > 1
    for chunk in doc.chunks:
        # Generous upper bound around the 150-220 word target band, allowing for one
        # full paragraph to push slightly past 220 before a new chunk starts.
        assert len(chunk.split()) <= 220 + 100
    # No content lost or duplicated across the split.
    total_words = sum(len(c.split()) for c in doc.chunks)
    assert total_words == len(("## Big Section\n" + "\n\n".join(paragraphs)).split())


def test_small_section_is_not_split(tmp_path):
    body = "## Small Section\n" + _paragraph("word", 50)
    path = _write(tmp_path, body)
    doc = parse_corpus_file(path)
    assert len(doc.chunks) == 1


def test_no_overlap_between_chunks(tmp_path):
    paragraphs = [f"ParagraphMarker{i} " + _paragraph("filler", 80) for i in range(3)]
    body = "## Big Section\n" + "\n\n".join(paragraphs)
    path = _write(tmp_path, body)
    doc = parse_corpus_file(path)

    assert len(doc.chunks) > 1
    for i in range(3):
        marker = f"ParagraphMarker{i}"
        occurrences = sum(chunk.count(marker) for chunk in doc.chunks)
        assert occurrences == 1, f"{marker} appeared {occurrences} times — chunks overlap"


def test_parsing_is_deterministic(tmp_path):
    paragraphs = [_paragraph("word", 90) for _ in range(3)]
    body = "## Heading One\n" + "\n\n".join(paragraphs) + "\n\n## Heading Two\nShort body."
    path = _write(tmp_path, body)

    first = parse_corpus_file(path)
    second = parse_corpus_file(path)
    assert first.chunks == second.chunks
